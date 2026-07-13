# Signal Catalog for AIOps (TF2 / AIO4)

This catalog inventories all telemetry signals (Prometheus metrics, Jaeger trace attributes, and OpenSearch log fields) available in the **TechX Corp Platform** relevant to AIOps anomaly detection, RCA, and automated remediation.

---

## 🗂️ Table of Contents
1. [Core Latency (p50 / p95 / p99)](#1-core-latency-p50--p95--p99)
2. [Service Error Rate (5xx / Errors)](#2-service-error-rate-5xx--errors)
3. [Saturation (CPU / Memory / Connection Pool)](#3-saturation-cpu--memory--connection-pool)
4. [Queue Lag (Kafka Consumer Lag)](#4-queue-lag-kafka-consumer-lag)
5. [AI-Specific Telemetry (LLM Latency, Tokens, Errors)](#5-ai-specific-telemetry-llm-latency-tokens-errors)

---

## 1. Core Latency (p50 / p95 / p99)
Monitors the execution duration of microservices at gRPC, HTTP, and internal span levels.

### A. Prometheus Metrics
| Metric Name | Source / Receiver | Unit | Description |
| :--- | :--- | :--- | :--- |
| `rpc_server_duration_milliseconds_bucket` | OTel Collector (gRPC auto-instr) | ms | Histogram of incoming gRPC request durations |
| `http_server_request_duration_seconds_bucket` | OTel Collector (Flask/HTTP) | seconds | Histogram of incoming HTTP request durations |
| `traces_span_metrics_duration_milliseconds_bucket` | Spanmetrics Connector | ms | Histogram of span durations automatically generated for all traced functions/services |

#### PromQL Query Examples
*   **p95 Latency by Service (gRPC):**
    ```promql
    histogram_quantile(0.95, sum(rate(rpc_server_duration_milliseconds_bucket[5m])) by (le, service_name))
    ```
*   **p99 Latency by Endpoint (Spanmetrics):**
    ```promql
    histogram_quantile(0.99, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name="product-reviews"}[5m])) by (le, span_name))
    ```

### B. Jaeger Trace Attributes
| Attribute Key | Type | Example | Description |
| :--- | :--- | :--- | :--- |
| `duration` | Integer (µs) | `45000` (45ms) | Total execution time of the span |
| `http.route` | String | `/api/checkout` | HTTP route being serviced |
| `rpc.method` | String | `GetProduct` | gRPC method name |
| `service.name` | String | `payment-svc` | Name of the service emitting the span |

### C. OpenSearch Log Fields
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `request_time` | Float | HTTP response time in seconds (recorded in Nginx access logs) |
| `duration_ms` | Float | Request processing time in milliseconds (recorded in application log JSONs) |

---

## 2. Service Error Rate (5xx / Errors)
Tracks the frequency and ratio of failures to establish service health baselines.

### A. Prometheus Metrics
| Metric Name | Source / Receiver | Unit | Description |
| :--- | :--- | :--- | :--- |
| `rpc_server_duration_milliseconds_count` | OTel Collector (gRPC) | count | Total count of gRPC requests. Error filtering is done via status codes |
| `http_server_request_duration_seconds_count` | OTel Collector (HTTP) | count | Total count of HTTP requests. Error filtering is done via status codes |
| `traces_span_metrics_calls_total` | Spanmetrics Connector | count | Total trace calls. Includes status code attributes |

#### PromQL Query Examples
*   **HTTP 5xx Error Rate per Service:**
    ```promql
    sum(rate(http_server_request_duration_seconds_count{http_response_status_code=~"5.."}[5m])) by (service_name)
    ```
*   **gRPC Error Ratio by Method:**
    ```promql
    sum(rate(rpc_server_duration_milliseconds_count{rpc_grpc_status_code!="0"}[5m])) by (service_name, rpc_method) 
    / 
    sum(rate(rpc_server_duration_milliseconds_count[5m])) by (service_name, rpc_method)
    ```
*   **Traces Span Failure Rate (Global):**
    ```promql
    sum(rate(traces_span_metrics_calls_total{status_code="STATUS_CODE_ERROR"}[5m])) by (service_name)
    ```

### B. Jaeger Trace Attributes
| Attribute Key | Type | Value | Description |
| :--- | :--- | :--- | :--- |
| `otel.status_code` | String | `"ERROR"` | Explicit marker indicating the span failed |
| `error` | Boolean | `true` | Indicates the operation encountered an unhandled error |
| `exception.type` | String | `"ValueError"` | The class/type of exception captured |
| `exception.message` | String | `"product ID not found"` | Detailed error message |
| `exception.stacktrace`| String | `Traceback (most...)` | Complete stack trace of the failure |

### C. OpenSearch Log Fields
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `severity_text` | String | Log level. Anomalies focus on `"ERROR"`, `"CRITICAL"`, and `"FATAL"` |
| `body.message` | String | Text body containing error keywords (`Exception`, `Failed`, `Timeout`, `OOM`) |
| `http_response_status_code` | Integer | HTTP status code parsed into logs |

---

## 3. Saturation (CPU / Memory / Connection Pool)
Identifies resource constraints before they lead to service degradation (critical for RCA of cascading failures).

### A. Prometheus Metrics
| Metric Name | Source / Receiver | Unit | Description |
| :--- | :--- | :--- | :--- |
| `system_cpu_utilization_ratio` | OTel hostmetrics | ratio | CPU utilization on the host node (excluding `state="idle"`) |
| `system_cpu_load_average_5m` | OTel hostmetrics | load | 5-minute CPU load average |
| `system_memory_utilization_ratio`| OTel hostmetrics | ratio | Host memory utilization ratio |
| `system_memory_usage_bytes` | OTel hostmetrics | bytes | Host memory usage (by state: `used`, `free`, `cached`, `buffered`) |
| `container.cpu.usage.system` | OTel docker_stats | ratio | CPU usage of specific container |
| `container.memory.usage.limit` | OTel docker_stats | bytes | Memory usage limit of specific container |
| `postgresql_backends` | OTel postgresql | count | Number of active backends/connections on the PostgreSQL server |
| `db_client_connections_usage` | `otelsql` (Go Client) | count | Number of connections currently active in the service's database pool |
| `db_client_connections_max` | `otelsql` (Go Client) | count | Maximum database connections configured in the pool |
| `db_client_connections_wait_total`| `otelsql` (Go Client) | ns | Cumulative wait time for database connections |

#### PromQL Query Examples
*   **Database Connection Pool Saturation Ratio (Client-Side):**
    ```promql
    sum(db_client_connections_usage) by (service_name) / sum(db_client_connections_max) by (service_name)
    ```
*   **Active Postgres Server Connections:**
    ```promql
    postgresql_backends{postgresql_database_name="reviews"}
    ```
*   **Host CPU Utilization Percentage:**
    ```promql
    sum(system_cpu_utilization_ratio{state!="idle"}) by (host_name) * 100
    ```

### B. Jaeger Trace Attributes
| Attribute Key | Type | Example | Description |
| :--- | :--- | :--- | :--- |
| `db.system` | String | `"postgresql"` | Database engine type |
| `db.name` | String | `"reviews"` | Database name called in SQL span |
| `db.connection.wait_ms`| Integer | `120` | Client wait time to acquire a connection from the pool (if tracked) |

### C. OpenSearch Log Fields
| Field Name | Type | Matching Log Query Pattern | Description |
| :--- | :--- | :--- | :--- |
| `body.message` | String | `"connection pool exhausted"` \| `"too many clients already"` | Pool exhaustion logs in Go client or postgres |
| `body.message` | String | `"Out of Memory"` \| `"OOM"` \| `"exit code 137"` | Container OOM killed indications |

---

## 4. Queue Lag (Kafka Consumer Lag)
Monitors streaming queue delays between producer and consumer services.

### A. Prometheus Metrics
| Metric Name | Source / Receiver | Unit | Description |
| :--- | :--- | :--- | :--- |
| `kafka_consumer_group_lag` | `kafkametrics` | messages | Number of messages consumer group is behind broker per partition |
| `kafka_consumer_group_lag_sum` | `kafkametrics` | messages | Total consumer group lag across all partitions |
| `kafka_topic_partition_offset` | `kafkametrics` | offset | Latest message offset written on the broker |
| `kafka_consumer_group_offset` | `kafkametrics` | offset | Consumer group's currently committed offset |

#### PromQL Query Examples
*   **Total Lag by Consumer Group:**
    ```promql
    sum(kafka_consumer_group_lag) by (group, topic)
    ```
*   **Consumer Group Offsets Rate vs Broker Write Rate:**
    ```promql
    # Positive values indicate consumer is lagging behind incoming traffic
    sum(rate(kafka_topic_partition_offset[5m])) by (topic) - sum(rate(kafka_consumer_group_offset[5m])) by (group, topic)
    ```

### B. Jaeger Trace Attributes
| Attribute Key | Type | Example | Description |
| :--- | :--- | :--- | :--- |
| `messaging.system` | String | `"kafka"` | Messaging broker protocol |
| `messaging.destination` | String | `"orders"` | Kafka topic name |
| `messaging.operation` | String | `"process"` \| `"publish"` | Messaging operation context |
| `messaging.kafka.message.offset` | Integer | `4523` | Specific offset of the message in partition |
| `messaging.kafka.destination.partition`| Integer | `2` | Partition index inside the topic |
| `messaging.kafka.producer.success` | Boolean | `true` | Success status of checkout sending orders to Kafka |
| `messaging.kafka.producer.duration_ms`| Integer | `12` | Network/broker write latency for the message |

### C. OpenSearch Log Fields
| Field Name | Type | Matching Log Query Pattern | Description |
| :--- | :--- | :--- | :--- |
| `body.message` | String | `"Failed to send message to Kafka"` | Producer-side publish errors |
| `body.message` | String | `"consumer lag too high"` \| `"rebalancing"` | Consumer-side group issues |

---

## 5. AI-Specific Telemetry (LLM Latency, Tokens, Errors)
Tracks metrics on OpenAI/LLM API client operations in `product-reviews` calling `llm` (generates AI reviews summary).

### A. Prometheus Metrics
| Metric Name | Source / Receiver | Unit | Description |
| :--- | :--- | :--- | :--- |
| `gen_ai_client_operation_duration_milliseconds_bucket` | OTel auto-instr (OpenAI) | ms | Latency of completions request to LLM |
| `gen_ai_client_token_usage_total` | OTel auto-instr (OpenAI) | tokens | Total tokens consumed (prompt and completion tokens) |
| `app_ai_assistant_counter_total` | `product-reviews` (custom) | count | Number of AI Assistant requests handled by the service |

#### PromQL Query Examples
*   **LLM Latency (p99) on Reviews Assistant:**
    ```promql
    histogram_quantile(0.99, sum(rate(gen_ai_client_operation_duration_milliseconds_bucket[5m])) by (le, model))
    ```
*   **LLM Token Consumption Rate (Tokens/sec):**
    ```promql
    sum(rate(gen_ai_client_token_usage_total[5m])) by (token_type, model)
    ```
*   **LLM API Client Error Rate:**
    ```promql
    sum(rate(gen_ai_client_operation_duration_count{status_code="error"}[5m])) / sum(rate(gen_ai_client_operation_duration_count[5m]))
    ```

### B. Jaeger Trace Attributes
Standard `gen_ai` OTel attributes captured on the outbound HTTP calls:
| Attribute Key | Type | Example | Description |
| :--- | :--- | :--- | :--- |
| `gen_ai.system` | String | `"openai"` | AI provider system |
| `gen_ai.request.model` | String | `"techx-llm"` | LLM model targeted by application |
| `gen_ai.usage.prompt_tokens` | Integer | `350` | Input tokens count in prompt |
| `gen_ai.usage.completion_tokens` | Integer | `75` | Output tokens count returned by LLM |
| `gen_ai.usage.total_tokens` | Integer | `425` | Total token usage |
| `gen_ai.choice.finish_reason` | String | `"stop"` \| `"length"` | Generation terminal state reason |

Custom Business-layer Trace Attributes added inside `product-reviews` server (`get_ai_assistant_response` span):
| Attribute Key | Type | Example | Description |
| :--- | :--- | :--- | :--- |
| `app.product.id` | String | `"L9ECAV7KIM"` | Product ID requested for summary |
| `app.product.question` | String | `"Were there negative reviews?"` | User question to the AI |
| `app.product_reviews.count` | Integer | `5` | Total reviews fetched and fed to prompt |
| `app.product_reviews.average_score` | Float | `4.2` | Average rating of product reviews |

### C. OpenSearch Log Fields
| Field Name | Type | Matching Log Query Pattern | Description |
| :--- | :--- | :--- | :--- |
| `body.message` | String | `"Rate limit reached. Please try again later."` | LLM rate limit 429 response |
| `body.message` | String | `"openai.RateLimitError"` \| `"openai.APITimeoutError"` | Python client-side exceptions from openai library |
| `body.message` | String | `"llmInaccurateResponse feature flag: True"` | Feature flag hook state audits |
