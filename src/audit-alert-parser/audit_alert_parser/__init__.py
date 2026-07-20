#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Mandate 11 audit alert parser package."""

from .handler import classify_event, lambda_handler

__all__ = ["classify_event", "lambda_handler"]
