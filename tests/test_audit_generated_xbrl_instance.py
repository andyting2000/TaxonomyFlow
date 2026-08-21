import tempfile
import unittest
from pathlib import Path

from scripts.audit_generated_xbrl_instance import (
    ExpectedFact,
    compare_expected_to_generated,
    parse_xbrl_instance,
    summarize_facts,
    summarize_context_unit_usage,
)


XBRL_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl
  xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:link="http://www.xbrl.org/2003/linkbase"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
  xmlns:ssmt="http://www.ssm.com.my/xbrl/ssm/taxonomy/2022-12-31/ssmt">
  <link:schemaRef xlink:type="simple" xlink:href="local.xsd"/>
  <xbrli:context id="asof_2024-12-31">
    <xbrli:entity>
      <xbrli:identifier scheme="https://www.ssm.com.my">123</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period>
      <xbrli:instant>2024-12-31</xbrli:instant>
    </xbrli:period>
  </xbrli:context>
  <xbrli:unit id="MYR">
    <xbrli:measure>iso4217:MYR</xbrli:measure>
  </xbrli:unit>
  <ssmt:Assets contextRef="asof_2024-12-31" unitRef="MYR" decimals="0">100</ssmt:Assets>
  <ssmt:Assets contextRef="asof_2024-12-31" unitRef="MYR" decimals="0">100</ssmt:Assets>
  <ssmt:Liabilities contextRef="asof_2024-12-31" unitRef="MYR" decimals="0">-20</ssmt:Liabilities>
</xbrli:xbrl>
"""


class AuditGeneratedXbrlInstanceTests(unittest.TestCase):
    def _parse_fixture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.xbrl"
            path.write_text(XBRL_FIXTURE, encoding="utf-8")
            return parse_xbrl_instance(path)

    def test_parse_xbrl_instance_summarizes_facts_contexts_and_units(self):
        parsed = self._parse_fixture()

        self.assertEqual(len(parsed["facts"]), 3)
        self.assertEqual(parsed["schema_refs"], ["local.xsd"])
        self.assertEqual(parsed["contexts"]["count"], 1)
        self.assertEqual(parsed["contexts"]["period_type_counts"], {"instant": 1})
        self.assertEqual(parsed["units"]["ids"], ["MYR"])

    def test_fact_summary_detects_duplicate_and_negative_facts(self):
        parsed = self._parse_fixture()
        summary = summarize_facts(parsed["facts"])

        self.assertEqual(summary["total_generated_facts"], 3)
        self.assertEqual(summary["duplicate_concept_context_unit_facts"]["group_count"], 1)
        self.assertEqual(
            summary["concepts_multiple_times_identical_value_context_unit"]["group_count"],
            1,
        )
        self.assertEqual(summary["negative_numeric_facts"]["count"], 1)
        self.assertEqual(summary["monetary_facts_without_unitRef"]["count"], 0)

    def test_compare_expected_to_generated_reports_coverage_and_leftovers(self):
        parsed = self._parse_fixture()
        expected = [
            ExpectedFact(
                item_id="item-1",
                page_id="page-1",
                page_number=1,
                extracted_label="Assets",
                extracted_value="100",
                statement_type="Statement of Financial Position",
                template_field_id="ssmt:Assets",
                confirmed_tag_id=None,
                concept_source="template_field_id",
                concept="ssmt:Assets",
                context_ref="asof_2024-12-31",
                unit_ref="MYR",
                value="100",
                value_year=2024,
                source_value_column="extracted_value",
                signed_value_suspicious=False,
            )
        ]

        coverage = compare_expected_to_generated(expected, parsed["facts"])

        self.assertEqual(coverage["expected_generated_fact_count"], 1)
        self.assertEqual(coverage["represented_expected_fact_count"], 1)
        self.assertEqual(coverage["not_represented_expected_fact_count"], 0)
        self.assertEqual(coverage["xbrl_facts_not_traceable_to_extracted_rows"]["count"], 2)

    def test_context_unit_usage_detects_missing_references(self):
        parsed = self._parse_fixture()
        facts = parsed["facts"] + [
            {
                "concept": "ssmt:Equity",
                "namespace": "http://www.ssm.com.my/xbrl/ssm/taxonomy/2022-12-31/ssmt",
                "prefix": "ssmt",
                "local_name": "Equity",
                "contextRef": "missing_context",
                "unitRef": "missing_unit",
                "decimals": "0",
                "value": "80",
                "is_numeric": True,
            }
        ]

        summary = summarize_context_unit_usage(parsed, facts)

        self.assertEqual(summary["contexts"]["missing_context_refs"], ["missing_context"])
        self.assertEqual(summary["units"]["missing_unit_refs"], ["missing_unit"])


if __name__ == "__main__":
    unittest.main()
