"""Mandate 11 audit alert parser package."""

from .handler import classify_event, lambda_handler

__all__ = ["classify_event", "lambda_handler"]
