package kafka

import (
	"crypto/tls"
	"fmt"
	"os"

	"github.com/IBM/sarama"
	"github.com/xdg-go/scram"
)

type scramClient struct {
	client *scram.Client
	conv   *scram.ClientConversation
}

func (x *scramClient) Begin(userName, password, authzID string) error {
	client, err := scram.SHA512.NewClient(userName, password, authzID)
	if err != nil {
		return err
	}
	x.client = client
	x.conv = client.NewConversation()
	return nil
}

func (x *scramClient) Step(challenge string) (string, error) {
	return x.conv.Step(challenge)
}

func (x *scramClient) Done() bool { return x.conv.Done() }

// ConfigureSaramaSecurity applies the same verified TLS and SCRAM contract to
// the checkout producer and consumer group. Empty SCRAM variables keep local
// development compatible with the unauthenticated in-cluster broker.
func ConfigureSaramaSecurity(config *sarama.Config) error {
	if os.Getenv("KAFKA_TLS") == "true" {
		config.Net.TLS.Enable = true
		config.Net.TLS.Config = &tls.Config{MinVersion: tls.VersionTLS12}
	}

	username := os.Getenv("KAFKA_SASL_USERNAME")
	password := os.Getenv("KAFKA_SASL_PASSWORD")
	if username == "" && password == "" {
		return nil
	}
	if username == "" || password == "" {
		return fmt.Errorf("both KAFKA_SASL_USERNAME and KAFKA_SASL_PASSWORD are required")
	}

	config.Net.SASL.Enable = true
	config.Net.SASL.User = username
	config.Net.SASL.Password = password
	config.Net.SASL.Mechanism = sarama.SASLTypeSCRAMSHA512
	config.Net.SASL.SCRAMClientGeneratorFunc = func() sarama.SCRAMClient { return &scramClient{} }
	return nil
}
