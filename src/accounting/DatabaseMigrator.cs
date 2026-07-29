// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Microsoft.Extensions.Logging;

namespace Accounting;

internal static class DatabaseMigrator
{
    public const long AdvisoryLockId = 20260728;

    internal static bool SetEquals(IEnumerable<string> cols, params string[] expected)
    {
        var set = new HashSet<string>(cols.Select(c => c.ToLowerInvariant()), StringComparer.Ordinal);
        var expectedSet = new HashSet<string>(expected.Select(e => e.ToLowerInvariant()), StringComparer.Ordinal);
        return set.SetEquals(expectedSet);
    }

    internal static bool IsDesiredShippingPrimaryKey(IEnumerable<string> columns)
    {
        return SetEquals(columns, "order_id", "transaction_type");
    }

    internal static bool IsSupportedShippingLegacyPrimaryKey(IEnumerable<string> columns)
    {
        return SetEquals(columns, "shipping_tracking_id")
            || SetEquals(columns, "shipping_tracking_id", "transaction_type")
            || IsDesiredShippingPrimaryKey(columns);
    }

    internal static bool IsDesiredOrderItemPrimaryKey(IEnumerable<string> columns)
    {
        return SetEquals(columns, "order_id", "product_id", "transaction_type");
    }

    internal static bool IsSupportedOrderItemLegacyPrimaryKey(IEnumerable<string> columns)
    {
        return SetEquals(columns, "order_id", "product_id")
            || IsDesiredOrderItemPrimaryKey(columns);
    }

    internal static bool IsSupportedLegacyPrimaryKey(IEnumerable<string> columns)
    {
        return IsSupportedShippingLegacyPrimaryKey(columns);
    }

    internal static List<string> GetPrimaryKeyColumns(IDbConnection conn, IDbTransaction transaction, string tableName)
    {
        var pkColumns = new List<string>();
        using var pkCmd = conn.CreateCommand();
        pkCmd.Transaction = transaction;
        pkCmd.CommandText = @"
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = 'accounting'
              AND tc.table_name = @tableName
            ORDER BY kcu.ordinal_position;";
        var p = pkCmd.CreateParameter();
        p.ParameterName = "tableName";
        p.Value = tableName;
        pkCmd.Parameters.Add(p);

        using var reader = pkCmd.ExecuteReader();
        while (reader.Read())
        {
            pkColumns.Add(reader.GetString(0).ToLowerInvariant());
        }
        return pkColumns;
    }

    public static bool RunMigration(string connectionString, ILogger logger)
    {
        if (string.IsNullOrEmpty(connectionString))
        {
            logger.LogError("DB_CONNECTION_STRING is required for migration.");
            return false;
        }

        using var dbContext = new DBContext();
        using var transaction = dbContext.Database.BeginTransaction();
        try
        {
            var conn = dbContext.Database.GetDbConnection();
            if (conn.State != ConnectionState.Open)
            {
                conn.Open();
            }

            var dbTransaction = transaction.GetDbTransaction();

            // 1. Take advisory lock for the duration of the transaction
            using (var lockCmd = conn.CreateCommand())
            {
                lockCmd.Transaction = dbTransaction;
                lockCmd.CommandText = "SELECT pg_advisory_xact_lock(@lockId);";
                var p = lockCmd.CreateParameter();
                p.ParameterName = "lockId";
                p.Value = AdvisoryLockId;
                lockCmd.Parameters.Add(p);
                lockCmd.ExecuteNonQuery();
            }

            // 2. Query current primary key columns for both tables
            var shippingPk = GetPrimaryKeyColumns(conn, dbTransaction, "shipping");
            var orderItemPk = GetPrimaryKeyColumns(conn, dbTransaction, "orderitem");

            bool shippingDesired = IsDesiredShippingPrimaryKey(shippingPk);
            bool orderItemDesired = IsDesiredOrderItemPrimaryKey(orderItemPk);

            if (shippingDesired && orderItemDesired)
            {
                logger.LogInformation("Both accounting.shipping and accounting.orderitem primary keys are already at desired layout. Migration is no-op.");
                transaction.Commit();
                return true;
            }

            // Validate layouts before proceeding
            if (!IsSupportedShippingLegacyPrimaryKey(shippingPk))
            {
                var currentPkStr = string.Join(", ", shippingPk);
                throw new InvalidOperationException($"Unknown primary key layout ({currentPkStr}) on accounting.shipping. Aborting migration.");
            }

            if (!IsSupportedOrderItemLegacyPrimaryKey(orderItemPk))
            {
                var currentPkStr = string.Join(", ", orderItemPk);
                throw new InvalidOperationException($"Unknown primary key layout ({currentPkStr}) on accounting.orderitem. Aborting migration.");
            }

            // 3. Migrate accounting.shipping if needed
            if (!shippingDesired)
            {
                using (var nullCmd = conn.CreateCommand())
                {
                    nullCmd.Transaction = dbTransaction;
                    nullCmd.CommandText = "SELECT COUNT(*) FROM accounting.shipping WHERE transaction_type IS NULL;";
                    var nullRes = Convert.ToInt32(nullCmd.ExecuteScalar());
                    if (nullRes > 0)
                    {
                        throw new InvalidOperationException($"transaction_type contains {nullRes} null values in accounting.shipping. Aborting migration.");
                    }
                }

                using (var dupCmd = conn.CreateCommand())
                {
                    dupCmd.Transaction = dbTransaction;
                    dupCmd.CommandText = @"
                        SELECT COUNT(*) FROM (
                            SELECT order_id, transaction_type
                            FROM accounting.shipping
                            GROUP BY order_id, transaction_type
                            HAVING COUNT(*) > 1
                        ) dups;";
                    var dupCount = Convert.ToInt32(dupCmd.ExecuteScalar());
                    if (dupCount > 0)
                    {
                        throw new InvalidOperationException($"Duplicate (order_id, transaction_type) rows found ({dupCount}) in accounting.shipping. Aborting migration.");
                    }
                }

                using (var alterCmd = conn.CreateCommand())
                {
                    alterCmd.Transaction = dbTransaction;
                    alterCmd.CommandText = @"
                        ALTER TABLE accounting.shipping DROP CONSTRAINT shipping_pkey;
                        ALTER TABLE accounting.shipping ADD PRIMARY KEY (order_id, transaction_type);";
                    alterCmd.ExecuteNonQuery();
                }
                logger.LogInformation("Migrated accounting.shipping primary key to (order_id, transaction_type).");
            }

            // 4. Migrate accounting.orderitem if needed
            if (!orderItemDesired)
            {
                using (var nullCmd = conn.CreateCommand())
                {
                    nullCmd.Transaction = dbTransaction;
                    nullCmd.CommandText = "SELECT COUNT(*) FROM accounting.orderitem WHERE transaction_type IS NULL;";
                    var nullRes = Convert.ToInt32(nullCmd.ExecuteScalar());
                    if (nullRes > 0)
                    {
                        throw new InvalidOperationException($"transaction_type contains {nullRes} null values in accounting.orderitem. Aborting migration.");
                    }
                }

                using (var dupCmd = conn.CreateCommand())
                {
                    dupCmd.Transaction = dbTransaction;
                    dupCmd.CommandText = @"
                        SELECT COUNT(*) FROM (
                            SELECT order_id, product_id, transaction_type
                            FROM accounting.orderitem
                            GROUP BY order_id, product_id, transaction_type
                            HAVING COUNT(*) > 1
                        ) dups;";
                    var dupCount = Convert.ToInt32(dupCmd.ExecuteScalar());
                    if (dupCount > 0)
                    {
                        throw new InvalidOperationException($"Duplicate (order_id, product_id, transaction_type) rows found ({dupCount}) in accounting.orderitem. Aborting migration.");
                    }
                }

                using (var alterCmd = conn.CreateCommand())
                {
                    alterCmd.Transaction = dbTransaction;
                    alterCmd.CommandText = @"
                        ALTER TABLE accounting.orderitem DROP CONSTRAINT orderitem_pkey;
                        ALTER TABLE accounting.orderitem ADD PRIMARY KEY (order_id, product_id, transaction_type);";
                    alterCmd.ExecuteNonQuery();
                }
                logger.LogInformation("Migrated accounting.orderitem primary key to (order_id, product_id, transaction_type).");
            }

            // 5. Postconditions check: re-read both primary keys
            var postShippingPk = GetPrimaryKeyColumns(conn, dbTransaction, "shipping");
            var postOrderItemPk = GetPrimaryKeyColumns(conn, dbTransaction, "orderitem");

            if (!IsDesiredShippingPrimaryKey(postShippingPk) || !IsDesiredOrderItemPrimaryKey(postOrderItemPk))
            {
                throw new InvalidOperationException("Post-migration primary key verification failed. Aborting transaction.");
            }

            transaction.Commit();
            logger.LogInformation("Successfully completed Accounting database migration.");
            return true;
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Accounting database migration failed:");
            transaction.Rollback();
            return false;
        }
    }
}

// Change trail: @hungxqt - 2026-07-29 - Update DatabaseMigrator to validate and migrate both shipping and orderitem primary keys.
