# Checkout durable Kafka outbox

Production checkout no longer waits for Kafka before returning an order.

- `CHECKOUT_OUTBOX_TABLE` enables a DynamoDB-backed durable outbox.
- The order ID is used as the idempotency key.
- A background worker queries pending events, publishes to Kafka, and deletes
  the record only after broker acknowledgement.
- Kafka producer creation is retried by the worker after broker recovery.
- Without `CHECKOUT_OUTBOX_TABLE`, development retains the prior direct Kafka
  path for local compatibility.
- The duplicate blocking `grpc.Server.Serve` call was removed so SIGTERM reaches
  `GracefulStop` during Kubernetes maintenance.

The application uses the AWS default credential chain. Production supplies a
dedicated checkout ServiceAccount annotated with a least-privilege IRSA role.
