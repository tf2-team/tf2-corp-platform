#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Catalog search tool for Shopping Copilot (A2.1).

Calls ProductCatalogService.SearchProducts with structured filter fields
extracted by the intent parser. Applies a secondary price filter in
Python code (defense-in-depth) in case the catalog service's SQL filter
is not strict enough.

Public API:
    search_catalog(intent, product_catalog_stub) -> list[CopilotProductResult]
"""

import logging
import os
import sys

_PRODUCT_REVIEWS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../product-reviews")
)
if _PRODUCT_REVIEWS_DIR not in sys.path:
    sys.path.insert(0, _PRODUCT_REVIEWS_DIR)

import grpc


import demo_pb2
import demo_pb2_grpc
from copilot_contracts import CopilotProductResult, ShoppingIntent

logger = logging.getLogger("catalog_tool")

_MAX_RESULTS = 10  # hard cap on number of products returned to the user


def _price_to_float(units: int, nanos: int) -> float:
    """Convert proto Money (units + nanos) to a float for comparison."""
    return units + nanos / 1_000_000_000


def _intent_to_request(intent: ShoppingIntent) -> demo_pb2.SearchProductsRequest:
    """Build a SearchProductsRequest from a parsed ShoppingIntent.

    Only sets the optional filter fields if the intent has them, so that
    the catalog service can apply them efficiently in SQL.
    """
    req = demo_pb2.SearchProductsRequest(query=intent.query)

    if intent.category is not None:
        req.category = intent.category

    if intent.max_price is not None:
        # Split float price into units + nanos for the proto Money fields.
        units = int(intent.max_price)
        nanos = int(round((intent.max_price - units) * 1_000_000_000))
        req.max_price_units = units
        req.max_price_nanos = nanos

    return req


def search_catalog(
    intent: ShoppingIntent,
    product_catalog_stub: demo_pb2_grpc.ProductCatalogServiceStub,
) -> list[CopilotProductResult]:
    """Call ProductCatalogService.SearchProducts and apply secondary filters.

    Returns an empty list when no results match — callers must handle
    the empty case and return NO_RESULTS without fabricating products.

    Raises:
        grpc.RpcError: propagated to the LangGraph node which must catch it
                       and route to the fallback node.
    """
    request = _intent_to_request(intent)
    logger.info(
        "Calling SearchProducts: query=%r category=%r max_price_units=%s",
        request.query,
        request.category if request.HasField("category") else None,
        request.max_price_units if request.HasField("max_price_units") else None,
    )

    response = product_catalog_stub.SearchProducts(request)
    products = response.results

    # Secondary Python-level price filter (defense-in-depth).
    if intent.max_price is not None:
        products = [
            p for p in products
            if _price_to_float(p.price_usd.units, p.price_usd.nanos) <= intent.max_price
        ]

    # Secondary category filter (defense-in-depth).
    if intent.category is not None:
        cat_lower = intent.category.lower()
        products = [
            p for p in products
            if any(c.lower() == cat_lower for c in p.categories)
        ]

    results = [
        CopilotProductResult(
            product_id=p.id,
            name=p.name,
            description=p.description if isinstance(getattr(p, "description", None), str) else "",
            price_units=p.price_usd.units,
            price_nanos=p.price_usd.nanos,
            currency_code=p.price_usd.currency_code or "USD",
        )
        for p in products[:_MAX_RESULTS]
    ]

    logger.info(
        "SearchProducts returned %d results (after filters, capped at %d)",
        len(results), _MAX_RESULTS,
    )
    return results


def make_catalog_stub() -> demo_pb2_grpc.ProductCatalogServiceStub:
    """Build a gRPC stub from the PRODUCT_CATALOG_ADDR env var."""
    addr = os.environ["PRODUCT_CATALOG_ADDR"]
    channel = grpc.insecure_channel(addr)
    return demo_pb2_grpc.ProductCatalogServiceStub(channel)
