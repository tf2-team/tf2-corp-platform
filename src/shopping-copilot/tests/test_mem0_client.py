#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mem0_client


def test_profile_scope_excludes_shared_anonymous_identity():
    assert mem0_client._profile_user_id("anonymous") == ""
    assert mem0_client._profile_user_id("browser-user-id") == "browser-user-id"
