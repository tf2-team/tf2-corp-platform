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
    val consumer = KafkaConsumer<String, ByteArray>(props).apply {
        subscribe(listOf(topic))
    }

    val producerProps = Properties()
    producerProps[ProducerConfig.BOOTSTRAP_SERVERS_CONFIG] = bootstrapServers
    producerProps[ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG] = StringSerializer::class.java.name
    producerProps[ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG] = ByteArraySerializer::class.java.name
    val producer = KafkaProducer<String, ByteArray>(producerProps)

    var totalCount = 0L

    consumer.use {
        producer.use {
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

                        // Fraud detection: check if total cost exceeds $100
                        var totalUnits = orders.shippingCost.units
                        var totalNanos = orders.shippingCost.nanos
                        for (orderItem in orders.itemsList) {
                            val qty = orderItem.item.quantity
                            totalUnits += orderItem.cost.units * qty
                            totalNanos += orderItem.cost.nanos * qty
                        }
                        val totalAmount = totalUnits.toDouble() + (totalNanos.toDouble() / 1_000_000_000.0)

                        if (totalAmount > 100.0) {
                            logger.warn("Fraud detected: Order ${orders.orderId} total amount $totalAmount exceeds $100. Publishing OrderCancelled event.")
                            val orderCancelled = OrderCancelled.newBuilder()
                                .setOrderId(orders.orderId)
                                .setReason("Order total amount $totalAmount exceeds $100 threshold")
                                .build()

                            val producerRecord = ProducerRecord<String, ByteArray>(
                                "orders-cancelled",
                                orders.orderId,
                                orderCancelled.toByteArray()
                            )
                            producer.send(producerRecord) { metadata, exception ->
                                if (exception != null) {
                                    logger.error("Failed to send OrderCancelled for order: ${orders.orderId}", exception)
                                } else {
                                    logger.info("Sent OrderCancelled event to orders-cancelled topic for order: ${orders.orderId}")
                                }
                            }
                        }

                        newCount
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
    val intValue = client.getIntegerValue(ff, 0)
    return intValue
}
