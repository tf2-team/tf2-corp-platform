# MSK SCRAM client authentication

Checkout, Accounting, and Fraud Detection now support SASL/SCRAM-SHA-512 over
TLS for Amazon MSK. Checkout applies one shared Sarama security configuration
to its producer and consumer group, validates that both credentials are
present, requires TLS 1.2 or newer, and no longer disables certificate
verification. Accounting and Fraud Detection apply the equivalent native
client settings.

Local development remains compatible: when SCRAM variables are absent, clients
retain their existing in-cluster Kafka behavior. Production injects usernames
and passwords from the ESO-managed `techx-corp-msk` Secret.

