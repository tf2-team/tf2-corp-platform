// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

using Confluent.Kafka;
using Microsoft.Extensions.Logging;
using Oteldemo;
using Microsoft.EntityFrameworkCore;
using System.Diagnostics;

namespace Accounting;

internal class DBContext : DbContext
{
    public DbSet<OrderEntity> Orders { get; set; }
    public DbSet<OrderItemEntity> CartItems { get; set; }
    public DbSet<ShippingEntity> Shipping { get; set; }

    protected override void OnConfiguring(DbContextOptionsBuilder optionsBuilder)
    {
        var connectionString = Environment.GetEnvironmentVariable("DB_CONNECTION_STRING");

        optionsBuilder.UseNpgsql(connectionString).UseSnakeCaseNamingConvention();
    }
}


internal class Consumer : IDisposable
{
    private static readonly string[] SubscribedTopics = new[] { "orders", "orders-cancelled", "orders-shipped" };

    private ILogger _logger;
    private IConsumer<string, byte[]> _consumer;
    private bool _isListening;
    private static readonly ActivitySource MyActivitySource = new("Accounting.Consumer");

    public Consumer(ILogger<Consumer> logger)
    {
        _logger = logger;

        var servers = Environment.GetEnvironmentVariable("KAFKA_ADDR")
            ?? throw new InvalidOperationException("The KAFKA_ADDR environment variable is not set.");

        _consumer = BuildConsumer(servers);
        _consumer.Subscribe(SubscribedTopics);

       if (_logger.IsEnabled(LogLevel.Information))
       {
           _logger.LogInformation("Connecting to Kafka: {servers}", servers);
       }
    }

    public void StartListening()
    {
        _isListening = true;

        try
        {
            while (_isListening)
            {
                try
                {
                    using var activity = MyActivitySource.StartActivity("order-consumed",  ActivityKind.Internal);
                    var consumeResult = _consumer.Consume();
                    if (consumeResult.Topic == "orders")
                    {
                        ProcessMessage(consumeResult.Message);
                    }
                    else if (consumeResult.Topic == "orders-cancelled")
                    {
                        ProcessCancelledMessage(consumeResult.Message);
                    }
                    else if (consumeResult.Topic == "orders-shipped")
                    {
                        ProcessShippedMessage(consumeResult.Message);
                    }
                }
                catch (ConsumeException e)
                {
                    if (_logger.IsEnabled(LogLevel.Error))
                    {
                        _logger.LogError(e, "Consume error: {reason}", e.Error.Reason);
                    }
                }
            }
        }
        catch (OperationCanceledException)
        {
            _logger.LogInformation("Closing consumer");

            _consumer.Close();
        }
    }

    private void ProcessMessage(Message<string, byte[]> message)
    {
        try
        {
            var order = OrderResult.Parser.ParseFrom(message.Value);
            Log.OrderReceivedMessage(_logger, order);

            if (Environment.GetEnvironmentVariable("DB_CONNECTION_STRING") == null)
            {
                return;
            }

            using var dbContext = new DBContext();
            var existingOrder = dbContext.Orders.Find(order.OrderId);
            if (existingOrder != null)
            {
                _logger.LogWarning("Order {orderId} already exists in database. Skipping duplicate processing.", order.OrderId);
                return;
            }

            var orderEntity = new OrderEntity
            {
                Id = order.OrderId,
                Status = "PENDING"
            };
            dbContext.Add(orderEntity);
            foreach (var item in order.Items)
            {
                var orderItem = new OrderItemEntity
                {
                    ItemCostCurrencyCode = item.Cost.CurrencyCode,
                    ItemCostUnits = item.Cost.Units,
                    ItemCostNanos = item.Cost.Nanos,
                    ProductId = item.Item.ProductId,
                    Quantity = item.Item.Quantity,
                    OrderId = order.OrderId,
                    TransactionType = "CHARGE"
                };

                dbContext.Add(orderItem);
            }

            var shipping = new ShippingEntity
            {
                ShippingTrackingId = order.ShippingTrackingId,
                ShippingCostCurrencyCode = order.ShippingCost.CurrencyCode,
                ShippingCostUnits = order.ShippingCost.Units,
                ShippingCostNanos = order.ShippingCost.Nanos,
                StreetAddress = order.ShippingAddress.StreetAddress,
                City = order.ShippingAddress.City,
                State = order.ShippingAddress.State,
                Country = order.ShippingAddress.Country,
                ZipCode = order.ShippingAddress.ZipCode,
                OrderId = order.OrderId,
                TransactionType = "CHARGE"
            };
            dbContext.Add(shipping);
            dbContext.SaveChanges();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Order parsing failed:");
        }
    }

    private void ProcessCancelledMessage(Message<string, byte[]> message)
    {
        try
        {
            var cancelled = OrderCancelled.Parser.ParseFrom(message.Value);
            if (_logger.IsEnabled(LogLevel.Information))
            {
                _logger.LogInformation("OrderCancelled message received for OrderId: {orderId}, Reason: {reason}", cancelled.OrderId, cancelled.Reason);
            }

            if (Environment.GetEnvironmentVariable("DB_CONNECTION_STRING") == null)
            {
                return;
            }

            using var dbContext = new DBContext();
            var order = dbContext.Orders.Find(cancelled.OrderId);
            if (order == null)
            {
                _logger.LogWarning("Order {orderId} not found in database for cancellation.", cancelled.OrderId);
                return;
            }

            if (order.Status == "CANCELLED" || order.Status == "REFUNDED")
            {
                _logger.LogWarning("Order {orderId} is already in status {status}. Skipping duplicate cancellation.", cancelled.OrderId, order.Status);
                return;
            }

            order.Status = "CANCELLED";

            // Find existing CHARGE records to reverse
            var originalItems = dbContext.CartItems.Where(x => x.OrderId == cancelled.OrderId && x.TransactionType == "CHARGE").ToList();
            var originalShipping = dbContext.Shipping.Where(x => x.OrderId == cancelled.OrderId && x.TransactionType == "CHARGE").ToList();

            if (originalItems.Count == 0 && originalShipping.Count == 0)
            {
                _logger.LogWarning("Original order items or shipping not found for cancelled order: {orderId}", cancelled.OrderId);
                return;
            }

            foreach (var item in originalItems)
            {
                var refundItem = new OrderItemEntity
                {
                    ItemCostCurrencyCode = item.ItemCostCurrencyCode,
                    ItemCostUnits = -item.ItemCostUnits,
                    ItemCostNanos = -item.ItemCostNanos,
                    ProductId = item.ProductId,
                    Quantity = -item.Quantity,
                    OrderId = item.OrderId,
                    TransactionType = "REFUND"
                };
                dbContext.Add(refundItem);
            }

            foreach (var shipping in originalShipping)
            {
                var refundShipping = new ShippingEntity
                {
                    ShippingTrackingId = shipping.ShippingTrackingId,
                    ShippingCostCurrencyCode = shipping.ShippingCostCurrencyCode,
                    ShippingCostUnits = -shipping.ShippingCostUnits,
                    ShippingCostNanos = -shipping.ShippingCostNanos,
                    StreetAddress = shipping.StreetAddress,
                    City = shipping.City,
                    State = shipping.State,
                    Country = shipping.Country,
                    ZipCode = shipping.ZipCode,
                    OrderId = shipping.OrderId,
                    TransactionType = "REFUND"
                };
                dbContext.Add(refundShipping);
            }

            dbContext.SaveChanges();
            if (_logger.IsEnabled(LogLevel.Information))
            {
                _logger.LogInformation("Successfully recorded compensating transaction (REFUND) for order: {orderId}", cancelled.OrderId);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to process cancelled order message:");
        }
    }

    private void ProcessShippedMessage(Message<string, byte[]> message)
    {
        try
        {
            var order = OrderResult.Parser.ParseFrom(message.Value);
            if (_logger.IsEnabled(LogLevel.Information))
            {
                _logger.LogInformation("OrderShipped message received for OrderId: {orderId}, TrackingId: {trackingId}", order.OrderId, order.ShippingTrackingId);
            }

            if (Environment.GetEnvironmentVariable("DB_CONNECTION_STRING") == null)
            {
                return;
            }

            using var dbContext = new DBContext();
            var orderEntity = dbContext.Orders.Find(order.OrderId);
            if (orderEntity == null)
            {
                _logger.LogWarning("Order {orderId} not found for shipment completion.", order.OrderId);
                return;
            }

            if (orderEntity.Status == "COMPLETED" || orderEntity.Status == "CANCELLED")
            {
                _logger.LogWarning("Order {orderId} is already in status {status}. Skipping shipment update.", order.OrderId, orderEntity.Status);
                return;
            }

            orderEntity.Status = "COMPLETED";

            // Update shipping tracking id
            var shippingRecords = dbContext.Shipping.Where(x => x.OrderId == order.OrderId && x.TransactionType == "CHARGE").ToList();
            foreach (var ship in shippingRecords)
            {
                ship.ShippingTrackingId = order.ShippingTrackingId;
            }

            dbContext.SaveChanges();
            _logger.LogInformation("Successfully completed shipment and updated order {orderId} status to COMPLETED.", order.OrderId);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to process shipped order message:");
        }
    }

    private static IConsumer<string, byte[]> BuildConsumer(string servers)
    {
        var conf = new ConsumerConfig
        {
            GroupId = $"accounting",
            BootstrapServers = servers,
            // https://github.com/confluentinc/confluent-kafka-dotnet/tree/07de95ed647af80a0db39ce6a8891a630423b952#basic-consumer-example
            AutoOffsetReset = AutoOffsetReset.Earliest,
            EnableAutoCommit = true
        };

        return new ConsumerBuilder<string, byte[]>(conf)
            .Build();
    }

    public void Dispose()
    {
        _isListening = false;
        _consumer?.Dispose();
    }
}

