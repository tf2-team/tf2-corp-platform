# Checkout Service

This service provides checkout services for the application.

## Durable Kafka outbox

Set `CHECKOUT_OUTBOX_TABLE` in production to enable the DynamoDB durable
outbox. Checkout persists the protobuf order event under the order ID and
returns without waiting for Kafka. A background worker retries pending records
and deletes them only after broker acknowledgement.

The pod uses the AWS default credential chain; on EKS, configure a dedicated
IRSA ServiceAccount with `PutItem`, `Query`, `UpdateItem`, and `DeleteItem`
limited to the outbox table/index. If the variable is absent, the service keeps
the direct Kafka behavior for local development.

## Local Build

To build the service binary, run:

```sh
go build -o /go/bin/checkout/
```

## Docker Build

From the root directory, run:

```sh
docker compose build checkout
```

## Regenerate protos

To build the protos, run from the root directory:

```sh
make docker-generate-protobuf
```

## Bump dependencies

To bump all dependencies run:

```sh
go get -u -t ./...
go mod tidy
```
