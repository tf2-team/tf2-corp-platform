#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest

from pydantic import ValidationError

from ai_contracts import (
    GroundedClaim,
    GroundedResponse,
    GuardrailAction,
    GuardrailResult,
    ResponseStatus,
    SafeReview,
    SafeReviewSet,
    ToolValidationResult,
)


class AIContractsTest(unittest.TestCase):
    def test_safe_review_set_accepts_numeric_score(self):
        review_set = SafeReviewSet(
            product_id="P001",
            reviews=[
                SafeReview(
                    source_id="review-1",
                    text="Pin dùng tốt.",
                    score=5,
                )
            ],
        )

        self.assertEqual(str(review_set.reviews[0].score), "5")

    def test_empty_safe_review_set_requires_reason(self):
        with self.assertRaises(ValidationError):
            SafeReviewSet(product_id="P001", reviews=[])

    def test_safe_review_set_rejects_duplicate_source_ids(self):
        with self.assertRaises(ValidationError):
            SafeReviewSet(
                product_id="P001",
                reviews=[
                    SafeReview(source_id="review-1", text="Pin tốt."),
                    SafeReview(source_id="review-1", text="Máy nhẹ."),
                ],
            )

    def test_claim_requires_a_source(self):
        with self.assertRaises(ValidationError):
            GroundedClaim(text="Pin tốt.", sources=[])

    def test_grounded_response_requires_a_claim(self):
        with self.assertRaises(ValidationError):
            GroundedResponse(
                answer="Pin tốt.",
                claims=[],
                status=ResponseStatus.GROUNDED,
            )

    def test_abstained_response_rejects_claims(self):
        with self.assertRaises(ValidationError):
            GroundedResponse(
                answer="Không đủ thông tin.",
                claims=[GroundedClaim(text="Pin tốt.", sources=["review-1"])],
                status=ResponseStatus.ABSTAINED,
                reason="INSUFFICIENT_EVIDENCE",
            )

    def test_blocked_guardrail_result_requires_reason(self):
        with self.assertRaises(ValidationError):
            GuardrailResult(action=GuardrailAction.BLOCK)

    def test_sanitized_guardrail_result_requires_sanitized_text(self):
        with self.assertRaises(ValidationError):
            GuardrailResult(action=GuardrailAction.SANITIZED)

    def test_rejected_tool_call_requires_reason(self):
        with self.assertRaises(ValidationError):
            ToolValidationResult(allowed=False)

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            GuardrailResult(action=GuardrailAction.ALLOW, unexpected=True)


if __name__ == "__main__":
    unittest.main()
# Change trail: @hungxqt - 2026-07-16 - Add Apache-2.0 copyright headers for license-checker.
