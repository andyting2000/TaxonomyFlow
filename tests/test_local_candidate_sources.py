import json
import tempfile
import unittest
from pathlib import Path

from services.local_candidate_sources import (
    build_local_candidate_sources_report,
    generate_local_candidate_specs,
    load_concept_playbook_cards,
)
from services.pdf_xbrl_deterministic_alignment import canonical_label


def record(label, *, family, section, role="component", main=True, notes=False):
    return {
        "sample_id": "case_test",
        "row_id": f"case_test:{canonical_label(label)}:current",
        "pdf_label": label,
        "normalized_label": canonical_label(label),
        "value": "100",
        "statement_family": family,
        "section_block": section,
        "row_role": role,
        "is_main_statement": main,
        "is_notes_context": notes,
    }


class LocalCandidateSourcesTests(unittest.TestCase):
    def test_statement_role_pack_generates_pl_candidate_only_in_pl_context(self):
        specs = generate_local_candidate_specs(record("Revenue", family="income_statement", section="revenue"))

        self.assertIn("ifrs-smes:Revenue", [item["qname"] for item in specs])
        self.assertIn("statement_role_pack", [item["candidate_source"] for item in specs])

    def test_statement_role_pack_does_not_generate_pl_candidate_in_sfp_context(self):
        specs = generate_local_candidate_specs(record("Revenue", family="financial_position", section="current_assets"))

        self.assertNotIn("ifrs-smes:Revenue", [item["qname"] for item in specs])

    def test_sfp_asset_pack_generates_asset_candidate_only_in_asset_section(self):
        specs = generate_local_candidate_specs(
            record("Total current assets", family="financial_position", section="current_assets", role="total")
        )
        blocked = generate_local_candidate_specs(
            record("Total current assets", family="financial_position", section="current_liabilities", role="total")
        )

        self.assertIn("ifrs-smes:CurrentAssets", [item["qname"] for item in specs])
        self.assertNotIn("ifrs-smes:CurrentAssets", [item["qname"] for item in blocked])

    def test_sfp_liability_pack_generates_liability_candidate_only_in_liability_section(self):
        specs = generate_local_candidate_specs(
            record("Total current liabilities", family="financial_position", section="current_liabilities", role="total")
        )
        blocked = generate_local_candidate_specs(
            record("Total current liabilities", family="financial_position", section="current_assets", role="total")
        )

        self.assertIn("ifrs-smes:CurrentLiabilities", [item["qname"] for item in specs])
        self.assertNotIn("ifrs-smes:CurrentLiabilities", [item["qname"] for item in blocked])

    def test_cash_flow_pack_generates_cash_flow_candidate_only_in_cash_flow_context(self):
        specs = generate_local_candidate_specs(
            record("Operating loss before working capital changes", family="cash_flow", section="cash_flow_operating")
        )
        blocked = generate_local_candidate_specs(
            record("Operating loss before working capital changes", family="income_statement", section="profit_loss")
        )

        self.assertIn("ssmt-mpers:CashFlowsFromUsedInOperations", [item["qname"] for item in specs])
        self.assertNotIn("ssmt-mpers:CashFlowsFromUsedInOperations", [item["qname"] for item in blocked])

    def test_equity_movement_pack_generates_equity_candidate_only_in_equity_context(self):
        specs = generate_local_candidate_specs(
            record("Share capital", family="changes_in_equity", section="changes_in_equity")
        )
        blocked = generate_local_candidate_specs(
            record("Share capital", family="income_statement", section="income_statement_other")
        )

        self.assertIn("ifrs-smes:IssuedCapital", [item["qname"] for item in specs])
        self.assertNotIn("ifrs-smes:IssuedCapital", [item["qname"] for item in blocked])

    def test_note_detail_row_does_not_generate_main_statement_candidate(self):
        specs = generate_local_candidate_specs(
            record("Trade and other payables", family="notes", section="notes_payables", role="note_detail", main=False, notes=True)
        )

        self.assertEqual(specs, [])

    def test_note_summary_total_can_generate_review_required_candidate_if_boundary_allows_support(self):
        specs = generate_local_candidate_specs(
            record("Total current liabilities", family="notes", section="notes_payables", role="total", main=False, notes=True)
        )

        self.assertIn("ifrs-smes:CurrentLiabilities", [item["qname"] for item in specs])
        candidate = next(item for item in specs if item["qname"] == "ifrs-smes:CurrentLiabilities")
        self.assertEqual(candidate["candidate_source"], "note_total_candidate")
        self.assertTrue(candidate["requires_human_review"])
        self.assertFalse(candidate["safe_for_auto_apply"])

    def test_missing_concept_playbook_files_handled_gracefully(self):
        cards, diagnostics = load_concept_playbook_cards(["missing-concept-playbook.json"], allow_missing=True)

        self.assertEqual(cards, [])
        self.assertEqual(diagnostics["status"], "missing_allowed")

    def test_concept_playbook_fixture_can_generate_local_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fs_mpers_concept_playbook_fixture.json"
            path.write_text(
                json.dumps(
                    {
                        "concept_cards": [
                            {
                                "concept_qname": "ifrs-smes:OtherExpenseByFunction",
                                "canonical_label": "Other expense by function",
                                "statement_families_observed": ["Statement of Comprehensive Income"],
                                "common_extracted_labels": ["Bank charges"],
                                "accounting_synonyms": ["bank charges"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            cards, diagnostics = load_concept_playbook_cards([path], allow_missing=False)
            specs = generate_local_candidate_specs(
                record("Bank charges", family="income_statement", section="administrative_expenses"),
                concept_cards=cards,
            )

        self.assertEqual(diagnostics["concept_card_count"], 1)
        self.assertIn("ifrs-smes:OtherExpenseByFunction", [item["qname"] for item in specs])
        self.assertIn("concept_playbook_lookup", [item["candidate_source"] for item in specs])

    def test_all_candidates_remain_review_required_and_not_safe_for_auto_apply(self):
        specs = generate_local_candidate_specs(record("Revenue", family="income_statement", section="revenue"))

        self.assertTrue(specs)
        self.assertTrue(all(item["requires_human_review"] for item in specs))
        self.assertTrue(all(item["safe_for_auto_apply"] is False for item in specs))

    def test_reports_serialize_valid_json(self):
        report = build_local_candidate_sources_report(
            [record("Revenue", family="income_statement", section="revenue")],
            concept_cards=[],
        )

        encoded = json.dumps(report, default=str)
        self.assertIn("local_candidate_count", encoded)
        self.assertEqual(report["summary"]["safe_for_auto_apply_count"], 0)


if __name__ == "__main__":
    unittest.main()
