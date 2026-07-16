#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared data contracts for the review AI trustworthiness pipeline.

This module contains data shapes and schema-level validation only. Guardrail,
grounding, database, and transport logic belong in their respective modules.
"""

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    """Base settings shared by all internal AI contracts."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GuardrailAction(str, Enum):
    ALLOW = "ALLOW"
    SANITIZED = "SANITIZED"
    BLOCK = "BLOCK"


class ResponseStatus(str, Enum):
    GROUNDED = "GROUNDED"
    ABSTAINED = "ABSTAINED"
    BLOCKED = "BLOCKED"


class GuardrailResult(ContractModel):
    action: GuardrailAction
    reason: str | None = None
    sanitized_text: str | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> "GuardrailResult":
        if self.action == GuardrailAction.BLOCK and not self.reason:
            raise ValueError("A blocked guardrail result must include a reason")
        if (
            self.action == GuardrailAction.SANITIZED
            and self.sanitized_text is None
        ):
            raise ValueError("A sanitized guardrail result must include sanitized_text")
        return self


class ToolValidationResult(ContractModel):
    allowed: bool
    reason: str | None = None

    @model_validator(mode="after")
    def rejected_tool_has_reason(self) -> "ToolValidationResult":
        if not self.allowed and not self.reason:
            raise ValueError("A rejected tool call must include a reason")
        return self


class SafeReview(ContractModel):
    source_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    score: Decimal | None = None


class SafeReviewSet(ContractModel):
    product_id: str = Field(min_length=1)
    reviews: list[SafeReview] = Field(default_factory=list)
    reason: str | None = None

    @model_validator(mode="after")
    def validate_review_set(self) -> "SafeReviewSet":
        source_ids = [review.source_id for review in self.reviews]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("SafeReviewSet cannot contain duplicate source_id values")
        if not self.reviews and not self.reason:
            raise ValueError("An empty SafeReviewSet must include a reason")
        return self


class GroundedClaim(ContractModel):
    text: str = Field(min_length=1)
    sources: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_sources(self) -> "GroundedClaim":
        if any(not source_id.strip() for source_id in self.sources):
            raise ValueError("Claim source_id values cannot be blank")
        if len(self.sources) != len(set(self.sources)):
            raise ValueError("Claim source_id values must be unique")
        return self


class GroundedDraft(ContractModel):
    answer: str = ""
    claims: list[GroundedClaim] = Field(default_factory=list)


class GroundedResponse(ContractModel):
    answer: str = ""
    claims: list[GroundedClaim] = Field(default_factory=list)
    status: ResponseStatus
    reason: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "GroundedResponse":
        if self.status == ResponseStatus.GROUNDED:
            if not self.claims:
                raise ValueError("A grounded response must include at least one claim")
            if not self.answer:
                raise ValueError("A grounded response must include an answer")
        else:
            if self.claims:
                raise ValueError("A non-grounded response cannot include claims")
            if not self.reason:
                raise ValueError("A non-grounded response must include a reason")
        return self


__all__ = [
    "GroundedClaim",
    "GroundedDraft",
    "GroundedResponse",
    "GuardrailAction",
    "GuardrailResult",
    "ResponseStatus",
    "SafeReview",
    "SafeReviewSet",
    "ToolValidationResult",
]
# Change trail: @hungxqt - 2026-07-16 - Add Apache-2.0 copyright headers for license-checker.
