# Change: retain checkout outbox events until RDS persistence ACK

## Summary

Checkout no longer deletes a DynamoDB outbox event when Kafka merely accepts
the `orders` message. The worker changes the event from `pending` to
`published`. Accounting writes the order to PostgreSQL and then publishes an
`orders-persisted` acknowledgement containing the order ID. Checkout consumes
that acknowledgement and only then deletes the DynamoDB item.

## Delivery contract

1. Checkout writes the order event to DynamoDB with status `pending`.
2. The outbox worker publishes `orders` to MSK and changes the item to
   `published`; it does not delete the item.
3. Accounting consumes `orders` and commits the PostgreSQL write.
4. Accounting publishes `orders-persisted` with `acks=all` and idempotence.
5. Accounting commits the consumed Kafka offset only after the persistence ACK
   is delivered.
6. Checkout consumes the ACK and deletes the matching DynamoDB outbox item.

Accounting also runs an in-process reconciler every five minutes. It queries
the `published` GSI partition and examines only events older than 15 minutes:

- If the order exists in RDS, it replays `orders-persisted`.
- If the order does not exist in RDS, it conditionally changes the event back
  to `pending`, allowing the checkout worker to republish it.

The conditional update includes the observed `published_at`, so a concurrent
ACK or reconciliation cannot overwrite newer state.

An RDS or ACK publication failure leaves both the Kafka offset uncommitted and
the DynamoDB item intact. Accounting seeks back to the failed offset for an
immediate bounded retry. A replay after an ambiguous failure is safe: if the
order already exists in PostgreSQL, accounting publishes the ACK again without
inserting duplicate rows.

## Deployment

Create the `orders-persisted` MSK topic with the same partition and replication
policy as the other order lifecycle topics before deploying the new accounting
and checkout images. Apply the commerce-ha Terraform change to create the
accounting reconciler IRSA role, deploy the chart ServiceAccount annotation,
then deploy accounting first and checkout second.

## Verification

- Stop or deny RDS writes and submit an order: the DynamoDB item remains
  `published`, no `orders-persisted` ACK is emitted, and accounting does not
  commit the input offset.
- Restore RDS, allow replay, and verify the order exists in PostgreSQL before
  the matching DynamoDB item disappears.
- Restart accounting after PostgreSQL commit but before offset commit and
  confirm replay emits another ACK without duplicate accounting rows.
