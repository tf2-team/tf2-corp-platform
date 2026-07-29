// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
package outbox

import (
	"io"
	"log/slog"
)

func newTestLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}
