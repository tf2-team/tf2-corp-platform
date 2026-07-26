// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

using Microsoft.Extensions.Logging;
using Oteldemo;

namespace Accounting
{
    internal static partial class Log
    {
        [LoggerMessage(
            Level = LogLevel.Information,
            Message = "Order details: {@OrderResult}.")]
        public static partial void OrderReceivedMessage(ILogger logger, OrderResult orderResult);

        [LoggerMessage(
            Level = LogLevel.Information,
            Message = "Successfully completed shipment and updated order {orderId} status to COMPLETED.")]
        public static partial void ShipmentCompleted(ILogger logger, string orderId);

        [LoggerMessage(
            Level = LogLevel.Information,
            Message = "Published RDS persistence acknowledgement for order {orderId}.")]
        public static partial void PersistenceAckPublished(ILogger logger, string orderId);

        [LoggerMessage(
            Level = LogLevel.Information,
            Message = "Replayed RDS persistence ACK for stale outbox event {orderId}.")]
        public static partial void PersistenceAckReplayed(ILogger logger, string orderId);
    }
}
