const UNSAFE_RANKED_CANDIDATE_ACTIONS = new Set([
  "accept",
  "apply",
  "confirm",
  "auto_apply",
  "auto_accept",
  "set_confirmed_tag_id",
]);

export function rankedCandidateSafetyViolation(result) {
  if (!result) {
    return false;
  }
  const safety = result.safety || {};
  const mutationCounters = [
    "safe_for_auto_apply_count",
    "confirmed_tag_id_mutations",
    "final_mapping_mutations",
    "persistence_writes",
    "ai_suggestion_table_writes",
  ];
  if (mutationCounters.some((key) => Number(safety[key] || 0) !== 0)) {
    return true;
  }
  return (result.rows || []).some((row) =>
    (row.candidates || []).some((candidate) => {
      const action = String(candidate.recommended_action || "").trim().toLowerCase();
      return candidate.safe_for_auto_apply === true
        || candidate.requires_human_review !== true
        || UNSAFE_RANKED_CANDIDATE_ACTIONS.has(action);
    }),
  );
}

export function rankedCandidateRunErrorMessage(error) {
  const detail = String(error?.message || "").trim();
  const normalized = detail.toLowerCase();
  if (detail.includes("403") || normalized.includes("disabled")) {
    return "Ranked candidate dry-run is disabled by the backend. The preview remains unavailable until an authorized test environment enables it.";
  }
  if (normalized.includes("unknown ranked candidate profile")) {
    return "The selected ranked-candidate profile is not supported by the backend. No preview was produced.";
  }
  if (normalized.includes("baseline report") || normalized.includes("taxonomy metadata") || normalized.includes("concept card artifacts")) {
    return "Required local ranked-candidate artifacts are unavailable. No preview was produced.";
  }
  if (normalized.includes("failed to fetch") || normalized.includes("network")) {
    return "Ranked candidate dry-run could not reach the backend. No preview was produced.";
  }
  return detail
    ? `Ranked candidate dry-run could not be completed. ${detail}`
    : "Ranked candidate dry-run could not be completed. No preview was produced.";
}
