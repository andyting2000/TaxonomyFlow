import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ChevronDown,
  CheckCircle2,
  FileSpreadsheet,
  LoaderCircle,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Tag,
  X,
} from "lucide-react";
import {
  acceptAiMappingSuggestion,
  bulkUpdateExtractedItems,
  createExtractedItem,
  fetchAiMappingSuggestions,
  fetchAiMappingSuggestionsStatus,
  fetchExtractedData,
  fetchJobPages,
  fetchRankedCandidateCapabilities,
  fetchSupervisorOrchestrationCapabilities,
  fetchSupervisorOrchestrationPlan,
  fetchSupervisorMapperFeedbackCapabilities,
  fetchTemplate,
  fetchTemplates,
  fetchTaxonomyStatus,
  ignoreAiMappingSuggestion,
  listSupervisorGuidedMappingRevisions,
  listSupervisorReviews,
  remapWithSupervisorFeedback,
  runBatchSupervisorReviews,
  runRankedCandidateDryRun,
  runSupervisorReview,
  searchTaxonomy,
} from "./api";
import {
  rankedCandidateRunErrorMessage,
  rankedCandidateSafetyViolation,
} from "./ranked-candidate-advisory-ui";
import {
  SUPERVISOR_ORCHESTRATION_FILTERS,
  buildSupervisorOrchestrationItemMap,
  eligibleUnreviewedSuggestions,
  filterSuggestionsByOrchestration,
  orchestrationValueLabel,
  supervisorOrchestrationSafetyViolation,
} from "./supervisor-orchestration-ui";

const UNASSIGNED_STATEMENT_CODE = "__unassigned__";
const UNASSIGNED_STATEMENT_LABEL = "Unassigned / Unmapped";
const AI_SUGGESTION_POST_COMPLETION_GRACE_MS = 90_000;
const AI_SUGGESTION_POLL_INTERVAL_MS = 3_000;
const AI_SUGGESTION_TERMINAL_JOB_STATUSES = new Set(["REVIEW", "COMPLETED"]);
const FRONTEND_FLAG_TRUE_VALUES = new Set(["1", "true", "yes", "on"]);

function readFrontendFlag(name, defaultValue = false) {
  const rawValue = import.meta.env?.[name];
  if (rawValue === undefined || rawValue === null || rawValue === "") {
    return defaultValue;
  }
  return FRONTEND_FLAG_TRUE_VALUES.has(String(rawValue).trim().toLowerCase());
}

const SHOW_AI_SUGGESTION_PANEL = readFrontendFlag("VITE_SHOW_AI_SUGGESTION_PANEL", true);
const SHOW_SUPERVISOR_LIVE_CONTROLS = readFrontendFlag("VITE_SHOW_SUPERVISOR_LIVE_CONTROLS", false);
const SHOW_SUPERVISOR_MAPPER_FEEDBACK = readFrontendFlag(
  "VITE_SHOW_SUPERVISOR_MAPPER_FEEDBACK",
  false,
);
const SHOW_SUPERVISOR_ORCHESTRATION_QUEUE = readFrontendFlag(
  "VITE_SHOW_SUPERVISOR_ORCHESTRATION_QUEUE",
  false,
);
const SHOW_RANKED_CANDIDATE_TEST_PANEL = readFrontendFlag(
  "VITE_SHOW_RANKED_CANDIDATE_TEST_PANEL",
  false,
);

function normalizeSupervisorReviewMode(mode) {
  return mode === "live" ? "live" : "mock";
}

function confirmBatchSupervisorRun(message) {
  return typeof window !== "undefined" && typeof window.confirm === "function"
    ? window.confirm(message)
    : false;
}

function supervisorEmptyReviewMessage(showLiveControls) {
  if (showLiveControls) {
    return "No Supervisor review yet. Run a live advisory review to see Supervisor status.";
  }
  return "No Supervisor review yet.";
}

function normalizeFieldId(fieldId) {
  if (!fieldId) {
    return fieldId;
  }

  const underscoreIndex = fieldId.indexOf("_");
  if (underscoreIndex > 0) {
    return fieldId.slice(underscoreIndex + 1);
  }

  return fieldId;
}

function fieldSort(a, b) {
  if ((a.position ?? 0) !== (b.position ?? 0)) {
    return (a.position ?? 0) - (b.position ?? 0);
  }

  if ((a.level ?? 0) !== (b.level ?? 0)) {
    return (a.level ?? 0) - (b.level ?? 0);
  }

  return (a.label || "").localeCompare(b.label || "");
}

function sortByYear(items) {
  return [...items].sort((left, right) => {
    const yearDelta = (right.financial_year || 0) - (left.financial_year || 0);
    if (yearDelta !== 0) {
      return yearDelta;
    }

    return String(right.id).localeCompare(String(left.id));
  });
}

function normalizeExtractedRows(response) {
  if (Array.isArray(response)) {
    return response;
  }

  if (Array.isArray(response?.items)) {
    return response.items;
  }

  return [];
}

function buildExtractedLookup(items) {
  const lookup = {};

  for (const item of items) {
    if (!item.template_field_id) {
      continue;
    }

    const normalizedId = normalizeFieldId(item.template_field_id);
    if (!lookup[normalizedId]) {
      lookup[normalizedId] = [];
    }
    lookup[normalizedId].push(item);
  }

  return lookup;
}

function normalizeStatementLabel(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

function buildTemplateFieldStatementMap(templateDetails) {
  const fieldToStatement = {};
  const fieldToStatements = {};
  const statementMetaByCode = {};

  function addFieldStatement(fieldId, code) {
    if (!fieldId || !code) {
      return;
    }
    if (!fieldToStatements[fieldId]) {
      fieldToStatements[fieldId] = [];
    }
    if (!fieldToStatements[fieldId].includes(code)) {
      fieldToStatements[fieldId].push(code);
    }
    if (!fieldToStatement[fieldId]) {
      fieldToStatement[fieldId] = code;
    }
  }

  for (const detail of templateDetails) {
    if (!detail?.code) {
      continue;
    }

    statementMetaByCode[detail.code] = {
      code: detail.code,
      description: detail.user_display_name || detail.description || detail.code,
    };

    for (const concept of detail.concepts || []) {
      if (!concept?.id) {
        continue;
      }

      addFieldStatement(concept.id, detail.code);
      addFieldStatement(normalizeFieldId(concept.id), detail.code);
    }
  }

  return { fieldToStatement, fieldToStatements, statementMetaByCode };
}

function buildStatementTypeLookup(templates) {
  const statementTypeLookup = {};
  for (const template of templates) {
    statementTypeLookup[normalizeStatementLabel(template.description)] = template.code;
    statementTypeLookup[normalizeStatementLabel(template.user_display_name)] = template.code;
    statementTypeLookup[normalizeStatementLabel(template.canonical_name)] = template.code;
    statementTypeLookup[normalizeStatementLabel(template.official_role_definition)] = template.code;
    for (const alias of template.aliases || []) {
      statementTypeLookup[normalizeStatementLabel(alias)] = template.code;
    }
    statementTypeLookup[normalizeStatementLabel(template.code)] = template.code;
  }
  return statementTypeLookup;
}

function statementCodeFromItemType(item, templates) {
  if (!item?.statement_type) {
    return null;
  }
  return buildStatementTypeLookup(templates)[normalizeStatementLabel(item.statement_type)] || null;
}

function buildStatementGroups(
  items,
  templates,
  fieldToStatement,
  fieldToStatements,
  statementMetaByCode,
) {
  const byStatement = {};
  const statementTypeLookup = buildStatementTypeLookup(templates);

  for (const item of items) {
    const rawFieldId = item.template_field_id || "";
    const normalizedFieldId = normalizeFieldId(rawFieldId);
    const statementCodeFromType = item.statement_type
      ? statementTypeLookup[normalizeStatementLabel(item.statement_type)] || null
      : null;
    const fieldStatementCodes =
      fieldToStatements[rawFieldId] ||
      fieldToStatements[normalizedFieldId] ||
      [];
    let statementCode = null;

    if (
      statementCodeFromType &&
      (fieldStatementCodes.length !== 1 || fieldStatementCodes.includes(statementCodeFromType))
    ) {
      statementCode = statementCodeFromType;
    }

    statementCode =
      statementCode ||
      fieldToStatement[rawFieldId] ||
      fieldToStatement[normalizedFieldId] ||
      statementCodeFromType ||
      null;

    if (!statementCode) {
      statementCode = UNASSIGNED_STATEMENT_CODE;
    }

    if (!byStatement[statementCode]) {
      const meta = statementMetaByCode[statementCode];
      byStatement[statementCode] = {
        code: statementCode,
        description:
          meta?.description || item.statement_type || UNASSIGNED_STATEMENT_LABEL,
        items: [],
      };
    }

    byStatement[statementCode].items.push(item);
  }

  return byStatement;
}

function buildTagDraftMap(items) {
  const nextTags = {};

  for (const item of items) {
    nextTags[item.id] = item.confirmed_tag_id
      ? {
          id: item.confirmed_tag_id,
          label: item.confirmed_tag_label || `Tag #${item.confirmed_tag_id}`,
        }
      : null;
  }

  return nextTags;
}

function inferFieldKind(concept) {
  const haystack = `${concept.id || ""} ${concept.label || ""}`.toLowerCase();
  if (
    haystack.includes("description") ||
    haystack.includes("disclosure") ||
    haystack.includes("principal activity") ||
    haystack.includes("nature of business")
  ) {
    return "textarea";
  }

  return "input";
}

function StatementButton({ statement, active, onSelect }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(statement.code)}
      className={`min-w-[10.5rem] rounded-xl border px-3 py-3 text-left transition ${
        active
          ? "border-brand-300 bg-brand-50 text-brand-900 dark:border-brand-500/60 dark:bg-brand-500/10 dark:text-brand-100"
          : "border-slate-200 bg-white hover:border-brand-200 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-brand-500/40 dark:hover:bg-slate-900"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            {statement.code}
          </p>
          <p className="mt-1 line-clamp-2 text-sm font-medium">
            {statement.description}
          </p>
        </div>
        <span
          className={`rounded-full px-2 py-1 text-[11px] font-semibold ${
            active
              ? "bg-brand-100 text-brand-700 dark:bg-brand-500/20 dark:text-brand-200"
              : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
          }`}
        >
          {statement.matchedItemCount || 0}
        </span>
      </div>
      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
        {statement.total_concepts} fields
        {typeof statement.matchedItemCount === "number"
          ? ` | ${statement.matchedItemCount} rows`
          : ""}
      </p>
    </button>
  );
}

function ExtractedItemList({ title, description, items }) {
  if (!items.length) {
    return null;
  }

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-base font-semibold text-slate-900 dark:text-slate-100">
          {title}
        </h4>
        {description ? (
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {description}
          </p>
        ) : null}
      </div>

      <div className="space-y-3">
        {items.map((item) => (
          <div
            key={item.id}
            className="rounded-lg border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-950/70"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                  {item.extracted_label || item.template_field_label || item.template_field_id || `Row #${item.id}`}
                </p>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {item.template_field_id || "No template field"}
                  {item.statement_type ? ` | ${item.statement_type}` : ""}
                </p>
              </div>
              {item.financial_year ? (
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {item.financial_year}
                </span>
              ) : null}
            </div>
            <div className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-3 text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
              {item.extracted_value || <span className="text-slate-400">No value</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatementTabButton({ statement, active, onSelect }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(statement.code)}
      className={`grid h-32 w-52 flex-none grid-rows-[1.25rem_minmax(2.75rem,1fr)_1.25rem] rounded-lg border px-4 py-3 text-left transition ${
        active
          ? "border-brand-300 bg-brand-50 text-brand-900 shadow-glow dark:border-brand-400/35 dark:bg-brand-400/10 dark:text-brand-100"
          : "border-slate-200/80 bg-white/80 hover:border-brand-200 hover:bg-white dark:border-white/10 dark:bg-white/[0.045] dark:hover:border-brand-400/30 dark:hover:bg-white/[0.075]"
      }`}
    >
      <div className="flex h-5 items-center justify-between gap-3">
        <p className="min-w-0 truncate text-[11px] font-semibold uppercase leading-4 tracking-[0.12em] text-slate-500 dark:text-slate-500">
          {statement.code}
        </p>
        <span
          className={`inline-flex h-5 min-w-5 flex-none items-center justify-center rounded-full px-1.5 text-[11px] font-semibold leading-none ${
            active
              ? "bg-brand-100 text-brand-700 dark:bg-brand-500/20 dark:text-brand-200"
              : "bg-slate-100 text-slate-600 dark:bg-white/[0.07] dark:text-slate-300"
          }`}
        >
          {statement.matchedItemCount || 0}
        </span>
      </div>
      <p className="line-clamp-2 self-center text-sm font-semibold leading-5">
        {statement.description}
      </p>
      <div className="flex h-5 items-center gap-2 self-end whitespace-nowrap text-xs text-slate-500 dark:text-slate-500">
        <span>{statement.total_concepts} fields</span>
        <span className="text-slate-300 dark:text-slate-600">|</span>
        <span>{statement.matchedItemCount || 0} rows</span>
      </div>
    </button>
  );
}

function SectionHeader({ title, description, count, tone = "slate" }) {
  const badgeClass =
    tone === "brand"
      ? "bg-brand-100 text-brand-700 dark:bg-brand-500/15 dark:text-brand-200"
      : tone === "amber"
        ? "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
        : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300";

  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-base font-semibold text-slate-900 dark:text-slate-100">
            {title}
          </h4>
          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${badgeClass}`}>
            {count}
          </span>
        </div>
        {description ? (
          <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
            {description}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function CollapsibleExtractedItemList({
  title,
  description,
  items,
  defaultOpen = false,
  badgeTone = "slate",
  taxonomyReady = false,
  selectedTagsByItem = {},
  onSelectTag,
  onClearTag,
}) {
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    setOpen(defaultOpen);
  }, [defaultOpen, title]);

  if (!items.length) {
    return null;
  }

  const badgeClass =
    badgeTone === "amber"
      ? "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
      : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300";

  return (
    <section className="overflow-hidden rounded-lg border border-slate-200/80 bg-slate-50/70 dark:border-white/10 dark:bg-white/[0.035]">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-start justify-between gap-4 px-4 py-3 text-left transition hover:bg-white/70 dark:hover:bg-white/[0.055]"
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {title}
            </h4>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${badgeClass}`}>
              {items.length} rows
            </span>
          </div>
          {description ? (
            <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-500">
              {description}
            </p>
          ) : null}
        </div>
        <ChevronDown
          className={`mt-0.5 h-4 w-4 flex-none text-slate-400 transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open ? (
        <div className="border-t border-slate-200/70 px-4 py-4 dark:border-white/10">
          <div className="space-y-3">
            {items.map((item) => (
              <ExtractedRowCard
                key={item.id}
                item={item}
                taxonomyReady={taxonomyReady}
                selectedTag={selectedTagsByItem[item.id] || null}
                onSelectTag={(tag) => onSelectTag?.(item.id, tag)}
                onClearTag={() => onClearTag?.(item.id)}
              />
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function TaxonomyPicker({
  fieldId,
  disabled,
  taxonomyReady,
  selectedTag,
  onSelectTag,
  onClearTag,
}) {
  const [query, setQuery] = useState(selectedTag?.label || "");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setQuery(selectedTag?.label || "");
  }, [selectedTag?.id, selectedTag?.label]);

  useEffect(() => {
    if (!taxonomyReady || disabled) {
      setResults([]);
      setOpen(false);
      setLoading(false);
      return undefined;
    }

    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setResults([]);
      setOpen(false);
      setLoading(false);
      return undefined;
    }

    let cancelled = false;
    setLoading(true);

    const timeoutId = window.setTimeout(async () => {
      try {
        const response = await searchTaxonomy(trimmed);
        if (!cancelled) {
          setResults(response.results || []);
          setOpen(true);
        }
      } catch (error) {
        if (!cancelled) {
          setResults([]);
          setOpen(false);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }, 300);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [disabled, query, taxonomyReady]);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <label className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Manual taxonomy tag
        </label>
        {selectedTag?.id ? (
          <button
            type="button"
            onClick={onClearTag}
            className="inline-flex items-center gap-1 text-xs text-slate-500 transition hover:text-rose-600 dark:text-slate-400 dark:hover:text-rose-300"
          >
            <X className="h-3 w-3" />
            Clear
          </button>
        ) : null}
      </div>

      <div className="relative">
        <div className="pointer-events-none absolute inset-y-0 left-3 flex items-center">
          {loading ? (
            <LoaderCircle className="h-4 w-4 animate-spin text-slate-400" />
          ) : (
            <Search className="h-4 w-4 text-slate-400" />
          )}
        </div>
        <input
          value={query}
          disabled={disabled || !taxonomyReady}
          onChange={(event) => {
            setQuery(event.target.value);
            if (selectedTag?.id) {
              onClearTag();
            }
          }}
          onFocus={() => {
            if (results.length > 0) {
              setOpen(true);
            }
          }}
          onBlur={() => {
            window.setTimeout(() => setOpen(false), 150);
          }}
          className="input-base pl-10"
          placeholder={
            taxonomyReady
              ? "Search MBRS taxonomy tags"
              : "Taxonomy data not loaded"
          }
        />

        {open && (results.length > 0 || loading) ? (
          <div className="absolute z-20 mt-2 max-h-64 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-premium dark:border-white/10 dark:bg-slate-900">
            {results.map((result) => (
              <button
                key={`${fieldId}-${result.id}`}
                type="button"
                onMouseDown={(event) => {
                  event.preventDefault();
                  onSelectTag({
                    id: result.id,
                    label: result.original_label || result.label,
                    xbrlTag: result.xbrl_tag,
                  });
                  setQuery(result.original_label || result.label);
                  setOpen(false);
                }}
                className="block w-full border-b border-slate-100 px-3 py-3 text-left transition last:border-b-0 hover:bg-slate-50 dark:border-white/10 dark:hover:bg-white/[0.06]"
              >
                <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                  {result.original_label || result.label}
                </p>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {result.xbrl_tag} | #{result.id}
                </p>
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {selectedTag?.id ? (
        <div className="inline-flex max-w-full items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200">
          <Tag className="h-3 w-3 flex-none" />
          <span className="truncate">{selectedTag.label}</span>
          <span className="text-emerald-500 dark:text-emerald-400">
            #{selectedTag.id}
          </span>
        </div>
      ) : (
        <p className="text-xs text-slate-500 dark:text-slate-500">
          No manual tag selected for this field.
        </p>
      )}
    </div>
  );
}

function ExtractedRowCard({
  item,
  taxonomyReady,
  selectedTag,
  onSelectTag,
  onClearTag,
}) {
  const [showTagging, setShowTagging] = useState(false);
  const hasTag = Boolean(selectedTag?.id);

  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/90 p-4 shadow-sm dark:border-white/10 dark:bg-slate-950/50">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
            {item.extracted_label || item.template_field_label || item.template_field_id || `Row #${item.id}`}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-500">
            <span className="max-w-full truncate">{item.template_field_id || "No template field"}</span>
            {item.statement_type ? (
              <>
                <span className="text-slate-300 dark:text-slate-600">|</span>
                <span>{item.statement_type}</span>
              </>
            ) : null}
            <span className="text-slate-300 dark:text-slate-600">|</span>
            <span>{hasTag ? `Tag #${selectedTag.id}` : "No tag"}</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-start gap-2 sm:justify-end">
          {item.financial_year ? (
            <span className="metric-pill">
              {item.financial_year}
            </span>
          ) : null}
          <button
            type="button"
            onClick={() => setShowTagging((current) => !current)}
            className="button-secondary min-h-8 px-3 py-1.5 text-xs"
          >
            <Tag className="h-3.5 w-3.5" />
            {showTagging ? "Hide mapping" : hasTag ? "Edit mapping" : "Map row"}
          </button>
        </div>
      </div>

      <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200/70 bg-slate-50/80 px-3 py-3 text-sm text-slate-700 dark:border-white/10 dark:bg-white/[0.035] dark:text-slate-200">
        {item.extracted_value || <span className="text-slate-400">No value</span>}
      </div>

      {showTagging ? (
        <div className="mt-3 rounded-lg border border-slate-200/70 bg-slate-50/70 p-3 dark:border-white/10 dark:bg-white/[0.035]">
          <TaxonomyPicker
            fieldId={`row-${item.id}`}
            disabled={false}
            taxonomyReady={taxonomyReady}
            selectedTag={selectedTag}
            onSelectTag={onSelectTag}
            onClearTag={onClearTag}
          />
        </div>
      ) : null}
    </div>
  );
}

function FieldCard({
  field,
  value,
  onChange,
}) {
  const level = field.level ?? 0;
  const levelRailClass =
    level >= 4
      ? "bg-indigo-400/70 dark:bg-indigo-300/60"
      : level === 3
        ? "bg-sky-400/70 dark:bg-sky-300/60"
        : level === 2
          ? "bg-brand-400/70 dark:bg-brand-300/60"
          : "bg-transparent";
  const inputKind = inferFieldKind(field);

  return (
    <div className="relative overflow-hidden rounded-lg border border-slate-200/80 bg-white/95 p-4 shadow-sm transition hover:border-brand-200/80 dark:border-white/10 dark:bg-slate-950/60 dark:hover:border-brand-400/25">
      <div className={`absolute inset-y-0 left-0 w-1 ${levelRailClass}`} aria-hidden="true" />
      <div className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                {field.label}
              </p>
              {field.required && (
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
                  Required
                </span>
              )}
              {field.sourceItems.length > 1 && (
                <span className="rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-semibold text-sky-700 dark:bg-sky-500/10 dark:text-sky-300">
                  {field.sourceItems.length} extracted rows
                </span>
              )}
            </div>
            <p className="mt-1 break-all text-xs text-slate-500 dark:text-slate-500">
              {field.id}
              {field.sourceItems.length > 0 && field.latestYear
                ? ` | latest year ${field.latestYear}`
                : ""}
            </p>
          </div>
          <span className="metric-pill">
            Level {field.level ?? 0}
          </span>
        </div>

        {inputKind === "textarea" ? (
          <textarea
            value={value}
            onChange={(event) => onChange(field.id, event.target.value)}
            className="input-base min-h-[7rem] resize-y"
            placeholder="Enter extracted value"
          />
        ) : (
          <input
            value={value}
            onChange={(event) => onChange(field.id, event.target.value)}
            className="input-base"
            placeholder="Enter extracted value"
          />
        )}

      </div>
    </div>
  );
}

function confidencePercent(value) {
  const numeric = Number(value) || 0;
  return `${Math.round(Math.max(0, Math.min(1, numeric)) * 100)}%`;
}

function confidenceChipLabel(value) {
  return `${confidencePercent(value)} confidence`;
}

function confidenceCategory(suggestion) {
  if (suggestion.confidence_category) {
    return suggestion.confidence_category;
  }
  const value = Number(suggestion.confidence) || 0;
  if (value >= 0.88) {
    return "high";
  }
  if (value >= 0.5) {
    return "medium";
  }
  return "low";
}

function confidenceCategoryLabel(category) {
  if (category === "high") {
    return "High confidence";
  }
  if (category === "medium") {
    return "Medium confidence";
  }
  return "Low confidence";
}

function suggestionStatusLabel(status) {
  if (status === "suggested") {
    return "Requires confirmation";
  }
  if (status === "accepted") {
    return "Accepted";
  }
  if (status === "ignored") {
    return "Rejected";
  }
  return "No safe AI mapping";
}

function suggestionStatusBadgeClass(status) {
  if (status === "accepted") {
    return "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200";
  }
  if (status === "ignored") {
    return "bg-slate-100 text-slate-600 dark:bg-white/[0.07] dark:text-slate-300";
  }
  if (status === "rejected") {
    return "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-200";
  }
  return "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300";
}

function confidenceBadgeClass(category) {
  if (category === "high") {
    return "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200";
  }
  if (category === "medium") {
    return "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-200";
  }
  return "bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-200";
}

const compactBadgeClass = "inline-flex h-6 items-center rounded-full px-2 text-[11px] font-semibold";

function normalizeSupervisorReviews(response) {
  return Array.isArray(response) ? response : [];
}

function supervisorReviewTimestamp(review) {
  return Date.parse(review?.updated_at || review?.created_at || "") || 0;
}

function buildSupervisorReviewMap(reviews) {
  const bySuggestion = {};
  for (const review of reviews || []) {
    const suggestionId = review?.llm_mapping_suggestion_id;
    if (!suggestionId) {
      continue;
    }
    const existing = bySuggestion[suggestionId];
    if (!existing || supervisorReviewTimestamp(review) >= supervisorReviewTimestamp(existing)) {
      bySuggestion[suggestionId] = review;
    }
  }
  return bySuggestion;
}

function supervisorIssueTypes(review) {
  return new Set((review?.supervisor_issues || []).map((issue) => issue?.type).filter(Boolean));
}

const SUPERVISOR_CORRECTION_CONCRETE_ISSUES = new Set([
  "ambiguous_label",
  "broad_substitute",
  "candidate_not_supported",
  "missing_concept_card",
  "no_supporting_evidence",
  "statement_family_mismatch",
  "weak_label_match",
]);

const SUPERVISOR_CORRECTION_UNSAFE_ISSUES = new Set([
  "invalid_supervisor_response",
  "unrepaired_invalid_supervisor_response",
  "unsafe_response",
]);

function supervisorCorrectionEligibility(review) {
  if (!review || review.review_status !== "completed" || review.error_type) {
    return false;
  }
  const issueTypes = supervisorIssueTypes(review);
  if ([...issueTypes].some((issue) => SUPERVISOR_CORRECTION_UNSAFE_ISSUES.has(issue))) {
    return false;
  }
  if (review.supervisor_decision === "agree") {
    return false;
  }
  if (["disagree", "prefer_alternative_candidate"].includes(review.supervisor_decision)) {
    return true;
  }
  if (["prefer_alternative_candidate", "request_better_candidate"].includes(review.supervisor_recommended_action)) {
    return true;
  }
  return review.supervisor_decision === "needs_human_review" &&
    [...issueTypes].some((issue) => SUPERVISOR_CORRECTION_CONCRETE_ISSUES.has(issue));
}

function supervisorCorrectionsForSuggestion(revisions, suggestionId) {
  return (revisions || [])
    .filter((revision) => revision?.parent_suggestion_id === suggestionId)
    .sort((left, right) => Number(right.correction_attempt || 0) - Number(left.correction_attempt || 0));
}

function supervisorBadgeLabel(review) {
  if (!review) {
    return "No Supervisor review";
  }
  if (review.review_status === "failed") {
    return "Supervisor: Failed";
  }
  if (review.review_status === "pending" || review.review_status === "running") {
    return `Supervisor: ${review.review_status === "running" ? "Running" : "Pending"}`;
  }

  const issueTypes = supervisorIssueTypes(review);
  if ((review.supervisor_safe_to_accept || review.calibrated_safe_to_accept) && review.supervisor_risk_level === "low") {
    return "Supervisor: Safe to accept (advisory)";
  }
  if (review.supervisor_risk_level === "high") {
    return "Supervisor: High risk";
  }
  if (review.supervisor_recommended_action === "request_better_candidate") {
    return "Supervisor: Better candidate needed";
  }
  if (issueTypes.has("candidate_not_supported")) {
    return "Supervisor: Unsupported candidate";
  }
  if (issueTypes.has("ambiguous_label")) {
    return "Supervisor: Ambiguous label";
  }
  if (review.supervisor_decision === "needs_human_review") {
    return "Supervisor: Review needed";
  }
  return "Supervisor: Reviewed";
}

function supervisorBadgeClass(review) {
  if (!review) {
    return "border border-slate-200/80 bg-white/80 text-slate-500 dark:border-white/10 dark:bg-white/[0.06] dark:text-slate-400";
  }
  if (review.review_status === "failed" || review.supervisor_risk_level === "high") {
    return "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-200";
  }
  if ((review.supervisor_safe_to_accept || review.calibrated_safe_to_accept) && review.supervisor_risk_level === "low") {
    return "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200";
  }
  if (review.supervisor_decision === "needs_human_review" || review.supervisor_risk_level === "medium") {
    return "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300";
  }
  return "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-200";
}

function orchestrationBadgeLabel(item) {
  if (!item) {
    return "Not eligible";
  }
  if (item.existing_revision_id) {
    return "Correction completed";
  }
  if (item.remapping_executable === true) {
    return "Remapping available";
  }
  if (
    item.supervisor_eligibility === "already_reviewed" ||
    item.existing_supervisor_review_id
  ) {
    return "Already reviewed";
  }
  if (
    item.supervisor_eligibility === "blocked" ||
    item.orchestration_state === "blocked"
  ) {
    return "Blocked";
  }
  if (item.supervisor_eligibility === "eligible") {
    return `${item.priority === "high" ? "High" : "Medium"} priority Supervisor eligible`;
  }
  return "Not eligible";
}

function orchestrationBadgeClass(item) {
  if (!item || ["not_eligible", "terminal"].includes(item.supervisor_eligibility)) {
    return "border border-slate-200/80 bg-white/80 text-slate-500 dark:border-white/10 dark:bg-white/[0.06] dark:text-slate-400";
  }
  if (
    item.supervisor_eligibility === "blocked" ||
    item.orchestration_state === "blocked"
  ) {
    return "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-200";
  }
  if (item.priority === "high" && item.supervisor_eligibility === "eligible") {
    return "bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-200";
  }
  if (item.supervisor_eligibility === "eligible") {
    return "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300";
  }
  return "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-200";
}

function supervisorValueLabel(value) {
  if (value === true) {
    return "Yes";
  }
  if (value === false) {
    return "No";
  }
  return String(value || "n/a").replace(/_/g, " ");
}

function supervisorDateLabel(value) {
  if (!value) {
    return "n/a";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function supervisorSafeWithheldExplanation(review) {
  if (!review) {
    return "";
  }
  const agreeLowAccept =
    review.supervisor_decision === "agree" &&
    review.supervisor_risk_level === "low" &&
    review.supervisor_recommended_action === "accept";
  if (!agreeLowAccept || review.supervisor_safe_to_accept || review.calibrated_safe_to_accept) {
    return "";
  }

  const issue = (review.supervisor_issues || []).find((item) => item?.description);
  if (issue?.description) {
    if (String(issue.description).startsWith("Safe flag withheld")) {
      return issue.description;
    }
    return `Safe flag withheld by guardrail: ${issue.description}`;
  }
  return "Safe flag withheld by Supervisor response: safe_to_accept was false despite agree/low/accept. Keep human confirmation.";
}

function rankedCandidateValueLabel(value) {
  if (Array.isArray(value)) {
    return value.join(", ") || "n/a";
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value).filter(([, item]) => item !== null && item !== undefined && item !== "");
    return entries.length > 0 ? entries.map(([key, item]) => `${key}: ${item}`).join(" | ") : "n/a";
  }
  return value === null || value === undefined || value === "" ? "n/a" : String(value).replace(/_/g, " ");
}

function RankedCandidateTestPanel({ jobId }) {
  const [capabilities, setCapabilities] = useState(null);
  const [loadingCapabilities, setLoadingCapabilities] = useState(true);
  const [runningDryRun, setRunningDryRun] = useState(false);
  const [profile, setProfile] = useState("balanced");
  const [maxCandidatesPerRow, setMaxCandidatesPerRow] = useState(5);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadCapabilities() {
      setLoadingCapabilities(true);
      setError("");
      setResult(null);
      try {
        const response = await fetchRankedCandidateCapabilities(jobId);
        if (cancelled) {
          return;
        }
        const maxCandidates = Math.max(1, Math.min(10, Number(response?.max_candidates_per_row || 5)));
        setCapabilities(response || null);
        setProfile("balanced");
        setMaxCandidatesPerRow(Math.min(5, maxCandidates));
      } catch (capabilityError) {
        if (!cancelled) {
          setCapabilities(null);
          setError(`Ranked candidate advisory capabilities could not be loaded. ${capabilityError.message}`);
        }
      } finally {
        if (!cancelled) {
          setLoadingCapabilities(false);
        }
      }
    }

    loadCapabilities();
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const candidateCap = Math.max(1, Math.min(10, Number(capabilities?.max_candidates_per_row || 5)));
  const supportedProfiles = capabilities?.supported_profiles || [];
  const safetyViolation = rankedCandidateSafetyViolation(result);
  const canRun = Boolean(capabilities?.enabled) && !loadingCapabilities && !runningDryRun;

  const handleRunDryRun = useCallback(async () => {
    if (!canRun) {
      return;
    }
    setRunningDryRun(true);
    setError("");
    setResult(null);
    try {
      const response = await runRankedCandidateDryRun(jobId, {
        profile,
        maxCandidatesPerRow,
        maxCandidatesCap: candidateCap,
      });
      if (rankedCandidateSafetyViolation(response)) {
        setResult(response);
        setError("Ranked candidate dry-run returned a safety contract violation. Candidate rows were blocked from rendering.");
        return;
      }
      setResult(response);
    } catch (runError) {
      setError(rankedCandidateRunErrorMessage(runError));
    } finally {
      setRunningDryRun(false);
    }
  }, [candidateCap, canRun, jobId, maxCandidatesPerRow, profile]);

  return (
    <section className="panel min-w-0 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-brand-600 dark:text-brand-300" />
            <h4 className="text-base font-semibold text-slate-950 dark:text-white">Ranked Candidate Dry-Run</h4>
          </div>
          <p className="mt-1 text-sm leading-5 text-slate-500 dark:text-slate-400">
            Internal test-only preview. Ranked candidates are advisory only. Dry-run preview only. Human review required. No auto-apply. No confirmed_tag_id mutation. No final mapping mutation.
          </p>
        </div>
        <span className="metric-pill">Read-only preview</span>
      </div>

      {loadingCapabilities ? (
        <div className="mt-4 flex items-center text-sm text-slate-500 dark:text-slate-400">
          <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
          Loading ranked candidate capabilities. No preview is available yet.
        </div>
      ) : capabilities ? (
        <div className="mt-4 rounded-lg border border-slate-200/70 bg-slate-50/80 p-3 text-xs dark:border-white/10 dark:bg-white/[0.035]">
          <p className="font-semibold text-slate-700 dark:text-slate-200">Backend capabilities</p>
          <div className="mt-2 grid gap-2 text-slate-600 dark:text-slate-400 sm:grid-cols-2 lg:grid-cols-3">
            <p><span className="font-semibold">Enabled:</span> {rankedCandidateValueLabel(capabilities.enabled)}</p>
            <p><span className="font-semibold">Default mode:</span> {rankedCandidateValueLabel(capabilities.default_mode)}</p>
            <p><span className="font-semibold">Default profile:</span> {rankedCandidateValueLabel(capabilities.default_profile)}</p>
            <p><span className="font-semibold">Persistence allowed:</span> {rankedCandidateValueLabel(capabilities.allow_persistence)}</p>
            <p><span className="font-semibold">Admin-only:</span> {rankedCandidateValueLabel(capabilities.admin_only)}</p>
            <p><span className="font-semibold">Max rows:</span> {rankedCandidateValueLabel(capabilities.max_rows)}</p>
            <p><span className="font-semibold">Max candidates per row:</span> {rankedCandidateValueLabel(candidateCap)}</p>
            <p><span className="font-semibold">Profiles:</span> {rankedCandidateValueLabel(supportedProfiles)}</p>
            <p><span className="font-semibold">Actions:</span> {rankedCandidateValueLabel(capabilities.supported_actions)}</p>
          </div>
        </div>
      ) : null}

      {capabilities && !capabilities.enabled ? (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-3 text-sm text-amber-700 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200">
          Ranked candidate advisory is disabled by the backend. This panel fails closed and cannot run a dry-run until the backend flag is enabled.
        </div>
      ) : null}

      {capabilities?.enabled ? (
        <div className="mt-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200/70 bg-white/80 p-3 dark:border-white/10 dark:bg-white/[0.025]">
          <label className="grid gap-1 text-xs font-semibold text-slate-600 dark:text-slate-300">
            Profile
            <select
              value={profile}
              onChange={(event) => setProfile(event.target.value)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm font-normal text-slate-800 dark:border-white/15 dark:bg-slate-900 dark:text-slate-100"
              disabled={runningDryRun}
            >
              {supportedProfiles.map((supportedProfile) => (
                <option key={supportedProfile} value={supportedProfile}>{supportedProfile}</option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-semibold text-slate-600 dark:text-slate-300">
            Candidates per row
            <select
              value={maxCandidatesPerRow}
              onChange={(event) => setMaxCandidatesPerRow(Number(event.target.value))}
              className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm font-normal text-slate-800 dark:border-white/15 dark:bg-slate-900 dark:text-slate-100"
              disabled={runningDryRun}
            >
              {Array.from({ length: candidateCap }, (_, index) => index + 1).map((count) => (
                <option key={count} value={count}>{count}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={handleRunDryRun}
            className="button-secondary min-h-9 px-3 py-2 text-xs"
            disabled={!canRun}
          >
            {runningDryRun ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            {runningDryRun ? "Running dry-run preview..." : "Run Ranked Candidate Dry-Run"}
          </button>
        </div>
      ) : null}

      {error ? (
        <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50/80 px-3 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
          {error}
        </div>
      ) : null}

      {result ? (
        <div className="mt-4 space-y-4">
          <div className="rounded-lg border border-slate-200/70 bg-slate-50/80 p-3 text-xs dark:border-white/10 dark:bg-white/[0.035]">
            <p className="font-semibold text-slate-700 dark:text-slate-200">Dry-run summary</p>
            <div className="mt-2 grid gap-2 text-slate-600 dark:text-slate-400 sm:grid-cols-2 lg:grid-cols-3">
              <p><span className="font-semibold">Profile:</span> {rankedCandidateValueLabel(result.profile)}</p>
              <p><span className="font-semibold">Total rows:</span> {rankedCandidateValueLabel(result.total_rows)}</p>
              <p><span className="font-semibold">Rows with candidates:</span> {rankedCandidateValueLabel(result.rows_with_candidates)}</p>
              <p><span className="font-semibold">Candidate coverage:</span> {rankedCandidateValueLabel(result.candidate_coverage)}</p>
              <p><span className="font-semibold">Candidate count:</span> {(result.rows || []).reduce((count, row) => count + (row.candidates || []).length, 0)}</p>
              <p><span className="font-semibold">Generated:</span> {rankedCandidateValueLabel(result.generated_at)}</p>
            </div>
          </div>

          <div className="rounded-lg border border-slate-200/70 bg-slate-50/80 p-3 text-xs dark:border-white/10 dark:bg-white/[0.035]">
            <p className="font-semibold text-slate-700 dark:text-slate-200">Safety summary</p>
            <div className="mt-2 grid gap-2 text-slate-600 dark:text-slate-400 sm:grid-cols-2 lg:grid-cols-3">
              <p><span className="font-semibold">Auto-apply candidates (must be zero):</span> {rankedCandidateValueLabel(result.safety?.safe_for_auto_apply_count)}</p>
              <p><span className="font-semibold">Human review required:</span> {rankedCandidateValueLabel(result.safety?.requires_human_review_count)}</p>
              <p><span className="font-semibold">confirmed_tag_id mutations:</span> {rankedCandidateValueLabel(result.safety?.confirmed_tag_id_mutations)}</p>
              <p><span className="font-semibold">Final mapping mutations:</span> {rankedCandidateValueLabel(result.safety?.final_mapping_mutations)}</p>
              <p><span className="font-semibold">Persistence writes:</span> {rankedCandidateValueLabel(result.safety?.persistence_writes)}</p>
              <p><span className="font-semibold">AI suggestion writes:</span> {rankedCandidateValueLabel(result.safety?.ai_suggestion_table_writes)}</p>
            </div>
            <p className="mt-3 font-semibold text-slate-600 dark:text-slate-300">Advisory only. Human review required. No auto-apply, confirmed_tag_id mutation, or final mapping mutation.</p>
          </div>

          {safetyViolation ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50/80 px-3 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
              Ranked candidate response failed the read-only safety contract. Candidate rows are not rendered as actionable results.
            </div>
          ) : !result.rows?.length || Number(result.rows_with_candidates || 0) === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-300/80 bg-slate-50/70 px-4 py-5 text-sm text-slate-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-400">
              No ranked candidates are available for this dry-run.
            </div>
          ) : (
            <div className="space-y-3">
              {result.rows.map((row) => (
                <article key={row.row_id} className="rounded-lg border border-slate-200/80 bg-white/90 p-3 text-xs dark:border-white/10 dark:bg-slate-950/50">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="metric-pill">{rankedCandidateValueLabel(row.candidate_coverage_status)}</span>
                    <span className="metric-pill">{rankedCandidateValueLabel(row.statement_family)}</span>
                    <span className="metric-pill">{rankedCandidateValueLabel(row.section_block)}</span>
                  </div>
                  <p className="mt-2 text-sm font-semibold text-slate-900 dark:text-slate-100">{row.row_label || row.row_id}</p>
                  <p className="mt-1 text-slate-500 dark:text-slate-400">Value: {rankedCandidateValueLabel(row.row_value)} | Period: {rankedCandidateValueLabel(row.period)}</p>
                  {row.candidates?.length > 0 ? (
                    <div className="mt-3 space-y-2">
                      {row.candidates.map((candidate) => (
                        <div key={`${row.row_id}-${candidate.rank}-${candidate.qname}`} className="rounded-md border border-slate-200/70 bg-slate-50/80 p-2 dark:border-white/10 dark:bg-white/[0.035]">
                          <p className="font-semibold text-slate-700 dark:text-slate-200">#{candidate.rank} {candidate.concept_label || candidate.qname}</p>
                          <p className="mt-1 break-all text-slate-500 dark:text-slate-400">{candidate.qname}</p>
                          <div className="mt-1 flex flex-wrap gap-1 text-xs">
                            <span className="metric-pill">Score: {rankedCandidateValueLabel(candidate.score)}</span>
                            <span className="metric-pill">Confidence: {rankedCandidateValueLabel(candidate.confidence_bucket)}</span>
                            <span className="metric-pill">Risk: {rankedCandidateValueLabel(candidate.risk_level)}</span>
                            <span className="metric-pill">Sources: {rankedCandidateValueLabel(candidate.candidate_sources_combined)}</span>
                          </div>
                          <p className="mt-1 text-slate-600 dark:text-slate-400">Evidence: {rankedCandidateValueLabel(candidate.evidence?.match_reasons)}</p>
                          <p className="mt-1 text-slate-600 dark:text-slate-400">Ambiguity: {rankedCandidateValueLabel(candidate.ambiguity_reasons)}</p>
                          <p className="mt-1 text-slate-600 dark:text-slate-400">Blocking: {rankedCandidateValueLabel(candidate.blocking_reasons)}</p>
                          <p className="mt-1 font-semibold text-slate-600 dark:text-slate-300">Recommended action: {rankedCandidateValueLabel(candidate.recommended_action)} (read-only label)</p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-3 text-slate-500 dark:text-slate-400">No candidates for this row.</p>
                  )}
                </article>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}

function AiMappingSuggestionsPanel({
  suggestions,
  status,
  loading,
  supervisorReviews = [],
  loadingSupervisorReviews = false,
  supervisorReviewError = "",
  supervisorActionId = "",
  supervisorBatchRunning = false,
  supervisorGuidedRevisions = [],
  supervisorMapperFeedbackCapabilities = null,
  supervisorCorrectionActionId = "",
  supervisorCorrectionError = "",
  showSupervisorLiveControls = false,
  showSupervisorMapperFeedback = false,
  showSupervisorOrchestrationQueue = false,
  supervisorOrchestrationCapabilities = null,
  supervisorOrchestrationPlan = null,
  loadingSupervisorOrchestration = false,
  supervisorOrchestrationError = "",
  checkingPostCompletionSuggestions = false,
  postCompletionSuggestionGraceExpired = false,
  actionBusyId,
  onAccept,
  onIgnore,
  onRunSupervisorReview,
  onRunBatchSupervisorReviews,
  onRemapWithSupervisorFeedback,
  onRefreshSupervisorOrchestration,
}) {
  const [orchestrationFilter, setOrchestrationFilter] = useState("all");
  const visibleSuggestions = suggestions.filter((suggestion) =>
    ["suggested", "accepted", "ignored", "rejected"].includes(suggestion.status),
  );
  const orchestrationItemsBySuggestion = buildSupervisorOrchestrationItemMap(
    supervisorOrchestrationPlan?.items,
  );
  const orchestrationSafetyError = showSupervisorOrchestrationQueue
    ? supervisorOrchestrationSafetyViolation(
        supervisorOrchestrationCapabilities,
        supervisorOrchestrationPlan,
      )
    : "";
  const orchestrationQueueAvailable =
    showSupervisorOrchestrationQueue &&
    supervisorOrchestrationCapabilities?.available === true &&
    Boolean(supervisorOrchestrationPlan) &&
    !orchestrationSafetyError;
  const displayedSuggestions = orchestrationQueueAvailable
    ? filterSuggestionsByOrchestration(
        visibleSuggestions,
        orchestrationItemsBySuggestion,
        orchestrationFilter,
      )
    : visibleSuggestions;
  const eligibleBatchSuggestions = orchestrationQueueAvailable
    ? eligibleUnreviewedSuggestions(
        visibleSuggestions,
        orchestrationItemsBySuggestion,
      )
    : [];
  const orchestrationBatchLimit = Math.max(
    1,
    Number(supervisorOrchestrationCapabilities?.max_batch_size || 1),
  );
  const boundedEligibleBatchSuggestions = eligibleBatchSuggestions.slice(
    0,
    orchestrationBatchLimit,
  );
  const supervisorReviewsBySuggestion = buildSupervisorReviewMap(supervisorReviews);
  const supervisorReviewedCount = visibleSuggestions.filter(
    (suggestion) => supervisorReviewsBySuggestion[suggestion.id],
  ).length;
  const actionableCount = visibleSuggestions.filter(
    (suggestion) => suggestion.status === "suggested" && suggestion.suggested_template_field_id,
  ).length;
  const acceptedCount = visibleSuggestions.filter((suggestion) => suggestion.status === "accepted").length;
  const ignoredCount = visibleSuggestions.filter((suggestion) => suggestion.status === "ignored").length;
  const rejectedSuggestions = displayedSuggestions.filter((suggestion) => suggestion.status === "rejected");
  const rejectedCount = visibleSuggestions.filter((suggestion) => suggestion.status === "rejected").length;
  const pendingSuggestions = displayedSuggestions.filter((suggestion) => suggestion.status === "suggested");
  const acceptedSuggestions = displayedSuggestions.filter((suggestion) => suggestion.status === "accepted");
  const ignoredSuggestions = displayedSuggestions.filter((suggestion) => suggestion.status === "ignored");
  const statusValue = status?.ai_mapping_status || "not_started";
  const isGenerating = statusValue === "running";
  const isRateLimited = statusValue === "rate_limited";
  const isFailed = statusValue === "failed";
  const isNotStarted = statusValue === "not_started";
  const isCompletedEmpty = statusValue === "completed" && (status?.suggestions_count || 0) === 0;
  const isCheckingPostCompletion =
    checkingPostCompletionSuggestions && visibleSuggestions.length === 0 && !isRateLimited && !isFailed;
  const isGraceExpiredEmpty =
    postCompletionSuggestionGraceExpired &&
    visibleSuggestions.length === 0 &&
    !isGenerating &&
    !isRateLimited &&
    !isFailed;
  const showSupervisorControls = showSupervisorLiveControls;

  const renderSuggestionCard = (suggestion) => {
    const busy = actionBusyId === suggestion.id;
    const isSuggested = suggestion.status === "suggested";
    const ranked = suggestion.ranked_candidates || [];
    const category = confidenceCategory(suggestion);
    const supervisorReview = supervisorReviewsBySuggestion[suggestion.id];
    const orchestrationItem = orchestrationItemsBySuggestion[String(suggestion.id)];
    const supervisorBusy = supervisorActionId === suggestion.id;
    const correctionBusy = supervisorCorrectionActionId === suggestion.id;
    const suggestionRevisions = supervisorCorrectionsForSuggestion(
      supervisorGuidedRevisions,
      suggestion.id,
    );
    const latestRevision = suggestionRevisions[0];
    const correctionMaxRetries = Number(supervisorMapperFeedbackCapabilities?.max_retries || 0);
    const correctionRetryReached =
      correctionMaxRetries > 0 && suggestionRevisions.length >= correctionMaxRetries;
    const supervisorReviewActionVisible =
      showSupervisorLiveControls &&
      (
        !orchestrationQueueAvailable ||
        orchestrationItem?.supervisor_review_executable === true
      );
    const remappingActionVisible =
      !orchestrationQueueAvailable ||
      orchestrationItem?.remapping_executable === true;
    const showCorrectionAction =
      showSupervisorMapperFeedback &&
      supervisorMapperFeedbackCapabilities?.available === true &&
      isSuggested &&
      remappingActionVisible &&
      supervisorCorrectionEligibility(supervisorReview);
    const correctionCompleted = latestRevision?.status === "completed";
    const showCorrectionSecondaryRow = showCorrectionAction || correctionCompleted;
    const safeWithheldExplanation = supervisorSafeWithheldExplanation(supervisorReview);

    return (
      <div
        key={suggestion.id}
        className="rounded-lg border border-slate-200/80 bg-white/90 p-3 shadow-sm dark:border-white/10 dark:bg-slate-950/50"
      >
        <div className="flex min-w-0 flex-col gap-3">
          <div className="suggestion-card-header grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
            <div className="suggestion-card-summary min-w-0 space-y-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className={`${compactBadgeClass} bg-brand-100 text-brand-700 dark:bg-brand-500/15 dark:text-brand-200`}>
                  AI suggestion
                </span>
                <span className={`${compactBadgeClass} ${suggestionStatusBadgeClass(suggestion.status)}`}>
                  {suggestionStatusLabel(suggestion.status)}
                </span>
                <span className={`${compactBadgeClass} ${confidenceBadgeClass(category)}`}>
                  {confidenceCategoryLabel(category)}
                </span>
                <span className={`${compactBadgeClass} border border-slate-200/80 bg-white/80 text-slate-600 dark:border-white/10 dark:bg-white/[0.06] dark:text-slate-300`}>
                  {confidenceChipLabel(suggestion.confidence)}
                </span>
                {supervisorReview ? (
                  <span className={`${compactBadgeClass} ${supervisorBadgeClass(supervisorReview)}`}>
                    {supervisorBadgeLabel(supervisorReview)}
                  </span>
                ) : null}
                {showSupervisorOrchestrationQueue ? (
                  <span className={`${compactBadgeClass} ${orchestrationBadgeClass(orchestrationItem)}`}>
                    {orchestrationBadgeLabel(orchestrationItem)}
                  </span>
                ) : null}
              </div>

              <div className="min-w-0">
                <p className="break-words text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {suggestion.extracted_label || `Row #${suggestion.extracted_data_item_id}`}
                </p>
                <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-500">
                  Page {suggestion.page_number || "n/a"} | {suggestion.extracted_value || "No value"}
                </p>
              </div>
            </div>

            <div className="suggestion-action-column flex min-w-0 max-w-full flex-col items-end gap-2">
              <div className="suggestion-primary-actions flex max-w-full flex-wrap items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => onAccept(suggestion)}
                  className="button-primary min-h-8 px-3 py-1.5 text-xs"
                  disabled={!isSuggested || !suggestion.suggested_template_field_id || busy}
                >
                  {busy ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                  Accept suggestion
                </button>
                <button
                  type="button"
                  onClick={() => onIgnore(suggestion)}
                  className="button-secondary min-h-8 px-3 py-1.5 text-xs"
                  disabled={!isSuggested || busy}
                >
                  <X className="h-3.5 w-3.5" />
                  Reject
                </button>
                {supervisorReviewActionVisible ? (
                  <button
                    type="button"
                    onClick={() => onRunSupervisorReview(suggestion, "live")}
                    className="button-secondary min-h-8 px-3 py-1.5 text-xs"
                    disabled={supervisorBusy || !suggestion.id}
                  >
                    {supervisorBusy ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                    {supervisorBusy ? "Running Supervisor review..." : "Run Supervisor review"}
                  </button>
                ) : null}
              </div>

              {showCorrectionSecondaryRow ? (
                <div className="suggestion-secondary-actions flex min-h-0 max-w-full flex-wrap items-center justify-end gap-2">
                  {correctionCompleted ? (
                    <span className="metric-pill py-1 text-[11px]">
                      Correction attempt {latestRevision.correction_attempt} completed
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => onRemapWithSupervisorFeedback(suggestion)}
                      className="button-secondary min-h-8 px-3 py-1.5 text-xs"
                      disabled={correctionBusy || correctionRetryReached}
                      title={correctionRetryReached ? "Supervisor feedback retry limit reached" : undefined}
                    >
                      {correctionBusy ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                      {correctionBusy ? "Re-running mapping..." : "Re-run mapping with Supervisor feedback"}
                    </button>
                  )}
                </div>
              ) : null}
            </div>
          </div>

          <div className="rounded-lg border border-slate-200/70 bg-slate-50/80 px-3 py-2 dark:border-white/10 dark:bg-white/[0.035]">
            <p className="text-[11px] font-semibold uppercase text-slate-500 dark:text-slate-400">
              Initial suggestion
            </p>
            {suggestion.suggested_template_field_id ? (
              <>
                <p className="mt-1 break-words text-sm font-medium text-slate-900 dark:text-slate-100">
                  {suggestion.suggested_template_field_label || suggestion.suggested_template_field_id}
                </p>
                <p className="mt-0.5 break-all text-xs text-slate-500 dark:text-slate-500">
                  {suggestion.suggested_template_field_id}
                  {suggestion.suggested_statement_type
                    ? ` | ${suggestion.suggested_statement_type}`
                    : ""}
                </p>
              </>
            ) : (
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                No safe AI suggestion
              </p>
            )}
          </div>

          {suggestion.reason ? (
            <p className="text-xs leading-5 text-slate-600 dark:text-slate-400">
              {suggestion.reason}
            </p>
          ) : null}

          {showSupervisorOrchestrationQueue && orchestrationItem ? (
            <details className="rounded-lg border border-amber-200/80 bg-amber-50/60 px-3 py-2 text-xs dark:border-amber-400/20 dark:bg-amber-400/[0.07]">
              <summary className="cursor-pointer font-semibold text-amber-700 dark:text-amber-200">
                Supervisor orchestration eligibility
              </summary>
              <p className="mt-2 leading-5 text-slate-600 dark:text-slate-400">
                Structural review signals indicate review priority only. They do not prove that the current mapping is incorrect.
              </p>
              <div className="mt-2 grid gap-2 text-slate-600 dark:text-slate-400 sm:grid-cols-2">
                <p><span className="font-semibold">Priority:</span> {orchestrationValueLabel(orchestrationItem.priority)}</p>
                <p><span className="font-semibold">Mapper status:</span> {orchestrationValueLabel(orchestrationItem.mapper_status)}</p>
                <p><span className="font-semibold">State:</span> {orchestrationValueLabel(orchestrationItem.orchestration_state)}</p>
                <p><span className="font-semibold">Recommended manual action:</span> {orchestrationValueLabel(orchestrationItem.recommended_manual_action)}</p>
                <p><span className="font-semibold">Review executable:</span> {orchestrationValueLabel(orchestrationItem.supervisor_review_executable)}</p>
                <p><span className="font-semibold">Supervisor decision:</span> {orchestrationValueLabel(orchestrationItem.supervisor_decision)}</p>
                <p><span className="font-semibold">Remapping:</span> {orchestrationValueLabel(orchestrationItem.remapping_eligibility)}</p>
                <p><span className="font-semibold">Remapping executable:</span> {orchestrationValueLabel(orchestrationItem.remapping_executable)}</p>
                <p><span className="font-semibold">Correction attempts used:</span> {orchestrationItem.correction_attempts_used || 0}</p>
              </div>
              {orchestrationItem.supervisor_action_block_reason ? (
                <p className="mt-2 leading-5 text-slate-600 dark:text-slate-400">
                  <span className="font-semibold">Review action blocked:</span>{" "}
                  {orchestrationValueLabel(orchestrationItem.supervisor_action_block_reason)}
                </p>
              ) : null}
              {orchestrationItem.remapping_action_block_reason ? (
                <p className="mt-2 leading-5 text-slate-600 dark:text-slate-400">
                  <span className="font-semibold">Remapping action blocked:</span>{" "}
                  {orchestrationValueLabel(orchestrationItem.remapping_action_block_reason)}
                </p>
              ) : null}
              {(orchestrationItem.eligibility_reasons || []).length > 0 ? (
                <p className="mt-2 leading-5 text-slate-600 dark:text-slate-400">
                  <span className="font-semibold">Eligibility reasons:</span>{" "}
                  {orchestrationItem.eligibility_reasons.map(orchestrationValueLabel).join("; ")}
                </p>
              ) : null}
              {(orchestrationItem.blocking_reasons || []).length > 0 ? (
                <p className="mt-2 leading-5 text-rose-700 dark:text-rose-200">
                  <span className="font-semibold">Blocking reasons:</span>{" "}
                  {orchestrationItem.blocking_reasons.map(orchestrationValueLabel).join("; ")}
                </p>
              ) : null}
              <p className="mt-2 font-semibold text-amber-700 dark:text-amber-200">
                Human review required. No automatic action is permitted.
              </p>
            </details>
          ) : null}

          {supervisorReview ? (
            <details className="rounded-lg border border-slate-200/70 bg-slate-50/80 px-3 py-2 text-xs dark:border-white/10 dark:bg-white/[0.035]">
              <summary className="cursor-pointer font-semibold text-slate-600 dark:text-slate-300">
                Supervisor advisory details
              </summary>
              <div className="mt-3 grid gap-2 text-slate-600 dark:text-slate-400 sm:grid-cols-2">
                <p><span className="font-semibold">Decision:</span> {supervisorValueLabel(supervisorReview.supervisor_decision)}</p>
                <p><span className="font-semibold">Risk:</span> {supervisorValueLabel(supervisorReview.supervisor_risk_level)}</p>
                <p><span className="font-semibold">Recommended action:</span> {supervisorValueLabel(supervisorReview.supervisor_recommended_action)}</p>
                <p><span className="font-semibold">Safe to accept:</span> {supervisorValueLabel(supervisorReview.supervisor_safe_to_accept)} (advisory only)</p>
                <p><span className="font-semibold">Calibrated safe:</span> {supervisorValueLabel(supervisorReview.calibrated_safe_to_accept)} (advisory only)</p>
                <p><span className="font-semibold">Confidence adjustment:</span> {supervisorValueLabel(supervisorReview.supervisor_confidence_adjustment)}</p>
                <p><span className="font-semibold">Source:</span> {supervisorValueLabel(supervisorReview.source)}</p>
                <p><span className="font-semibold">Model:</span> {supervisorReview.supervisor_model_id || "n/a"}</p>
                <p><span className="font-semibold">Created:</span> {supervisorDateLabel(supervisorReview.created_at)}</p>
                <p><span className="font-semibold">Updated:</span> {supervisorDateLabel(supervisorReview.updated_at)}</p>
              </div>
              {safeWithheldExplanation ? (
                <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-2 leading-5 text-amber-700 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200">
                  {safeWithheldExplanation}
                </div>
              ) : null}
              {supervisorReview.supervisor_reason ? (
                <p className="mt-3 leading-5 text-slate-600 dark:text-slate-400">
                  <span className="font-semibold">Reason:</span> {supervisorReview.supervisor_reason}
                </p>
              ) : null}
              {(supervisorReview.supervisor_issues || []).length > 0 ? (
                <div className="mt-3">
                  <p className="font-semibold text-slate-600 dark:text-slate-300">Issues:</p>
                  <ul className="mt-1 list-disc space-y-1 pl-5 text-slate-600 dark:text-slate-400">
                    {supervisorReview.supervisor_issues.map((issue, index) => (
                      <li key={`${supervisorReview.id}-issue-${index}`}>
                        <span className="font-medium">{supervisorValueLabel(issue.type)}:</span>{" "}
                        {issue.description || "No description"}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </details>
          ) : (
            <div className="rounded-lg border border-dashed border-slate-200/80 bg-slate-50/60 px-3 py-2 text-xs text-slate-500 dark:border-white/10 dark:bg-white/[0.025] dark:text-slate-400">
              {supervisorEmptyReviewMessage(showSupervisorLiveControls)}
            </div>
          )}

          {latestRevision ? (
            <div className="rounded-lg border border-violet-200 bg-violet-50/70 px-3 py-3 text-xs dark:border-violet-400/20 dark:bg-violet-400/10">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-semibold uppercase text-violet-700 dark:text-violet-200">
                  Revised suggestion
                </p>
                <span className="metric-pill py-0.5 text-[11px]">
                  Correction attempt {latestRevision.correction_attempt}
                </span>
              </div>
              <p className="mt-2 break-all font-medium text-slate-900 dark:text-slate-100">
                {latestRevision.revised_suggested_qname || "No safe revised mapping"}
              </p>
              {latestRevision.original_suggested_qname === latestRevision.revised_suggested_qname ? (
                <p className="mt-1 text-slate-600 dark:text-slate-400">
                  <span className="font-semibold">Outcome:</span>{" "}
                  Original suggestion retained after Supervisor-guided review.
                </p>
              ) : (
                <p className="mt-1 text-slate-600 dark:text-slate-400">
                  <span className="font-semibold">What changed:</span>{" "}
                  {latestRevision.original_suggested_qname || "No initial concept"} {"\u2192"}{" "}
                  {latestRevision.revised_suggested_qname || "No safe revised mapping"}
                </p>
              )}
              {latestRevision.reason ? (
                <p className="mt-1 text-slate-600 dark:text-slate-400">
                  <span className="font-semibold">Reason:</span> {latestRevision.reason}
                </p>
              ) : null}
              {(latestRevision.addressed_supervisor_issues || []).length > 0 ? (
                <div className="mt-1 text-slate-600 dark:text-slate-400">
                  <span className="font-semibold">Addressed Supervisor issues:</span>
                  <ul className="mt-1 list-disc space-y-1 pl-5">
                    {latestRevision.addressed_supervisor_issues.map((issue, index) => (
                      <li key={`${latestRevision.id}-addressed-${index}`}>
                        {supervisorValueLabel(issue.type)}: {issue.resolution || "Addressed during correction review"}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {(latestRevision.remaining_ambiguities || []).length > 0 ? (
                <p className="mt-1 text-slate-600 dark:text-slate-400">
                  <span className="font-semibold">Remaining ambiguities:</span>{" "}
                  {latestRevision.remaining_ambiguities.join("; ")}
                </p>
              ) : null}
              <p className="mt-2 font-semibold text-amber-700 dark:text-amber-200">
                Human review required. This revised suggestion was not applied or confirmed.
              </p>
            </div>
          ) : null}

          {ranked.length > 0 ? (
            <div className="text-xs leading-5 text-slate-500 dark:text-slate-500">
              <span className="font-semibold text-slate-600 dark:text-slate-300">
                Alternatives:
              </span>{" "}
              {ranked.slice(0, 3).map((candidate) => (
                <span key={`${suggestion.id}-${candidate.template_field_id}`} className="mr-2">
                  {candidate.label || candidate.template_field_id} ({confidencePercent(candidate.confidence)})
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    );
  };

  const renderSuggestionGroup = (title, rows) => {
    if (rows.length === 0) {
      return null;
    }
    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <h5 className="text-xs font-semibold uppercase text-slate-500 dark:text-slate-400">
            {title}
          </h5>
          <span className="metric-pill py-0.5 text-[11px]">{rows.length}</span>
        </div>
        <div className="space-y-2">
          {rows.map(renderSuggestionCard)}
        </div>
      </div>
    );
  };

  return (
    <section className="panel min-w-0 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-brand-600 dark:text-brand-300" />
            <h4 className="text-base font-semibold text-slate-950 dark:text-white">
              AI Mapping Suggestions
            </h4>
          </div>
          <p className="mt-1 text-sm leading-5 text-slate-500 dark:text-slate-400">
            AI suggestion results require confirmation before they become official mappings.
          </p>
          {showSupervisorLiveControls ? (
            <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
              Live Supervisor controls are test-stage visibility controls only; the backend feature flag and permissions remain authoritative.
            </p>
          ) : null}
        </div>
        {visibleSuggestions.length > 0 && showSupervisorControls ? (
          <div className="flex flex-wrap items-center justify-end gap-2">
            {showSupervisorLiveControls && !showSupervisorOrchestrationQueue ? (
              <button
                type="button"
                onClick={() => onRunBatchSupervisorReviews("live")}
                className="button-secondary min-h-8 px-3 py-1.5 text-xs"
                disabled={supervisorBatchRunning}
              >
                {supervisorBatchRunning ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                Run Supervisor reviews for all
              </button>
            ) : null}
            {showSupervisorLiveControls && orchestrationQueueAvailable ? (
              <button
                type="button"
                onClick={() =>
                  onRunBatchSupervisorReviews(
                    "live",
                    boundedEligibleBatchSuggestions.map((suggestion) => suggestion.id),
                  )
                }
                className="button-secondary min-h-8 px-3 py-1.5 text-xs"
                disabled={
                  supervisorBatchRunning ||
                  boundedEligibleBatchSuggestions.length === 0
                }
              >
                {supervisorBatchRunning ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                Run Supervisor reviews for eligible suggestions ({boundedEligibleBatchSuggestions.length})
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
        <span className="metric-pill">{visibleSuggestions.length} AI suggestions</span>
        <span className="metric-pill">{actionableCount} require confirmation</span>
        <span className="metric-pill">{acceptedCount} accepted</span>
        <span className="metric-pill">{ignoredCount} rejected</span>
        <span className="metric-pill">{rejectedCount} no-safe-mapping</span>
        <span className="metric-pill">{supervisorReviewedCount} Supervisor reviews</span>
      </div>

      {showSupervisorOrchestrationQueue ? (
        <div className="mt-4 rounded-lg border border-slate-200/80 bg-slate-50/70 p-3 dark:border-white/10 dark:bg-white/[0.025]">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                Supervisor review queue
              </p>
              <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                Local, read-only eligibility planning. Supervisor review and remapping occur only after an explicit manual action.
              </p>
            </div>
            <button
              type="button"
              onClick={onRefreshSupervisorOrchestration}
              className="button-secondary min-h-8 px-3 py-1.5 text-xs"
              disabled={loadingSupervisorOrchestration}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loadingSupervisorOrchestration ? "animate-spin" : ""}`} />
              Refresh queue
            </button>
          </div>

          {loadingSupervisorOrchestration ? (
            <div className="mt-3 flex items-center text-xs text-slate-500 dark:text-slate-400">
              <LoaderCircle className="mr-2 h-3.5 w-3.5 animate-spin" />
              Loading Supervisor orchestration capabilities and plan
            </div>
          ) : supervisorOrchestrationError ? (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs text-amber-700 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200">
              Supervisor orchestration queue could not be loaded. {supervisorOrchestrationError}
            </div>
          ) : !supervisorOrchestrationCapabilities?.enabled ? (
            <div className="mt-3 rounded-lg border border-dashed border-slate-300/80 px-3 py-3 text-xs text-slate-500 dark:border-white/10 dark:text-slate-400">
              Supervisor orchestration is disabled by the backend. Normal AI mapping review remains available.
            </div>
          ) : (supervisorOrchestrationCapabilities?.unsafe_configuration_reasons || []).length > 0 ? (
            <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50/70 px-3 py-2 text-xs text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
              Safety warning: the backend reported an unsafe orchestration configuration. Queue actions are blocked.
            </div>
          ) : !supervisorOrchestrationCapabilities?.available ? (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs text-amber-700 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200">
              Supervisor orchestration is not available for this job or user. Backend permissions remain authoritative.
            </div>
          ) : orchestrationSafetyError ? (
            <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50/70 px-3 py-2 text-xs text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
              Safety warning: {orchestrationSafetyError} Queue batch controls are blocked.
            </div>
          ) : supervisorOrchestrationPlan ? (
            <>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500 dark:text-slate-400">
                <span className="metric-pill">{supervisorOrchestrationPlan.total_suggestions || 0} total suggestions</span>
                <span className="metric-pill">{supervisorOrchestrationPlan.eligible_count || 0} policy eligible</span>
                <span className="metric-pill">{supervisorOrchestrationPlan.review_executable_count || 0} review executable</span>
                <span className="metric-pill">{supervisorOrchestrationPlan.high_priority_count || 0} high priority</span>
                <span className="metric-pill">{supervisorOrchestrationPlan.medium_priority_count || 0} medium priority</span>
                <span className="metric-pill">{supervisorOrchestrationPlan.already_reviewed_count || 0} already reviewed</span>
                <span className="metric-pill">{supervisorOrchestrationPlan.remapping_eligible_count || 0} remapping eligible</span>
                <span className="metric-pill">{supervisorOrchestrationPlan.remapping_executable_count || 0} remapping executable</span>
                <span className="metric-pill">{supervisorOrchestrationPlan.revision_completed_count || 0} revisions completed</span>
                <span className="metric-pill">{supervisorOrchestrationPlan.blocked_count || 0} blocked</span>
                <span className="metric-pill">{supervisorOrchestrationPlan.not_eligible_count || 0} not eligible</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {SUPERVISOR_ORCHESTRATION_FILTERS.map((filter) => (
                  <button
                    key={filter.id}
                    type="button"
                    onClick={() => setOrchestrationFilter(filter.id)}
                    className={
                      orchestrationFilter === filter.id
                        ? "button-primary min-h-8 px-3 py-1.5 text-xs"
                        : "button-secondary min-h-8 px-3 py-1.5 text-xs"
                    }
                  >
                    {filter.label}
                  </button>
                ))}
              </div>
              <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
                Planning live calls: 0 | Automatic reviews: 0 | Automatic remaps: 0 | Confirmed tag mutations: 0 | Final mapping mutations: 0 | Human review required.
              </p>
              {eligibleBatchSuggestions.length > orchestrationBatchLimit ? (
                <p className="mt-2 text-xs leading-5 text-amber-700 dark:text-amber-200">
                  The next manual batch is limited to {orchestrationBatchLimit} of {eligibleBatchSuggestions.length} eligible, unreviewed suggestions by the backend batch limit.
                </p>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}

      {loadingSupervisorReviews ? (
        <div className="mt-3 flex items-center text-xs text-slate-500 dark:text-slate-400">
          <LoaderCircle className="mr-2 h-3.5 w-3.5 animate-spin" />
          Loading Supervisor advisory reviews
        </div>
      ) : null}

      {supervisorReviewError ? (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs text-amber-700 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200">
          Supervisor advisory reviews could not be loaded. {supervisorReviewError}
        </div>
      ) : null}

      {supervisorCorrectionError ? (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs text-amber-700 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200">
          Supervisor-guided mapping correction could not be completed. {supervisorCorrectionError}
        </div>
      ) : null}

      {loading ? (
        <div className="mt-4 flex items-center text-sm text-slate-500 dark:text-slate-400">
          <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
          Loading AI suggestion results
        </div>
      ) : isGenerating ? (
        <div className="mt-4 flex items-center rounded-lg border border-brand-200 bg-brand-50/70 px-4 py-4 text-sm text-brand-700 dark:border-brand-400/20 dark:bg-brand-400/10 dark:text-brand-200">
          <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
          AI mapping suggestions are being generated...
        </div>
      ) : isCheckingPostCompletion ? (
        <div className="mt-4 flex items-center rounded-lg border border-brand-200 bg-brand-50/70 px-4 py-4 text-sm text-brand-700 dark:border-brand-400/20 dark:bg-brand-400/10 dark:text-brand-200">
          <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
          Checking for AI mapping suggestions...
        </div>
      ) : isRateLimited ? (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50/70 px-4 py-4 text-sm text-amber-700 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200">
          AI provider is temporarily rate limited. Please wait a few minutes and try again.
        </div>
      ) : isFailed ? (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50/70 px-4 py-4 text-sm text-red-700 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-200">
          AI mapping suggestions could not be generated automatically.
          {status?.last_error_message ? ` ${status.last_error_message}` : ""}
        </div>
      ) : isNotStarted && !isGraceExpiredEmpty ? (
        <div className="mt-4 rounded-lg border border-dashed border-slate-300/80 bg-slate-50/70 px-4 py-6 text-sm text-slate-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-400">
          AI mapping suggestions will appear automatically after processing.
        </div>
      ) : isCompletedEmpty ? (
        <div className="mt-4 rounded-lg border border-dashed border-slate-300/80 bg-slate-50/70 px-4 py-6 text-sm text-slate-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-400">
          No AI suggestions were generated.
        </div>
      ) : isGraceExpiredEmpty ? (
        <div className="mt-4 rounded-lg border border-dashed border-slate-300/80 bg-slate-50/70 px-4 py-6 text-sm text-slate-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-400">
          No safe AI suggestion results are available for this job.
        </div>
      ) : visibleSuggestions.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed border-slate-300/80 bg-slate-50/70 px-4 py-6 text-sm text-slate-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-400">
          No safe AI suggestion results are available for this job.
        </div>
      ) : orchestrationQueueAvailable && displayedSuggestions.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed border-slate-300/80 bg-slate-50/70 px-4 py-6 text-sm text-slate-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-400">
          No suggestions match the selected Supervisor queue filter.
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          {renderSuggestionGroup("Pending AI suggestions", pendingSuggestions)}
          {renderSuggestionGroup("Accepted AI suggestions", acceptedSuggestions)}
          {renderSuggestionGroup("Rejected AI suggestions", ignoredSuggestions)}
          {rejectedSuggestions.length > 0 ? (
            <details
              className="rounded-lg border border-slate-200/80 bg-slate-50/70 p-3 dark:border-white/10 dark:bg-white/[0.025]"
              open={orchestrationQueueAvailable && orchestrationFilter !== "all"}
            >
              <summary className="cursor-pointer text-xs font-semibold uppercase text-slate-500 dark:text-slate-400">
                No safe AI mapping / rejected ({rejectedSuggestions.length})
              </summary>
              <div className="mt-3 space-y-2">
                {rejectedSuggestions.map(renderSuggestionCard)}
              </div>
            </details>
          ) : null}
        </div>
      )}
    </section>
  );
}

export function ReviewWorkspace({
  job,
  refreshKey = 0,
  postCompletionAiRefreshKey = 0,
  onStateChange,
}) {
  const [templates, setTemplates] = useState([]);
  const [templateDetailsByCode, setTemplateDetailsByCode] = useState({});
  const [selectedStatementCode, setSelectedStatementCode] = useState("");
  const [statementDetail, setStatementDetail] = useState(null);
  const [pages, setPages] = useState([]);
  const [extractedItems, setExtractedItems] = useState([]);
  const [draftValues, setDraftValues] = useState({});
  const [initialValues, setInitialValues] = useState({});
  const [draftTags, setDraftTags] = useState({});
  const [initialTags, setInitialTags] = useState({});
  const [draftRowTags, setDraftRowTags] = useState({});
  const [initialRowTags, setInitialRowTags] = useState({});
  const [taxonomyReady, setTaxonomyReady] = useState(true);
  const [taxonomyStatusMessage, setTaxonomyStatusMessage] = useState("");
  const [aiSuggestions, setAiSuggestions] = useState([]);
  const [aiMappingStatus, setAiMappingStatus] = useState({
    ai_mapping_status: "not_started",
    suggestions_count: 0,
  });
  const [loadingAiSuggestions, setLoadingAiSuggestions] = useState(false);
  const [supervisorReviews, setSupervisorReviews] = useState([]);
  const [loadingSupervisorReviews, setLoadingSupervisorReviews] = useState(false);
  const [supervisorReviewError, setSupervisorReviewError] = useState("");
  const [supervisorReviewActionId, setSupervisorReviewActionId] = useState("");
  const supervisorReviewPendingIds = useMemo(() => new Set(), []);
  const [supervisorBatchRunning, setSupervisorBatchRunning] = useState(false);
  const [supervisorGuidedRevisions, setSupervisorGuidedRevisions] = useState([]);
  const [supervisorMapperFeedbackCapabilities, setSupervisorMapperFeedbackCapabilities] = useState(null);
  const [supervisorCorrectionActionId, setSupervisorCorrectionActionId] = useState("");
  const supervisorCorrectionPendingIds = useMemo(() => new Set(), []);
  const [supervisorCorrectionError, setSupervisorCorrectionError] = useState("");
  const [supervisorOrchestrationCapabilities, setSupervisorOrchestrationCapabilities] = useState(null);
  const [supervisorOrchestrationPlan, setSupervisorOrchestrationPlan] = useState(null);
  const [loadingSupervisorOrchestration, setLoadingSupervisorOrchestration] = useState(false);
  const [supervisorOrchestrationError, setSupervisorOrchestrationError] = useState("");
  const [postCompletionAiPollingActive, setPostCompletionAiPollingActive] = useState(false);
  const [postCompletionAiPollingExpired, setPostCompletionAiPollingExpired] = useState(false);
  const [aiSuggestionActionId, setAiSuggestionActionId] = useState("");
  const [loadingBase, setLoadingBase] = useState(true);
  const [loadingStatement, setLoadingStatement] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saveMessage, setSaveMessage] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadBaseData() {
      setLoadingBase(true);
      setError("");
      setSaveMessage("");
      setStatementDetail(null);
      setDraftValues({});
      setInitialValues({});
      setDraftTags({});
      setInitialTags({});
      setDraftRowTags({});
      setInitialRowTags({});
      setAiSuggestions([]);
      setAiMappingStatus({
        ai_mapping_status: "not_started",
        suggestions_count: 0,
      });
      setSupervisorReviews([]);
      setSupervisorReviewError("");
      setSupervisorGuidedRevisions([]);
      setSupervisorMapperFeedbackCapabilities(null);
      setSupervisorCorrectionError("");
      setSupervisorOrchestrationCapabilities(null);
      setSupervisorOrchestrationPlan(null);
      setSupervisorOrchestrationError("");
      setLoadingAiSuggestions(true);
      setLoadingSupervisorReviews(true);

      try {
        const [
          templateList,
          extractedResponse,
          jobPages,
          taxonomyStatus,
          aiSuggestionResponse,
          aiSuggestionStatusResponse,
          supervisorReviewResponse,
          supervisorFeedbackCapabilitiesResponse,
          supervisorGuidedRevisionResponse,
        ] = await Promise.all([
          fetchTemplates(),
          fetchExtractedData(job.id, 1, 1000),
          fetchJobPages(job.id),
          fetchTaxonomyStatus().catch(() => null),
          fetchAiMappingSuggestions(job.id).catch(() => ({ suggestions: [] })),
          fetchAiMappingSuggestionsStatus(job.id).catch(() => ({
            ai_mapping_status: "not_started",
            suggestions_count: 0,
          })),
          listSupervisorReviews(job.id).catch((reviewError) => ({
            supervisorReviewError: reviewError.message,
            reviews: [],
          })),
          SHOW_SUPERVISOR_MAPPER_FEEDBACK
            ? fetchSupervisorMapperFeedbackCapabilities(job.id).catch(() => null)
            : Promise.resolve(null),
          SHOW_SUPERVISOR_MAPPER_FEEDBACK
            ? listSupervisorGuidedMappingRevisions(job.id).catch(() => [])
            : Promise.resolve([]),
        ]);

        if (cancelled) {
          return;
        }

        const sortedTemplates = [...templateList].sort((left, right) =>
          left.code.localeCompare(right.code),
        );

        const templateDetails = await Promise.all(
          sortedTemplates.map(async (template) => {
            try {
              return await fetchTemplate(template.code);
            } catch (detailError) {
              return null;
            }
          }),
        );

        if (cancelled) {
          return;
        }

        const nextTemplateDetailsByCode = {};
        for (const detail of templateDetails) {
          if (detail?.code) {
            nextTemplateDetailsByCode[detail.code] = detail;
          }
        }

        const nextTemplateFieldMap = buildTemplateFieldStatementMap(
          Object.values(nextTemplateDetailsByCode),
        );
        const extractedRows = normalizeExtractedRows(extractedResponse);
        const nextStatementGroups = buildStatementGroups(
          extractedRows,
          sortedTemplates,
          nextTemplateFieldMap.fieldToStatement,
          nextTemplateFieldMap.fieldToStatements,
          nextTemplateFieldMap.statementMetaByCode,
        );

        setTemplates(sortedTemplates);
        setTemplateDetailsByCode(nextTemplateDetailsByCode);
        setPages(jobPages);
        setExtractedItems(extractedRows);
        setTaxonomyReady(taxonomyStatus?.is_loaded !== false);
        setTaxonomyStatusMessage(taxonomyStatus?.message || "");
        setAiSuggestions(aiSuggestionResponse?.suggestions || []);
        setAiMappingStatus(aiSuggestionStatusResponse || {
          ai_mapping_status: "not_started",
          suggestions_count: 0,
        });
        setSupervisorReviews(normalizeSupervisorReviews(supervisorReviewResponse));
        setSupervisorReviewError(supervisorReviewResponse?.supervisorReviewError || "");
        setSupervisorMapperFeedbackCapabilities(supervisorFeedbackCapabilitiesResponse);
        setSupervisorGuidedRevisions(
          Array.isArray(supervisorGuidedRevisionResponse)
            ? supervisorGuidedRevisionResponse
            : [],
        );
        setSelectedStatementCode((current) => {
          if (
            current &&
            (
              (current === UNASSIGNED_STATEMENT_CODE &&
                (nextStatementGroups[UNASSIGNED_STATEMENT_CODE]?.items.length || 0) > 0) ||
              (sortedTemplates.some((item) => item.code === current) &&
                (nextStatementGroups[current]?.items.length || 0) > 0)
            )
          ) {
            return current;
          }

          const firstTemplateWithData = sortedTemplates.find(
            (item) => (nextStatementGroups[item.code]?.items.length || 0) > 0,
          );

          if (firstTemplateWithData) {
            return firstTemplateWithData.code;
          }

          if (nextStatementGroups[UNASSIGNED_STATEMENT_CODE]?.items.length) {
            return UNASSIGNED_STATEMENT_CODE;
          }

          return sortedTemplates[0]?.code || UNASSIGNED_STATEMENT_CODE;
        });
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError.message);
        }
      } finally {
        if (!cancelled) {
          setLoadingBase(false);
          setLoadingAiSuggestions(false);
          setLoadingSupervisorReviews(false);
        }
      }
    }

    loadBaseData();

    return () => {
      cancelled = true;
    };
  }, [job.id, refreshKey]);

  useEffect(() => {
    if (
      !postCompletionAiRefreshKey ||
      !AI_SUGGESTION_TERMINAL_JOB_STATUSES.has(job.status)
    ) {
      setPostCompletionAiPollingActive(false);
      setPostCompletionAiPollingExpired(false);
      return undefined;
    }

    setPostCompletionAiPollingActive(true);
    setPostCompletionAiPollingExpired(false);
    const timeoutId = window.setTimeout(() => {
      setPostCompletionAiPollingActive(false);
      setPostCompletionAiPollingExpired(true);
    }, AI_SUGGESTION_POST_COMPLETION_GRACE_MS);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [job.id, job.status, postCompletionAiRefreshKey]);

  useEffect(() => {
    if (
      !selectedStatementCode ||
      selectedStatementCode === UNASSIGNED_STATEMENT_CODE
    ) {
      setStatementDetail(null);
      return;
    }

    let cancelled = false;

    async function loadStatement() {
      setLoadingStatement(true);
      setError("");

      try {
        const detail = await fetchTemplate(selectedStatementCode);
        if (!cancelled) {
          setStatementDetail(detail);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError.message);
        }
      } finally {
        if (!cancelled) {
          setLoadingStatement(false);
        }
      }
    }

    loadStatement();

    return () => {
      cancelled = true;
    };
  }, [selectedStatementCode]);

  const extractedLookup = useMemo(
    () => buildExtractedLookup(extractedItems),
    [extractedItems],
  );

  const { fieldToStatement, fieldToStatements, statementMetaByCode } = useMemo(
    () => buildTemplateFieldStatementMap(Object.values(templateDetailsByCode)),
    [templateDetailsByCode],
  );

  const statementGroups = useMemo(
    () =>
      buildStatementGroups(
        extractedItems,
        templates,
        fieldToStatement,
        fieldToStatements,
        statementMetaByCode,
      ),
    [extractedItems, fieldToStatement, fieldToStatements, statementMetaByCode, templates],
  );

  const statementOptions = useMemo(() => {
    const options = templates.map((template) => ({
      ...template,
      matchedItemCount: statementGroups[template.code]?.items.length || 0,
    }));

    if (statementGroups[UNASSIGNED_STATEMENT_CODE]?.items.length) {
      options.push({
        code: UNASSIGNED_STATEMENT_CODE,
        description: UNASSIGNED_STATEMENT_LABEL,
        total_concepts: 0,
        matchedItemCount: statementGroups[UNASSIGNED_STATEMENT_CODE].items.length,
      });
    }

    return options;
  }, [statementGroups, templates]);

  const statementFields = useMemo(() => {
    if (!statementDetail?.concepts) {
      return [];
    }

    return [...statementDetail.concepts]
      .sort(fieldSort)
      .map((concept) => {
        const rawSourceItems =
          extractedLookup[normalizeFieldId(concept.id)] ||
          extractedLookup[concept.id] ||
          [];
        const fieldStatementCodes =
          fieldToStatements[concept.id] ||
          fieldToStatements[normalizeFieldId(concept.id)] ||
          [];
        const sourceItems = rawSourceItems.filter((item) => {
          if (fieldStatementCodes.length <= 1) {
            return true;
          }
          const itemStatementCode = statementCodeFromItemType(item, templates);
          return !itemStatementCode || itemStatementCode === statementDetail.code;
        });
        const sortedItems = sortByYear(sourceItems);

        return {
          ...concept,
          sourceItems: sortedItems,
          initialValue: sortedItems[0]?.extracted_value || "",
          initialTagId: sortedItems[0]?.confirmed_tag_id || null,
          initialTagLabel: sortedItems[0]?.confirmed_tag_id
            ? `Tag #${sortedItems[0].confirmed_tag_id}`
            : "",
          latestYear: sortedItems[0]?.financial_year || null,
        };
      });
  }, [fieldToStatements, statementDetail, extractedLookup, templates]);

  const visibleItemIds = useMemo(() => {
    const ids = new Set();

    for (const field of statementFields) {
      for (const item of field.sourceItems) {
        ids.add(item.id);
      }
    }

    return ids;
  }, [statementFields]);

  const groupedItemsForSelectedStatement = useMemo(
    () => statementGroups[selectedStatementCode]?.items || [],
    [selectedStatementCode, statementGroups],
  );

  const additionalGroupedItems = useMemo(() => {
    if (selectedStatementCode === UNASSIGNED_STATEMENT_CODE) {
      return groupedItemsForSelectedStatement;
    }

    return groupedItemsForSelectedStatement.filter((item) => !visibleItemIds.has(item.id));
  }, [groupedItemsForSelectedStatement, selectedStatementCode, visibleItemIds]);

  const unassignedItems = useMemo(
    () => statementGroups[UNASSIGNED_STATEMENT_CODE]?.items || [],
    [statementGroups],
  );

  const templateBackedRowCount = useMemo(
    () => extractedItems.filter((item) => item.template_field_id).length,
    [extractedItems],
  );

  useEffect(() => {
    const nextRowTags = buildTagDraftMap(extractedItems);
    setInitialRowTags(nextRowTags);
    setDraftRowTags(nextRowTags);
  }, [extractedItems]);

  useEffect(() => {
    if (!statementFields.length) {
      setDraftValues({});
      setInitialValues({});
      setDraftTags({});
      setInitialTags({});
      return;
    }

    const nextInitialValues = {};
    const nextInitialTags = {};
    for (const field of statementFields) {
      nextInitialValues[field.id] = field.initialValue;
      nextInitialTags[field.id] = field.initialTagId
        ? {
            id: field.initialTagId,
            label: field.initialTagLabel || `Tag #${field.initialTagId}`,
          }
        : null;
    }

    setInitialValues(nextInitialValues);
    setDraftValues(nextInitialValues);
    setInitialTags(nextInitialTags);
    setDraftTags(nextInitialTags);
  }, [statementFields]);

  const dirtyCount = useMemo(() => {
    const valueChanges = Object.entries(draftValues).filter(([fieldId, value]) => {
      return (value || "") !== (initialValues[fieldId] || "");
    }).length;
    const tagChanges = Object.entries(draftTags).filter(([fieldId, tag]) => {
      return (tag?.id || null) !== (initialTags[fieldId]?.id || null);
    }).length;
    const rowTagChanges = Object.entries(draftRowTags).filter(([itemId, tag]) => {
      return (tag?.id || null) !== (initialRowTags[itemId]?.id || null);
    }).length;
    return valueChanges + tagChanges + rowTagChanges;
  }, [draftRowTags, draftTags, draftValues, initialRowTags, initialTags, initialValues]);

  function handleFieldChange(fieldId, value) {
    setDraftValues((current) => ({
      ...current,
      [fieldId]: value,
    }));
    setSaveMessage("");
  }

  function handleTagSelect(fieldId, tag) {
    setDraftTags((current) => ({
      ...current,
      [fieldId]: tag,
    }));
    setSaveMessage("");
  }

  function handleTagClear(fieldId) {
    setDraftTags((current) => ({
      ...current,
      [fieldId]: null,
    }));
    setSaveMessage("");
  }

  function handleRowTagSelect(itemId, tag) {
    setDraftRowTags((current) => ({
      ...current,
      [itemId]: tag,
    }));
    setSaveMessage("");
  }

  function handleRowTagClear(itemId) {
    setDraftRowTags((current) => ({
      ...current,
      [itemId]: null,
    }));
    setSaveMessage("");
  }

  const reloadExtractedItems = useCallback(async () => {
    const refreshed = await fetchExtractedData(job.id, 1, 1000);
    const items = normalizeExtractedRows(refreshed);
    setExtractedItems(items);
    return items;
  }, [job.id]);

  const reloadAiSuggestions = useCallback(async () => {
    setLoadingAiSuggestions(true);
    try {
      const [response, statusResponse] = await Promise.all([
        fetchAiMappingSuggestions(job.id),
        fetchAiMappingSuggestionsStatus(job.id).catch(() => null),
      ]);
      setAiSuggestions(response?.suggestions || []);
      if (statusResponse) {
        setAiMappingStatus(statusResponse);
      }
      return response?.suggestions || [];
    } finally {
      setLoadingAiSuggestions(false);
    }
  }, [job.id]);

  const reloadSupervisorReviews = useCallback(async () => {
    setLoadingSupervisorReviews(true);
    setSupervisorReviewError("");
    try {
      const response = await listSupervisorReviews(job.id);
      const reviews = normalizeSupervisorReviews(response);
      setSupervisorReviews(reviews);
      return reviews;
    } catch (reviewError) {
      setSupervisorReviewError(reviewError.message);
      return [];
    } finally {
      setLoadingSupervisorReviews(false);
    }
  }, [job.id]);

  const reloadSupervisorOrchestration = useCallback(async () => {
    if (!SHOW_SUPERVISOR_ORCHESTRATION_QUEUE) {
      return null;
    }

    setLoadingSupervisorOrchestration(true);
    setSupervisorOrchestrationError("");
    try {
      const capabilities = await fetchSupervisorOrchestrationCapabilities(job.id);
      setSupervisorOrchestrationCapabilities(capabilities);
      if (
        capabilities?.enabled !== true ||
        capabilities?.available !== true ||
        (capabilities?.unsafe_configuration_reasons || []).length > 0
      ) {
        setSupervisorOrchestrationPlan(null);
        return null;
      }

      const plan = await fetchSupervisorOrchestrationPlan(job.id);
      setSupervisorOrchestrationPlan(plan);
      return plan;
    } catch (orchestrationError) {
      setSupervisorOrchestrationPlan(null);
      setSupervisorOrchestrationError(orchestrationError.message);
      return null;
    } finally {
      setLoadingSupervisorOrchestration(false);
    }
  }, [job.id]);

  useEffect(() => {
    reloadSupervisorOrchestration();
  }, [aiSuggestions.length, refreshKey, reloadSupervisorOrchestration]);

  useEffect(() => {
    if (aiSuggestions.length === 0) {
      return undefined;
    }

    let cancelled = false;

    async function loadPersistedSupervisorReviews() {
      setLoadingSupervisorReviews(true);
      setSupervisorReviewError("");
      try {
        const response = await listSupervisorReviews(job.id);
        if (!cancelled) {
          setSupervisorReviews(normalizeSupervisorReviews(response));
        }
      } catch (reviewError) {
        if (!cancelled) {
          setSupervisorReviewError(reviewError.message);
        }
      } finally {
        if (!cancelled) {
          setLoadingSupervisorReviews(false);
        }
      }
    }

    loadPersistedSupervisorReviews();

    return () => {
      cancelled = true;
    };
  }, [aiSuggestions.length, job.id]);

  const aiMappingStatusValue = aiMappingStatus?.ai_mapping_status || "not_started";
  const visibleAiSuggestionCount = aiSuggestions.length;
  const shouldPollAiSuggestions =
    aiMappingStatusValue === "running" ||
    (
      postCompletionAiPollingActive &&
      visibleAiSuggestionCount === 0 &&
      (aiMappingStatusValue === "not_started" || aiMappingStatusValue === "completed")
    );
  const checkingPostCompletionSuggestions =
    postCompletionAiPollingActive &&
    visibleAiSuggestionCount === 0 &&
    (aiMappingStatusValue === "not_started" || aiMappingStatusValue === "completed");

  useEffect(() => {
    if (!postCompletionAiPollingActive) {
      return;
    }

    if (
      visibleAiSuggestionCount > 0 ||
      aiMappingStatusValue === "failed" ||
      aiMappingStatusValue === "rate_limited"
    ) {
      setPostCompletionAiPollingActive(false);
      setPostCompletionAiPollingExpired(false);
    }
  }, [aiMappingStatusValue, postCompletionAiPollingActive, visibleAiSuggestionCount]);

  useEffect(() => {
    if (!shouldPollAiSuggestions) {
      return undefined;
    }

    let cancelled = false;

    async function pollAiSuggestions() {
      try {
        const [statusResponse, suggestionResponse] = await Promise.all([
          fetchAiMappingSuggestionsStatus(job.id),
          fetchAiMappingSuggestions(job.id).catch(() => ({ suggestions: [] })),
        ]);
        if (cancelled) {
          return;
        }

        const nextSuggestions = suggestionResponse?.suggestions || [];
        const statusSuggestionCount = Number(statusResponse?.suggestions_count || 0);
        const nextStatus = {
          ...statusResponse,
          suggestions_count: Math.max(statusSuggestionCount, nextSuggestions.length),
        };
        if (nextStatus.ai_mapping_status === "not_started" && nextSuggestions.length > 0) {
          nextStatus.ai_mapping_status = "completed";
        }

        setAiMappingStatus(nextStatus);
        setAiSuggestions(nextSuggestions);

        if (
          nextSuggestions.length > 0 ||
          nextStatus.ai_mapping_status === "failed" ||
          nextStatus.ai_mapping_status === "rate_limited"
        ) {
          setPostCompletionAiPollingActive(false);
        }
        if (
          nextStatus.ai_mapping_status === "completed" &&
          Number(nextStatus.suggestions_count || 0) > 0
        ) {
          setPostCompletionAiPollingActive(false);
        }
      } catch (pollError) {
        // Keep polling quiet; normal error surfaces still come from explicit actions.
      }
    }

    pollAiSuggestions();
    const intervalId = window.setInterval(pollAiSuggestions, AI_SUGGESTION_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [job.id, shouldPollAiSuggestions]);

  useEffect(() => {
    if (aiMappingStatusValue !== "completed") {
      return undefined;
    }

    let cancelled = false;

    async function refreshCompletedSuggestions() {
      try {
        const response = await fetchAiMappingSuggestions(job.id);
        if (!cancelled) {
          const nextSuggestions = response?.suggestions || [];
          setAiSuggestions(nextSuggestions);
          if (nextSuggestions.length > 0) {
            setAiMappingStatus((current) => ({
              ...current,
              suggestions_count: Math.max(Number(current?.suggestions_count || 0), nextSuggestions.length),
            }));
            setPostCompletionAiPollingActive(false);
          }
        }
      } catch (refreshError) {
        // Keep refresh quiet; the panel state still comes from status polling.
      }
    }

    refreshCompletedSuggestions();

    return () => {
      cancelled = true;
    };
  }, [aiMappingStatusValue, job.id]);

  const handleRunSupervisorReview = useCallback(async (suggestion, mode = "mock") => {
    if (!suggestion?.id || supervisorReviewPendingIds.has(suggestion.id)) {
      return;
    }
    const normalizedMode = normalizeSupervisorReviewMode(mode);

    supervisorReviewPendingIds.add(suggestion.id);
    setSupervisorReviewActionId(suggestion.id);
    setSupervisorReviewError("");
    setSaveMessage("");

    try {
      await runSupervisorReview(job.id, suggestion.id, { mode: normalizedMode });
      await Promise.all([
        reloadSupervisorReviews(),
        reloadSupervisorOrchestration(),
      ]);
      setSaveMessage(
        normalizedMode === "live"
          ? "Live Supervisor advisory review completed. No mapping was applied automatically."
          : "Mock Supervisor advisory review completed. No mapping was applied automatically.",
      );
    } catch (reviewError) {
      setSupervisorReviewError(reviewError.message);
    } finally {
      supervisorReviewPendingIds.delete(suggestion.id);
      setSupervisorReviewActionId("");
    }
  }, [job.id, reloadSupervisorOrchestration, reloadSupervisorReviews, supervisorReviewPendingIds]);

  const handleRunBatchSupervisorReviews = useCallback(async (mode = "mock", suggestionIds = null) => {
    const normalizedMode = normalizeSupervisorReviewMode(mode);
    const intendedCount = Array.isArray(suggestionIds) ? suggestionIds.length : null;
    if (
      normalizedMode === "live" &&
      !confirmBatchSupervisorRun(
        intendedCount == null
          ? "Run Supervisor reviews for all visible suggestions? This calls the configured Supervisor LLM. The backend feature flag, permissions, and batch limit remain authoritative, and no mappings will be applied automatically."
          : `Run Supervisor reviews for ${intendedCount} eligible, unreviewed suggestions? This calls the configured Supervisor LLM. The backend feature flag, permissions, and batch limit remain authoritative, and no mappings will be applied automatically.`,
      )
    ) {
      return;
    }

    setSupervisorBatchRunning(true);
    setSupervisorReviewError("");
    setSaveMessage("");

    try {
      const options = { mode: normalizedMode };
      if (Array.isArray(suggestionIds)) {
        options.suggestionIds = suggestionIds;
      }
      await runBatchSupervisorReviews(job.id, options);
      await Promise.all([
        reloadSupervisorReviews(),
        reloadSupervisorOrchestration(),
      ]);
      setSaveMessage(
        normalizedMode === "live"
          ? "Live Supervisor advisory reviews completed. No mappings were applied automatically."
          : "Mock Supervisor advisory reviews completed. No mappings were applied automatically.",
      );
    } catch (reviewError) {
      setSupervisorReviewError(reviewError.message);
    } finally {
      setSupervisorBatchRunning(false);
    }
  }, [job.id, reloadSupervisorOrchestration, reloadSupervisorReviews]);

  const handleRemapWithSupervisorFeedback = useCallback(async (suggestion) => {
    if (!suggestion?.id || supervisorCorrectionPendingIds.has(suggestion.id)) {
      return;
    }

    supervisorCorrectionPendingIds.add(suggestion.id);
    setSupervisorCorrectionActionId(suggestion.id);
    setSupervisorCorrectionError("");
    setSaveMessage("");
    try {
      const response = await remapWithSupervisorFeedback(job.id, suggestion.id);
      const revision = response?.revised_suggestion;
      if (revision) {
        setSupervisorGuidedRevisions((current) => [
          revision,
          ...current.filter((row) => row.id !== revision.id),
        ]);
      }
      setSaveMessage(
        "Revised mapping suggestion created for human review. No mapping was applied or confirmed.",
      );
      await reloadSupervisorOrchestration();
    } catch (correctionError) {
      setSupervisorCorrectionError(correctionError.message);
    } finally {
      supervisorCorrectionPendingIds.delete(suggestion.id);
      setSupervisorCorrectionActionId("");
    }
  }, [job.id, reloadSupervisorOrchestration, supervisorCorrectionPendingIds]);

  const handleAcceptAiSuggestion = useCallback(async (suggestion) => {
    setAiSuggestionActionId(suggestion.id);
    setError("");
    setSaveMessage("");

    try {
      await acceptAiMappingSuggestion(suggestion.extracted_data_item_id, suggestion.id);
      await Promise.all([
        reloadExtractedItems(),
        reloadAiSuggestions(),
        reloadSupervisorOrchestration(),
      ]);
      setSaveMessage("AI suggestion accepted. Official mapped rows updated.");
    } catch (acceptError) {
      setError(acceptError.message);
    } finally {
      setAiSuggestionActionId("");
    }
  }, [reloadAiSuggestions, reloadExtractedItems, reloadSupervisorOrchestration]);

  const handleIgnoreAiSuggestion = useCallback(async (suggestion) => {
    setAiSuggestionActionId(suggestion.id);
    setError("");
    setSaveMessage("");

    try {
      await ignoreAiMappingSuggestion(suggestion.extracted_data_item_id, suggestion.id);
      await Promise.all([
        reloadAiSuggestions(),
        reloadSupervisorOrchestration(),
      ]);
      setSaveMessage("AI suggestion rejected.");
    } catch (ignoreError) {
      setError(ignoreError.message);
    } finally {
      setAiSuggestionActionId("");
    }
  }, [reloadAiSuggestions, reloadSupervisorOrchestration]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError("");
    setSaveMessage("");

    try {
      const updates = [];
      const creates = [];
      const pendingTagAssignments = [];
      const rowTagUpdates = [];

      for (const field of statementFields) {
        const nextValue = (draftValues[field.id] || "").trim();
        const previousValue = (initialValues[field.id] || "").trim();
        const nextTagId = draftTags[field.id]?.id || null;
        const previousTagId = initialTags[field.id]?.id || null;
        const valueChanged = nextValue !== previousValue;
        const tagChanged = nextTagId !== previousTagId;

        if (!nextValue && !tagChanged) {
          continue;
        }

        if (field.sourceItems.length > 0) {
          if (!valueChanged && !tagChanged) {
            continue;
          }

          for (const item of field.sourceItems) {
            updates.push({
              id: item.id,
              extracted_value: nextValue || item.extracted_value,
              template_field_id: field.id,
              confirmed_tag_id: nextTagId,
              is_reviewed: true,
            });
          }
        } else if (nextValue && (valueChanged || tagChanged)) {
          creates.push({
            fieldId: field.id,
            template_field_id: field.id,
            extracted_label: field.label,
            extracted_value: nextValue,
            financial_year: job.financial_year_end
              ? new Date(job.financial_year_end).getFullYear()
              : new Date().getFullYear(),
            is_reviewed: true,
            statement_type: statementDetail?.description || null,
          });

          if (nextTagId) {
            pendingTagAssignments.push({
              fieldId: field.id,
              confirmed_tag_id: nextTagId,
            });
          }
        }
      }

      for (const item of extractedItems) {
        const nextTagId = draftRowTags[item.id]?.id || null;
        const previousTagId = initialRowTags[item.id]?.id || null;

        if (nextTagId === previousTagId) {
          continue;
        }

        rowTagUpdates.push({
          id: item.id,
          confirmed_tag_id: nextTagId,
          is_reviewed: true,
        });
      }

      if (updates.length === 0 && creates.length === 0 && rowTagUpdates.length === 0) {
        setSaveMessage("No review changes to save.");
        return true;
      }

      if (creates.length > 0 && pages.length === 0) {
        throw new Error("No job pages found. New review values cannot be created.");
      }

      if (updates.length > 0) {
        await bulkUpdateExtractedItems(updates);
      }

      if (rowTagUpdates.length > 0) {
        await bulkUpdateExtractedItems(rowTagUpdates);
      }

      if (creates.length > 0) {
        const firstPageId = pages[0].id;
        for (const item of creates) {
          const { fieldId, ...payload } = item;
          await createExtractedItem(firstPageId, payload);
        }
      }

      const refreshedItems = await reloadExtractedItems();

      if (pendingTagAssignments.length > 0) {
        const refreshedLookup = buildExtractedLookup(refreshedItems);
        const tagUpdates = [];

        for (const assignment of pendingTagAssignments) {
          const matchingItems =
            refreshedLookup[normalizeFieldId(assignment.fieldId)] ||
            refreshedLookup[assignment.fieldId] ||
            [];

          for (const item of matchingItems) {
            if (!item.confirmed_tag_id) {
              tagUpdates.push({
                id: item.id,
                confirmed_tag_id: assignment.confirmed_tag_id,
                template_field_id: assignment.fieldId,
                is_reviewed: true,
              });
            }
          }
        }

        if (tagUpdates.length > 0) {
          await bulkUpdateExtractedItems(tagUpdates);
          await reloadExtractedItems();
        }
      }

      setSaveMessage(
        `Saved ${updates.length + creates.length + rowTagUpdates.length} review change${updates.length + creates.length + rowTagUpdates.length === 1 ? "" : "s"}.`,
      );
      return true;
    } catch (saveError) {
      setError(saveError.message);
      return false;
    } finally {
      setSaving(false);
    }
  }, [
    draftRowTags,
    draftValues,
    initialValues,
    draftTags,
    initialRowTags,
    initialTags,
    extractedItems,
    job.financial_year_end,
    job.id,
    pages,
    reloadExtractedItems,
    statementDetail?.description,
    statementFields,
  ]);

  useEffect(() => {
    if (!onStateChange) {
      return undefined;
    }

    onStateChange({
      dirtyCount,
      saving,
      loading: loadingBase || loadingStatement || loadingAiSuggestions,
      saveChanges: handleSave,
    });

    return () => {
      onStateChange(null);
    };
  }, [
    dirtyCount,
    handleSave,
    loadingAiSuggestions,
    loadingBase,
    loadingStatement,
    onStateChange,
    saving,
  ]);

  if (job.status === "PROCESSING") {
    return (
      <section className="panel p-6">
        <div className="flex items-start gap-4">
          <div className="flex h-10 w-10 flex-none items-center justify-center rounded-lg bg-brand-50 text-brand-600 dark:bg-brand-400/10 dark:text-brand-200">
            <LoaderCircle className="h-5 w-5 animate-spin" />
          </div>
          <div className="min-w-0">
            <h3 className="text-lg font-semibold text-slate-950 dark:text-white">
              Processing filing
            </h3>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-400">
              Review fields will appear as soon as extraction completes.
            </p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <div className="min-w-0 max-w-full space-y-5">
      <section className="panel min-w-0 p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <FileSpreadsheet className="h-5 w-5 text-brand-600 dark:text-brand-300" />
              <h3 className="text-lg font-semibold text-slate-950 dark:text-white">
                Review workspace
              </h3>
            </div>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-400">
              Review statement values and taxonomy tags before validation.
            </p>
          </div>
          <div className="flex w-full flex-wrap items-center gap-3 sm:w-auto">
            <div className="metric-pill flex-1 justify-center px-3 py-2 text-sm sm:flex-none">
              {statementFields.length} fields in current statement
            </div>
            <button
              type="button"
              onClick={handleSave}
              className="button-primary flex-1 sm:flex-none"
              disabled={saving || loadingBase || loadingStatement}
            >
              {saving ? (
                <>
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  Saving
                </>
              ) : (
                <>
                  <Save className="h-4 w-4" />
                  Save changes
                </>
              )}
            </button>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
          {loadingBase ? (
            <span className="metric-pill">
              <LoaderCircle className="mr-1 h-3.5 w-3.5 animate-spin" />
              Loading extracted results...
            </span>
          ) : (
            <>
              <span className="metric-pill">
                {templates.length} statements loaded
              </span>
              <span className="metric-pill">
                {extractedItems.length} extracted rows loaded
              </span>
              <span className="metric-pill">
                {templateBackedRowCount} template-backed rows
              </span>
              <span className="metric-pill">
                {unassignedItems.length} unassigned rows
              </span>
            </>
          )}
          <span className="metric-pill">
            {dirtyCount} unsaved field change{dirtyCount === 1 ? "" : "s"}
          </span>
          {!taxonomyReady && (
            <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-500 dark:border-white/10 dark:bg-white/[0.045] dark:text-slate-400">
              Taxonomy unavailable
            </span>
          )}
        </div>

        {error && (
          <div className="mt-5 flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
            <AlertCircle className="mt-0.5 h-4 w-4" />
            <span>{error}</span>
          </div>
        )}

        {saveMessage && (
          <div className="mt-5 flex items-start gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
            <CheckCircle2 className="mt-0.5 h-4 w-4" />
            <span>{saveMessage}</span>
          </div>
        )}

        <div className="mt-6 min-w-0 max-w-full overflow-hidden">
          <div className="tf-horizontal-scrollbar max-w-full overflow-x-auto overscroll-x-contain pb-3">
            <div className="flex w-max max-w-none gap-3 pr-3">
              {statementOptions.map((statement) => (
                <StatementTabButton
                  key={statement.code}
                  statement={statement}
                  active={statement.code === selectedStatementCode}
                  onSelect={setSelectedStatementCode}
                />
              ))}
            </div>
          </div>
        </div>
      </section>

      {SHOW_AI_SUGGESTION_PANEL ? (
        <AiMappingSuggestionsPanel
          suggestions={aiSuggestions}
          status={aiMappingStatus}
          loading={loadingAiSuggestions}
          supervisorReviews={supervisorReviews}
          loadingSupervisorReviews={loadingSupervisorReviews}
          supervisorReviewError={supervisorReviewError}
          supervisorActionId={supervisorReviewActionId}
          supervisorBatchRunning={supervisorBatchRunning}
          supervisorGuidedRevisions={supervisorGuidedRevisions}
          supervisorMapperFeedbackCapabilities={supervisorMapperFeedbackCapabilities}
          supervisorCorrectionActionId={supervisorCorrectionActionId}
          supervisorCorrectionError={supervisorCorrectionError}
          showSupervisorLiveControls={SHOW_SUPERVISOR_LIVE_CONTROLS}
          showSupervisorMapperFeedback={SHOW_SUPERVISOR_MAPPER_FEEDBACK}
          showSupervisorOrchestrationQueue={SHOW_SUPERVISOR_ORCHESTRATION_QUEUE}
          supervisorOrchestrationCapabilities={supervisorOrchestrationCapabilities}
          supervisorOrchestrationPlan={supervisorOrchestrationPlan}
          loadingSupervisorOrchestration={loadingSupervisorOrchestration}
          supervisorOrchestrationError={supervisorOrchestrationError}
          checkingPostCompletionSuggestions={checkingPostCompletionSuggestions}
          postCompletionSuggestionGraceExpired={postCompletionAiPollingExpired}
          actionBusyId={aiSuggestionActionId}
          onAccept={handleAcceptAiSuggestion}
          onIgnore={handleIgnoreAiSuggestion}
          onRunSupervisorReview={handleRunSupervisorReview}
          onRunBatchSupervisorReviews={handleRunBatchSupervisorReviews}
          onRemapWithSupervisorFeedback={handleRemapWithSupervisorFeedback}
          onRefreshSupervisorOrchestration={reloadSupervisorOrchestration}
        />
      ) : null}

      {SHOW_RANKED_CANDIDATE_TEST_PANEL ? (
        <RankedCandidateTestPanel jobId={job.id} />
      ) : null}

      <section className="panel min-w-0 p-4 sm:p-6">
        {loadingBase || loadingStatement ? (
          <div className="flex items-center justify-center py-16 text-sm text-slate-500 dark:text-slate-400">
            <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
            Loading review data
          </div>
        ) : selectedStatementCode === UNASSIGNED_STATEMENT_CODE ? (
          <div className="space-y-5">
            <CollapsibleExtractedItemList
              title={UNASSIGNED_STATEMENT_LABEL}
              description="These rows could not be mapped to a template statement from template_field_id or statement_type, so they are surfaced here instead of being dropped."
              items={groupedItemsForSelectedStatement}
              defaultOpen
              badgeTone="amber"
              taxonomyReady={taxonomyReady}
              selectedTagsByItem={draftRowTags}
              onSelectTag={handleRowTagSelect}
              onClearTag={handleRowTagClear}
            />
          </div>
        ) : !statementDetail ? (
          groupedItemsForSelectedStatement.length > 0 ? (
            <div className="space-y-5">
              <CollapsibleExtractedItemList
                title="Additional extracted rows"
                description="This statement currently has extracted rows but no template-backed field layout available in the React review pane."
                items={groupedItemsForSelectedStatement}
                defaultOpen
                taxonomyReady={taxonomyReady}
                selectedTagsByItem={draftRowTags}
                onSelectTag={handleRowTagSelect}
                onClearTag={handleRowTagClear}
              />
              {selectedStatementCode !== UNASSIGNED_STATEMENT_CODE &&
              unassignedItems.length > 0 ? (
                <CollapsibleExtractedItemList
                  title={UNASSIGNED_STATEMENT_LABEL}
                  description="Rows without a template_field_id or reliable statement mapping are always surfaced here."
                  items={unassignedItems}
                  badgeTone="amber"
                  taxonomyReady={taxonomyReady}
                  selectedTagsByItem={draftRowTags}
                  onSelectTag={handleRowTagSelect}
                  onClearTag={handleRowTagClear}
                />
              ) : null}
            </div>
          ) : extractedItems.length > 0 && unassignedItems.length > 0 ? (
            <div className="space-y-5">
              <CollapsibleExtractedItemList
                title={UNASSIGNED_STATEMENT_LABEL}
                description="Rows without a template_field_id or reliable statement mapping are always surfaced here."
                items={unassignedItems}
                defaultOpen
                badgeTone="amber"
                taxonomyReady={taxonomyReady}
                selectedTagsByItem={draftRowTags}
                onSelectTag={handleRowTagSelect}
                onClearTag={handleRowTagClear}
              />
            </div>
          ) : (
          <div className="rounded-lg border border-dashed border-slate-300/80 bg-slate-50/70 px-4 py-12 text-center text-sm text-slate-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-400">
            No statement template available for this job.
          </div>
          )
        ) : (
          <div className="space-y-5">
            <div className="space-y-4 border-b border-slate-200/70 pb-5 dark:border-white/10">
              <div>
                <p className="eyebrow">
                  Statement {statementDetail.code}
                </p>
                <h4 className="mt-2 text-xl font-semibold tracking-tight text-slate-950 dark:text-white sm:text-2xl">
                  {statementDetail.description}
                </h4>
                <p className="mt-2 text-sm text-slate-500 dark:text-slate-500">
                  Editable line items are grouped by statement for review.
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                <span className="metric-pill">
                  {statementFields.length} template fields
                </span>
                <span className="metric-pill">
                  {additionalGroupedItems.length} additional rows
                </span>
                <span className="metric-pill">
                  {unassignedItems.length} unmapped rows
                </span>
              </div>
            </div>

            <section className="space-y-3">
              <SectionHeader
                title="Template-backed fields"
                description="These fields stay editable and remain the primary review surface for the selected statement."
                count={`${statementFields.length} fields`}
                tone="brand"
              />

              {statementFields.map((field) => (
                <FieldCard
                  key={field.id}
                  field={field}
                  value={draftValues[field.id] ?? ""}
                  onChange={handleFieldChange}
                />
              ))}
            </section>

            <CollapsibleExtractedItemList
              title="Additional extracted rows"
              description="These rows belong to this statement after template-field mapping, but do not line up with a rendered template concept in the current React form."
              items={additionalGroupedItems}
              defaultOpen={statementFields.length === 0 && additionalGroupedItems.length > 0}
              taxonomyReady={taxonomyReady}
              selectedTagsByItem={draftRowTags}
              onSelectTag={handleRowTagSelect}
              onClearTag={handleRowTagClear}
            />

            {selectedStatementCode !== UNASSIGNED_STATEMENT_CODE &&
            unassignedItems.length > 0 ? (
              <CollapsibleExtractedItemList
                title={UNASSIGNED_STATEMENT_LABEL}
                description="Rows without a template_field_id or reliable statement mapping are always surfaced here."
                items={unassignedItems}
                badgeTone="amber"
                taxonomyReady={taxonomyReady}
                selectedTagsByItem={draftRowTags}
                onSelectTag={handleRowTagSelect}
                onClearTag={handleRowTagClear}
              />
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}
