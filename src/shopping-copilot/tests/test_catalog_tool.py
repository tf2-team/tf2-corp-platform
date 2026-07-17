# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for catalog_tool.py (A2.1)."""

import sys
import os
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from copilot_contracts import ShoppingIntent, CopilotProductResult
import catalog_tool


def _make_proto_product(pid, name, price_units, price_nanos, categories):
    """Build a minimal mock proto Product."""
    p = MagicMock()
    p.id = pid
    p.name = name
    p.price_usd.units = price_units
    p.price_usd.nanos = price_nanos
    p.price_usd.currency_code = "USD"
    p.categories = categories
    return p


def _make_stub(products):
    stub = MagicMock()
    resp = MagicMock()
    resp.results = products
    stub.SearchProducts.return_value = resp
    return stub


class TestPriceToFloat:
    def test_whole_units(self):
        assert catalog_tool._price_to_float(50, 0) == 50.0

    def test_fractional(self):
        assert abs(catalog_tool._price_to_float(50, 500_000_000) - 50.5) < 1e-6


class TestSecondaryFilters:
    def test_price_filter_removes_expensive(self):
        products = [
            _make_proto_product("A", "Cheap", 30, 0, ["headphones"]),
            _make_proto_product("B", "Expensive", 200, 0, ["headphones"]),
        ]
        intent = ShoppingIntent(query="headphones", max_price=100.0)
        stub = _make_stub(products)
        results = catalog_tool.search_catalog(intent, stub)
        assert len(results) == 1
        assert results[0].product_id == "A"

    def test_category_filter_removes_wrong_category(self):
        products = [
            _make_proto_product("A", "Sony WH", 50, 0, ["headphones"]),
            _make_proto_product("B", "Nike Shirt", 30, 0, ["clothing"]),
        ]
        intent = ShoppingIntent(query="headphones", category="headphones")
        stub = _make_stub(products)
        results = catalog_tool.search_catalog(intent, stub)
        assert len(results) == 1
        assert results[0].product_id == "A"

    def test_no_results_returns_empty_list(self):
        intent = ShoppingIntent(query="nonexistent")
        stub = _make_stub([])
        results = catalog_tool.search_catalog(intent, stub)
        assert results == []

    def test_results_capped_at_max(self, monkeypatch):
        monkeypatch.setattr(catalog_tool, "_MAX_RESULTS", 3)
        products = [
            _make_proto_product(str(i), f"Product {i}", 10, 0, ["electronics"])
            for i in range(10)
        ]
        intent = ShoppingIntent(query="product")
        stub = _make_stub(products)
        results = catalog_tool.search_catalog(intent, stub)
        assert len(results) == 3

    def test_intent_to_request_sets_price(self):
        intent = ShoppingIntent(query="laptop", max_price=999.99)
        req = catalog_tool._intent_to_request(intent)
        assert req.query == "laptop"
        assert req.max_price_units == 999
        assert req.max_price_nanos == 990_000_000

    def test_intent_to_request_no_filters(self):
        intent = ShoppingIntent(query="watch")
        req = catalog_tool._intent_to_request(intent)
        assert req.query == "watch"
        # Optional fields not set when not provided
