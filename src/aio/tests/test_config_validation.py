from __future__ import annotations

import unittest
from copy import deepcopy

from scripts.validate_config import CONFIG_ROOT, canonical_digest, load_documents, validate, validate_documents


class ConfigValidationTest(unittest.TestCase):
    def test_current_config_is_valid(self) -> None:
        self.assertEqual(validate(CONFIG_ROOT), [])

    def test_broken_signal_query_ref_fails(self) -> None:
        documents, load_errors = load_documents(CONFIG_ROOT)
        self.assertEqual(load_errors, [])
        documents = deepcopy(documents)
        documents["signals/checkout.yaml"]["signals"][0]["query_ref"] = "queries/checkout.yaml#missing_query"

        errors = validate_documents(documents)

        self.assertTrue(any("broken query_ref" in error for error in errors), errors)

    def test_official_sli_cannot_be_fallback_only(self) -> None:
        documents, load_errors = load_documents(CONFIG_ROOT)
        self.assertEqual(load_errors, [])
        documents = deepcopy(documents)
        documents["signals/official_slos.yaml"]["signals"][0]["qualification_state"] = "fallback-only"

        errors = validate_documents(documents)

        self.assertTrue(any("official SLI cannot be fallback-only" in error for error in errors), errors)

    def test_canonical_digest_is_stable_for_unchanged_config(self) -> None:
        first = canonical_digest(CONFIG_ROOT)
        second = canonical_digest(CONFIG_ROOT)

        self.assertEqual(first, second)
        self.assertRegex(first, r"^sha256:[a-f0-9]{64}$")


if __name__ == "__main__":
    unittest.main()
