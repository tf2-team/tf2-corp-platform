from __future__ import annotations

import unittest
from copy import deepcopy

from scripts.validate_config import CONFIG_ROOT, RUNBOOK_ROOT, load_documents, load_runbooks, match_runbook, validate_documents


class RunbookValidationTest(unittest.TestCase):
    def _loaded(self):
        documents, load_errors = load_documents(CONFIG_ROOT)
        runbooks, runbook_errors = load_runbooks(RUNBOOK_ROOT)
        self.assertEqual(load_errors, [])
        self.assertEqual(runbook_errors, [])
        return documents, runbooks

    def test_current_runbooks_are_validated_with_config(self) -> None:
        documents, runbooks = self._loaded()

        self.assertEqual(validate_documents(documents, runbooks), [])

    def test_runbook_index_sample_incidents_link_to_expected_runbooks(self) -> None:
        documents, _runbooks = self._loaded()
        index = documents["runbooks/index.yaml"]

        for entry in index["runbooks"]:
            self.assertEqual(match_runbook(index, entry["sample_incident"]), entry["runbook_id"])

    def test_broken_runbook_index_path_fails(self) -> None:
        documents, runbooks = self._loaded()
        documents = deepcopy(documents)
        documents["runbooks/index.yaml"]["runbooks"][0]["path"] = "runbooks/RB-MISSING.md"

        errors = validate_documents(documents, runbooks)

        self.assertTrue(any("runbook index path does not exist" in error for error in errors), errors)

    def test_missing_runbook_front_matter_key_fails(self) -> None:
        documents, runbooks = self._loaded()
        runbooks = deepcopy(runbooks)
        del runbooks["runbooks/RB-CHECKOUT-SLO.md"]["front_matter"]["communication_template"]

        errors = validate_documents(documents, runbooks)

        self.assertTrue(any("missing required key" in error and "communication_template" in error for error in errors), errors)

    def test_sample_incident_runbook_mismatch_fails(self) -> None:
        documents, runbooks = self._loaded()
        documents = deepcopy(documents)
        documents["runbooks/index.yaml"]["runbooks"][0]["sample_incident"]["runbook_id"] = "RB-DB-SATURATION"

        errors = validate_documents(documents, runbooks)

        self.assertTrue(any("sample incident runbook_id must match" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
