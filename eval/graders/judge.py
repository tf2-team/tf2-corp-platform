#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Claim-level LLM judging for semantic Mandate 14 metrics."""

from __future__ import annotations

import json
import os
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field


class ClaimVerdict(BaseModel):
    text: str
    claim_type: Literal["product_fact", "opinion"]
    verdict: Literal["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFORMATION"]
    evidence: list[str] = Field(default_factory=list)


class JudgeOutput(BaseModel):
    claims: list[ClaimVerdict] = Field(
        default_factory=list,
        validation_alias=AliasChoices("claims", "extracted_claims"),
    )
    task_success: Literal["correct", "partial", "incorrect"] = Field(
        validation_alias=AliasChoices("task_success", "task_fulfilment"),
    )


_SYSTEM = """You are an exacting evaluator. Extract only factual claims explicitly
stated in ANSWER. Never copy a claim from the sources when ANSWER did not state it.
Classify product identity, availability, price, category, specifications, and other
objective facts as product_fact. Classify customer opinions or experiences as opinion.

Evidence rules:
- product_fact: use CATALOG_PRODUCTS, RETURNED_PRODUCTS, or PRODUCT_DESCRIPTION.
- opinion: use REVIEWS only.
- task_success: use ANSWER, ACTUAL_STATUS, TOOL_CALLS, RETURNED_PRODUCTS, and
  PENDING_ACTION together. Judge whether the user received the expected outcome;
  do not require a particular tool call when the answer and result are correct.
- Do not treat source text itself as an answer claim.
- Preserve conditions, scope, and quantifiers.

For each claim return SUPPORTED, CONTRADICTED, or NOT_ENOUGH_INFORMATION with short
verbatim evidence. Then assess whether the answer fulfils EXPECTED BEHAVIOR as
correct, partial, or incorrect. Return exactly these keys: claims and task_success.
Never use extracted_claims or task_fulfilment in your output.

Example:
ANSWER: "I found Roof Binoculars for bird watching."
RETURNED_PRODUCTS: [{"name":"Roof Binoculars","categories":["binoculars"]}]
TOOL_CALLS: [{"name":"search_catalog"}]
{
  "claims": [
    {"text": "Roof Binoculars were found.", "claim_type": "product_fact",
     "verdict": "SUPPORTED", "evidence": ["RETURNED_PRODUCTS: Roof Binoculars"]}
  ],
  "task_success": "correct"
}

For an answer with no factual claims, return "claims": [] and still include
"task_success". Return JSON only."""


def _prompt(case: dict, output: dict) -> str:
    source = case["input"]
    return json.dumps({
        "USER_REQUEST": source.get("question") or source.get("user_message") or source.get("turns", [{}])[-1].get("user_message", ""),
        "EXPECTED_BEHAVIOR": case["labels"].get("expected_behavior", ""),
        "EXPECTED_STATUS": case["labels"].get("expected_status", ""),
        "ANSWER": output.get("answer", ""),
        "ACTUAL_STATUS": output.get("status", ""),
        "CATALOG_PRODUCTS": source.get("mock_catalog_products", []),
        "RETURNED_PRODUCTS": output.get("products", []),
        "PRODUCT_DESCRIPTION": source.get("mock_product_description", ""),
        "REVIEWS": [item if isinstance(item, str) else item.get("text", "") for item in source.get("mock_reviews", [])],
        "TOOL_CALLS": output.get("tool_calls", []),
        "PENDING_ACTION": output.get("pending_action"),
    })


def judge_case(case: dict, output: dict) -> dict:
    """Call the configured judge model; its usage is captured by the eval runner."""
    from techx_ai_common.bedrock import converse_json, is_bedrock_provider

    prompt = _prompt(case, output)
    if is_bedrock_provider():
        return converse_json(JudgeOutput, _SYSTEM, prompt).model_dump()

    from openai import OpenAI

    response = OpenAI(
        base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"],
    ).chat.completions.create(
        model=os.environ["LLM_MODEL"], temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
    )
    return JudgeOutput.model_validate_json(response.choices[0].message.content or "{}").model_dump()


def grade_judgement(judgement: dict, deterministic_behavior_ok: bool = True) -> list[dict]:
    claims = judgement.get("claims", [])
    supported = sum(item["verdict"] == "SUPPORTED" for item in claims)
    hallucinated = sum(item["verdict"] != "SUPPORTED" for item in claims)
    total = len(claims)
    return [
        {"metric": "faithfulness", "value": None if not total else supported / total, "passed": True, "detail": f"supported={supported}/{total}"},
        {"metric": "hallucination_rate", "value": None if not total else hallucinated / total, "passed": True, "detail": f"unsupported={hallucinated}/{total}"},
        {
            "metric": "task_success",
            "value": judgement["task_success"],
            "passed": judgement["task_success"] == "correct" and deterministic_behavior_ok,
            "detail": f"LLM judge; deterministic_behavior_ok={deterministic_behavior_ok}",
        },
    ]
