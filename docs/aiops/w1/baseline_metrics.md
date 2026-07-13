# TechX Corp Platform - AIOps Baseline Metrics & Discovery

This document records the baseline metrics, request flows, and traffic analysis of the TechX Corp Platform. Use these PromQL queries in the Grafana **Explore** view to find the baseline performance and error metrics.

### 📊 PromQL Queries for Baseline Estimation

Use these queries in Grafana **Explore** with the Prometheus data source. Query one service at a time by replacing `<service>` with the target service name.

Recommended window: `[5m]`. If traffic is low or bursty, also record `[15m]`.

1. **QPS (Requests/second) for one service**

   Use this for both gRPC and HTTP services:
   ```promql
   sum(rate(traces_span_metrics_calls_total{service_name="<service>", span_kind="SPAN_KIND_SERVER"}[5m]))
   ```

2. **Error Rate (%) for one service**

   Use this for both gRPC and HTTP services:
   ```promql
   (
     sum(rate(traces_span_metrics_calls_total{service_name="<service>", span_kind="SPAN_KIND_SERVER", status_code="STATUS_CODE_ERROR"}[5m]))
     /
     sum(rate(traces_span_metrics_calls_total{service_name="<service>", span_kind="SPAN_KIND_SERVER"}[5m]))
   ) * 100
   ```

3. **Latency p50 / p95 / p99 for one service**

   Use these for both gRPC and HTTP services. Result is milliseconds.

   p50:
   ```promql
   histogram_quantile(0.50, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name="<service>", span_kind="SPAN_KIND_SERVER"}[5m])) by (le))
   ```

   p95:
   ```promql
   histogram_quantile(0.95, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name="<service>", span_kind="SPAN_KIND_SERVER"}[5m])) by (le))
   ```

   p99:
   ```promql
   histogram_quantile(0.99, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name="<service>", span_kind="SPAN_KIND_SERVER"}[5m])) by (le))
   ```

4. **Checkout `PlaceOrder` baseline**

   Use these for the checkout-specific baseline used by OPS-01. Result is milliseconds.

   p50:
   ```promql
   histogram_quantile(0.50, sum(rate(rpc_server_duration_milliseconds_bucket{service_name="checkout", rpc_method="PlaceOrder"}[5m])) by (le))
   ```

   p95:
   ```promql
   histogram_quantile(0.95, sum(rate(rpc_server_duration_milliseconds_bucket{service_name="checkout", rpc_method="PlaceOrder"}[5m])) by (le))
   ```

   p99:
   ```promql
   histogram_quantile(0.99, sum(rate(rpc_server_duration_milliseconds_bucket{service_name="checkout", rpc_method="PlaceOrder"}[5m])) by (le))
   ```

   error rate:
   ```promql
   (
     sum(rate(rpc_server_duration_milliseconds_count{service_name="checkout", rpc_method="PlaceOrder", rpc_grpc_status_code!="0"}[5m]))
     /
     sum(rate(rpc_server_duration_milliseconds_count{service_name="checkout", rpc_method="PlaceOrder"}[5m]))
   ) * 100
   ```

   Note: `rpc_server_duration_milliseconds_*` is in milliseconds. For a 3 second alert threshold, compare p95 with `> 3000`, not `> 3`.

---

## 1. 🛒 Storefront & Test Order Verification
* **Timestamp of Test Order:** July 9 2026, 23:40:41.093
* **Order ID:** f26f4303-7bb4-11f1-add1-32764887a2ea
* **Observations:** 
  - AI product review summaries successfully viewed: `Yes`
  - Items successfully added to cart: `Yes`
  - Checkout and payment successfully completed: `Yes`

---

## 2. 🔗 Jaeger Request Tracing (Checkout Flow)
* **Trace ID of Test Order:** 182cb790ab365c1fc9cf14ece08a1c9b
* **Service Flow:** `frontend` $\rightarrow$ `checkout` $\rightarrow$ `payment`
* **Asynchronous Flow:** `checkout` $\rightarrow$ `kafka` $\rightarrow$ `accounting`
* **Jaeger Metrics Observed:**
  - Total latency of checkout request: 5.44s

---



## 📈 Baseline Metrics Table

| Service | QPS (Requests/sec) | Error Rate (%) | p50 Latency (ms) | p95 Latency (ms) | p99 Latency (ms) |
|---|---|---|---|---|---|
| **frontend** |0.0184|n/a|7.75|15000|15000|
| **checkout** |3.16|7.87|2000|8420|10200|
| **product-reviews** |1.8|n/a|3420|8500|9700|
| **cart** |10.2|n/a|20.2|91|198|
| **payment** |2.94|0|1.2|9.76|43.5|

---

## 🎯 4. Load-Generator Analysis
Use the **Locust** interface at `http://localhost:8080/loadgen/` and the Request Rate query above to identify active traffic routes.

1. **Locust Configuration:**
   - Active Users count: `10`
   - Spawn Rate: `1` user/second
2. **Traffic Identification:**
   - Which services are receiving continuous synthetic traffic from the load-generator?
     `[x] frontend`
     `[x] product-catalog`
     `[x] recommendation`
     `[x] ad`
     `[x] cart`
     `[x] checkout`
     `[x] payment`
     `[x] product-reviews`
   - Which services remain idle (QPS ≈ 0) unless a manual action is performed?
     - `image-provider` (only loads static assets during full browser simulation, very low traffic)
     - `flagd-ui` / `flagd` (read-only configuration fetch, does not receive direct user traffic)
     - `llm` (only active when AI reviews/assistant are triggered via `product-reviews`, which occurs in low-frequency tasks)
