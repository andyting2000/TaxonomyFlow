export const SUPERVISOR_ORCHESTRATION_FILTERS = [
  { id: "all", label: "All suggestions" },
  { id: "eligible", label: "Supervisor eligible" },
  { id: "high", label: "High priority" },
  { id: "medium", label: "Medium priority" },
  { id: "reviewed", label: "Already reviewed" },
  { id: "remapping", label: "Remapping available" },
  { id: "revised", label: "Revision completed" },
  { id: "not_eligible", label: "Not eligible" },
];

export function buildSupervisorOrchestrationItemMap(items = []) {
  return Object.fromEntries(
    items
      .filter((item) => item?.suggestion_id)
      .map((item) => [String(item.suggestion_id), item]),
  );
}

export function isPolicyEligibleOrchestrationItem(item) {
  return Boolean(
    item &&
      item.supervisor_eligibility === "eligible" &&
      item.is_human_terminal === false,
  );
}

export function isEligibleUnreviewedOrchestrationItem(item, suggestion) {
  return Boolean(
    item &&
      suggestion &&
      item.batch_review_executable === true &&
      item.supervisor_review_executable === true &&
      item.is_human_terminal === false,
  );
}

export function supervisorOrchestrationFilterMatches(filterId, item, suggestion) {
  if (filterId === "all") {
    return true;
  }
  if (!item) {
    return filterId === "not_eligible";
  }
  if (filterId === "eligible") {
    return isPolicyEligibleOrchestrationItem(item);
  }
  if (filterId === "high" || filterId === "medium") {
    return (
      isPolicyEligibleOrchestrationItem(item) &&
      item.priority === filterId
    );
  }
  if (filterId === "reviewed") {
    return item.supervisor_eligibility === "already_reviewed";
  }
  if (filterId === "remapping") {
    return item.remapping_executable === true;
  }
  if (filterId === "revised") {
    return Boolean(item.existing_revision_id);
  }
  if (filterId === "not_eligible") {
    return ["not_eligible", "terminal"].includes(item.supervisor_eligibility);
  }
  return true;
}

export function filterSuggestionsByOrchestration(
  suggestions = [],
  itemMap = {},
  filterId = "all",
) {
  return suggestions.filter((suggestion) =>
    supervisorOrchestrationFilterMatches(
      filterId,
      itemMap[String(suggestion.id)],
      suggestion,
    ),
  );
}

export function eligibleUnreviewedSuggestions(suggestions = [], itemMap = {}) {
  return suggestions.filter((suggestion) =>
    isEligibleUnreviewedOrchestrationItem(
      itemMap[String(suggestion.id)],
      suggestion,
    ),
  );
}

export function supervisorOrchestrationSafetyViolation(capabilities, plan) {
  if (!capabilities || !plan) {
    return "";
  }

  if (
    capabilities.plan_only !== true ||
    capabilities.mode !== "manual" ||
    capabilities.auto_review !== false ||
    capabilities.auto_remap !== false ||
    (capabilities.unsafe_configuration_reasons || []).length > 0
  ) {
    return "Backend capabilities contradict manual, plan-only orchestration.";
  }

  if (plan.orchestration_enabled !== true || plan.mode !== "plan_only") {
    return "Backend plan is not enabled in plan-only mode.";
  }

  const safety = plan.safety_summary || {};
  const zeroFields = [
    "planning_live_calls",
    "auto_review_calls",
    "auto_remap_calls",
    "confirmed_tag_id_mutations",
    "final_mapping_mutations",
    "safe_for_auto_apply_count",
  ];
  if (zeroFields.some((field) => safety[field] !== 0)) {
    return "Backend plan reported an unsafe automatic call or mapping mutation.";
  }
  if (safety.human_review_required !== true) {
    return "Backend plan did not require human review.";
  }
  if (
    (plan.items || []).some(
      (item) =>
        item.requires_human_review !== true ||
        item.safe_for_auto_apply !== false ||
        typeof item.is_human_terminal !== "boolean" ||
        typeof item.supervisor_review_executable !== "boolean" ||
        typeof item.batch_review_executable !== "boolean" ||
        typeof item.remapping_eligible !== "boolean" ||
        typeof item.remapping_executable !== "boolean",
    )
  ) {
    return "Backend plan contains an incomplete or non-advisory actionability contract.";
  }

  const items = plan.items || [];
  if (
    items.some(
      (item) =>
        (item.supervisor_review_executable === true &&
          (!isPolicyEligibleOrchestrationItem(item) ||
            item.batch_review_executable !== true ||
            item.supervisor_action_block_reason != null)) ||
        (item.batch_review_executable === true &&
          item.supervisor_review_executable !== true) ||
        (item.remapping_executable === true &&
          (item.remapping_eligible !== true ||
            item.mapper_status !== "suggested" ||
            item.is_human_terminal === true ||
            item.remapping_action_block_reason != null)),
    )
  ) {
    return "Backend plan actionability fields contradict persisted queue state.";
  }

  const policyEligible = items.filter(isPolicyEligibleOrchestrationItem);
  const reviewed = items.filter(
    (item) => item.supervisor_eligibility === "already_reviewed",
  );
  const notEligible = items.filter((item) =>
    ["not_eligible", "terminal"].includes(item.supervisor_eligibility),
  );
  const revised = items.filter((item) => Boolean(item.existing_revision_id));
  const countPairs = [
    [plan.eligible_count, policyEligible.length],
    [plan.policy_eligible_count, policyEligible.length],
    [
      plan.review_executable_count,
      items.filter((item) => item.supervisor_review_executable === true).length,
    ],
    [
      plan.batch_review_executable_count,
      items.filter((item) => item.batch_review_executable === true).length,
    ],
    [
      plan.high_priority_count,
      policyEligible.filter((item) => item.priority === "high").length,
    ],
    [
      plan.medium_priority_count,
      policyEligible.filter((item) => item.priority === "medium").length,
    ],
    [plan.already_reviewed_count, reviewed.length],
    [plan.not_eligible_count, notEligible.length],
    [
      plan.remapping_executable_count,
      items.filter((item) => item.remapping_executable === true).length,
    ],
    [plan.revision_completed_count, revised.length],
  ];
  if (countPairs.some(([reported, actual]) => reported !== actual)) {
    return "Backend plan summary counts contradict item actionability fields.";
  }

  return "";
}

export function orchestrationValueLabel(value) {
  return String(value == null || value === "" ? "n/a" : value).replace(/_/g, " ");
}
