#!/bin/sh
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
# Restore script for postgresql in docker-compose
# Ensure you are running this from the project root.

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <backup_file.sql>"
  exit 1
fi

BACKUP_FILE=$1

if [ ! -f "$BACKUP_FILE" ]; then
  echo "Error: File $BACKUP_FILE not found."
  exit 1
fi

echo "Restoring PostgreSQL database from $BACKUP_FILE..."
cat "$BACKUP_FILE" | docker compose exec -T postgresql psql -U root -d otel
echo "Restore completed successfully."
