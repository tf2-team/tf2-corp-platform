#!/usr/bin/python

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import catalog_tool
from copilot_contracts import CatalogSearchInput


def _product(product_id, price, categories):
    product = MagicMock()
    product.id = product_id
    product.name = product_id
    product.description = ""
    product.price_usd.units = price
    product.price_usd.nanos = 0
    product.price_usd.currency_code = "USD"
    product.categories = categories
    return product


def _stub(products):
    stub = MagicMock()
    stub.SearchProducts.return_value.results = products
    return stub


def test_search_catalog_enforces_price_and_category():
    results = catalog_tool.search_catalog(
        CatalogSearchInput(query="kit", category="accessories", max_price=100),
        _stub([_product("A", 30, ["accessories"]), _product("B", 200, ["accessories"])]),
    )
    assert [product.product_id for product in results] == ["A"]


def test_filters_to_request_sets_money_fields():
    request = catalog_tool._filters_to_request(CatalogSearchInput(query="kit", max_price=99.99))
    assert request.query == "kit"
    assert request.max_price_units == 99
    assert request.max_price_nanos == 990_000_000
