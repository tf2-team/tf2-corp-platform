#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Compatibility module for the shared TechX AI grounding pipeline."""

import sys

from techx_ai_common import grounding as _implementation

sys.modules[__name__] = _implementation
