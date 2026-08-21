from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config import settings
from schemas import JobStatus
from services.toc_aware_document_structure import document_structure_artifact_path
from services.toc_aware_template_classification import (
    load_template_classification,
    template_classification_artifact_path,
)
from tests import test_toc_aware_pipeline_integration as toc_pipeline_support


class TocAwareTemplateClassificationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def run_pipeline(
        self,
        uploads,
        *,
        classification_enabled,
        classification_persistence,
        live_llm=False,
        analyze_patch=None,
        persist_patch=None,
    ):
        helper = toc_pipeline_support.TocAwarePipelineIntegrationTests(
            methodName="runTest"
        )
        patches = [
            patch.object(
                settings,
                "toc_aware_template_classification_enabled",
                classification_enabled,
            ),
            patch.object(
                settings,
                "toc_aware_template_classification_persistence_enabled",
                classification_persistence,
            ),
            patch.object(
                settings,
                "toc_aware_template_classification_live_llm_enabled",
                live_llm,
            ),
        ]
        if analyze_patch is not None:
            patches.append(
                patch(
                    "services.toc_aware_template_classification.analyze_template_classification",
                    side_effect=analyze_patch,
                )
            )
        if persist_patch is not None:
            patches.append(
                patch(
                    "services.toc_aware_template_classification.persist_template_classification",
                    side_effect=persist_patch,
                )
            )
        entered = []
        try:
            for item in patches:
                entered.append(item)
                item.__enter__()
            return await helper.run_job(
                uploads,
                enabled=True,
                persistence=True,
            )
        finally:
            for item in reversed(entered):
                item.__exit__(None, None, None)

    async def test_false_default_classification_preserves_existing_pipeline(self):
        with tempfile.TemporaryDirectory() as disabled_temp, tempfile.TemporaryDirectory() as enabled_temp:
            disabled_uploads = Path(disabled_temp) / "uploads"
            with patch(
                "services.toc_aware_template_classification.analyze_template_classification"
            ) as analyzer:
                disabled = await self.run_pipeline(
                    disabled_uploads,
                    classification_enabled=False,
                    classification_persistence=False,
                )
            analyzer.assert_not_called()
            enabled_uploads = Path(enabled_temp) / "uploads"
            enabled = await self.run_pipeline(
                enabled_uploads,
                classification_enabled=True,
                classification_persistence=True,
            )
            with patch.object(settings, "upload_directory", str(enabled_uploads)):
                artifact = load_template_classification(16)

        disabled_result, _disabled_session, disabled_provider, disabled_snapshot = disabled
        enabled_result, enabled_session, enabled_provider, enabled_snapshot = enabled
        self.assertEqual(disabled_result.status, JobStatus.REVIEW)
        self.assertEqual(enabled_result.status, JobStatus.REVIEW)
        self.assertEqual(disabled_provider.call_count, 1)
        self.assertEqual(enabled_provider.call_count, 1)
        self.assertEqual(enabled_snapshot, disabled_snapshot)
        self.assertTrue(all(item.confirmed_tag_id is None for item in enabled_session.added_items))
        self.assertEqual(artifact.llm_count, 0)
        self.assertEqual(artifact.classification_version, "19B-v2")
        self.assertEqual(
            template_classification_artifact_path(16).name,
            "template_classification_19b_v2.json",
        )
        self.assertTrue(artifact.safety_summary["canonical_registry_only"])
        self.assertIn("notes_segmentation_metrics", artifact.safety_summary)
        self.assertFalse(artifact.safety_summary["taxonomy_qname_selection_performed"])
        self.assertFalse(artifact.safety_summary["template_values_mutated"])
        self.assertFalse(artifact.safety_summary["mapping_suggestions_mutated"])
        self.assertEqual(artifact.safety_summary["confirmed_tag_id_mutations"], 0)
        self.assertEqual(artifact.safety_summary["final_mapping_mutations"], 0)

    async def test_analysis_and_persistence_failures_are_warning_only(self):
        with tempfile.TemporaryDirectory() as analyze_temp:
            result, _session, _provider, _snapshot = await self.run_pipeline(
                Path(analyze_temp) / "uploads",
                classification_enabled=True,
                classification_persistence=True,
                analyze_patch=RuntimeError("synthetic classification failure"),
            )
            self.assertEqual(result.status, JobStatus.REVIEW)
            self.assertIn(
                "template_classification_analysis_failed",
                {warning["code"] for warning in result.warnings},
            )

        with tempfile.TemporaryDirectory() as persist_temp:
            uploads = Path(persist_temp) / "uploads"
            result, _session, _provider, _snapshot = await self.run_pipeline(
                uploads,
                classification_enabled=True,
                classification_persistence=True,
                persist_patch=OSError("synthetic persistence failure"),
            )
            self.assertEqual(result.status, JobStatus.REVIEW)
            self.assertIn(
                "template_classification_persistence_failed",
                {warning["code"] for warning in result.warnings},
            )
            with patch.object(settings, "upload_directory", str(uploads)):
                self.assertTrue(document_structure_artifact_path(16).is_file())
                self.assertFalse(template_classification_artifact_path(16).exists())

    async def test_live_llm_flag_false_makes_no_classification_provider_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "services.template_group_llm_classifier.HuggingFaceTemplateGroupClassificationClient"
            ) as client:
                result, _session, provider, _snapshot = await self.run_pipeline(
                    Path(temp_dir) / "uploads",
                    classification_enabled=True,
                    classification_persistence=True,
                    live_llm=False,
                )
        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(provider.call_count, 1)
        client.assert_not_called()

    async def test_retry_invalidates_prior_classification_even_when_now_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            await self.run_pipeline(
                uploads,
                classification_enabled=True,
                classification_persistence=True,
            )
            with patch.object(settings, "upload_directory", str(uploads)):
                self.assertTrue(template_classification_artifact_path(16).is_file())
            result, _session, provider, _snapshot = await self.run_pipeline(
                uploads,
                classification_enabled=False,
                classification_persistence=False,
            )
            with patch.object(settings, "upload_directory", str(uploads)):
                artifact_exists = template_classification_artifact_path(16).exists()
        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(provider.call_count, 1)
        self.assertFalse(artifact_exists)

    def test_all_new_flags_default_false_and_no_frontend_panel_was_added(self):
        with (
            patch.object(settings, "toc_aware_template_classification_enabled", False),
            patch.object(settings, "toc_aware_template_classification_persistence_enabled", False),
            patch.object(settings, "toc_aware_template_classification_live_llm_enabled", False),
        ):
            self.assertFalse(settings.toc_aware_template_classification_enabled)
            self.assertFalse(
                settings.toc_aware_template_classification_persistence_enabled
            )
            self.assertFalse(
                settings.toc_aware_template_classification_live_llm_enabled
            )
        workspace = (
            Path(__file__).resolve().parents[1]
            / "frontend"
            / "src"
            / "review-workspace.jsx"
        ).read_text(encoding="utf-8")
        self.assertNotIn("template-classification", workspace)
        self.assertNotIn("Template Classification", workspace)


if __name__ == "__main__":
    unittest.main()
