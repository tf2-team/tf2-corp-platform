// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace Accounting;

internal sealed class OutboxReconciler : IDisposable
{
    private const string PublishedStatus = "published";
    private const string PendingStatus = "pending";

    private readonly AmazonDynamoDBClient _dynamoDb;
    private readonly string _table;
    private readonly ILogger _logger;
    private readonly Action<string> _publishPersistenceAck;
    private readonly TimeSpan _interval;
    private readonly TimeSpan _staleAfter;
    private readonly CancellationTokenSource _stop = new();
    private Task? _worker;

    internal OutboxReconciler(string table, ILogger logger, Action<string> publishPersistenceAck)
    {
        _table = table;
        _logger = logger;
        _publishPersistenceAck = publishPersistenceAck;
        _dynamoDb = new AmazonDynamoDBClient();
        _interval = TimeSpan.FromSeconds(ReadPositiveInt("OUTBOX_RECONCILE_INTERVAL_SECONDS", 300));
        _staleAfter = TimeSpan.FromSeconds(ReadPositiveInt("OUTBOX_PUBLISHED_STALE_SECONDS", 900));
    }

    internal void Start()
    {
        _worker = Task.Run(() => RunAsync(_stop.Token));
    }

    private async Task RunAsync(CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(_interval);
        while (!cancellationToken.IsCancellationRequested)
        {
            await ReconcileAsync(cancellationToken);
            try
            {
                if (!await timer.WaitForNextTickAsync(cancellationToken))
                {
                    return;
                }
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                return;
            }
        }
    }

    private async Task ReconcileAsync(CancellationToken cancellationToken)
    {
        try
        {
            Dictionary<string, AttributeValue>? cursor = null;
            do
            {
                var response = await _dynamoDb.QueryAsync(new QueryRequest
                {
                    TableName = _table,
                    IndexName = "status-created-index",
                    KeyConditionExpression = "#status = :published",
                    ExpressionAttributeNames = new Dictionary<string, string>
                    {
                        ["#status"] = "status"
                    },
                    ExpressionAttributeValues = new Dictionary<string, AttributeValue>
                    {
                        [":published"] = new AttributeValue { S = PublishedStatus }
                    },
                    ExclusiveStartKey = cursor,
                    Limit = 25
                }, cancellationToken);

                foreach (var item in response.Items)
                {
                    await ReconcileItemAsync(item, cancellationToken);
                }
                cursor = response.LastEvaluatedKey?.Count > 0 ? response.LastEvaluatedKey : null;
            } while (cursor != null && !cancellationToken.IsCancellationRequested);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Checkout outbox reconciliation pass failed");
        }
    }

    private async Task ReconcileItemAsync(Dictionary<string, AttributeValue> item, CancellationToken cancellationToken)
    {
        if (!item.TryGetValue("event_id", out var eventIdValue) ||
            string.IsNullOrEmpty(eventIdValue.S) ||
            !item.TryGetValue("published_at", out var publishedAtValue) ||
            !long.TryParse(publishedAtValue.N, out var publishedAtMillis))
        {
            _logger.LogWarning("Skipping malformed published checkout outbox item");
            return;
        }

        var publishedAt = DateTimeOffset.FromUnixTimeMilliseconds(publishedAtMillis);
        if (DateTimeOffset.UtcNow - publishedAt < _staleAfter)
        {
            return;
        }

        var orderId = eventIdValue.S;
        try
        {
            using var dbContext = new DBContext();
            var persisted = await dbContext.Orders.AsNoTracking()
                .AnyAsync(order => order.Id == orderId, cancellationToken);

            if (persisted)
            {
                _publishPersistenceAck(orderId);
                Log.PersistenceAckReplayed(_logger, orderId);
                return;
            }

            await _dynamoDb.UpdateItemAsync(new UpdateItemRequest
            {
                TableName = _table,
                Key = new Dictionary<string, AttributeValue>
                {
                    ["event_id"] = new AttributeValue { S = orderId }
                },
                UpdateExpression = "SET #status = :pending REMOVE published_at",
                ConditionExpression = "#status = :published AND published_at = :published_at",
                ExpressionAttributeNames = new Dictionary<string, string>
                {
                    ["#status"] = "status"
                },
                ExpressionAttributeValues = new Dictionary<string, AttributeValue>
                {
                    [":pending"] = new AttributeValue { S = PendingStatus },
                    [":published"] = new AttributeValue { S = PublishedStatus },
                    [":published_at"] = new AttributeValue { N = publishedAtMillis.ToString() }
                }
            }, cancellationToken);
            _logger.LogWarning("Requeued stale checkout outbox event {orderId} because it is absent from RDS", orderId);
        }
        catch (ConditionalCheckFailedException)
        {
            // An ACK or another reconciler changed the item after this pass read it.
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to reconcile stale checkout outbox event {orderId}", orderId);
        }
    }

    private static int ReadPositiveInt(string name, int fallback)
    {
        return int.TryParse(Environment.GetEnvironmentVariable(name), out var value) && value > 0
            ? value
            : fallback;
    }

    public void Dispose()
    {
        _stop.Cancel();
        try
        {
            _worker?.Wait(TimeSpan.FromSeconds(5));
        }
        catch (AggregateException ex) when (ex.InnerExceptions.All(inner => inner is OperationCanceledException))
        {
        }
        _stop.Dispose();
        _dynamoDb.Dispose();
    }
}
