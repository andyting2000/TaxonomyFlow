import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional, List

# Load environment variables from .env file
load_dotenv()


class Settings(BaseSettings):
    # Database Configuration
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5433/xbrl_db")

    # Redis Configuration
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6380/0")

    # Celery Configuration
    celery_broker_url: str = os.getenv(
        "CELERY_BROKER_URL", "redis://localhost:6380/0")
    celery_result_backend: str = os.getenv(
        "CELERY_RESULT_BACKEND", "redis://localhost:6380/0")

    # File Storage
    upload_directory: str = os.getenv("UPLOAD_DIRECTORY", "uploads")
    max_file_size: int = int(os.getenv("MAX_FILE_SIZE", 50 * 1024 * 1024))
    allowed_extensions: List[str] = [".pdf"]

    # Windows specific paths
    temp_directory: str = os.getenv("TEMP_DIRECTORY", "C:\\temp\\xbrl")

    # AI Processing
    configured_model_provider: str = os.getenv("MODEL_PROVIDER", "huggingface").strip().lower()
    deprecated_model_provider: Optional[str] = (
        configured_model_provider if configured_model_provider == "openai" else None
    )
    model_provider: str = (
        "huggingface" if configured_model_provider in {"", "openai"} else configured_model_provider
    )
    model_api_token: str = os.getenv(
        "MODEL_API_TOKEN",
        os.getenv("HUGGING_FACE_TOKEN", "")
    )
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_text_model: str = os.getenv(
        "OPENAI_TEXT_MODEL", "gpt-4.1-mini"
    )
    openai_vision_model: str = os.getenv(
        "OPENAI_VISION_MODEL", "gpt-4.1-mini"
    )
    openai_embedding_model: str = os.getenv(
        "OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"
    )
    hugging_face_token: str = os.getenv(
        "MODEL_API_TOKEN",
        os.getenv("HUGGING_FACE_TOKEN", "")
    )
    ai_text_model_id: str = os.getenv(
        "TEXT_MODEL_ID",
        os.getenv("AI_TEXT_MODEL_ID", "Qwen/Qwen3-30B-A3B-Instruct-2507:featherless-ai")
    )
    ai_vlm_model_id: str = os.getenv(
        "VISION_MODEL_ID",
        os.getenv("AI_VLM_MODEL_ID", "Qwen/Qwen2.5-VL-72B-Instruct:hyperbolic")
    )
    embedding_model_id: str = os.getenv(
        "EMBEDDING_MODEL_ID",
        os.getenv("HF_EMBEDDING_MODEL_ID", "Qwen/Qwen3-Embedding-8B")
    )
    embedding_dimension: Optional[int] = (
        int(os.getenv("EMBEDDING_DIMENSION"))
        if os.getenv("EMBEDDING_DIMENSION")
        else 4096
    )
    embedding_normalize: bool = os.getenv("EMBEDDING_NORMALIZE", "true").lower() == "true"
    hf_inference_timeout_seconds: float = float(os.getenv("HF_INFERENCE_TIMEOUT_SECONDS", "60"))
    hf_inference_max_retries: int = int(os.getenv("HF_INFERENCE_MAX_RETRIES", "2"))
    pdf_render_dpi: int = int(os.getenv("PDF_RENDER_DPI", 300))
    max_pdf_pages: int = int(os.getenv("MAX_PDF_PAGES", 300))
    pdf_render_dpi_text_fast_path: int = int(
        os.getenv("PDF_RENDER_DPI_TEXT_FAST_PATH", 200))
    pdf_text_fast_path_min_chars: int = int(
        os.getenv("PDF_TEXT_FAST_PATH_MIN_CHARS", 400))
    pdf_text_context_chars: int = int(
        os.getenv("PDF_TEXT_CONTEXT_CHARS", 3000))
    extraction_text_min_chars: int = int(
        os.getenv("EXTRACTION_TEXT_MIN_CHARS", 250))
    page_quality_min_text_score: float = float(
        os.getenv("PAGE_QUALITY_MIN_TEXT_SCORE", 0.55))
    page_quality_force_vlm_score: float = float(
        os.getenv("PAGE_QUALITY_FORCE_VLM_SCORE", 0.35))
    region_vlm_enabled: bool = os.getenv(
        "REGION_VLM_ENABLED", "true").lower() == "true"
    region_vlm_max_regions: int = int(
        os.getenv("REGION_VLM_MAX_REGIONS", 3))

    # Azure Document Intelligence benchmark spike configuration.
    extraction_pipeline: str = os.getenv("EXTRACTION_PIPELINE", "azure_di").strip().lower()
    extraction_allow_legacy_fallback: bool = os.getenv(
        "EXTRACTION_ALLOW_LEGACY_FALLBACK",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    azure_document_intelligence_endpoint: str = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "")
    azure_document_intelligence_key: str = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY", "")
    azure_document_intelligence_model_id: str = os.getenv(
        "AZURE_DOCUMENT_INTELLIGENCE_MODEL_ID",
        "prebuilt-layout",
    )
    azure_document_intelligence_timeout_seconds: int = int(
        os.getenv("AZURE_DOCUMENT_INTELLIGENCE_TIMEOUT_SECONDS", "180")
    )
    azure_document_intelligence_max_retries: int = int(
        os.getenv("AZURE_DOCUMENT_INTELLIGENCE_MAX_RETRIES", "2")
    )
    azure_document_intelligence_pages: str = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_PAGES", "")
    azure_di_normalization_timeout_seconds: float = float(
        os.getenv("AZURE_DI_NORMALIZATION_TIMEOUT_SECONDS", "120")
    )
    azure_di_text_blocks_enabled: bool = os.getenv(
        "AZURE_DI_TEXT_BLOCKS_ENABLED",
        "true",
    ).strip().lower() in {"1", "true", "yes", "on"}
    azure_di_text_block_timeout_seconds: float = float(
        os.getenv("AZURE_DI_TEXT_BLOCK_TIMEOUT_SECONDS", "15")
    )
    azure_di_allow_table_fallback_on_text_timeout: bool = os.getenv(
        "AZURE_DI_ALLOW_TABLE_FALLBACK_ON_TEXT_TIMEOUT",
        "true",
    ).strip().lower() in {"1", "true", "yes", "on"}

    # Deterministic TOC-aware document structure foundation (#19A).
    # Analysis and artifact persistence are independently disabled by default.
    # The LLM fallback flag is reserved for a later feature and is not executed.
    toc_aware_pipeline_enabled: bool = os.getenv(
        "TOC_AWARE_PIPELINE_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    toc_aware_structure_persistence_enabled: bool = os.getenv(
        "TOC_AWARE_STRUCTURE_PERSISTENCE_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    toc_aware_llm_fallback_enabled: bool = os.getenv(
        "TOC_AWARE_LLM_FALLBACK_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}

    # Canonical section-to-template classification (#19B).
    # Classification, persistence, and live fallback are independently
    # disabled by default. Enabling classification still requires #19A.
    toc_aware_template_classification_enabled: bool = os.getenv(
        "TOC_AWARE_TEMPLATE_CLASSIFICATION_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    toc_aware_template_classification_persistence_enabled: bool = os.getenv(
        "TOC_AWARE_TEMPLATE_CLASSIFICATION_PERSISTENCE_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    toc_aware_template_classification_live_llm_enabled: bool = os.getenv(
        "TOC_AWARE_TEMPLATE_CLASSIFICATION_LIVE_LLM_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    toc_aware_template_classification_model_id: str = os.getenv(
        "TOC_AWARE_TEMPLATE_CLASSIFICATION_MODEL_ID",
        os.getenv(
            "TEXT_MODEL_ID",
            "Qwen/Qwen3-30B-A3B-Instruct-2507:featherless-ai",
        ),
    )
    toc_aware_template_classification_max_characters: int = int(
        os.getenv("TOC_AWARE_TEMPLATE_CLASSIFICATION_MAX_CHARACTERS", "12000")
    )
    toc_aware_template_classification_max_paragraphs: int = int(
        os.getenv("TOC_AWARE_TEMPLATE_CLASSIFICATION_MAX_PARAGRAPHS", "12")
    )
    toc_aware_template_classification_max_table_headers: int = int(
        os.getenv("TOC_AWARE_TEMPLATE_CLASSIFICATION_MAX_TABLE_HEADERS", "12")
    )
    toc_aware_template_classification_max_row_labels: int = int(
        os.getenv("TOC_AWARE_TEMPLATE_CLASSIFICATION_MAX_ROW_LABELS", "20")
    )
    toc_aware_template_classification_max_template_cards: int = int(
        os.getenv("TOC_AWARE_TEMPLATE_CLASSIFICATION_MAX_TEMPLATE_CARDS", "8")
    )

    # Section-aware taxonomy retrieval and advisory initial mapping (#19C).
    # Every execution and live-provider control is independently false by
    # default. The normal production mapping workflow remains separate.
    toc_aware_taxonomy_candidate_retrieval_enabled: bool = os.getenv(
        "TOC_AWARE_TAXONOMY_CANDIDATE_RETRIEVAL_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    toc_aware_initial_mapping_enabled: bool = os.getenv(
        "TOC_AWARE_INITIAL_MAPPING_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    toc_aware_initial_mapping_persistence_enabled: bool = os.getenv(
        "TOC_AWARE_INITIAL_MAPPING_PERSISTENCE_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    toc_aware_initial_mapping_live_llm_enabled: bool = os.getenv(
        "TOC_AWARE_INITIAL_MAPPING_LIVE_LLM_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    toc_aware_initial_mapping_mode: str = os.getenv(
        "TOC_AWARE_INITIAL_MAPPING_MODE",
        "deterministic_only",
    ).strip().lower()
    toc_aware_initial_mapping_model_id: str = os.getenv(
        "TOC_AWARE_INITIAL_MAPPING_MODEL_ID",
        os.getenv("LLM_MAPPING_MODEL_ID", "Qwen/Qwen3-235B-A22B-Instruct-2507"),
    ).strip()
    toc_aware_initial_mapping_max_candidates: int = min(
        20,
        max(1, int(os.getenv("TOC_AWARE_INITIAL_MAPPING_MAX_CANDIDATES", "8"))),
    )
    toc_aware_initial_mapping_max_rows_per_job: int = max(
        1,
        int(os.getenv("TOC_AWARE_INITIAL_MAPPING_MAX_ROWS_PER_JOB", "5000")),
    )
    toc_aware_initial_mapping_row_timeout_seconds: float = max(
        1.0,
        float(os.getenv("TOC_AWARE_INITIAL_MAPPING_ROW_TIMEOUT_SECONDS", "120")),
    )
    toc_aware_initial_mapping_max_concurrent_calls: int = max(
        1,
        int(os.getenv("TOC_AWARE_INITIAL_MAPPING_MAX_CONCURRENT_CALLS", "1")),
    )
    toc_aware_initial_mapping_min_candidate_score: float = min(
        1.0,
        max(
            0.0,
            float(os.getenv("TOC_AWARE_INITIAL_MAPPING_MIN_CANDIDATE_SCORE", "0.0")),
        ),
    )
    toc_aware_initial_mapping_max_context_characters: int = max(
        1000,
        int(os.getenv("TOC_AWARE_INITIAL_MAPPING_MAX_CONTEXT_CHARACTERS", "12000")),
    )
    toc_aware_initial_mapping_max_siblings: int = max(
        0,
        int(os.getenv("TOC_AWARE_INITIAL_MAPPING_MAX_SIBLINGS", "4")),
    )
    toc_aware_initial_mapping_max_ancestors: int = max(
        0,
        int(os.getenv("TOC_AWARE_INITIAL_MAPPING_MAX_ANCESTORS", "3")),
    )
    toc_aware_initial_mapping_max_descendants: int = max(
        0,
        int(os.getenv("TOC_AWARE_INITIAL_MAPPING_MAX_DESCENDANTS", "3")),
    )
    toc_aware_initial_mapping_max_nearby_paragraphs: int = max(
        0,
        int(os.getenv("TOC_AWARE_INITIAL_MAPPING_MAX_NEARBY_PARAGRAPHS", "2")),
    )

    # Candidate-constrained LLM taxonomy mapping suggestions after Azure DI.
    llm_mapping_enabled: bool = os.getenv(
        "LLM_MAPPING_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    llm_mapping_model_id: str = os.getenv(
        "LLM_MAPPING_MODEL_ID",
        "Qwen/Qwen3-235B-A22B-Instruct-2507",
    )
    llm_mapping_max_candidates: int = int(os.getenv("LLM_MAPPING_MAX_CANDIDATES", "8"))
    llm_mapping_timeout_seconds: float = float(os.getenv("LLM_MAPPING_TIMEOUT_SECONDS", "60"))
    llm_mapping_high_confidence_threshold: float = float(
        os.getenv("LLM_MAPPING_HIGH_CONFIDENCE_THRESHOLD", "0.88")
    )
    llm_mapping_min_display_confidence: float = float(
        os.getenv("LLM_MAPPING_MIN_DISPLAY_CONFIDENCE", "0.50")
    )
    llm_mapping_min_manual_confidence: float = float(
        os.getenv("LLM_MAPPING_MIN_MANUAL_CONFIDENCE", "0.0")
    )
    llm_mapping_max_rows_per_job: int = int(os.getenv("LLM_MAPPING_MAX_ROWS_PER_JOB", "50"))
    llm_mapping_auto_apply_high_confidence: bool = os.getenv(
        "LLM_MAPPING_AUTO_APPLY_HIGH_CONFIDENCE",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    llm_mapping_fewshot_enabled: bool = os.getenv(
        "LLM_MAPPING_FEWSHOT_ENABLED",
        "true",
    ).strip().lower() in {"1", "true", "yes", "on"}
    llm_mapping_fewshot_max_examples: int = int(os.getenv("LLM_MAPPING_FEWSHOT_MAX_EXAMPLES", "3"))
    llm_mapping_fewshot_case_split_mode: str = os.getenv(
        "LLM_MAPPING_FEWSHOT_CASE_SPLIT_MODE",
        "training_only",
    )
    llm_mapping_fewshot_guardrails_enabled: bool = os.getenv(
        "LLM_MAPPING_FEWSHOT_GUARDRAILS_ENABLED",
        "true",
    ).strip().lower() in {"1", "true", "yes", "on"}
    llm_mapping_fewshot_fallback_to_base_prompt: bool = os.getenv(
        "LLM_MAPPING_FEWSHOT_FALLBACK_TO_BASE_PROMPT",
        "true",
    ).strip().lower() in {"1", "true", "yes", "on"}
    llm_mapping_provider_rate_limit_max_retries: int = int(
        os.getenv("LLM_MAPPING_PROVIDER_RATE_LIMIT_MAX_RETRIES", "2")
    )
    llm_mapping_provider_rate_limit_base_delay_seconds: float = float(
        os.getenv("LLM_MAPPING_PROVIDER_RATE_LIMIT_BASE_DELAY_SECONDS", "4")
    )
    llm_mapping_provider_rate_limit_max_delay_seconds: float = float(
        os.getenv("LLM_MAPPING_PROVIDER_RATE_LIMIT_MAX_DELAY_SECONDS", "30")
    )
    llm_mapping_provider_request_delay_seconds: float = float(
        os.getenv("LLM_MAPPING_PROVIDER_REQUEST_DELAY_SECONDS", "0.5")
    )

    # Independent Supervisor LLM evaluation for #17D-B.
    # This is intentionally separate from MODEL_API_TOKEN/TEXT_MODEL_ID and
    # LLM_MAPPING_MODEL_ID; live supervisor runs must not silently reuse mapper
    # credentials or model config.
    supervisor_llm_enabled: bool = os.getenv(
        "SUPERVISOR_LLM_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    supervisor_llm_provider: str = os.getenv("SUPERVISOR_LLM_PROVIDER", "hf").strip().lower()
    supervisor_llm_api_token: str = os.getenv("SUPERVISOR_LLM_API_TOKEN", "")
    supervisor_llm_model_id: str = os.getenv("SUPERVISOR_LLM_MODEL_ID", "")
    supervisor_llm_base_url: str = os.getenv(
        "SUPERVISOR_LLM_BASE_URL",
        "https://router.huggingface.co/v1",
    )
    supervisor_llm_response_format: str = os.getenv("SUPERVISOR_LLM_RESPONSE_FORMAT", "json_schema").strip().lower()
    supervisor_llm_timeout_seconds: float = float(os.getenv("SUPERVISOR_LLM_TIMEOUT_SECONDS", "120"))
    supervisor_llm_max_retries: int = int(os.getenv("SUPERVISOR_LLM_MAX_RETRIES", "2"))
    supervisor_llm_retry_base_seconds: float = float(os.getenv("SUPERVISOR_LLM_RETRY_BASE_SECONDS", "3"))
    supervisor_llm_retry_max_seconds: float = float(os.getenv("SUPERVISOR_LLM_RETRY_MAX_SECONDS", "30"))
    supervisor_llm_repair_enabled: bool = os.getenv(
        "SUPERVISOR_LLM_REPAIR_ENABLED",
        "true",
    ).strip().lower() in {"1", "true", "yes", "on"}
    supervisor_llm_max_repair_retries: int = int(os.getenv("SUPERVISOR_LLM_MAX_REPAIR_RETRIES", "1"))

    # Production Supervisor live execution gate for #17D-C-E-A.
    # Live reviews are explicit, advisory-only, disabled by default, and use
    # only the independent SUPERVISOR_LLM_* client settings above.
    supervisor_production_live_enabled: bool = os.getenv(
        "SUPERVISOR_PRODUCTION_LIVE_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    supervisor_production_live_admin_only: bool = os.getenv(
        "SUPERVISOR_PRODUCTION_LIVE_ADMIN_ONLY",
        "true",
    ).strip().lower() in {"1", "true", "yes", "on"}
    supervisor_production_live_max_batch_size: int = max(
        1,
        int(os.getenv("SUPERVISOR_PRODUCTION_LIVE_MAX_BATCH_SIZE", "10")),
    )
    # Legacy compatibility setting. HTTP request schemas intentionally default
    # omitted modes to mock and do not use this value. A future config cleanup
    # may replace it with the clearer SUPERVISOR_DEFAULT_MODE name.
    supervisor_production_live_default_mode: str = os.getenv(
        "SUPERVISOR_PRODUCTION_LIVE_DEFAULT_MODE",
        "mock",
    ).strip().lower()

    # Manual Supervisor-guided mapper correction (#18F-G-A). This is an
    # explicit advisory rerun only; automatic recursion remains unsupported.
    supervisor_mapper_feedback_enabled: bool = os.getenv(
        "SUPERVISOR_MAPPER_FEEDBACK_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    supervisor_mapper_feedback_auto_run: bool = os.getenv(
        "SUPERVISOR_MAPPER_FEEDBACK_AUTO_RUN",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    supervisor_mapper_feedback_max_retries: int = max(
        0,
        int(os.getenv("SUPERVISOR_MAPPER_FEEDBACK_MAX_RETRIES", "1")),
    )
    supervisor_mapper_feedback_admin_only: bool = os.getenv(
        "SUPERVISOR_MAPPER_FEEDBACK_ADMIN_ONLY",
        "true",
    ).strip().lower() in {"1", "true", "yes", "on"}

    # Conditional Supervisor orchestration planning (#18F-G-B). Eligibility is
    # local-only; automatic provider review and remapping remain unsupported.
    supervisor_orchestration_enabled: bool = os.getenv(
        "SUPERVISOR_ORCHESTRATION_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    supervisor_orchestration_default_mode: str = os.getenv(
        "SUPERVISOR_ORCHESTRATION_DEFAULT_MODE",
        "manual",
    ).strip().lower()
    supervisor_orchestration_auto_eligibility: bool = os.getenv(
        "SUPERVISOR_ORCHESTRATION_AUTO_ELIGIBILITY",
        "true",
    ).strip().lower() in {"1", "true", "yes", "on"}
    supervisor_orchestration_auto_review: bool = os.getenv(
        "SUPERVISOR_ORCHESTRATION_AUTO_REVIEW",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    supervisor_orchestration_auto_remap: bool = os.getenv(
        "SUPERVISOR_ORCHESTRATION_AUTO_REMAP",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    supervisor_orchestration_admin_only: bool = os.getenv(
        "SUPERVISOR_ORCHESTRATION_ADMIN_ONLY",
        "true",
    ).strip().lower() in {"1", "true", "yes", "on"}
    # Comma-separated positive user IDs for the controlled internal-reviewer
    # rollout. Empty is fail-closed for every non-admin user.
    supervisor_orchestration_allowed_user_ids: str = os.getenv(
        "SUPERVISOR_ORCHESTRATION_ALLOWED_USER_IDS",
        "",
    ).strip()
    supervisor_orchestration_max_batch_size: int = max(
        1,
        int(os.getenv("SUPERVISOR_ORCHESTRATION_MAX_BATCH_SIZE", "10")),
    )
    supervisor_orchestration_max_remap_retries: int = max(
        0,
        int(os.getenv("SUPERVISOR_ORCHESTRATION_MAX_REMAP_RETRIES", "1")),
    )
    supervisor_orchestration_min_risk: str = os.getenv(
        "SUPERVISOR_ORCHESTRATION_MIN_RISK",
        "medium",
    ).strip().lower()
    supervisor_orchestration_max_concurrent_live_calls: int = max(
        1,
        int(os.getenv("SUPERVISOR_ORCHESTRATION_MAX_CONCURRENT_LIVE_CALLS", "2")),
    )
    supervisor_orchestration_confidence_threshold: float = min(
        1.0,
        max(
            0.0,
            float(os.getenv("SUPERVISOR_ORCHESTRATION_CONFIDENCE_THRESHOLD", "0.85")),
        ),
    )
    supervisor_orchestration_per_row_timeout_seconds: float = max(
        1.0,
        float(os.getenv("SUPERVISOR_ORCHESTRATION_PER_ROW_TIMEOUT_SECONDS", "120")),
    )

    # Deterministic PDF-XBRL rulebook advisory mapper API (#18D-D).
    # Disabled by default, dry-run only, and persistence remains blocked.
    rulebook_mapper_advisory_enabled: bool = os.getenv(
        "RULEBOOK_MAPPER_ADVISORY_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    rulebook_mapper_advisory_default_mode: str = os.getenv(
        "RULEBOOK_MAPPER_ADVISORY_DEFAULT_MODE",
        "dry_run",
    ).strip().lower()
    rulebook_mapper_advisory_allow_persistence: bool = os.getenv(
        "RULEBOOK_MAPPER_ADVISORY_ALLOW_PERSISTENCE",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}

    # Ranked taxonomy candidate advisory design (#18F-C).
    # Disabled by default, dry-run only, and persistence remains blocked.
    ranked_candidates_advisory_enabled: bool = os.getenv(
        "RANKED_CANDIDATES_ADVISORY_ENABLED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    ranked_candidates_advisory_default_mode: str = os.getenv(
        "RANKED_CANDIDATES_ADVISORY_DEFAULT_MODE",
        "dry_run",
    ).strip().lower()
    ranked_candidates_advisory_allow_persistence: bool = os.getenv(
        "RANKED_CANDIDATES_ADVISORY_ALLOW_PERSISTENCE",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    ranked_candidates_advisory_default_profile: str = os.getenv(
        "RANKED_CANDIDATES_ADVISORY_DEFAULT_PROFILE",
        "balanced",
    ).strip().lower()
    ranked_candidates_advisory_max_rows: int = max(
        1,
        int(os.getenv("RANKED_CANDIDATES_ADVISORY_MAX_ROWS", "1000")),
    )
    ranked_candidates_advisory_max_candidates_per_row: int = max(
        1,
        int(os.getenv("RANKED_CANDIDATES_ADVISORY_MAX_CANDIDATES_PER_ROW", "5")),
    )
    ranked_candidates_advisory_admin_only: bool = os.getenv(
        "RANKED_CANDIDATES_ADVISORY_ADMIN_ONLY",
        "true",
    ).strip().lower() in {"1", "true", "yes", "on"}

    # Security
    secret_key: str = os.getenv("SECRET_KEY", "")
    admin_route_token: str = os.getenv(
        "ADMIN_ROUTE_TOKEN", "replace-with-random-admin-route-token")
    bootstrap_admin_enabled: bool = os.getenv(
        "BOOTSTRAP_ADMIN_ENABLED", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    bootstrap_admin_email: str = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "")
    bootstrap_admin_password: str = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    cors_allowed_origins: str = os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:8001,http://127.0.0.1:8001"
    )

    # Performance
    cache_ttl: int = int(os.getenv("CACHE_TTL", 3600))
    search_cache_ttl: int = int(os.getenv("SEARCH_CACHE_TTL", 14400))
    page_size: int = int(os.getenv("PAGE_SIZE", 50))
    slow_query_threshold: float = float(os.getenv("SLOW_QUERY_THRESHOLD", 2.0))

    # Application
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug(cls, value):
        """Accept common environment strings like 'release' or 'development'."""
        if isinstance(value, bool):
            return value
        if value is None:
            return False

        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on", "debug", "development", "dev"}:
            return True
        if normalized in {"0", "false", "no", "off", "release", "production", "prod"}:
            return False
        return value

    @field_validator("model_provider", mode="before")
    @classmethod
    def normalize_model_provider(cls, value):
        normalized = str(value or "huggingface").strip().lower()
        if normalized in {"", "openai"}:
            return "huggingface"
        return normalized

    @field_validator("extraction_pipeline", mode="before")
    @classmethod
    def normalize_extraction_pipeline(cls, value):
        normalized = str(value or "azure_di").strip().lower()
        if normalized not in {"azure_di", "legacy"}:
            raise ValueError("EXTRACTION_PIPELINE must be one of: azure_di, legacy")
        return normalized

    class Config:
        # No longer need env_file since we're using load_dotenv()
        extra = "allow"  # Allow extra fields from environment

    @property
    def cors_allowed_origin_list(self) -> List[str]:
        """Return comma-separated CORS origins as a list for FastAPI."""
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]


# Create settings instance
settings = Settings()

# Print loaded configuration (for debugging)
if __name__ == "__main__":
    print("🔧 Configuration Loaded:")
    print(f"Database URL: {settings.database_url}")
    print(f"Redis URL: {settings.redis_url}")
    print(f"Celery Broker: {settings.celery_broker_url}")
    print(f"Upload Directory: {settings.upload_directory}")
    print(f"Temp Directory: {settings.temp_directory}")
    print(f"Debug Mode: {settings.debug}")
    print(f"Model Provider: {settings.model_provider}")
    if settings.deprecated_model_provider:
        print(f"Deprecated Provider Ignored: {settings.deprecated_model_provider}")
    print(f"Text Model ID: {settings.ai_text_model_id}")
    print(f"Vision Model ID: {settings.ai_vlm_model_id}")
    print(f"Embedding Model ID: {settings.embedding_model_id}")
    print(
        f"Model API Token Set: {'Yes' if settings.model_api_token not in {'', 'replace-with-your-model-provider-token', 'YOUR_MODEL_API_TOKEN_HERE'} else 'No'}")
