/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */

package frauddetection

import org.apache.kafka.clients.consumer.ConsumerConfig.*
import org.apache.kafka.clients.consumer.KafkaConsumer
import org.apache.kafka.clients.producer.KafkaProducer
import org.apache.kafka.clients.producer.ProducerConfig
import org.apache.kafka.clients.producer.ProducerRecord
import org.apache.kafka.common.serialization.ByteArrayDeserializer
import org.apache.kafka.common.serialization.ByteArraySerializer
import org.apache.kafka.common.serialization.StringDeserializer
import org.apache.kafka.common.serialization.StringSerializer
import org.apache.logging.log4j.LogManager
import org.apache.logging.log4j.Logger
import oteldemo.Demo.*
import java.time.Duration.ofMillis
import java.util.*
import kotlin.system.exitProcess
import dev.openfeature.contrib.providers.flagd.FlagdOptions
import dev.openfeature.contrib.providers.flagd.FlagdProvider
import dev.openfeature.sdk.Client
import dev.openfeature.sdk.EvaluationContext
import dev.openfeature.sdk.ImmutableContext
import dev.openfeature.sdk.Value
import dev.openfeature.sdk.OpenFeatureAPI

const val topic = "orders"
const val groupID = "fraud-detection"

private val logger: Logger = LogManager.getLogger(groupID)

fun main() {
    val options = FlagdOptions.builder()
    .withGlobalTelemetry(true)
    .build()
    val flagdProvider = FlagdProvider(options)
    OpenFeatureAPI.getInstance().setProvider(flagdProvider)

    val props = Properties()
    props[KEY_DESERIALIZER_CLASS_CONFIG] = StringDeserializer::class.java.name
    props[VALUE_DESERIALIZER_CLASS_CONFIG] = ByteArrayDeserializer::class.java.name
    props[GROUP_ID_CONFIG] = groupID
    val bootstrapServers = System.getenv("KAFKA_ADDR")
    if (bootstrapServers == null) {
        println("KAFKA_ADDR is not supplied")
        exitProcess(1)
    }
    props[BOOTSTRAP_SERVERS_CONFIG] = bootstrapServers

    if (System.getenv("KAFKA_TLS") == "true") {
        props["security.protocol"] = "SSL"
    }

    val saslUsername = System.getenv("KAFKA_SASL_USERNAME")
    val saslPassword = System.getenv("KAFKA_SASL_PASSWORD")
    if (!saslUsername.isNullOrBlank() || !saslPassword.isNullOrBlank()) {
        require(!saslUsername.isNullOrBlank() && !saslPassword.isNullOrBlank()) {
            "Both Kafka SCRAM credentials are required"
        }
        props["security.protocol"] = "SASL_SSL"
        props["sasl.mechanism"] = "SCRAM-SHA-512"
        props["sasl.jaas.config"] = "org.apache.kafka.common.security.scram.ScramLoginModule required username=\"$saslUsername\" password=\"$saslPassword\";"
    }

    val consumer = KafkaConsumer<String, ByteArray>(props).apply {
        subscribe(listOf(topic))
    }

    val producerProps = Properties()
    producerProps[ProducerConfig.BOOTSTRAP_SERVERS_CONFIG] = bootstrapServers
    producerProps[ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG] = StringSerializer::class.java.name
    producerProps[ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG] = ByteArraySerializer::class.java.name

    if (System.getenv("KAFKA_TLS") == "true") {
        producerProps["security.protocol"] = "SSL"
    }
    if (!saslUsername.isNullOrBlank() && !saslPassword.isNullOrBlank()) {
        producerProps["security.protocol"] = "SASL_SSL"
        producerProps["sasl.mechanism"] = "SCRAM-SHA-512"
        producerProps["sasl.jaas.config"] = "org.apache.kafka.common.security.scram.ScramLoginModule required username=\"$saslUsername\" password=\"$saslPassword\";"
    }

    val producer = KafkaProducer<String, ByteArray>(producerProps)

    val redisAddr = System.getenv("REDIS_ADDR") ?: "valkey-cart:6379"
    val redisParts = redisAddr.split(":")
    val redisHost = redisParts[0]
    val redisPort = if (redisParts.size > 1) redisParts[1].toInt() else 6379
    logger.info("Connecting to Valkey/Redis at $redisHost:$redisPort")
    val jedis = try {
        redis.clients.jedis.Jedis(redisHost, redisPort).apply {
            ping()
        }
    } catch (e: Exception) {
        logger.error("Could not connect to Valkey/Redis, velocity check will be bypassed: ", e)
        null
    }

    var totalCount = 0L

    consumer.use {
        producer.use {
            jedis?.use {
                while (true) {
                    totalCount = consumer
                        .poll(ofMillis(100))
                        .fold(totalCount) { accumulator, record ->
                            val newCount = accumulator + 1
                            if (getFeatureFlagValue("kafkaQueueProblems") > 0) {
                                logger.info("FeatureFlag 'kafkaQueueProblems' is enabled, sleeping 1 second")
                                Thread.sleep(1000)
                            }
                            val orders = OrderResult.parseFrom(record.value())
                            logger.info("Consumed record with orderId: ${orders.orderId}, and updated total count to: $newCount")

                            // 1. Velocity check per street address
                            val addressKey = orders.shippingAddress.streetAddress
                            var isFraud = false
                            if (addressKey != null && addressKey.isNotBlank()) {
                                try {
                                    val key = "fraud:velocity:${addressKey.replace(" ", "_")}"
                                    val count = jedis.incr(key)
                                    if (count == 1L) {
                                        jedis.expire(key, 3600) // TTL 1 hour
                                    }
                                    if (count > 5) {
                                        isFraud = true
                                        logger.warn("Velocity fraud detected for address '$addressKey': $count orders/hour (Limit: 5).")
                                    }
                                } catch (e: Exception) {
                                    logger.error("Failed to perform velocity check in Valkey, failing open: ", e)
                                }
                            }

                            // 2. Dynamic feature flag score threshold check or amount check
                            val threshold = getFeatureFlagValue("fraud_threshold_score")
                            var totalUnits = orders.shippingCost.units
                            var totalNanos = orders.shippingCost.nanos
                            for (orderItem in orders.itemsList) {
                                val qty = orderItem.item.quantity
                                totalUnits += orderItem.cost.units * qty
                                totalNanos += orderItem.cost.nanos * qty
                            }
                            val totalAmount = totalUnits.toDouble() + (totalNanos.toDouble() / 1_000_000_000.0)

                            val limit = if (threshold > 0) threshold.toDouble() else 1000.0 // default limit to $1000 to avoid false positives in demo
                            if (totalAmount > limit) {
                                isFraud = true
                                logger.warn("Amount fraud detected: Order ${orders.orderId} total amount $totalAmount exceeds limit $limit.")
                            }

                            if (isFraud) {
                                logger.warn("Order ${orders.orderId} rejected. Publishing OrderCancelled event.")
                                val orderCancelled = OrderCancelled.newBuilder()
                                    .setOrderId(orders.orderId)
                                    .setReason("Fraud detected by Velocity Check or Amount Limit ($limit)")
                                    .build()

                                val producerRecord = ProducerRecord<String, ByteArray>(
                                    "orders-cancelled",
                                    orders.orderId,
                                    orderCancelled.toByteArray()
                                )
                                producer.send(producerRecord) { _, exception ->
                                    if (exception != null) {
                                        logger.error("Failed to send OrderCancelled for order: ${orders.orderId}", exception)
                                    } else {
                                        logger.info("Sent OrderCancelled event to orders-cancelled topic for order: ${orders.orderId}")
                                    }
                                }
                            } else {
                                logger.info("Order ${orders.orderId} approved. Publishing OrderApproved event.")
                                val producerRecord = ProducerRecord<String, ByteArray>(
                                    "orders-approved",
                                    orders.orderId,
                                    record.value() // Forward the original OrderResult payload
                                )
                                producer.send(producerRecord) { _, exception ->
                                    if (exception != null) {
                                        logger.error("Failed to send OrderApproved for order: ${orders.orderId}", exception)
                                    } else {
                                        logger.info("Sent OrderApproved event to orders-approved topic for order: ${orders.orderId}")
                                    }
                                }
                            }

                            newCount
                        }
                }
            } ?: run {
                // Valkey/Redis bypass mode
                while (true) {
                    totalCount = consumer
                        .poll(ofMillis(100))
                        .fold(totalCount) { accumulator, record ->
                            val newCount = accumulator + 1
                            if (getFeatureFlagValue("kafkaQueueProblems") > 0) {
                                logger.info("FeatureFlag 'kafkaQueueProblems' is enabled, sleeping 1 second")
                                Thread.sleep(1000)
                            }
                            val orders = OrderResult.parseFrom(record.value())
                            logger.info("Consumed record with orderId: ${orders.orderId}, and updated total count to: $newCount")

                            val threshold = getFeatureFlagValue("fraud_threshold_score")
                            var totalUnits = orders.shippingCost.units
                            var totalNanos = orders.shippingCost.nanos
                            for (orderItem in orders.itemsList) {
                                val qty = orderItem.item.quantity
                                totalUnits += orderItem.cost.units * qty
                                totalNanos += orderItem.cost.nanos * qty
                            }
                            val totalAmount = totalUnits.toDouble() + (totalNanos.toDouble() / 1_000_000_000.0)

                            val limit = if (threshold > 0) threshold.toDouble() else 1000.0
                            val isFraud = totalAmount > limit

                            if (isFraud) {
                                logger.warn("Order ${orders.orderId} rejected. Publishing OrderCancelled event.")
                                val orderCancelled = OrderCancelled.newBuilder()
                                    .setOrderId(orders.orderId)
                                    .setReason("Fraud detected by Amount Limit ($limit)")
                                    .build()

                                val producerRecord = ProducerRecord<String, ByteArray>(
                                    "orders-cancelled",
                                    orders.orderId,
                                    orderCancelled.toByteArray()
                                )
                                producer.send(producerRecord) { _, exception ->
                                    if (exception != null) {
                                        logger.error("Failed to send OrderCancelled for order: ${orders.orderId}", exception)
                                    } else {
                                        logger.info("Sent OrderCancelled event to orders-cancelled topic for order: ${orders.orderId}")
                                    }
                                }
                            } else {
                                logger.info("Order ${orders.orderId} approved. Publishing OrderApproved event.")
                                val producerRecord = ProducerRecord<String, ByteArray>(
                                    "orders-approved",
                                    orders.orderId,
                                    record.value()
                                )
                                producer.send(producerRecord) { _, exception ->
                                    if (exception != null) {
                                        logger.error("Failed to send OrderApproved for order: ${orders.orderId}", exception)
                                    } else {
                                        logger.info("Sent OrderApproved event to orders-approved topic for order: ${orders.orderId}")
                                    }
                                }
                            }

                            newCount
                        }
                }
            }
        }
    }
}


/**
* Retrieves the status of a feature flag from the Feature Flag service.
*
* @param ff The name of the feature flag to retrieve.
* @return `true` if the feature flag is enabled, `false` otherwise or in case of errors.
*/
fun getFeatureFlagValue(ff: String): Int {
    val client = OpenFeatureAPI.getInstance().client
    // TODO: Plumb the actual session ID from the frontend via baggage?
    val uuid = UUID.randomUUID()

    val clientAttrs = mutableMapOf<String, Value>()
    clientAttrs["session"] = Value(uuid.toString())
    client.evaluationContext = ImmutableContext(clientAttrs)
    // BTC original + team local- twin: max so either source can inject.
    val btc = client.getIntegerValue(ff, 0)
    val local = client.getIntegerValue("local-$ff", 0)
    return maxOf(btc, local)
}
// Change trail: @hungxqt - 2026-07-17 - Dual-read local- integer flag twins (max with BTC).
