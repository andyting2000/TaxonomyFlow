import json
import tempfile
import unittest
from pathlib import Path

from services.golden_mbrs_dataset import align_extracted_row, build_golden_mbrs_reports
from services.reference_xbrl_parser import parse_reference_xbrl


SIMPLE_XBRL = """<?xml version="1.0" encoding="utf-8"?>
<xbrli:xbrl
  xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
  xmlns:ssmt-mpers="http://xbrl.ssm.com.my/taxonomy/2022-12-31/ssmt-mpers">
  <xbrli:context id="current"><xbrli:entity><xbrli:identifier scheme="local">123</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:context id="prior"><xbrli:entity><xbrli:identifier scheme="local">123</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:unit id="MYR"><xbrli:measure>iso4217:MYR</xbrli:measure></xbrli:unit>
  <ssmt-mpers:Revenue contextRef="current" unitRef="MYR" decimals="0">1234</ssmt-mpers:Revenue>
  <ssmt-mpers:Assets contextRef="current" unitRef="MYR" decimals="0">999</ssmt-mpers:Assets>
  <ssmt-mpers:Assets contextRef="prior" unitRef="MYR" decimals="0">888</ssmt-mpers:Assets>
  <ssmt-mpers:Liabilities contextRef="prior" unitRef="MYR" decimals="0">999</ssmt-mpers:Liabilities>
  <ssmt-mpers:DisclosureOfAccountingPolicyExplanatory contextRef="current">The company recognises revenue when services are delivered and measures financial assets using the applicable accounting policy.</ssmt-mpers:DisclosureOfAccountingPolicyExplanatory>
</xbrli:xbrl>
"""


class GoldenMBRSDatasetTests(unittest.TestCase):
    def _case_dir(self, *, rows):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        case_dir = root / "case_001"
        case_dir.mkdir()
        (case_dir / "source.pdf").write_bytes(b"%PDF-1.4 local test")
        (case_dir / "reference.xml").write_text(SIMPLE_XBRL, encoding="utf-8")
        (case_dir / "normalized_extraction.json").write_text(json.dumps({"candidates": rows}), encoding="utf-8")
        return root, case_dir

    def _facts(self, case_dir):
        return parse_reference_xbrl("case_001", case_dir / "reference.xml")["facts"]

    def test_exact_value_and_concept_alignment_is_strong(self):
        root, case_dir = self._case_dir(rows=[])
        alignment = align_extracted_row(
            case_id="case_001",
            row={"row_type": "numeric_fact", "label": "Revenue", "value": "1,234", "current_year": 2025},
            facts=self._facts(case_dir),
            template_qnames={"ssmt-mpers:revenue": "ssmt-mpers:Revenue"},
        )
        self.assertEqual(alignment["alignment_status"], "strong")
        self.assertEqual(alignment["correct_concept_qname"], "ssmt-mpers:Revenue")
        self.assertEqual(alignment["correct_template_field_id"], "ssmt-mpers:Revenue")

    def test_ambiguous_same_value_facts_are_flagged(self):
        root, case_dir = self._case_dir(rows=[])
        alignment = align_extracted_row(
            case_id="case_001",
            row={"row_type": "numeric_fact", "label": "Amount", "value": "999"},
            facts=self._facts(case_dir),
        )
        self.assertEqual(alignment["alignment_status"], "ambiguous")
        self.assertIsNone(alignment["correct_concept_qname"])
        self.assertGreaterEqual(len(alignment["candidate_facts"]), 2)

    def test_comparative_periods_for_same_concept_reinforce_alignment(self):
        root, case_dir = self._case_dir(rows=[])
        alignment = align_extracted_row(
            case_id="case_001",
            row={
                "row_type": "comparative_numeric_fact",
                "label": "Assets",
                "value": "999",
                "previous_value": "888",
                "current_year": 2025,
                "prior_year": 2024,
            },
            facts=self._facts(case_dir),
        )
        self.assertEqual(alignment["alignment_status"], "strong")
        self.assertEqual(alignment["correct_concept_qname"], "ssmt-mpers:Assets")

    def test_gold_examples_only_include_strong_alignments(self):
        rows = [
            {"candidate_id": "row-1", "row_type": "numeric_fact", "label": "Revenue", "value": "1234", "current_year": 2025},
            {"candidate_id": "row-2", "row_type": "numeric_fact", "label": "Amount", "value": "999"},
            {"candidate_id": "row-3", "row_type": "heading", "label": "Statement of financial position"},
        ]
        root, _case_dir = self._case_dir(rows=rows)
        summary, alignment, baseline = build_golden_mbrs_reports(cases_dir=root)
        self.assertEqual(summary["metrics"]["strong_gold_examples"], 1)
        self.assertEqual(summary["metrics"]["ambiguous_alignments"], 1)
        self.assertEqual(len(alignment["gold_examples"]), 1)
        self.assertEqual(alignment["gold_examples"][0]["correct_concept_qname"], "ssmt-mpers:Revenue")
        self.assertFalse(baseline["run_metadata"]["external_llm_called"])
        self.assertFalse(baseline["run_metadata"]["auditor_xml_sent_to_external_provider"])

    def test_local_baseline_accuracy_is_measured_without_llm_call(self):
        rows = [
            {
                "candidate_id": "row-1",
                "row_type": "numeric_fact",
                "label": "Revenue",
                "value": "1234",
                "current_year": 2025,
                "deterministic_concept_qname": "ssmt-mpers:Revenue",
                "qwen_concept_qname": "ssmt-mpers:Assets",
            }
        ]
        root, _case_dir = self._case_dir(rows=rows)
        _summary, _alignment, baseline = build_golden_mbrs_reports(cases_dir=root)
        self.assertEqual(baseline["deterministic_mapping_accuracy"]["accuracy"], 1.0)
        self.assertEqual(baseline["qwen_mapping_accuracy"]["accuracy"], 0.0)
        self.assertFalse(baseline["run_metadata"]["external_llm_called"])


if __name__ == "__main__":
    unittest.main()
