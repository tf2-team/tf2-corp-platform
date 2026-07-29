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

    internal static bool IsSupportedLegacyPrimaryKey(IEnumerable<string> columns)
    {
        var normalized = columns
            .Select(column => column.ToLowerInvariant())
            .ToHashSet(StringComparer.Ordinal);

        return (normalized.Count == 1 && normalized.Contains("shipping_tracking_id"))
            || (normalized.Count == 2
                && normalized.Contains("shipping_tracking_id")
                && normalized.Contains("transaction_type"));
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

            // 1. Take advisory lock for the duration of the transaction
            using (var lockCmd = conn.CreateCommand())
            {
                lockCmd.Transaction = transaction.GetDbTransaction();
                lockCmd.CommandText = "SELECT pg_advisory_xact_lock(@lockId);";
                var p = lockCmd.CreateParameter();
                p.ParameterName = "lockId";
                p.Value = AdvisoryLockId;
                lockCmd.Parameters.Add(p);
                lockCmd.ExecuteNonQuery();
            }

            // 2. Query current primary key columns
            var pkColumns = new List<string>();
            using (var pkCmd = conn.CreateCommand())
            {
                pkCmd.Transaction = transaction.GetDbTransaction();
                pkCmd.CommandText = @"
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_schema = 'accounting'
                      AND tc.table_name = 'shipping'
                    ORDER BY kcu.ordinal_position;";
                using var reader = pkCmd.ExecuteReader();
                while (reader.Read())
                {
                    pkColumns.Add(reader.GetString(0).ToLowerInvariant());
                }
            }

            var isDesired = pkColumns.Count == 2 && pkColumns.Contains("order_id") && pkColumns.Contains("transaction_type");
            if (isDesired)
            {
                logger.LogInformation("accounting.shipping primary key is already (order_id, transaction_type). Migration is no-op.");
                transaction.Commit();
                return true;
            }

            if (!IsSupportedLegacyPrimaryKey(pkColumns))
            {
                var currentPkStr = string.Join(", ", pkColumns);
                throw new InvalidOperationException($"Unknown primary key layout ({currentPkStr}) on accounting.shipping. Aborting migration.");
            }

            // 3. Validate duplicate (order_id, transaction_type) rows
            int duplicateCount = 0;
            using (var dupCmd = conn.CreateCommand())
            {
                dupCmd.Transaction = transaction.GetDbTransaction();
                dupCmd.CommandText = @"
                    SELECT COUNT(*) FROM (
                        SELECT order_id, transaction_type
                        FROM accounting.shipping
                        GROUP BY order_id, transaction_type
                        HAVING COUNT(*) > 1
                    ) dups;";
                var res = dupCmd.ExecuteScalar();
                if (res != null && res != DBNull.Value)
                {
                    duplicateCount = Convert.ToInt32(res);
                }
            }

            if (duplicateCount > 0)
            {
                throw new InvalidOperationException($"Duplicate (order_id, transaction_type) rows found ({duplicateCount}) in accounting.shipping. Aborting migration.");
            }

            // 4. Alter constraint
            using (var alterCmd = conn.CreateCommand())
            {
                alterCmd.Transaction = transaction.GetDbTransaction();
                alterCmd.CommandText = @"
                    ALTER TABLE accounting.shipping DROP CONSTRAINT shipping_pkey;
                    ALTER TABLE accounting.shipping ADD PRIMARY KEY (order_id, transaction_type);";
                alterCmd.ExecuteNonQuery();
            }

            transaction.Commit();
            logger.LogInformation("Successfully migrated accounting.shipping primary key to (order_id, transaction_type).");
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

// Change trail: @hungxqt - 2026-07-28 - Add idempotent Accounting database migration with advisory lock and duplicate check.
// Change trail: Person 3 - 2026-07-29 - Accept the observed one-column legacy PK while retaining fail-closed schema validation.
