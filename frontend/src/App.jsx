import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  FileUp,
  LogIn,
  LogOut,
  LoaderCircle,
  Menu,
  Moon,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sun,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import {
  clearStoredAuthToken,
  deleteFilingJob,
  downloadXbrlPackage,
  fetchDashboardStats,
  fetchCurrentUser,
  fetchJob,
  fetchJobs,
  fetchJobStatus,
  getStoredAuthToken,
  loginUser,
  logoutUser,
  uploadJob,
  validateXbrl,
} from "./api";
import { AdminUserManagement } from "./admin-user-management";
import { ReviewWorkspace } from "./review-workspace";

const STATUS_STYLES = {
  PROCESSING:
    "border-amber-300/60 bg-amber-50 text-amber-700 dark:border-amber-400/30 dark:bg-amber-400/10 dark:text-amber-200",
  REVIEW: "border-brand-300/60 bg-brand-50 text-brand-700 dark:border-brand-400/30 dark:bg-brand-400/10 dark:text-brand-200",
  COMPLETED:
    "border-emerald-300/60 bg-emerald-50 text-emerald-700 dark:border-emerald-400/30 dark:bg-emerald-400/10 dark:text-emerald-200",
  ERROR: "border-rose-300/60 bg-rose-50 text-rose-700 dark:border-rose-400/30 dark:bg-rose-400/10 dark:text-rose-200",
};

const DEFAULT_UPLOAD_FORM = {
  company_name: "",
  registration_number: "",
  financial_year_end: "",
  xbrl_format: "FS-MPERS",
  file: null,
};

const XBRL_FORMAT_OPTIONS = [
  {
    value: "FS-MPERS",
    label: "FS-MPERS",
  },
];

const TERMINAL_JOB_STATUSES = new Set(["REVIEW", "COMPLETED", "ERROR"]);

function isTerminalJobStatus(status) {
  return TERMINAL_JOB_STATUSES.has(status);
}

const MONTH_LABELS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

const DATE_PICKER_START_YEAR = 1990;
const DATE_PICKER_END_YEAR = 2035;
const DATE_PICKER_YEAR_OPTIONS = Array.from(
  { length: DATE_PICKER_END_YEAR - DATE_PICKER_START_YEAR + 1 },
  (_, index) => DATE_PICKER_START_YEAR + index,
);

function formatDate(value) {
  if (!value) {
    return "Not set";
  }

  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatDateTime(value) {
  if (!value) {
    return "Unknown";
  }

  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function parseLocalDate(value) {
  if (!value) {
    return null;
  }

  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) {
    return null;
  }

  return new Date(year, month - 1, day);
}

function toDateInputValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDateDisplayValue(value) {
  const date = parseLocalDate(value);
  if (!date) {
    return "";
  }

  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const year = String(date.getFullYear());
  return `${month}/${day}/${year}`;
}

function maskDateDisplayValue(value) {
  const digits = value.replace(/\D/g, "").slice(0, 8);
  if (digits.length <= 2) {
    return digits;
  }

  if (digits.length <= 4) {
    return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  }

  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}

function parseDateDisplayValue(value) {
  const match = value.trim().match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!match) {
    return null;
  }

  const month = Number(match[1]);
  const day = Number(match[2]);
  const year = Number(match[3]);
  if (year < DATE_PICKER_START_YEAR || year > DATE_PICKER_END_YEAR) {
    return null;
  }

  const date = new Date(year, month - 1, day);

  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }

  return date;
}

function getDateDisplayError(value) {
  if (!value.trim()) {
    return "Financial year end is required.";
  }

  if (value.length < 10) {
    return "Enter a complete date as mm/dd/yyyy.";
  }

  if (!parseDateDisplayValue(value)) {
    return `Enter a valid date from ${DATE_PICKER_START_YEAR} to ${DATE_PICKER_END_YEAR}.`;
  }

  return "";
}

function isSameCalendarDay(left, right) {
  return (
    left &&
    right &&
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  );
}

function getCalendarWeeks(monthDate) {
  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const firstOfMonth = new Date(year, month, 1);
  const start = new Date(year, month, 1 - firstOfMonth.getDay());

  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
}

function StatusBadge({ status }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${STATUS_STYLES[status] || "border-slate-200 bg-slate-100 text-slate-700 dark:border-white/10 dark:bg-white/[0.06] dark:text-slate-200"}`}
    >
      {status || "UNKNOWN"}
    </span>
  );
}

export function deriveReadinessState(validation, dirtyCount = 0) {
  if (validation && dirtyCount > 0) {
    return "stale";
  }

  if (!validation) {
    return "not_run";
  }

  if (validation.errors?.length > 0) {
    return "failed";
  }

  if (validation.warnings?.length > 0 || validation.missing_required_fields?.length > 0) {
    return "warnings";
  }

  return "passed";
}

export function requiresDownloadConfirmation(readinessState) {
  return ["not_run", "warnings", "failed", "stale"].includes(readinessState);
}

function readinessLabel(readinessState) {
  const labels = {
    not_run: "Not run",
    stale: "Stale",
    failed: "Failed",
    warnings: "Warnings",
    passed: "Passed",
  };
  return labels[readinessState] || "Not run";
}

function ValidationStatusPill({ readinessState }) {
  if (readinessState === "not_run") {
    return (
      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
        Readiness not run
      </span>
    );
  }

  if (readinessState === "passed") {
    return (
      <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
        Readiness passed
      </span>
    );
  }

  if (readinessState === "failed") {
    return (
      <span className="rounded-full bg-rose-100 px-2.5 py-1 text-xs font-semibold text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
        Readiness failed
      </span>
    );
  }

  return (
    <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
      {readinessState === "stale" ? "Readiness stale" : "Readiness warnings"}
    </span>
  );
}

function getDownloadPrompt(readinessState) {
  if (readinessState === "failed") {
    return {
      title: "Download despite validation issues?",
      body: "Readiness validation has not passed. This XBRL package may not be submission-ready. You can still download it for internal review.",
      primaryLabel: "Download anyway",
      secondaryLabel: "Review validation issues",
      secondaryAction: "review",
    };
  }

  if (readinessState === "warnings") {
    return {
      title: "Download with warnings?",
      body: "Readiness validation completed with warnings. This does not prove full MBRS/FS-MPERS submission validity. Do you want to download it for internal review?",
      primaryLabel: "Download anyway",
      secondaryLabel: "Review warnings",
      secondaryAction: "review",
    };
  }

  if (readinessState === "stale") {
    return {
      title: "Download unvalidated changes?",
      body: "The current review state has changed since the last validation. Downloading now may export unvalidated changes.",
      primaryLabel: "Continue download",
      secondaryLabel: "Cancel and run validation",
      secondaryAction: "validate",
    };
  }

  return {
    title: "Download without validation?",
    body: "This XBRL package has not been validated yet. It may contain mapping, required-field, or format issues. You can still download it for internal review.",
    primaryLabel: "Continue download",
    secondaryLabel: "Cancel and run validation",
    secondaryAction: "validate",
  };
}

function triggerBrowserDownload(blob, filename) {
  const blobUrl = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(blobUrl);
}

function TensorFlowLogoMark({ className = "h-10 w-10" }) {
  return (
    // User-requested prototype logo; review TensorFlow trademark/branding rights before production use.
    <svg viewBox="0 0 256 256" role="img" aria-label="TensorFlow logo" className={`${className} flex-none`}>
      <path
        fill="#ff6f00"
        d="M128 20 44 68v42l47-27v95l37 21z"
      />
      <path
        fill="#ff8f00"
        d="m128 20 84 48v42l-47-27v95l-37 21z"
      />
      <path
        fill="#ffa000"
        d="M91 83v42l37 21 37-21V83l-37 21z"
      />
      <path
        fill="#ff6f00"
        d="M91 125v42l37 21v-42z"
      />
      <path
        fill="#ff8f00"
        d="M165 125v42l-37 21v-42z"
      />
    </svg>
  );
}

function XbrlActionsPanel({ job, reviewState }) {
  const [validation, setValidation] = useState(null);
  const [validating, setValidating] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadPrompt, setDownloadPrompt] = useState(null);
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState("success");
  const [error, setError] = useState("");
  const readinessState = deriveReadinessState(validation, reviewState?.dirtyCount ?? 0);

  useEffect(() => {
    setValidation(null);
    setDownloadPrompt(null);
    setMessage("");
    setMessageTone("success");
    setError("");
  }, [job.id]);

  async function ensureReviewSaved() {
    if (!reviewState?.saveChanges || !reviewState?.dirtyCount) {
      return;
    }

    const saved = await reviewState.saveChanges();
    if (!saved) {
      throw new Error("Review changes could not be saved. Resolve the review errors first.");
    }
  }

  async function handleValidate() {
    setValidating(true);
    setError("");
    setMessage("");
    setMessageTone("success");

    try {
      await ensureReviewSaved();
      const result = await validateXbrl(job.id);
      setValidation(result);

      if (result.errors?.length > 0) {
        setMessage("Readiness validation found blocking issues. Review the errors below.");
        setMessageTone("error");
      } else if (result.warnings?.length > 0 || result.missing_required_fields?.length > 0) {
        setMessage("Readiness validation completed with warnings. Review the warnings below.");
        setMessageTone("warning");
      } else {
        setMessage("Readiness validation passed. Full Arelle/MBRS validation is not yet integrated.");
        setMessageTone("success");
      }
    } catch (validationError) {
      setError(validationError.message);
    } finally {
      setValidating(false);
    }
  }

  async function performDownload() {
    setDownloading(true);
    setError("");
    setMessage("");
    setMessageTone("success");

    try {
      await ensureReviewSaved();
      const blob = await downloadXbrlPackage(job.id);
      const safeCompany = (job.company_name || "taxonomyflow")
        .replace(/\s+/g, "_")
        .replace(/[^A-Za-z0-9._-]/g, "");
      triggerBrowserDownload(blob, `${safeCompany}_MBRS.zip`);
      setMessage("XBRL package downloaded for internal review. Submission-readiness is not proven.");
      setMessageTone("success");
    } catch (downloadError) {
      setError(downloadError.message);
    } finally {
      setDownloading(false);
    }
  }

  function handleDownload() {
    setError("");
    setMessage("");
    setMessageTone("success");

    if (requiresDownloadConfirmation(readinessState)) {
      setDownloadPrompt(getDownloadPrompt(readinessState));
      return;
    }

    performDownload();
  }

  function handleDownloadPromptSecondary() {
    const action = downloadPrompt?.secondaryAction;
    setDownloadPrompt(null);

    if (action === "validate") {
      handleValidate();
    }
  }

  return (
    <div className="panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="eyebrow">Export control</p>
          <h3 className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">
            Validate package
          </h3>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-400">
            Save review edits, run readiness checks, then export the XBRL package.
          </p>
        </div>
        <ValidationStatusPill readinessState={readinessState} />
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          onClick={handleValidate}
          disabled={validating || downloading || job.status === "PROCESSING" || reviewState?.loading || reviewState?.saving}
          className="button-secondary"
        >
          {validating ? (
            <>
              <LoaderCircle className="h-4 w-4 animate-spin" />
              Validating
            </>
          ) : (
            <>
              <CheckCircle2 className="h-4 w-4" />
              Run validation
            </>
          )}
        </button>
        <button
          type="button"
          onClick={handleDownload}
          disabled={downloading || validating || job.status === "PROCESSING" || reviewState?.loading || reviewState?.saving}
          className="button-primary"
        >
          {downloading ? (
            <>
              <LoaderCircle className="h-4 w-4 animate-spin" />
              Downloading
            </>
          ) : (
            <>
              <Download className="h-4 w-4" />
              Download XBRL
            </>
          )}
        </button>
      </div>
      <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
        Internal export. Full Arelle/MBRS validation is not yet integrated.
      </p>

      {reviewState?.dirtyCount > 0 && (
        <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200">
          {reviewState.dirtyCount} unsaved review field{reviewState.dirtyCount === 1 ? "" : "s"} will be saved automatically before validation or download.
        </div>
      )}

      {message && (
        <div
          className={`mt-5 flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${messageTone === "error"
            ? "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200"
            : messageTone === "warning"
              ? "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200"
              : "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200"
            }`}
        >
          {messageTone === "success" ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4" />
          ) : (
            <TriangleAlert className="mt-0.5 h-4 w-4" />
          )}
          <span>{message}</span>
        </div>
      )}

      {error && (
        <div className="mt-5 flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
          <AlertCircle className="mt-0.5 h-4 w-4" />
          <span>{error}</span>
        </div>
      )}

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <div className="stat-card">
          <p className="text-sm text-slate-500 dark:text-slate-400">Readiness check</p>
          <p className="mt-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
            {readinessLabel(readinessState)}
          </p>
        </div>
        <div className="stat-card">
          <p className="text-sm text-slate-500 dark:text-slate-400">Arelle validation</p>
          <p className="mt-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
            Not run
          </p>
        </div>
        <div className="stat-card">
          <p className="text-sm text-slate-500 dark:text-slate-400">Submission-ready</p>
          <p className="mt-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
            Not proven
          </p>
        </div>
      </div>

      {validation && (
        <div className="mt-5 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="stat-card">
              <p className="text-sm text-slate-500 dark:text-slate-400">Reviewed mappable rows</p>
              <p className="mt-2 text-xl font-semibold text-slate-900 dark:text-slate-100">
                {validation.statistics?.reviewed_mappable_items ?? 0} / {validation.statistics?.total_items ?? 0}
              </p>
            </div>
            <div className="stat-card">
              <p className="text-sm text-slate-500 dark:text-slate-400">Missing required fields</p>
              <p className="mt-2 text-xl font-semibold text-slate-900 dark:text-slate-100">
                {validation.statistics?.missing_required_fields_count ?? validation.missing_required_fields?.length ?? 0}
              </p>
            </div>
          </div>

          {validation.errors?.length > 0 && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 dark:border-rose-500/30 dark:bg-rose-500/10">
              <div className="flex items-center gap-2 text-sm font-semibold text-rose-700 dark:text-rose-300">
                <TriangleAlert className="h-4 w-4" />
                Errors
              </div>
              <ul className="mt-3 space-y-2 text-sm text-rose-700 dark:text-rose-300">
                {validation.errors.map((item) => (
                  <li key={item}>- {item}</li>
                ))}
              </ul>
            </div>
          )}

          {validation.warnings?.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
              <div className="flex items-center gap-2 text-sm font-semibold text-amber-700 dark:text-amber-300">
                <TriangleAlert className="h-4 w-4" />
                Warnings
              </div>
              <ul className="mt-3 space-y-2 text-sm text-amber-700 dark:text-amber-300">
                {validation.warnings.map((item) => (
                  <li key={item}>- {item}</li>
                ))}
              </ul>
            </div>
          )}

          {validation.missing_required_fields?.length > 0 && (
            <div className="soft-card p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
                <AlertCircle className="h-4 w-4 text-rose-500" />
                Missing required fields
              </div>
              <div className="mt-3 space-y-2">
                {validation.missing_required_fields.slice(0, 8).map((field) => (
                  <div
                    key={`${field.statement_code}-${field.field_id}`}
                    className="rounded-lg border border-slate-200/70 bg-slate-50 px-3 py-3 text-sm dark:border-white/10 dark:bg-white/[0.035]"
                  >
                    <p className="font-medium text-slate-900 dark:text-slate-100">
                      {field.label}
                    </p>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {field.statement_type} | {field.statement_code} | {field.field_id}
                    </p>
                  </div>
                ))}
                {validation.missing_required_fields.length > 8 && (
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Showing first 8 of {validation.missing_required_fields.length} missing required fields.
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {downloadPrompt && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/70 px-4 py-6 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-white/10 dark:bg-slate-950">
            <div className="flex items-start gap-3">
              <div className="rounded-lg bg-amber-100 p-2 text-amber-700 dark:bg-amber-400/10 dark:text-amber-300">
                <TriangleAlert className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h4 className="text-base font-semibold text-slate-950 dark:text-white">
                  {downloadPrompt.title}
                </h4>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {downloadPrompt.body}
                </p>
              </div>
            </div>
            <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <button
                type="button"
                className="button-secondary"
                onClick={handleDownloadPromptSecondary}
                disabled={downloading || validating}
              >
                {downloadPrompt.secondaryLabel}
              </button>
              <button
                type="button"
                className="button-primary"
                onClick={() => {
                  setDownloadPrompt(null);
                  performDownload();
                }}
                disabled={downloading || validating}
              >
                {downloadPrompt.primaryLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SidebarJobRow({ job, collapsed, active, onSelect, onRequestDelete }) {
  const taskIdLabel = `Task ID: ${job.id}`;
  const taskIdTitle = "Backend task id used by benchmark scripts";

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => onSelect(job.id)}
        className={`relative mx-auto flex h-11 w-11 items-center justify-center rounded-lg border text-sm font-semibold transition ${active
          ? "border-brand-300 bg-brand-50 text-brand-800 shadow-panel dark:border-brand-400/35 dark:bg-brand-400/10 dark:text-brand-100"
          : "border-transparent bg-transparent text-slate-600 hover:border-slate-200/80 hover:bg-white/70 dark:text-slate-300 dark:hover:border-white/10 dark:hover:bg-white/[0.055]"
          }`}
        title={`${taskIdLabel} - ${job.company_name || "Untitled filing"}`}
        aria-label={`${taskIdLabel} ${job.company_name || "Untitled filing"}`}
      >
        <span aria-hidden="true">{(job.company_name || "J").trim().slice(0, 1).toUpperCase()}</span>
        <span className="sr-only">{taskIdLabel}</span>
        <span
          className={`absolute right-2 top-2 h-2 w-2 rounded-full ${job.status === "ERROR"
            ? "bg-rose-400"
            : job.status === "PROCESSING"
              ? "bg-amber-400"
              : job.status === "COMPLETED"
                ? "bg-emerald-400"
                : "bg-brand-400"
            }`}
          aria-hidden="true"
        />
      </button>
    );
  }

  return (
    <div
      className={`group flex w-full items-stretch rounded-lg border transition ${active
        ? "border-brand-200 bg-brand-50 shadow-panel dark:border-brand-400/30 dark:bg-brand-400/10"
        : "border-transparent bg-transparent hover:border-slate-200/80 hover:bg-white/70 dark:hover:border-white/10 dark:hover:bg-white/[0.055]"
        }`}
    >
      <button
        type="button"
        onClick={() => onSelect(job.id)}
        className="min-w-0 flex-1 px-3 py-3 text-left"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
              {job.company_name}
            </p>
            <p
              className="mt-1 text-xs font-semibold text-brand-700 dark:text-brand-300"
              title={taskIdTitle}
            >
              {taskIdLabel}
            </p>
            <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">
              {job.registration_number || "Registration number not provided"}
            </p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              FYE {formatDate(job.financial_year_end)}
            </p>
          </div>
          <StatusBadge status={job.status} />
        </div>
      </button>
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onRequestDelete(job);
        }}
        className="my-2 mr-2 inline-flex h-9 w-9 flex-none items-center justify-center rounded-lg text-slate-400 transition hover:bg-rose-50 hover:text-rose-600 focus:outline-none focus:ring-2 focus:ring-rose-100 dark:text-slate-500 dark:hover:bg-rose-500/10 dark:hover:text-rose-300 dark:focus:ring-rose-500/30"
        title={`Delete ${taskIdLabel}`}
        aria-label={`Delete ${taskIdLabel} ${job.company_name || ""}`.trim()}
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  );
}

function UploadModal({
  open,
  form,
  submitting,
  error,
  onClose,
  onChange,
  onFileChange,
  onSubmit,
}) {
  const [formatMenuOpen, setFormatMenuOpen] = useState(false);
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  const [monthMenuOpen, setMonthMenuOpen] = useState(false);
  const [yearMenuOpen, setYearMenuOpen] = useState(false);
  const [dateDisplayValue, setDateDisplayValue] = useState(() =>
    formatDateDisplayValue(form.financial_year_end)
  );
  const [dateInputError, setDateInputError] = useState("");
  const selectedDate = parseLocalDate(form.financial_year_end);
  const [visibleMonth, setVisibleMonth] = useState(() => selectedDate || new Date());
  const formatMenuRef = useRef(null);
  const datePickerRef = useRef(null);
  const selectedFormat =
    XBRL_FORMAT_OPTIONS.find((option) => option.value === form.xbrl_format) ||
    XBRL_FORMAT_OPTIONS[0];
  const today = new Date();
  const calendarDays = getCalendarWeeks(visibleMonth);

  useEffect(() => {
    setDateDisplayValue(formatDateDisplayValue(form.financial_year_end));
    setDateInputError("");

    if (selectedDate) {
      setVisibleMonth(new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1));
    }
  }, [form.financial_year_end]);

  useEffect(() => {
    if (!formatMenuOpen) {
      return undefined;
    }

    function handlePointerDown(event) {
      if (formatMenuRef.current && !formatMenuRef.current.contains(event.target)) {
        setFormatMenuOpen(false);
      }
    }

    function handleKeyDown(event) {
      if (event.key === "Escape") {
        setFormatMenuOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [formatMenuOpen]);

  useEffect(() => {
    if (!datePickerOpen) {
      setMonthMenuOpen(false);
      setYearMenuOpen(false);
      return undefined;
    }

    function handlePointerDown(event) {
      if (datePickerRef.current && !datePickerRef.current.contains(event.target)) {
        setMonthMenuOpen(false);
        setYearMenuOpen(false);
        setDatePickerOpen(false);
      }
    }

    function handleKeyDown(event) {
      if (event.key === "Escape") {
        setMonthMenuOpen(false);
        setYearMenuOpen(false);
        setDatePickerOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [datePickerOpen]);

  function handleSelectDate(date) {
    const value = toDateInputValue(date);

    onChange({
      target: {
        name: "financial_year_end",
        value,
      },
    });
    setDateDisplayValue(formatDateDisplayValue(value));
    setDateInputError("");
    setMonthMenuOpen(false);
    setYearMenuOpen(false);
    setDatePickerOpen(false);
  }

  function handleDateInputChange(event) {
    const nextValue = maskDateDisplayValue(event.target.value);
    setDateDisplayValue(nextValue);

    if (!nextValue.trim()) {
      onChange({
        target: {
          name: "financial_year_end",
          value: "",
        },
      });
      setDateInputError("");
      return;
    }

    const parsedDate = parseDateDisplayValue(nextValue);
    if (!parsedDate) {
      if (nextValue.length === 10) {
        setDateInputError(getDateDisplayError(nextValue));
      } else {
        setDateInputError("");
      }
      return;
    }

    const value = toDateInputValue(parsedDate);
    onChange({
      target: {
        name: "financial_year_end",
        value,
      },
    });
    setDateInputError("");
    setVisibleMonth(new Date(parsedDate.getFullYear(), parsedDate.getMonth(), 1));
  }

  function handleDateInputBlur() {
    const parsedDate = parseDateDisplayValue(dateDisplayValue);
    if (parsedDate) {
      setDateDisplayValue(formatDateDisplayValue(toDateInputValue(parsedDate)));
      setDateInputError("");
    } else if (dateDisplayValue.trim()) {
      setDateInputError(getDateDisplayError(dateDisplayValue));
    }
  }

  function moveVisibleMonth(offset) {
    setMonthMenuOpen(false);
    setYearMenuOpen(false);
    setVisibleMonth((current) => {
      const nextMonth = new Date(current.getFullYear(), current.getMonth() + offset, 1);
      if (
        nextMonth.getFullYear() < DATE_PICKER_START_YEAR ||
        nextMonth.getFullYear() > DATE_PICKER_END_YEAR
      ) {
        return current;
      }

      return nextMonth;
    });
  }

  function handleSelectVisibleMonth(month) {
    setVisibleMonth((current) => new Date(current.getFullYear(), month, 1));
    setMonthMenuOpen(false);
  }

  function handleSelectVisibleYear(year) {
    setVisibleMonth((current) => new Date(year, current.getMonth(), 1));
    setYearMenuOpen(false);
  }

  function handleSubmit(event) {
    const validationMessage = getDateDisplayError(dateDisplayValue);
    if (validationMessage) {
      event.preventDefault();
      setDateInputError(validationMessage);
      return;
    }

    onSubmit(event);
  }

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-slate-950/75 p-4 backdrop-blur-sm">
      <div className="panel w-full max-w-2xl overflow-hidden">
        <div className="border-b border-slate-200/70 bg-slate-50/70 px-6 py-5 dark:border-white/10 dark:bg-white/[0.035]">
          <div>
            <p className="eyebrow">New filing</p>
            <h2 className="mt-1 text-xl font-semibold text-slate-950 dark:text-white">
              Upload financial statements
            </h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Create a review task from a PDF source file.
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="grid gap-5 px-6 py-6 md:grid-cols-2">
          <div className="md:col-span-2">
            <label htmlFor="company_name" className="field-label">
              Company name
            </label>
            <input
              id="company_name"
              name="company_name"
              required
              value={form.company_name}
              onChange={onChange}
              className="input-base"
              placeholder="ABC Company Sdn Bhd"
            />
          </div>

          <div>
            <label htmlFor="registration_number" className="field-label">
              Registration number
            </label>
            <input
              id="registration_number"
              name="registration_number"
              value={form.registration_number}
              onChange={onChange}
              className="input-base"
              placeholder="202401000123"
            />
          </div>

          <div>
            <label htmlFor="financial_year_end" className="field-label">
              Financial year end
            </label>
            <div ref={datePickerRef} className="relative">
              <input
                id="financial_year_end"
                name="financial_year_end_display"
                required
                inputMode="numeric"
                pattern="[0-9]{2}/[0-9]{2}/[0-9]{4}"
                title="Use mm/dd/yyyy"
                aria-haspopup="dialog"
                aria-expanded={datePickerOpen}
                aria-invalid={Boolean(dateInputError)}
                aria-describedby={dateInputError ? "financial_year_end_error" : undefined}
                onClick={() => setDatePickerOpen(true)}
                onFocus={() => setDatePickerOpen(true)}
                onChange={handleDateInputChange}
                onBlur={handleDateInputBlur}
                value={dateDisplayValue}
                placeholder="mm/dd/yyyy"
                className={`input-base h-11 pr-10 font-semibold ${dateInputError ? "border-rose-400 focus:border-rose-500 focus:ring-rose-100 dark:border-rose-400/50 dark:focus:ring-rose-500/20" : ""}`}
              />
              <CalendarDays
                className="pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500 dark:text-slate-400"
                aria-hidden="true"
              />
              <div
                role="dialog"
                aria-label="Choose financial year end"
                className={`absolute bottom-full right-0 z-[2200] mb-1 w-[17rem] rounded-xl border border-slate-200/80 bg-white p-2 shadow-premium transition dark:border-white/10 dark:bg-slate-950 ${datePickerOpen
                  ? "visible translate-y-0 opacity-100"
                  : "invisible translate-y-1 opacity-0"
                  }`}
              >
                <div className="flex items-center justify-between gap-1 rounded-lg border border-slate-200/70 bg-slate-50/80 px-1 py-1 dark:border-white/10 dark:bg-white/[0.045]">
                  <button
                    type="button"
                    onClick={() => moveVisibleMonth(-1)}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-600 transition hover:bg-white hover:text-slate-950 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:text-slate-300 dark:hover:bg-white/[0.08] dark:hover:text-white dark:focus:ring-brand-500/30"
                    aria-label="Previous month"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </button>
                  <div className="flex min-w-0 flex-1 items-center gap-1">
                    <div className="relative min-w-0 flex-1">
                      <button
                        type="button"
                        aria-haspopup="listbox"
                        aria-expanded={monthMenuOpen}
                        aria-label="Select month"
                        onClick={() => {
                          setMonthMenuOpen((current) => !current);
                          setYearMenuOpen(false);
                        }}
                        className="flex h-7 w-full min-w-0 items-center justify-between gap-1 rounded-md border border-slate-200 bg-white px-1.5 text-xs font-semibold text-slate-900 outline-none transition hover:border-slate-300 hover:bg-slate-50 focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-white/10 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-white/20 dark:hover:bg-white/[0.06] dark:focus:border-brand-400 dark:focus:ring-brand-500/20"
                      >
                        <span className="truncate">{MONTH_LABELS[visibleMonth.getMonth()]}</span>
                        <ChevronDown
                          className={`h-3.5 w-3.5 shrink-0 text-slate-500 transition dark:text-slate-400 ${monthMenuOpen ? "rotate-180" : ""}`}
                        />
                      </button>
                      <div
                        role="listbox"
                        aria-label="Financial year-end month"
                        className={`tf-date-dropdown-scrollbar absolute left-0 top-full z-[2300] mt-1 max-h-40 w-32 overflow-y-auto rounded-lg border border-slate-200 bg-white p-1 shadow-premium transition dark:border-white/10 dark:bg-slate-900 ${monthMenuOpen
                          ? "visible translate-y-0 opacity-100"
                          : "invisible -translate-y-1 opacity-0"
                          }`}
                      >
                        {MONTH_LABELS.map((month, index) => {
                          const selectedMonth = index === visibleMonth.getMonth();
                          return (
                            <button
                              key={month}
                              type="button"
                              role="option"
                              aria-selected={selectedMonth}
                              onClick={() => handleSelectVisibleMonth(index)}
                              className={`block w-full rounded-md px-2 py-1 text-left text-xs font-semibold transition focus:outline-none focus:ring-2 focus:ring-brand-100 dark:focus:ring-brand-500/30 ${selectedMonth
                                ? "bg-brand-600 text-white dark:bg-brand-500"
                                : "text-slate-700 hover:bg-slate-100 hover:text-slate-950 dark:text-slate-200 dark:hover:bg-white/[0.07] dark:hover:text-white"
                                }`}
                            >
                              {month}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    <div className="relative">
                      <button
                        type="button"
                        aria-haspopup="listbox"
                        aria-expanded={yearMenuOpen}
                        aria-label="Select year"
                        onClick={() => {
                          setYearMenuOpen((current) => !current);
                          setMonthMenuOpen(false);
                        }}
                        className="flex h-7 w-[4.75rem] items-center justify-between gap-1 rounded-md border border-slate-200 bg-white px-1.5 text-xs font-semibold text-slate-900 outline-none transition hover:border-slate-300 hover:bg-slate-50 focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-white/10 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-white/20 dark:hover:bg-white/[0.06] dark:focus:border-brand-400 dark:focus:ring-brand-500/20"
                      >
                        <span>{visibleMonth.getFullYear()}</span>
                        <ChevronDown
                          className={`h-3.5 w-3.5 text-slate-500 transition dark:text-slate-400 ${yearMenuOpen ? "rotate-180" : ""}`}
                        />
                      </button>
                      <div
                        role="listbox"
                        aria-label="Financial year-end year"
                        className={`tf-date-dropdown-scrollbar absolute right-0 top-full z-[2300] mt-1 max-h-40 w-24 overflow-y-auto rounded-lg border border-slate-200 bg-white p-1 shadow-premium transition dark:border-white/10 dark:bg-slate-900 ${yearMenuOpen
                          ? "visible translate-y-0 opacity-100"
                          : "invisible -translate-y-1 opacity-0"
                          }`}
                      >
                        {DATE_PICKER_YEAR_OPTIONS.map((year) => {
                          const selectedYear = year === visibleMonth.getFullYear();
                          return (
                            <button
                              key={year}
                              type="button"
                              role="option"
                              aria-selected={selectedYear}
                              onClick={() => handleSelectVisibleYear(year)}
                              className={`block w-full rounded-md px-2 py-1 text-left text-xs font-semibold transition focus:outline-none focus:ring-2 focus:ring-brand-100 dark:focus:ring-brand-500/30 ${selectedYear
                                ? "bg-brand-600 text-white dark:bg-brand-500"
                                : "text-slate-700 hover:bg-slate-100 hover:text-slate-950 dark:text-slate-200 dark:hover:bg-white/[0.07] dark:hover:text-white"
                                }`}
                            >
                              {year}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => moveVisibleMonth(1)}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-600 transition hover:bg-white hover:text-slate-950 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:text-slate-300 dark:hover:bg-white/[0.08] dark:hover:text-white dark:focus:ring-brand-500/30"
                    aria-label="Next month"
                  >
                    <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </div>

                <div className="mt-1 grid grid-cols-7 gap-0.5 px-0.5 text-center text-[9px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-500">
                  {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => (
                    <div key={day} className="py-px">
                      {day}
                    </div>
                  ))}
                </div>

                <div className="mt-0.5 grid grid-cols-7 gap-0.5">
                  {calendarDays.map((date) => {
                    const outsideMonth = date.getMonth() !== visibleMonth.getMonth();
                    const selected = isSameCalendarDay(date, selectedDate);
                    const currentDay = isSameCalendarDay(date, today);
                    return (
                      <button
                        key={toDateInputValue(date)}
                        type="button"
                        onClick={() => !outsideMonth && handleSelectDate(date)}
                        disabled={outsideMonth}
                        className={`flex h-7 items-center justify-center rounded-md text-xs font-semibold transition focus:outline-none focus:ring-2 focus:ring-brand-100 dark:focus:ring-brand-500/30 ${selected
                          ? "bg-brand-600 text-white shadow-glow dark:bg-brand-500"
                          : currentDay
                            ? "border border-brand-300/80 bg-brand-50 text-brand-700 hover:bg-brand-100 dark:border-brand-400/30 dark:bg-brand-400/10 dark:text-brand-200 dark:hover:bg-brand-400/20"
                            : outsideMonth
                              ? "cursor-default text-slate-300 dark:text-slate-700"
                              : "text-slate-700 hover:bg-slate-100 hover:text-slate-950 dark:text-slate-200 dark:hover:bg-white/[0.07] dark:hover:text-white"
                          }`}
                      >
                        {date.getDate()}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
            {dateInputError && (
              <p
                id="financial_year_end_error"
                className="mt-2 text-xs font-medium text-rose-600 dark:text-rose-300"
              >
                {dateInputError}
              </p>
            )}
          </div>

          <div>
            <label id="xbrl_format_label" className="field-label">
              XBRL format
            </label>
            <div ref={formatMenuRef} className="relative">
              <button
                type="button"
                aria-haspopup="menu"
                aria-expanded={formatMenuOpen}
                aria-labelledby="xbrl_format_label"
                onClick={() => setFormatMenuOpen((current) => !current)}
                className="flex h-11 w-full items-center justify-between gap-3 rounded-xl border border-slate-300 bg-white/95 px-3.5 text-left text-sm font-semibold text-slate-900 shadow-sm transition hover:border-slate-400 hover:bg-white focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-white/10 dark:bg-slate-950/80 dark:text-slate-100 dark:hover:border-white/20 dark:hover:bg-slate-950 dark:focus:ring-brand-500/20"
              >
                <span className="min-w-0 truncate">{selectedFormat.label}</span>
                <ChevronDown
                  className={`h-4 w-4 flex-none text-slate-500 transition dark:text-slate-400 ${formatMenuOpen ? "rotate-180" : ""
                    }`}
                />
              </button>
              <div
                role="menu"
                className={`absolute left-0 top-full z-[2100] mt-2 w-full rounded-xl border border-slate-200 bg-white p-2 shadow-premium transition dark:border-white/10 dark:bg-slate-900 ${formatMenuOpen
                  ? "visible translate-y-0 opacity-100"
                  : "invisible -translate-y-1 opacity-0"
                  }`}
              >
                {XBRL_FORMAT_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      onChange({
                        target: {
                          name: "xbrl_format",
                          value: option.value,
                        },
                      });
                      setFormatMenuOpen(false);
                    }}
                    className="block w-full rounded-lg px-3 py-3 text-left transition hover:bg-slate-50 focus:bg-slate-50 focus:outline-none dark:hover:bg-white/[0.06] dark:focus:bg-white/[0.06]"
                  >
                    <span className="block text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {option.label}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div>
            <label htmlFor="file" className="field-label">
              Annual report PDF
            </label>
            <input
              id="file"
              name="file"
              type="file"
              required
              accept=".pdf,application/pdf"
              onChange={onFileChange}
              className="input-base file:mr-4 file:rounded-md file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:text-sm file:font-medium file:text-brand-700 hover:file:bg-brand-100 dark:file:bg-brand-500/10 dark:file:text-brand-300"
            />
          </div>

          {error && (
            <div className="md:col-span-2 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
              {error}
            </div>
          )}

          <div className="md:col-span-2 flex items-center justify-end gap-3 border-t border-slate-200/70 pt-5 dark:border-white/10">
            <button type="button" onClick={onClose} className="button-secondary">
              Cancel
            </button>
            <button type="submit" className="button-primary" disabled={submitting || Boolean(dateInputError)}>
              {submitting ? (
                <>
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  Uploading
                </>
              ) : (
                <>
                  <FileUp className="h-4 w-4" />
                  Start processing
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function AuthScreen({
  mode,
  loading,
  error,
  successMessage,
  initialEmail,
  theme,
  onThemeToggle,
  onModeChange,
  onSubmit,
}) {
  const [email, setEmail] = useState(initialEmail || "");
  const [password, setPassword] = useState("");

  useEffect(() => {
    setEmail(initialEmail || "");
    setPassword("");
  }, [initialEmail, mode]);

  function handleSubmit(event) {
    event.preventDefault();
    onSubmit({
      email,
      password,
    });
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center px-4 py-10 text-slate-950 dark:text-slate-100">
      <button
        type="button"
        className="button-secondary absolute right-4 top-4 h-10 px-3 py-0 sm:right-6 sm:top-6"
        onClick={onThemeToggle}
        title="Toggle theme"
        aria-label="Toggle theme"
      >
        {theme === "dark" ? (
          <Sun className="h-4 w-4" />
        ) : (
          <Moon className="h-4 w-4" />
        )}
      </button>
      <div className="w-full max-w-md">
        <div className="mb-7 flex items-center justify-center gap-3">
          <TensorFlowLogoMark className="h-10 w-10" />
          <div>
            <p className="eyebrow">TaxonomyFlow</p>
            <h1 className="text-xl font-semibold text-slate-950 dark:text-white">
              Sign in
            </h1>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="panel p-6">
          <div className="space-y-5">
            <div>
              <label htmlFor="auth_email" className="field-label">
                Email
              </label>
              <input
                id="auth_email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="input-base"
                placeholder="you@example.com"
              />
            </div>

            <div>
              <label htmlFor="auth_password" className="field-label">
                Password
              </label>
              <input
                id="auth_password"
                type="password"
                autoComplete="current-password"
                minLength={8}
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="input-base"
                placeholder="Minimum 8 characters"
              />
            </div>

            {error && (
              <div className="flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
                <AlertCircle className="mt-0.5 h-4 w-4" />
                <span>{error}</span>
              </div>
            )}

            {successMessage && (
              <div className="flex items-start gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200">
                <CheckCircle2 className="mt-0.5 h-4 w-4" />
                <span>{successMessage}</span>
              </div>
            )}

            <button type="submit" className="button-primary w-full" disabled={loading}>
              {loading ? (
                <>
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  Signing in
                </>
              ) : (
                <>
                  <LogIn className="h-4 w-4" />
                  Sign in
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function replaceAppPath(path) {
  if (typeof window === "undefined" || window.location.pathname === path) {
    return;
  }

  window.history.replaceState({}, "", path);
}

function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === "undefined") {
      return false;
    }
    return window.innerWidth < 768;
  });
  const [theme, setTheme] = useState(() => localStorage.getItem("taxonomyflow-theme") || "dark");
  const [currentUser, setCurrentUser] = useState(null);
  const [authInitializing, setAuthInitializing] = useState(true);
  const [authMode, setAuthMode] = useState("login");
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authSuccess, setAuthSuccess] = useState("");
  const [authPrefillEmail, setAuthPrefillEmail] = useState("");
  const [jobs, setJobs] = useState([]);
  const [selectedJobId, setSelectedJobId] = useState(null);
  const [selectedJob, setSelectedJob] = useState(null);
  const [stats, setStats] = useState(null);
  const [loadingJobs, setLoadingJobs] = useState(true);
  const [loadingJob, setLoadingJob] = useState(false);
  const [jobsError, setJobsError] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploadSubmitting, setUploadSubmitting] = useState(false);
  const [uploadForm, setUploadForm] = useState(DEFAULT_UPLOAD_FORM);
  const [reviewState, setReviewState] = useState(null);
  const [workspaceRefreshKey, setWorkspaceRefreshKey] = useState(0);
  const [aiSuggestionPostCompletionRefreshKey, setAiSuggestionPostCompletionRefreshKey] = useState(0);
  const [workspaceAutoRefreshing, setWorkspaceAutoRefreshing] = useState(false);
  const [deletePromptJob, setDeletePromptJob] = useState(null);
  const [deletingJob, setDeletingJob] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [deleteMessage, setDeleteMessage] = useState("");
  const [deleteSummary, setDeleteSummary] = useState(null);
  const deletedJobIdsRef = useRef(new Set());
  const deleteRequestInFlightRef = useRef(false);
  const delayedJobsRefetchTimeoutRef = useRef(null);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("taxonomyflow-theme", theme);
  }, [theme]);

  useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      const token = getStoredAuthToken();
      if (!token) {
        replaceAppPath("/app/login");
        setAuthInitializing(false);
        return;
      }

      try {
        const user = await fetchCurrentUser();
        if (!cancelled) {
          setCurrentUser(user);
          setAuthError("");
          replaceAppPath(user.is_admin ? "/app/admin" : "/app");
        }
      } catch (error) {
        clearStoredAuthToken();
        if (!cancelled) {
          setCurrentUser(null);
          setAuthError("Please sign in again.");
          replaceAppPath("/app/login");
        }
      } finally {
        if (!cancelled) {
          setAuthInitializing(false);
        }
      }
    }

    restoreSession();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!currentUser) {
      setJobs([]);
      setSelectedJobId(null);
      setSelectedJob(null);
      setStats(null);
      setReviewState(null);
      setLoadingJobs(false);
    }
  }, [currentUser]);

  useEffect(() => {
    return () => {
      if (delayedJobsRefetchTimeoutRef.current) {
        window.clearTimeout(delayedJobsRefetchTimeoutRef.current);
      }
    };
  }, []);

  function filterDeletedJobs(jobList) {
    const deletedJobIds = deletedJobIdsRef.current;
    if (deletedJobIds.size === 0) {
      return jobList;
    }
    return jobList.filter((job) => !deletedJobIds.has(job.id));
  }

  function scheduleDelayedJobsRefetch() {
    if (delayedJobsRefetchTimeoutRef.current) {
      window.clearTimeout(delayedJobsRefetchTimeoutRef.current);
    }

    delayedJobsRefetchTimeoutRef.current = window.setTimeout(() => {
      delayedJobsRefetchTimeoutRef.current = null;
      loadJobs({
        preserveSelection: true,
        selectFirstWhenEmptySelection: false,
      });
    }, 1200);
  }

  async function loadJobs({ preserveSelection = true, selectFirstWhenEmptySelection = true } = {}) {
    if (!currentUser) {
      setLoadingJobs(false);
      return [];
    }

    setLoadingJobs(true);
    setJobsError("");
    try {
      const [rawJobList, dashboardStats] = await Promise.all([
        fetchJobs(50),
        fetchDashboardStats().catch(() => null),
      ]);
      const deletedJobIds = deletedJobIdsRef.current;
      const staleDeletedJobVisible = rawJobList.some((job) => deletedJobIds.has(job.id));
      const jobList = filterDeletedJobs(rawJobList);

      setJobs(jobList);
      setStats(dashboardStats);

      if (staleDeletedJobVisible) {
        scheduleDelayedJobsRefetch();
      }

      if (!preserveSelection && jobList.length > 0) {
        setSelectedJobId(jobList[0].id);
        return jobList;
      }

      if (preserveSelection && selectedJobId) {
        const stillExists = jobList.some((job) => job.id === selectedJobId);
        if (!stillExists) {
          setSelectedJobId(selectFirstWhenEmptySelection ? jobList[0]?.id || null : null);
        }
      } else if (jobList.length > 0 && selectFirstWhenEmptySelection) {
        setSelectedJobId(jobList[0].id);
      }

      return jobList;
    } catch (error) {
      setJobsError(error.message);
      return [];
    } finally {
      setLoadingJobs(false);
    }
  }

  async function refreshSelectedWorkspace() {
    if (!selectedJobId) {
      await loadJobs();
      return;
    }

    if (reviewState?.dirtyCount > 0) {
      const confirmed = window.confirm(
        "There are unsaved review changes. Refreshing will reload the workspace and discard unsaved edits. Continue?",
      );

      if (!confirmed) {
        return;
      }
    }

    setLoadingJob(true);
    setWorkspaceAutoRefreshing(false);
    setJobsError("");

    try {
      const refreshedJobs = await loadJobs();
      const latestSummary = refreshedJobs.find((job) => job.id === selectedJobId);
      const latestJob = await fetchJob(selectedJobId);
      setSelectedJob(latestSummary ? { ...latestJob, status: latestSummary.status } : latestJob);
      setReviewState(null);
      setWorkspaceRefreshKey((current) => current + 1);
    } catch (error) {
      setJobsError(error.message);
    } finally {
      setLoadingJob(false);
    }
  }

  useEffect(() => {
    if (currentUser) {
      loadJobs({ preserveSelection: false });
    }
  }, [currentUser?.id]);

  useEffect(() => {
    if (!currentUser || !selectedJobId) {
      setSelectedJob(null);
      setReviewState(null);
      return;
    }

    let cancelled = false;

    async function loadSelectedJob() {
      setLoadingJob(true);
      try {
        const job = await fetchJob(selectedJobId);
        if (!cancelled && !deletedJobIdsRef.current.has(selectedJobId)) {
          setSelectedJob(job);
        }
      } catch (error) {
        if (!cancelled && !deletedJobIdsRef.current.has(selectedJobId)) {
          setJobsError(error.message);
        }
      } finally {
        if (!cancelled) {
          setLoadingJob(false);
        }
      }
    }

    loadSelectedJob();

    return () => {
      cancelled = true;
    };
  }, [currentUser?.id, selectedJobId]);

  useEffect(() => {
    if (!currentUser) {
      return undefined;
    }

    const intervalId = setInterval(async () => {
      try {
        const refreshedJobs = filterDeletedJobs(await fetchJobs(50));
        setJobs(refreshedJobs);

        if (!selectedJobId) {
          return;
        }

        if (deletedJobIdsRef.current.has(selectedJobId)) {
          return;
        }

        const latestSelectedSummary = refreshedJobs.find((job) => job.id === selectedJobId);
        const previousSelectedStatus = selectedJob?.status;
        const latestSummaryStatus = latestSelectedSummary?.status;

        async function refreshSelectedJobAfterProcessing(nextStatus, latestSummary = null) {
          setLoadingJob(true);
          setWorkspaceAutoRefreshing(true);
          try {
            let latestJob = latestSummary
              ? { ...(selectedJob || {}), ...latestSummary, status: nextStatus }
              : selectedJob
                ? { ...selectedJob, status: nextStatus }
                : null;

            try {
              const latestDetail = await fetchJob(selectedJobId);
              latestJob = { ...latestDetail, status: nextStatus };
            } catch (detailError) {
              // Use the already-polled summary when detail fetch is momentarily behind.
            }

            if (latestJob && !deletedJobIdsRef.current.has(selectedJobId)) {
              setSelectedJob(latestJob);
              setReviewState(null);
              setWorkspaceRefreshKey((current) => current + 1);
              setAiSuggestionPostCompletionRefreshKey((current) => current + 1);
            }
          } finally {
            setLoadingJob(false);
            setWorkspaceAutoRefreshing(false);
          }
        }

        if (
          previousSelectedStatus === "PROCESSING" &&
          isTerminalJobStatus(latestSummaryStatus)
        ) {
          await refreshSelectedJobAfterProcessing(latestSummaryStatus, latestSelectedSummary);
          return;
        }

        if (latestSelectedSummary && latestSummaryStatus !== previousSelectedStatus) {
          setSelectedJob((current) =>
            current
              ? {
                ...current,
                status: latestSummaryStatus,
              }
              : latestSelectedSummary,
          );
        }

        if (previousSelectedStatus === "PROCESSING") {
          const status = await fetchJobStatus(selectedJobId);
          if (deletedJobIdsRef.current.has(selectedJobId)) {
            return;
          }

          if (isTerminalJobStatus(status.status)) {
            await refreshSelectedJobAfterProcessing(status.status, latestSelectedSummary);
            return;
          }

          setSelectedJob((current) =>
            current
              ? {
                ...current,
                status: status.status,
              }
              : current,
          );
        }
      } catch (error) {
        // Keep polling quiet in the shell.
      }
    }, 5000);

    return () => clearInterval(intervalId);
  }, [currentUser?.id, selectedJobId, selectedJob?.status]);

  const selectedJobSummary = useMemo(() => {
    if (!selectedJob) {
      return null;
    }

    return [
      {
        label: "Task ID",
        value: selectedJob.id,
      },
      {
        label: "Registration",
        value: selectedJob.registration_number || "Not provided",
      },
      {
        label: "Financial year end",
        value: formatDate(selectedJob.financial_year_end),
      },
      {
        label: "Uploaded",
        value: formatDateTime(selectedJob.uploaded_at),
      },
    ];
  }, [selectedJob]);

  function handleUploadFieldChange(event) {
    const { name, value } = event.target;
    setUploadForm((current) => ({ ...current, [name]: value }));
  }

  function handleUploadFileChange(event) {
    const file = event.target.files?.[0] || null;
    setUploadForm((current) => ({ ...current, file }));
  }

  async function handleUploadSubmit(event) {
    event.preventDefault();
    setUploadSubmitting(true);
    setUploadError("");

    try {
      const formData = new FormData();
      formData.append("company_name", uploadForm.company_name);
      formData.append("registration_number", uploadForm.registration_number);
      formData.append("financial_year_end", uploadForm.financial_year_end);
      formData.append("xbrl_format", uploadForm.xbrl_format);
      if (uploadForm.file) {
        formData.append("file", uploadForm.file);
      }

      const createdJob = await uploadJob(formData);
      setUploadOpen(false);
      setUploadForm(DEFAULT_UPLOAD_FORM);
      await loadJobs();
      setSelectedJobId(createdJob.id);
    } catch (error) {
      setUploadError(error.message);
    } finally {
      setUploadSubmitting(false);
    }
  }

  function handleRequestDelete(job) {
    setDeletePromptJob(job);
    setDeleteError("");
    setDeleteSummary(null);
  }

  function handleCancelDelete() {
    if (deletingJob) {
      return;
    }
    setDeletePromptJob(null);
    setDeleteError("");
  }

  async function handleConfirmDelete() {
    if (!deletePromptJob || deletingJob || deleteRequestInFlightRef.current) {
      return;
    }

    const deletedJobId = deletePromptJob.id;
    const deletedSelectedJob = deletedJobId === selectedJobId;

    deleteRequestInFlightRef.current = true;
    setDeletingJob(true);
    setDeleteError("");
    setDeleteMessage("");

    try {
      const summary = await deleteFilingJob(deletedJobId);
      deletedJobIdsRef.current.add(deletedJobId);
      setJobs((current) => current.filter((job) => job.id !== deletedJobId));
      setDeletePromptJob(null);
      setDeleteSummary(summary);
      setDeleteMessage(`Task ID ${deletedJobId} deleted.`);

      if (deletedSelectedJob) {
        setSelectedJobId(null);
        setSelectedJob(null);
        setReviewState(null);
        setLoadingJob(false);
        setWorkspaceRefreshKey((current) => current + 1);
      }

      await loadJobs({
        preserveSelection: true,
        selectFirstWhenEmptySelection: !deletedSelectedJob,
      });
    } catch (error) {
      setDeleteError(error.message);
    } finally {
      deleteRequestInFlightRef.current = false;
      setDeletingJob(false);
    }
  }

  function handleAuthModeChange(mode) {
    setAuthMode("login");
    setAuthError("");
    setAuthSuccess("");
    replaceAppPath("/app/login");
  }

  function handleThemeToggle() {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }

  async function handleAuthSubmit(payload) {
    setAuthSubmitting(true);
    setAuthError("");

    try {
      const result = await loginUser(payload);
      setCurrentUser(result.user);
      setAuthMode("login");
      setAuthPrefillEmail("");
      setAuthSuccess("");
      setJobs([]);
      setSelectedJobId(null);
      setSelectedJob(null);
      setStats(null);
      deletedJobIdsRef.current.clear();
      replaceAppPath(result.user?.is_admin ? "/app/admin" : "/app");
    } catch (error) {
      setAuthError(error.message);
    } finally {
      setAuthSubmitting(false);
    }
  }

  async function handleSignOut() {
    await logoutUser().catch(() => {
      clearStoredAuthToken();
    });
    setCurrentUser(null);
    setAuthMode("login");
    setAuthError("");
    setAuthSuccess("");
    replaceAppPath("/app/login");
  }

  function handleGoHome() {
    setSelectedJobId(null);
    setSelectedJob(null);
    setReviewState(null);
    setLoadingJob(false);
  }

  if (authInitializing) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-600 dark:text-slate-300">
        <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white/90 px-5 py-4 shadow-panel dark:border-white/10 dark:bg-slate-900/80">
          <LoaderCircle className="h-4 w-4 animate-spin" />
          <span className="text-sm font-medium">Checking sign-in</span>
        </div>
      </div>
    );
  }

  if (!currentUser) {
    return (
      <AuthScreen
        mode={authMode}
        loading={authSubmitting}
        error={authError}
        successMessage={authSuccess}
        initialEmail={authPrefillEmail}
        theme={theme}
        onThemeToggle={handleThemeToggle}
        onModeChange={handleAuthModeChange}
        onSubmit={handleAuthSubmit}
      />
    );
  }

  if (currentUser.is_admin) {
    return (
      <AdminUserManagement
        currentUser={currentUser}
        onSignOut={handleSignOut}
      />
    );
  }

  return (
    <div className="min-h-screen text-slate-950 dark:text-slate-100">
      <div className="flex min-h-screen">
        <aside
          className={`fixed inset-y-0 left-0 z-40 w-80 shrink-0 overflow-hidden border-r border-slate-200/70 bg-white/90 shadow-premium backdrop-blur-xl transition-[width,transform] duration-200 dark:border-white/10 dark:bg-slate-950/80 md:static md:flex-none md:translate-x-0 ${sidebarCollapsed ? "-translate-x-full md:w-[88px]" : "translate-x-0 md:w-80"
            }`}
        >
          <div className="flex h-full flex-col">
            <div className={`border-b border-slate-200/70 py-5 dark:border-white/10 ${sidebarCollapsed ? "px-0" : "px-4"}`}>
              <div className={`flex gap-3 ${sidebarCollapsed ? "flex-col items-center" : "items-center justify-between"}`}>
                <button
                  type="button"
                  onClick={handleGoHome}
                  aria-label="Go to workspace home"
                  title="Go to workspace home"
                  className={`group flex min-w-0 items-center gap-3 rounded-lg text-left transition hover:bg-slate-100/80 focus:outline-none focus:ring-2 focus:ring-brand-100 active:bg-slate-100 dark:hover:bg-white/[0.06] dark:focus:ring-brand-500/30 dark:active:bg-white/[0.08] ${sidebarCollapsed ? "h-11 w-11 justify-center p-0" : "h-12 flex-1 px-2"
                    }`}
                >
                  <TensorFlowLogoMark className="h-10 w-10" />
                  {!sidebarCollapsed && (
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-950 transition group-hover:text-brand-700 dark:text-white dark:group-hover:text-brand-200">
                        TaxonomyFlow
                      </p>
                      <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                        Compliance review
                      </p>
                    </div>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => setSidebarCollapsed((current) => !current)}
                  className={`${sidebarCollapsed ? "h-11 w-11 px-0" : "px-3"} button-ghost`}
                  aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
                >
                  {sidebarCollapsed ? (
                    <ChevronRight className="h-4 w-4" />
                  ) : (
                    <ChevronLeft className="h-4 w-4" />
                  )}
                </button>
              </div>

              <button
                type="button"
                onClick={() => setUploadOpen(true)}
                className={`button-primary mt-5 ${sidebarCollapsed ? "mx-auto flex h-11 w-11 px-0" : "w-full"}`}
                title={sidebarCollapsed ? "Upload PDF" : undefined}
              >
                <Plus className="h-4 w-4" />
                {!sidebarCollapsed && <span>Upload PDF</span>}
              </button>
            </div>

            <div className={`flex items-center py-4 ${sidebarCollapsed ? "justify-center px-0" : "justify-between px-4"}`}>
              {!sidebarCollapsed && (
                <div>
                  <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                    Task history
                  </h2>
                  <p className="text-xs text-slate-500 dark:text-slate-500">
                    Recent filings
                  </p>
                </div>
              )}
              <button
                type="button"
                onClick={() => loadJobs()}
                className={`${sidebarCollapsed ? "mx-auto h-11 w-11 px-0" : "px-3"} button-ghost`}
                title="Refresh tasks"
              >
                <RefreshCw className={`h-4 w-4 ${loadingJobs ? "animate-spin" : ""}`} />
              </button>
            </div>

            <div className={`flex-1 space-y-2 overflow-y-auto pb-5 ${sidebarCollapsed ? "px-0" : "px-3"}`}>
              {jobsError && (
                <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
                  {jobsError}
                </div>
              )}

              {deleteMessage && (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
                  {deleteMessage}
                  {deleteSummary?.deleted_files_count > 0
                    ? ` ${deleteSummary.deleted_files_count} artifact file${deleteSummary.deleted_files_count === 1 ? "" : "s"} cleaned.`
                    : ""}
                </div>
              )}

              {loadingJobs ? (
                <div className={`soft-card flex items-center justify-center py-10 text-sm text-slate-500 dark:text-slate-400 ${sidebarCollapsed ? "px-0" : ""}`}>
                  <LoaderCircle className={`${sidebarCollapsed ? "" : "mr-2"} h-4 w-4 animate-spin`} />
                  {!sidebarCollapsed && "Loading tasks"}
                </div>
              ) : jobs.length === 0 ? (
                <div className="soft-card border-dashed px-4 py-8 text-center text-sm text-slate-500 dark:text-slate-400">
                  {sidebarCollapsed ? <Plus className="mx-auto h-4 w-4" /> : "No tasks yet. Upload a PDF to start."}
                </div>
              ) : (
                jobs.map((job) => (
                  <SidebarJobRow
                    key={job.id}
                    job={job}
                    collapsed={sidebarCollapsed}
                    active={job.id === selectedJobId}
                    onSelect={setSelectedJobId}
                    onRequestDelete={handleRequestDelete}
                  />
                ))
              )}
            </div>
          </div>
        </aside>

        {!sidebarCollapsed && (
          <button
            type="button"
            aria-label="Close sidebar"
            className="fixed inset-0 z-30 bg-slate-950/40 md:hidden"
            onClick={() => setSidebarCollapsed(true)}
          />
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="relative z-[100] overflow-visible border-b border-slate-200/60 bg-white/60 px-4 py-4 backdrop-blur-xl dark:border-white/10 dark:bg-slate-950/50 sm:px-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setSidebarCollapsed((current) => !current)}
                    className="button-secondary px-3 md:hidden"
                  >
                    <Menu className="h-4 w-4" />
                  </button>
                  <div>
                    <p className="eyebrow">
                      Workspace
                    </p>
                    <h1 className="mt-1 truncate text-2xl font-semibold text-slate-950 dark:text-white">
                      {selectedJob ? selectedJob.company_name : "TaxonomyFlow"}
                    </h1>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="button-secondary h-10 px-3 py-0"
                  onClick={handleThemeToggle}
                  title="Toggle theme"
                >
                  {theme === "dark" ? (
                    <Sun className="h-4 w-4" />
                  ) : (
                    <Moon className="h-4 w-4" />
                  )}
                </button>
                <button
                  type="button"
                  className="button-secondary h-10 px-3 py-0"
                  onClick={handleSignOut}
                >
                  <LogOut className="h-4 w-4" />
                  Sign Out
                </button>
              </div>
            </div>
          </header>

          <main className="flex-1 overflow-y-auto p-4 sm:p-6">
            <div className="mx-auto flex w-full max-w-[96rem] flex-col gap-6">
              {!selectedJob ? (
                <>
                  <section className="panel overflow-hidden">
                    <div className="grid gap-0 lg:grid-cols-[1.35fr,1fr]">
                      <div className="relative overflow-hidden px-6 py-8 sm:px-8 sm:py-10">
                        <div className="absolute right-6 top-6 hidden h-24 w-24 rounded-full border border-brand-200/60 bg-brand-50/70 blur-2xl dark:border-brand-400/20 dark:bg-brand-400/10 lg:block" />
                        <p className="eyebrow">TaxonomyFlow</p>
                        <h2 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight text-slate-950 dark:text-white sm:text-4xl">
                          Financial statement review with a cleaner path to XBRL.
                        </h2>
                        <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-400">
                          Upload a filing, review extracted line items, validate readiness,
                          and export from one focused workspace.
                        </p>
                        <div className="mt-6 flex flex-wrap gap-3">
                          <button
                            type="button"
                            onClick={() => setUploadOpen(true)}
                            className="button-primary"
                          >
                            <FileUp className="h-4 w-4" />
                            Upload PDF
                          </button>
                        </div>
                      </div>

                      <div className="border-t border-slate-200/70 bg-slate-50/70 px-6 py-7 dark:border-white/10 dark:bg-white/[0.035] lg:border-l lg:border-t-0">
                        <div className="grid gap-3 sm:grid-cols-2">
                          <div className="stat-card">
                            <p className="text-sm text-slate-500 dark:text-slate-400">Total tasks</p>
                            <p className="mt-2 text-3xl font-semibold text-slate-950 dark:text-white">{stats?.total_jobs ?? jobs.length}</p>
                          </div>
                          <div className="stat-card">
                            <p className="text-sm text-slate-500 dark:text-slate-400">Processing</p>
                            <p className="mt-2 text-3xl font-semibold text-slate-950 dark:text-white">{stats?.processing_jobs ?? jobs.filter((job) => job.status === "PROCESSING").length}</p>
                          </div>
                          <div className="stat-card">
                            <p className="text-sm text-slate-500 dark:text-slate-400">Completed</p>
                            <p className="mt-2 text-3xl font-semibold text-slate-950 dark:text-white">{stats?.completed_jobs ?? jobs.filter((job) => job.status === "COMPLETED").length}</p>
                          </div>
                          <div className="stat-card">
                            <p className="text-sm text-slate-500 dark:text-slate-400">Reviewed items</p>
                            <p className="mt-2 text-3xl font-semibold text-slate-950 dark:text-white">{stats?.reviewed_items ?? 0}</p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </section>

                  <section className="grid gap-5">
                    <div className="panel p-5">
                      <p className="eyebrow">Workflow</p>
                      <h3 className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">
                        Review essentials
                      </h3>
                      <ul className="mt-4 grid gap-3 text-sm text-slate-600 dark:text-slate-300 sm:grid-cols-2">
                        <li className="soft-card flex items-start gap-3 px-4 py-3">
                          <ShieldCheck className="mt-0.5 h-4 w-4 text-brand-600 dark:text-brand-300" />
                          Upload and task history
                        </li>
                        <li className="soft-card flex items-start gap-3 px-4 py-3">
                          <ShieldCheck className="mt-0.5 h-4 w-4 text-brand-600 dark:text-brand-300" />
                          Statement review and save
                        </li>
                        <li className="soft-card flex items-start gap-3 px-4 py-3">
                          <ShieldCheck className="mt-0.5 h-4 w-4 text-brand-600 dark:text-brand-300" />
                          Taxonomy search and tagging
                        </li>
                        <li className="soft-card flex items-start gap-3 px-4 py-3">
                          <ShieldCheck className="mt-0.5 h-4 w-4 text-brand-600 dark:text-brand-300" />
                          Validation and download controls
                        </li>
                      </ul>
                    </div>
                  </section>
                </>
              ) : (
                <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.55fr)_24rem]">
                  <section className="min-w-0 space-y-6">
                    <div className="panel overflow-hidden">
                      <div className="border-b border-slate-200/70 bg-slate-50/70 px-6 py-6 dark:border-white/10 dark:bg-white/[0.035]">
                        <div className="flex flex-wrap items-start justify-between gap-4">
                          <div className="min-w-0">
                            <p className="eyebrow">Selected filing</p>
                            <div className="mt-2 flex flex-wrap items-center gap-3">
                              <h2 className="truncate text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">
                                {selectedJob.company_name}
                              </h2>
                              <StatusBadge status={selectedJob.status} />
                            </div>
                            <p
                              className="mt-2 text-sm text-slate-500 dark:text-slate-500"
                              title="Backend task id used by benchmark scripts"
                            >
                              Task ID {selectedJob.id} · Ready for review and export controls.
                            </p>
                          </div>
                          <div className="flex w-full flex-wrap justify-start gap-3 sm:w-auto sm:justify-end">
                            <button
                              type="button"
                              onClick={refreshSelectedWorkspace}
                              className="button-secondary flex-1 sm:flex-none"
                              disabled={loadingJob}
                            >
                              <RefreshCw className={`h-4 w-4 ${loadingJob ? "animate-spin" : ""}`} />
                              Refresh
                            </button>
                          </div>
                        </div>
                      </div>

                      <div className="grid gap-3 px-6 py-5 sm:grid-cols-4">
                        {selectedJobSummary?.map((item) => (
                          <div key={item.label} className="stat-card h-full">
                            <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-500">{item.label}</p>
                            <p className="mt-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
                              {item.value}
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>

                    {loadingJob ? (
                      <div className="panel p-6">
                        <div className="flex items-center justify-center py-12 text-sm text-slate-500 dark:text-slate-400">
                          <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
                          {workspaceAutoRefreshing ? "Loading extracted results..." : "Loading selected task"}
                        </div>
                      </div>
                    ) : (
                      <ReviewWorkspace
                        job={selectedJob}
                        refreshKey={workspaceRefreshKey}
                        postCompletionAiRefreshKey={aiSuggestionPostCompletionRefreshKey}
                        onStateChange={setReviewState}
                      />
                    )}
                  </section>

                  <aside className="space-y-4 2xl:sticky 2xl:top-5 2xl:self-start">
                    <div className="panel p-5">
                      <p className="eyebrow">Current state</p>
                      <div className="mt-4 soft-card p-4">
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                            Filing status
                          </p>
                          <StatusBadge status={selectedJob.status} />
                        </div>
                        <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-400">
                          {selectedJob.status === "PROCESSING"
                            ? "Processing is underway. Status refreshes automatically."
                            : "Review, validate, and export from this workspace."}
                        </p>
                      </div>
                    </div>

                    <XbrlActionsPanel
                      key={`${selectedJob.id}-${workspaceRefreshKey}`}
                      job={selectedJob}
                      reviewState={reviewState}
                    />
                  </aside>
                </div>
              )}
            </div>
          </main>
        </div>
      </div>

      <UploadModal
        open={uploadOpen}
        form={uploadForm}
        submitting={uploadSubmitting}
        error={uploadError}
        onClose={() => {
          if (!uploadSubmitting) {
            setUploadOpen(false);
            setUploadError("");
          }
        }}
        onChange={handleUploadFieldChange}
        onFileChange={handleUploadFileChange}
        onSubmit={handleUploadSubmit}
      />

      {deletePromptJob && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/70 px-4 py-6 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-white/10 dark:bg-slate-950">
            <div className="flex items-start gap-3">
              <div className="rounded-lg bg-rose-100 p-2 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
                <Trash2 className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h4 className="text-base font-semibold text-slate-950 dark:text-white">
                  Delete task?
                </h4>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  This will permanently delete this task and related extracted data. Continue?
                </p>
                <p className="mt-3 truncate text-xs text-slate-500 dark:text-slate-500">
                  Task ID {deletePromptJob.id} - {deletePromptJob.company_name}
                </p>
              </div>
            </div>

            {deleteError && (
              <div className="mt-5 flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
                <AlertCircle className="mt-0.5 h-4 w-4" />
                <span>{deleteError}</span>
              </div>
            )}

            <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <button
                type="button"
                className="button-secondary"
                onClick={handleCancelDelete}
                disabled={deletingJob}
              >
                Cancel
              </button>
              <button
                type="button"
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-rose-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-rose-500 focus:outline-none focus:ring-2 focus:ring-rose-100 focus:ring-offset-2 focus:ring-offset-white disabled:cursor-not-allowed disabled:opacity-50 dark:bg-rose-500 dark:hover:bg-rose-400 dark:focus:ring-rose-500/30 dark:focus:ring-offset-slate-950"
                onClick={handleConfirmDelete}
                disabled={deletingJob}
              >
                {deletingJob ? (
                  <>
                    <LoaderCircle className="h-4 w-4 animate-spin" />
                    Deleting
                  </>
                ) : (
                  <>
                    <Trash2 className="h-4 w-4" />
                    Delete
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
