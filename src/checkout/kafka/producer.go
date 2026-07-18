// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
package kafka

import (
	"fmt"
	"log/slog"

	"github.com/IBM/sarama"
)

var (
	Topic           = "orders"
	ProtocolVersion = sarama.V3_6_0_0
)

type saramaLogger struct {
	logger *slog.Logger
}

func (l *saramaLogger) Printf(format string, v ...interface{}) {
	l.logger.Info(fmt.Sprintf(format, v...))
}
func (l *saramaLogger) Println(v ...interface{}) {
	l.logger.Info(fmt.Sprint(v...))
}
func (l *saramaLogger) Print(v ...interface{}) {
	l.logger.Info(fmt.Sprint(v...))
}

func CreateKafkaProducer(brokers []string, logger *slog.Logger) (sarama.AsyncProducer, error) {
	// Set the logger for sarama to use.
	sarama.Logger = &saramaLogger{logger: logger}

	saramaConfig := sarama.NewConfig()
	saramaConfig.Producer.Return.Successes = true
	saramaConfig.Producer.Return.Errors = true

	// Sarama has an issue in a single broker kafka if the kafka broker is restarted.
	// This setting is to prevent that issue from manifesting itself, but may swallow failed messages.
	saramaConfig.Producer.RequiredAcks = sarama.NoResponse

	saramaConfig.Version = ProtocolVersion

	// SASL requires serialized handshake — only 1 in-flight request during auth.
	saramaConfig.Net.MaxOpenRequests = 1

	// So we can know the partition and offset of messages.
	saramaConfig.Producer.Return.Successes = true

	if err := ConfigureSaramaSecurity(saramaConfig); err != nil {
		return nil, err
	}

	producer, err := sarama.NewAsyncProducer(brokers, saramaConfig)
	if err != nil {
		return nil, err
	}

	// Do not drain producer.Errors() here. Callers (e.g. sendToPostProcessor)
	// select on Successes() and Errors(); a background consumer would race and
	// steal failures so the caller hangs until context cancel.
	return producer, nil
}

// Change trail: @hungxqt - 2026-07-14 - Stop draining Errors in CreateKafkaProducer so callers can observe failures.
