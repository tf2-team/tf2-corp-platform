---
runbookId: RB-KAFKA-PIPELINE
owner: platform-oncall
---

# Kafka Async Pipeline

## Scope

Use this runbook for Kafka, checkout outbox, accounting/fraud consumers, consumer lag, or async processing failures.

## First checks

- Check producer error rates in checkout and consumer error rates in accounting/fraud-detection/email.
- Check consumer lag, topic availability, broker health, and auth/TLS errors.
- Check outbox backlog and whether synchronous checkout path is affected.
- Check recent deploys or schema/config changes in producers and consumers.

## Do not do

- Do not mutate Kafka or brokers from AIOps.
- Do not reset consumer offsets without owner approval.
- Do not restart all consumers at once; this can increase lag and duplicate work.

## Safe actions

- Page `platform-oncall` and the owning service team for the failing producer/consumer.
- Restart a stateless consumer only as a dry-run recommendation unless an approved rollout exists.
- Prefer pausing/replaying through approved Kafka operational tooling.

## Escalation

Escalate with topic, consumer group, lag, first failing timestamp, and recent deploys.

