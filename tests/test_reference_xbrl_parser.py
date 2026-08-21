import tempfile
import unittest
from pathlib import Path

from services.reference_xbrl_parser import ReferenceXBRLParseError, parse_reference_xbrl


SIMPLE_XBRL = """<?xml version="1.0" encoding="utf-8"?>
<xbrli:xbrl
  xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
  xmlns:ssmt="http://xbrl.ssm.com.my/taxonomy/2022-12-31/ssmt-cor"
  xmlns:ifrs-smes="https://xbrl.ifrs.org/taxonomy/2022-03-24/ifrs-smes">
  <xbrli:context id="instant_ctx">
    <xbrli:entity><xbrli:identifier scheme="https://www.ssm.com.my/">123</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
    <xbrli:scenario>
      <xbrldi:explicitMember dimension="ifrs-smes:ConsolidatedAndSeparateFinancialStatementsAxis">ifrs-smes:SeparateMember</xbrldi:explicitMember>
    </xbrli:scenario>
  </xbrli:context>
  <xbrli:context id="duration_ctx">
    <xbrli:entity><xbrli:identifier scheme="https://www.ssm.com.my/">123</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="MYR"><xbrli:measure>iso4217:MYR</xbrli:measure></xbrli:unit>
  <ifrs-smes:Revenue contextRef="duration_ctx" unitRef="MYR" decimals="0">1,234</ifrs-smes:Revenue>
  <ssmt:CompanyName contextRef="instant_ctx">Example Sdn Bhd</ssmt:CompanyName>
  <ssmt:DisclosureOfAccountingPolicyTextBlock contextRef="duration_ctx">This is a long accounting policy disclosure that describes the basis of preparation, financial instruments, revenue recognition, estimates, and other accounting policies used by the company for the financial statements.</ssmt:DisclosureOfAccountingPolicyTextBlock>
  <ifrs-smes:Assets contextRef="instant_ctx">5678</ifrs-smes:Assets>
</xbrli:xbrl>
"""


class ReferenceXBRLParserTests(unittest.TestCase):
    def _write(self, content: str) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "reference.xml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_parse_simple_numeric_fact_with_context_and_unit(self):
        report = parse_reference_xbrl("case-a", self._write(SIMPLE_XBRL))
        revenue = next(fact for fact in report["facts"] if fact["local_name"] == "Revenue")
        self.assertTrue(revenue["is_numeric"])
        self.assertEqual(revenue["context_ref"], "duration_ctx")
        self.assertEqual(revenue["unit_ref"], "MYR")
        self.assertEqual(revenue["normalized_value"], "1234")

    def test_parse_text_fact(self):
        report = parse_reference_xbrl("case-a", self._write(SIMPLE_XBRL))
        company = next(fact for fact in report["facts"] if fact["local_name"] == "CompanyName")
        self.assertFalse(company["is_numeric"])
        self.assertEqual(company["value"], "Example Sdn Bhd")

    def test_parse_text_block_or_long_disclosure(self):
        report = parse_reference_xbrl("case-a", self._write(SIMPLE_XBRL))
        disclosure = next(fact for fact in report["facts"] if "TextBlock" in fact["local_name"])
        self.assertTrue(disclosure["is_text_block"])
        self.assertEqual(report["text_block_count"], 1)

    def test_parse_context_instant_and_dimensions(self):
        report = parse_reference_xbrl("case-a", self._write(SIMPLE_XBRL))
        assets = next(fact for fact in report["facts"] if fact["local_name"] == "Assets")
        self.assertEqual(assets["instant"], "2025-12-31")
        self.assertEqual(assets["period"], {"type": "instant", "instant": "2025-12-31"})
        self.assertEqual(assets["entity_identifier"], "123")
        self.assertEqual(assets["dimensions"][0]["member"], "ifrs-smes:SeparateMember")

    def test_parse_duration_context_start_and_end(self):
        report = parse_reference_xbrl("case-a", self._write(SIMPLE_XBRL))
        revenue = next(fact for fact in report["facts"] if fact["local_name"] == "Revenue")
        self.assertEqual(revenue["period_start"], "2025-01-01")
        self.assertEqual(revenue["period_end"], "2025-12-31")
        self.assertEqual(
            revenue["period"],
            {"type": "duration", "start_date": "2025-01-01", "end_date": "2025-12-31"},
        )

    def test_parse_unit(self):
        report = parse_reference_xbrl("case-a", self._write(SIMPLE_XBRL))
        self.assertEqual(report["units_count"], 1)

    def test_rejects_doctype_or_entity(self):
        path = self._write("""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x/>""")
        with self.assertRaises(ReferenceXBRLParseError):
            parse_reference_xbrl("case-a", path)

    def test_handle_missing_unit_ref_gracefully(self):
        report = parse_reference_xbrl("case-a", self._write(SIMPLE_XBRL))
        assets = next(fact for fact in report["facts"] if fact["local_name"] == "Assets")
        self.assertTrue(assets["is_numeric"])
        self.assertIn("numeric_looking_fact_without_unit_ref", assets["warnings"])

    def test_preserves_qname_local_name_and_namespace(self):
        report = parse_reference_xbrl("case-a", self._write(SIMPLE_XBRL))
        revenue = next(fact for fact in report["facts"] if fact["local_name"] == "Revenue")
        self.assertEqual(revenue["qname"], "ifrs-smes:Revenue")
        self.assertEqual(revenue["namespace_uri"], "https://xbrl.ifrs.org/taxonomy/2022-03-24/ifrs-smes")


if __name__ == "__main__":
    unittest.main()
