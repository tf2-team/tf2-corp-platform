#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Pydantic contracts for Shopping Copilot I/O and tool inputs."""

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

AllowedCategory = Literal[
    "telescopes", "accessories", "travel", "binoculars", "flashlights",
    "assembly", "books",
]


class CopilotContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CopilotStatus(str, Enum):
    GROUNDED = "GROUNDED"
    NO_RESULTS = "NO_RESULTS"
    ABSTAINED = "ABSTAINED"
    BLOCKED = "BLOCKED"
    FALLBACK = "FALLBACK"


class CatalogSearchInput(CopilotContractModel):
    """Validated input for the Catalog search tool."""

    query: str = Field(default="", max_length=200)
    category: Optional[AllowedCategory] = None
    max_price: Optional[float] = Field(default=None, ge=0)


class ProductInput(CopilotContractModel):
    """Validated product reference for detail, review, and cart tools."""

    product_id: str = Field(min_length=1, max_length=100)


class ReviewQuestionInput(ProductInput):
    question: str = Field(min_length=1, max_length=500)


class CartActionInput(ProductInput):
    quantity: int = Field(default=1, ge=1, le=10)


class RetrievalHint(CopilotContractModel):
    """Turn context used for Mem0 retrieval and tool access."""

    is_follow_up: bool = False
    semantic_query: str = Field(default="", max_length=500)
    tool_access: Literal["none", "shopping"] = "none"


class MemoryCandidate(CopilotContractModel):
    """A durable semantic fact extracted from the current user turn."""

    memory_kind: Literal["preference", "constraint", "shopping_goal"]
    content: str = Field(min_length=1, max_length=500)
    constraint_type: Optional[
        Literal["budget", "brand", "feature", "compatibility", "exclusion"]
    ] = None


class MemoryExtraction(CopilotContractModel):
    memories: list[MemoryCandidate] = Field(default_factory=list, max_length=5)


class CopilotProductResult(CopilotContractModel):
    product_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    price_units: int = 0
    price_nanos: int = 0
    currency_code: str = "USD"


class PendingCartAction(CopilotContractModel):
    """Add-to-cart action awaiting the separate confirmation RPC."""

    token: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    quantity: int = Field(default=1, ge=1, le=10)


__all__ = [
    "CatalogSearchInput", "CartActionInput", "CopilotContractModel",
    "CopilotProductResult", "CopilotStatus", "MemoryCandidate",
    "MemoryExtraction", "PendingCartAction", "ProductInput",
    "RetrievalHint", "ReviewQuestionInput",
]
