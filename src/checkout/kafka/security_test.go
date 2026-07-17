package kafka

import (
	"testing"

	"github.com/IBM/sarama"
)

func TestConfigureSaramaSecurityTLSAndSCRAM(t *testing.T) {
	t.Setenv("KAFKA_TLS", "true")
	t.Setenv("KAFKA_SASL_USERNAME", "app")
	t.Setenv("KAFKA_SASL_PASSWORD", "secret")

	config := sarama.NewConfig()
	if err := ConfigureSaramaSecurity(config); err != nil {
		t.Fatalf("ConfigureSaramaSecurity() error = %v", err)
	}
	if !config.Net.TLS.Enable || config.Net.TLS.Config == nil {
		t.Fatal("TLS was not enabled")
	}
	if config.Net.TLS.Config.InsecureSkipVerify {
		t.Fatal("TLS certificate verification must remain enabled")
	}
	if !config.Net.SASL.Enable || config.Net.SASL.Mechanism != sarama.SASLTypeSCRAMSHA512 {
		t.Fatal("SCRAM-SHA-512 was not enabled")
	}
}

func TestConfigureSaramaSecurityRejectsPartialCredentials(t *testing.T) {
	t.Setenv("KAFKA_SASL_USERNAME", "app")
	t.Setenv("KAFKA_SASL_PASSWORD", "")

	if err := ConfigureSaramaSecurity(sarama.NewConfig()); err == nil {
		t.Fatal("expected incomplete SCRAM credentials to fail")
	}
}
