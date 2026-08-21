import inspect
import unittest

from services import section_aware_initial_mapping_llm as boundary


class InitialMappingPayloadBoundaryTests(unittest.TestCase):
    def test_forbidden_external_payload_classes_are_permanent(self):
        required = {
            "auditor_xml",
            "reference_xml",
            "parsed_xbrl",
            "generated_xbrl",
            "benchmark_gold",
            "correct_qname",
            "expected_qname",
            "evaluation_label",
            "confirmed_tag_id",
            "final_mapping",
        }
        self.assertTrue(required.issubset(boundary.FORBIDDEN_PAYLOAD_KEY_FRAGMENTS))

    def test_boundary_module_has_no_reference_report_or_gold_loader(self):
        source = inspect.getsource(boundary).lower()
        self.assertNotIn("reference_xbrl_parser", source)
        self.assertNotIn("golden_mbrs_dataset", source)
        self.assertNotIn("fs_mpers_concept_playbook", source)


if __name__ == "__main__":
    unittest.main()
