// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

using System;
using System.IO;
using Accounting;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace Accounting.Tests;

public class MigrationTests
{
    [Fact]
    public void TwoOrdersWithPendingShippingCanCoexist()
    {
        var options = new DbContextOptionsBuilder<TestDbContext>()
            .UseSqlite("DataSource=:memory:")
            .Options;

        using var db = new TestDbContext(options);
        db.Database.OpenConnection();
        db.Database.EnsureCreated();

        var order1 = new OrderEntity { Id = "order-1", Status = "PENDING" };
        var order2 = new OrderEntity { Id = "order-2", Status = "PENDING" };

        var shipping1 = new ShippingEntity
        {
            OrderId = "order-1",
            ShippingTrackingId = "PENDING_SHIPPING",
            ShippingCostCurrencyCode = "USD",
            ShippingCostUnits = 10,
            ShippingCostNanos = 0,
            StreetAddress = "123 Main St",
            City = "City",
            State = "ST",
            Country = "US",
            ZipCode = "12345",
            TransactionType = "CHARGE"
        };

        var shipping2 = new ShippingEntity
        {
            OrderId = "order-2",
            ShippingTrackingId = "PENDING_SHIPPING",
            ShippingCostCurrencyCode = "USD",
            ShippingCostUnits = 15,
            ShippingCostNanos = 0,
            StreetAddress = "456 Oak St",
            City = "City",
            State = "ST",
            Country = "US",
            ZipCode = "12345",
            TransactionType = "CHARGE"
        };

        db.Orders.AddRange(order1, order2);
        db.Shipping.AddRange(shipping1, shipping2);
        db.SaveChanges();

        Assert.Equal(2, db.Shipping.Count());
    }

    [Fact]
    public void EmptyConnectionStringFailsMigration()
    {
        var result = DatabaseMigrator.RunMigration("", NullLogger.Instance);
        Assert.False(result);
    }

    [Fact]
    public void AdvisoryLockIdIsDefined()
    {
        Assert.Equal(20260728L, DatabaseMigrator.AdvisoryLockId);
    }

    [Theory]
    [InlineData("shipping_tracking_id", true)]
    [InlineData("shipping_tracking_id,transaction_type", true)]
    [InlineData("order_id", false)]
    [InlineData("shipping_tracking_id,unexpected_column", false)]
    public void LegacyPrimaryKeyGuardAcceptsOnlyKnownLayouts(string columns, bool expected)
    {
        var result = DatabaseMigrator.IsSupportedLegacyPrimaryKey(columns.Split(','));
        Assert.Equal(expected, result);
    }
}

internal class TestDbContext : DbContext
{
    public DbSet<OrderEntity> Orders { get; set; } = null!;
    public DbSet<OrderItemEntity> CartItems { get; set; } = null!;
    public DbSet<ShippingEntity> Shipping { get; set; } = null!;

    public TestDbContext(DbContextOptions<TestDbContext> options) : base(options) { }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<OrderEntity>().ToTable("order").HasKey(o => o.Id);
        modelBuilder.Entity<ShippingEntity>().ToTable("shipping").HasKey(s => new { s.OrderId, s.TransactionType });
        modelBuilder.Entity<OrderItemEntity>().ToTable("orderitem").HasKey(i => new { i.OrderId, i.ProductId, i.TransactionType });
    }
}

// Change trail: @hungxqt - 2026-07-28 - Add migration and co-existence tests for Accounting.
// Change trail: Person 3 - 2026-07-29 - Cover both known legacy primary-key layouts.
