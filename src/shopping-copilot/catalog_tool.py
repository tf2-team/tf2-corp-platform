#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Validated Product Catalog calls used by the ReAct agent."""

from __future__ import annotations

import logging
import os

import grpc
from techx_ai_common.proto import demo_pb2, demo_pb2_grpc

from copilot_contracts import CatalogSearchInput, CopilotProductResult

logger = logging.getLogger("catalog_tool")
_MAX_RESULTS = 10


def _price_to_float(units: int, nanos: int) -> float:
    return units + nanos / 1_000_000_000


def _filters_to_request(filters: CatalogSearchInput) -> demo_pb2.SearchProductsRequest:
    request = demo_pb2.SearchProductsRequest(query=filters.query)
    if filters.category is not None:
        request.category = filters.category
    if filters.max_price is not None:
        units = int(filters.max_price)
        request.max_price_units = units
        request.max_price_nanos = int(round((filters.max_price - units) * 1_000_000_000))
    return request


def search_catalog(
    filters: CatalogSearchInput,
    product_catalog_stub: demo_pb2_grpc.ProductCatalogServiceStub,
) -> list[CopilotProductResult]:
    """Call Catalog with validated filters and enforce them again locally."""
    request = _filters_to_request(filters)
    response = product_catalog_stub.SearchProducts(request)
    products = response.results
    if filters.max_price is not None:
        products = [
            product for product in products
            if _price_to_float(product.price_usd.units, product.price_usd.nanos) <= filters.max_price
        ]
    if filters.category is not None:
        products = [
            product for product in products
            if any(category.lower() == filters.category for category in product.categories)
        ]
    return [
        CopilotProductResult(
            product_id=product.id,
            name=product.name,
            description=getattr(product, "description", "") or "",
            price_units=product.price_usd.units,
            price_nanos=product.price_usd.nanos,
            currency_code=product.price_usd.currency_code or "USD",
        )
        for product in products[:_MAX_RESULTS]
    ]


def get_product(
    product_id: str,
    product_catalog_stub: demo_pb2_grpc.ProductCatalogServiceStub,
) -> CopilotProductResult | None:
    """Rehydrate one product from Catalog; caller validates its ID first."""
    if not product_id:
        return None
    product = product_catalog_stub.GetProduct(demo_pb2.GetProductRequest(id=product_id))
    if not getattr(product, "id", ""):
        return None
    return CopilotProductResult(
        product_id=product.id,
        name=product.name,
        description=getattr(product, "description", "") or "",
        price_units=product.price_usd.units,
        price_nanos=product.price_usd.nanos,
        currency_code=product.price_usd.currency_code or "USD",
    )


def make_catalog_stub() -> demo_pb2_grpc.ProductCatalogServiceStub:
    addr = os.environ["PRODUCT_CATALOG_ADDR"]
    channel = grpc.insecure_channel(addr)
    return demo_pb2_grpc.ProductCatalogServiceStub(channel)
