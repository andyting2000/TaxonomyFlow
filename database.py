# database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, DateTime, Boolean, Integer, Text, ForeignKey, Index, Float, CheckConstraint
from pgvector.sqlalchemy import Vector
from datetime import datetime
from typing import Optional, List, AsyncGenerator
import uuid
from config import settings

# Database setup
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_recycle=300,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)
 
class Base(DeclarativeBase):
    pass


# Dependency to get database session
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (
        Index("uq_users_email", "email", unique=True),
        Index("idx_users_active", "is_active"),
        Index("idx_users_deleted", "is_deleted"),
    )


class XMLTemplateField(Base):
    __tablename__ = "xml_template_fields"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    statement_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    statement_type: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    xbrl_tag: Mapped[str] = mapped_column(String(200), nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), default="string")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[Optional[str]] = mapped_column(String(500))
    
    # Embedding column for semantic search (same dimensions as taxonomy)
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(1752), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_template_field_label', 'label'),
        Index('idx_template_statement_code', 'statement_code'),
        Index('idx_template_xbrl_tag', 'xbrl_tag'),
        Index('idx_template_field_id', 'field_id'),
    )


class SemanticEmbedding(Base):
    __tablename__ = "semantic_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_label: Mapped[Optional[str]] = mapped_column(String(1000))
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[List[float]] = mapped_column(Vector(), nullable=False)
    source_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_hash: Mapped[Optional[str]] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        Index(
            "uq_semantic_embedding_provider_model_source_hash",
            "provider",
            "model",
            "source_type",
            "source_id",
            "source_text_hash",
            unique=True,
        ),
        Index("idx_semantic_embeddings_source", "source_type", "source_id"),
        Index("idx_semantic_embeddings_provider_model", "provider", "model"),
        Index("idx_semantic_embeddings_dimension", "provider", "model", "dimension"),
        Index("idx_semantic_embeddings_active", "is_active"),
    )


# Models
class MBRSTaxonomyTag(Base):
    __tablename__ = "mbrs_taxonomy_tags"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(1000), index=True)
    xbrl_tag: Mapped[str] = mapped_column(String(1000), index=True)
    namespace: Mapped[str] = mapped_column(String(50))
    period_type: Mapped[str] = mapped_column(String(10), default="duration")
    
    # Embedding column - truncated to 1752 dimensions for HNSW compatibility
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(1752), nullable=True)
    
    # Relationships
    confirmed_items: Mapped[List["ExtractedDataItem"]] = relationship(
        "ExtractedDataItem", 
        back_populates="confirmed_tag"
    )
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_label_search', 'label'),
        Index('idx_xbrl_tag', 'xbrl_tag'),
        Index('idx_namespace_period', 'namespace', 'period_type'),
    )


class FilingJob(Base):
    __tablename__ = "filing_jobs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    company_name: Mapped[str] = mapped_column(String(555))
    registration_number: Mapped[Optional[str]] = mapped_column(String(100))
    financial_year_end: Mapped[datetime] = mapped_column(DateTime)
    source_pdf_path: Mapped[str] = mapped_column(String(500))  # File path instead of FileField
    status: Mapped[str] = mapped_column(String(10), default="PROCESSING")  # PROCESSING, REVIEW, COMPLETED, ERROR
    progress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_mapping_status: Mapped[str] = mapped_column(String(20), default="not_started")
    ai_mapping_last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    directors_report_html: Mapped[Optional[str]] = mapped_column(Text)
    
    # Relationships
    pages: Mapped[List["FinancialStatementPage"]] = relationship(
        "FinancialStatementPage", 
        back_populates="job",
        cascade="all, delete-orphan"
    )
    llm_mapping_suggestions: Mapped[List["LLMMappingSuggestion"]] = relationship(
        "LLMMappingSuggestion",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    supervisor_reviews: Mapped[List["MappingSupervisorReview"]] = relationship(
        "MappingSupervisorReview",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    
    __table_args__ = (
        Index('idx_filing_jobs_user_uploaded', 'user_id', 'uploaded_at'),
        Index('idx_status_uploaded', 'status', 'uploaded_at'),
    )


class FinancialStatementPage(Base):
    __tablename__ = "financial_statement_pages"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[int] = mapped_column(ForeignKey("filing_jobs.id"))
    page_number: Mapped[int]
    image_path: Mapped[str] = mapped_column(String(500))  # Image file path
    
    # Relationships
    job: Mapped["FilingJob"] = relationship("FilingJob", back_populates="pages")
    extracted_items: Mapped[List["ExtractedDataItem"]] = relationship(
        "ExtractedDataItem", 
        back_populates="page",
        cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        Index('idx_job_page', 'job_id', 'page_number'),
    )

class ExtractedDataItem(Base):
    __tablename__ = "extracted_data_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    page_id: Mapped[str] = mapped_column(ForeignKey("financial_statement_pages.id"))
    extracted_label: Mapped[str] = mapped_column(String(1000))  # Increased from 555
    extracted_value: Mapped[str] = mapped_column(Text)  # Changed from String(500) to Text
    financial_year: Mapped[Optional[int]]
    value_previous_year: Mapped[Optional[str]] = mapped_column(Text)  # Changed to Text
    financial_year_previous: Mapped[Optional[int]]

    statement_type: Mapped[Optional[str]] = mapped_column(String(100))

    template_field_id: Mapped[Optional[str]] = mapped_column(String(200))
    template_position: Mapped[Optional[int]]
    is_required_field: Mapped[bool] = mapped_column(Boolean, default=False)

    is_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_tag_id: Mapped[Optional[int]] = mapped_column(ForeignKey("mbrs_taxonomy_tags.id"))

    # Validation fields (for calculation validation from linkbases)
    validation_warnings: Mapped[Optional[str]] = mapped_column(Text)  # JSON array of warnings
    has_calculation_warning: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    page: Mapped["FinancialStatementPage"] = relationship("FinancialStatementPage", back_populates="extracted_items")
    confirmed_tag: Mapped[Optional["MBRSTaxonomyTag"]] = relationship("MBRSTaxonomyTag", back_populates="confirmed_items")
    llm_mapping_suggestions: Mapped[List["LLMMappingSuggestion"]] = relationship(
        "LLMMappingSuggestion",
        back_populates="extracted_data_item",
        cascade="all, delete-orphan",
    )
    supervisor_reviews: Mapped[List["MappingSupervisorReview"]] = relationship(
        "MappingSupervisorReview",
        back_populates="extracted_data_item",
    )

    __table_args__ = (
        Index('idx_page_item', 'page_id', 'id'),
        Index('idx_reviewed_confirmed', 'is_reviewed', 'confirmed_tag_id'),
        Index('idx_statement_year', 'statement_type', 'financial_year'),
        Index('idx_template_field', 'template_field_id', 'statement_type'),
        Index('idx_template_position', 'statement_type', 'template_position'),
        Index('idx_validation_warnings', 'has_calculation_warning'),
    )


class LLMMappingSuggestion(Base):
    """Mapper output; rejected means abstention, while ignored is human rejection."""

    __tablename__ = "llm_mapping_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[int] = mapped_column(ForeignKey("filing_jobs.id", ondelete="CASCADE"), nullable=False)
    extracted_data_item_id: Mapped[str] = mapped_column(
        ForeignKey("extracted_data_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    suggested_template_field_id: Mapped[Optional[str]] = mapped_column(String(200))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    ranked_candidates_json: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="suggested")
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_response_preview: Mapped[Optional[str]] = mapped_column(Text)
    diagnostic_json: Mapped[Optional[str]] = mapped_column(Text)

    job: Mapped["FilingJob"] = relationship("FilingJob", back_populates="llm_mapping_suggestions")
    extracted_data_item: Mapped["ExtractedDataItem"] = relationship(
        "ExtractedDataItem",
        back_populates="llm_mapping_suggestions",
    )
    supervisor_reviews: Mapped[List["MappingSupervisorReview"]] = relationship(
        "MappingSupervisorReview",
        back_populates="llm_mapping_suggestion",
    )

    __table_args__ = (
        Index("idx_llm_mapping_suggestions_job", "job_id", "status"),
        Index("idx_llm_mapping_suggestions_item", "extracted_data_item_id"),
        Index("idx_llm_mapping_suggestions_template", "suggested_template_field_id"),
    )


class MappingSupervisorReview(Base):
    __tablename__ = "mapping_supervisor_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    job_id: Mapped[int] = mapped_column(ForeignKey("filing_jobs.id", ondelete="CASCADE"), nullable=False)
    extracted_data_item_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("extracted_data_items.id", ondelete="SET NULL")
    )
    llm_mapping_suggestion_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("llm_mapping_suggestions.id", ondelete="SET NULL")
    )
    mapper_selected_template_field_id: Mapped[Optional[str]] = mapped_column(String(200))
    mapper_selected_qname: Mapped[Optional[str]] = mapped_column(String(300))
    mapper_confidence: Mapped[Optional[float]] = mapped_column(Float)
    mapper_status: Mapped[Optional[str]] = mapped_column(String(40))
    review_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    supervisor_decision: Mapped[Optional[str]] = mapped_column(String(40))
    supervisor_risk_level: Mapped[Optional[str]] = mapped_column(String(20))
    supervisor_recommended_action: Mapped[Optional[str]] = mapped_column(String(50))
    supervisor_safe_to_accept: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    calibrated_safe_to_accept: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supervisor_confidence_adjustment: Mapped[Optional[str]] = mapped_column(String(20))
    supervisor_issues_json: Mapped[Optional[str]] = mapped_column(Text)
    supervisor_reason: Mapped[Optional[str]] = mapped_column(Text)
    supervisor_model_provider: Mapped[Optional[str]] = mapped_column(String(50))
    supervisor_model_id: Mapped[Optional[str]] = mapped_column(String(200))
    supervisor_prompt_version: Mapped[Optional[str]] = mapped_column(String(80))
    supervisor_schema_version: Mapped[Optional[str]] = mapped_column(String(80))
    supervisor_payload_hash: Mapped[Optional[str]] = mapped_column(String(64))
    supervisor_response_hash: Mapped[Optional[str]] = mapped_column(String(64))
    error_type: Mapped[Optional[str]] = mapped_column(String(80))
    error_message_sanitized: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    review_attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="mock", nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    job: Mapped["FilingJob"] = relationship("FilingJob", back_populates="supervisor_reviews")
    extracted_data_item: Mapped[Optional["ExtractedDataItem"]] = relationship(
        "ExtractedDataItem",
        back_populates="supervisor_reviews",
    )
    llm_mapping_suggestion: Mapped[Optional["LLMMappingSuggestion"]] = relationship(
        "LLMMappingSuggestion",
        back_populates="supervisor_reviews",
    )

    __table_args__ = (
        CheckConstraint(
            "review_status IN ('pending', 'running', 'completed', 'failed', 'skipped')",
            name="chk_mapping_supervisor_reviews_status",
        ),
        CheckConstraint(
            "supervisor_decision IS NULL OR supervisor_decision IN ('agree', 'disagree', 'needs_human_review')",
            name="chk_mapping_supervisor_reviews_decision",
        ),
        CheckConstraint(
            "supervisor_risk_level IS NULL OR supervisor_risk_level IN ('low', 'medium', 'high')",
            name="chk_mapping_supervisor_reviews_risk",
        ),
        CheckConstraint(
            "supervisor_recommended_action IS NULL OR supervisor_recommended_action IN "
            "('accept', 'reject', 'keep_for_human_review', 'request_better_candidate')",
            name="chk_mapping_supervisor_reviews_action",
        ),
        CheckConstraint(
            "supervisor_confidence_adjustment IS NULL OR supervisor_confidence_adjustment IN "
            "('increase', 'keep', 'decrease')",
            name="chk_mapping_supervisor_reviews_confidence_adjustment",
        ),
        CheckConstraint(
            "source IN ('mock', 'live', 'imported', 'manual')",
            name="chk_mapping_supervisor_reviews_source",
        ),
        CheckConstraint(
            "mapper_confidence IS NULL OR (mapper_confidence >= 0 AND mapper_confidence <= 1)",
            name="chk_mapping_supervisor_reviews_mapper_confidence",
        ),
        CheckConstraint("review_attempt >= 1", name="chk_mapping_supervisor_reviews_attempt"),
        Index("idx_mapping_supervisor_reviews_job", "job_id", "review_status"),
        Index("idx_mapping_supervisor_reviews_suggestion", "llm_mapping_suggestion_id"),
        Index("idx_mapping_supervisor_reviews_item", "extracted_data_item_id"),
        Index("idx_mapping_supervisor_reviews_status", "review_status"),
        Index("idx_mapping_supervisor_reviews_safe", "job_id", "supervisor_safe_to_accept"),
        Index("idx_mapping_supervisor_reviews_calibrated_safe", "job_id", "calibrated_safe_to_accept"),
        Index("idx_mapping_supervisor_reviews_risk", "job_id", "supervisor_risk_level"),
        Index("idx_mapping_supervisor_reviews_created", "created_at"),
    )


class SupervisorGuidedMappingRevision(Base):
    """Separate advisory mapper revision created from Supervisor feedback."""

    __tablename__ = "supervisor_guided_mapping_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[int] = mapped_column(ForeignKey("filing_jobs.id", ondelete="CASCADE"), nullable=False)
    parent_suggestion_id: Mapped[str] = mapped_column(
        ForeignKey("llm_mapping_suggestions.id", ondelete="CASCADE"),
        nullable=False,
    )
    supervisor_review_id: Mapped[str] = mapped_column(
        ForeignKey("mapping_supervisor_reviews.id", ondelete="CASCADE"),
        nullable=False,
    )
    correction_attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    correction_source: Mapped[str] = mapped_column(
        String(40),
        default="supervisor_feedback",
        nullable=False,
    )
    original_suggested_qname: Mapped[Optional[str]] = mapped_column(String(300))
    revised_suggested_qname: Mapped[Optional[str]] = mapped_column(String(300))
    revised_confidence: Mapped[Optional[float]] = mapped_column(Float)
    supervisor_decision: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    addressed_supervisor_issues_json: Mapped[Optional[str]] = mapped_column(Text)
    remaining_ambiguities_json: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    model_id: Mapped[Optional[str]] = mapped_column(String(200))
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    safe_for_auto_apply: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint(
            "correction_attempt >= 1",
            name="chk_supervisor_guided_revisions_attempt",
        ),
        CheckConstraint(
            "correction_source = 'supervisor_feedback'",
            name="chk_supervisor_guided_revisions_source",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="chk_supervisor_guided_revisions_status",
        ),
        CheckConstraint(
            "requires_human_review = TRUE",
            name="chk_supervisor_guided_revisions_human_review",
        ),
        CheckConstraint(
            "safe_for_auto_apply = FALSE",
            name="chk_supervisor_guided_revisions_no_auto_apply",
        ),
        Index("idx_supervisor_guided_revisions_job", "job_id", "created_at"),
        Index("idx_supervisor_guided_revisions_parent", "parent_suggestion_id", "correction_attempt", unique=True),
        Index("idx_supervisor_guided_revisions_review", "supervisor_review_id"),
    )
