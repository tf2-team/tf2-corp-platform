// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

using System.Linq;
using Accounting;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

Console.WriteLine("Accounting service started");

Environment.GetEnvironmentVariables()
    .FilterRelevant()
    .OutputInOrder();

if (args.Contains("--migrate-only"))
{
    using var loggerFactory = LoggerFactory.Create(builder => builder.AddConsole());
    var logger = loggerFactory.CreateLogger("DatabaseMigrator");
    var connStr = Environment.GetEnvironmentVariable("DB_CONNECTION_STRING") ?? string.Empty;
    var success = DatabaseMigrator.RunMigration(connStr, logger);
    if (success)
    {
        Console.WriteLine("Migration completed successfully.");
        Environment.Exit(0);
    }
    else
    {
        Console.Error.WriteLine("Migration failed.");
        Environment.Exit(1);
    }
}

var host = Host.CreateDefaultBuilder(args)
    .ConfigureServices(services =>
    {
        services.AddSingleton<Consumer>();
    })
    .Build();

var consumer = host.Services.GetRequiredService<Consumer>();
consumer.StartListening();

host.Run();

// Change trail: @hungxqt - 2026-07-28 - Add --migrate-only mode for Accounting database migration.
