"""Public score contract for #19C; implementation lives with retrieval."""

from schemas import CandidateScoreBreakdown
from services.section_aware_taxonomy_candidate_retriever import score_taxonomy_candidate

__all__ = ["CandidateScoreBreakdown", "score_taxonomy_candidate"]
