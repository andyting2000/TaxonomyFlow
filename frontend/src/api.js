const API_BASE = "/api/v1";
export const AUTH_TOKEN_STORAGE_KEY = "taxonomyflow-auth-token";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, withAuth(options));

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (Array.isArray(body.detail)) {
        detail = body.detail
          .map((item) => item.msg || item.message || item.type || "Validation error")
          .join("; ");
      } else {
        detail = body.detail || body.error || detail;
      }
    } catch (error) {
      // Keep fallback detail.
    }
    throw new Error(detail);
  }

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return null;
  }

  return response.json();
}

function getStorage() {
  if (typeof window === "undefined" || !window.localStorage) {
    return null;
  }

  return window.localStorage;
}

export function getStoredAuthToken() {
  return getStorage()?.getItem(AUTH_TOKEN_STORAGE_KEY) || "";
}

export function storeAuthToken(token) {
  if (!token) {
    return;
  }

  getStorage()?.setItem(AUTH_TOKEN_STORAGE_KEY, token);
}

export function clearStoredAuthToken() {
  getStorage()?.removeItem(AUTH_TOKEN_STORAGE_KEY);
}

export function buildAuthHeaders(options = {}, token = getStoredAuthToken()) {
  const headers = new Headers(options.headers || {});
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

export function withAuth(options = {}) {
  return {
    ...options,
    headers: buildAuthHeaders(options),
  };
}

export function getAuthPath(mode = "login") {
  return mode === "register" ? "/app/login" : "/app/login";
}

export async function registerUser(payload) {
  return request("/auth/register", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function loginUser(payload) {
  const result = await request("/auth/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  storeAuthToken(result.access_token);
  return result;
}

export async function logoutUser() {
  try {
    await request("/auth/logout", {
      method: "POST",
    });
  } finally {
    clearStoredAuthToken();
  }
}

export async function fetchCurrentUser() {
  return request("/auth/current-user");
}

export async function changePassword(payload) {
  const result = await request("/auth/change-password", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  clearStoredAuthToken();
  return result;
}

export async function deleteAccount(payload) {
  const result = await request("/auth/delete-account", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  clearStoredAuthToken();
  return result;
}

export async function fetchAdminUsers() {
  return request("/admin/users");
}

export async function createAdminUser(payload) {
  return request("/admin/users", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function adminChangeUserPassword(userId, payload) {
  return request(`/admin/users/${userId}/change-password`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function adminClearUserTasks(userId) {
  return request(`/admin/users/${userId}/clear-tasks`, {
    method: "POST",
  });
}

export async function adminDeleteUser(userId) {
  return request(`/admin/users/${userId}`, {
    method: "DELETE",
  });
}

export async function fetchJobs(limit = 50) {
  return request(`/filings/jobs?limit=${limit}`);
}

export async function fetchJob(jobId) {
  return request(`/filings/jobs/${jobId}`);
}

export async function fetchJobStatus(jobId) {
  return request(`/filings/jobs/${jobId}/status`);
}

export async function fetchJobPages(jobId) {
  return request(`/filings/jobs/${jobId}/pages`);
}

function normalizeExtractedDataResponse(response) {
  if (Array.isArray(response)) {
    return {
      items: response,
      page: 1,
      pages: 1,
      hasNext: false,
    };
  }

  if (Array.isArray(response?.items)) {
    return {
      items: response.items,
      page: Number(response.page) || 1,
      pages: Number(response.pages) || 1,
      hasNext: Boolean(response.has_next),
    };
  }

  return {
    items: [],
    page: 1,
    pages: 1,
    hasNext: false,
  };
}

export async function fetchExtractedData(jobId, page = 1, size = 1000) {
  const firstResponse = await request(
    `/filings/jobs/${jobId}/extracted-data?page=${page}&size=${size}`,
  );
  const firstPage = normalizeExtractedDataResponse(firstResponse);
  const items = [...firstPage.items];

  let nextPage = firstPage.page + 1;
  let hasNext = firstPage.hasNext;
  const maxPages = firstPage.pages > firstPage.page
    ? firstPage.pages
    : firstPage.page + 100;

  while (hasNext && nextPage <= maxPages) {
    const response = await request(
      `/filings/jobs/${jobId}/extracted-data?page=${nextPage}&size=${size}`,
    );
    const normalized = normalizeExtractedDataResponse(response);
    items.push(...normalized.items);
    hasNext = normalized.hasNext;
    nextPage = normalized.page + 1;
  }

  return items;
}

export async function fetchAiMappingSuggestions(jobId) {
  return request(`/filings/jobs/${jobId}/ai-mapping-suggestions`);
}

export async function fetchAiMappingSuggestionsStatus(jobId) {
  return request(`/filings/jobs/${jobId}/ai-mapping-suggestions/status`);
}

export async function runAiMappingSuggestions(jobId) {
  return request(`/filings/jobs/${jobId}/ai-mapping-suggestions/run`, {
    method: "POST",
  });
}

function rankedCandidateMaxCandidates(options = {}) {
  const backendCap = Number(options.maxCandidatesCap);
  const allowedCap = Number.isFinite(backendCap) && backendCap > 0
    ? Math.min(Math.floor(backendCap), 10)
    : 5;
  const requested = Number(options.maxCandidatesPerRow);
  const requestedCount = Number.isFinite(requested) && requested > 0
    ? Math.floor(requested)
    : Math.min(5, allowedCap);
  return Math.max(1, Math.min(requestedCount, allowedCap));
}

export async function fetchRankedCandidateCapabilities(jobId) {
  return request(`/filings/jobs/${jobId}/ranked-candidates/capabilities`);
}

export async function runRankedCandidateDryRun(jobId, options = {}) {
  return request(`/filings/jobs/${jobId}/ranked-candidates/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      mode: "dry_run",
      profile: options.profile || "balanced",
      max_candidates_per_row: rankedCandidateMaxCandidates(options),
    }),
  });
}

export async function listSupervisorReviews(jobId) {
  return request(`/filings/jobs/${jobId}/supervisor-reviews`);
}

export async function getSupervisorReview(jobId, reviewId) {
  return request(`/filings/jobs/${jobId}/supervisor-reviews/${reviewId}`);
}

const SUPERVISOR_REVIEW_MODES = new Set(["mock", "live"]);

function supervisorReviewMode(options = {}) {
  const requestedMode = String(options.mode || "mock").toLowerCase();
  return SUPERVISOR_REVIEW_MODES.has(requestedMode) ? requestedMode : "mock";
}

export async function runSupervisorReview(jobId, suggestionId, options = {}) {
  return request(`/filings/jobs/${jobId}/supervisor-reviews/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      llm_mapping_suggestion_id: suggestionId,
      mode: supervisorReviewMode(options),
      force_refresh: Boolean(options.forceRefresh),
    }),
  });
}

export async function runBatchSupervisorReviews(jobId, options = {}) {
  const body = {
    mode: supervisorReviewMode(options),
    force_refresh: Boolean(options.forceRefresh),
  };
  if (Array.isArray(options.suggestionIds)) {
    body.suggestion_ids = [...new Set(options.suggestionIds.map(String))];
  }
  return request(`/filings/jobs/${jobId}/supervisor-reviews/run-batch`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

export async function fetchSupervisorOrchestrationCapabilities(jobId) {
  return request(`/filings/jobs/${jobId}/supervisor-orchestration/capabilities`);
}

export async function fetchSupervisorOrchestrationPlan(jobId) {
  return request(`/filings/jobs/${jobId}/supervisor-orchestration/plan`);
}

export async function fetchSupervisorMapperFeedbackCapabilities(jobId) {
  return request(`/filings/jobs/${jobId}/supervisor-mapper-feedback/capabilities`);
}

export async function listSupervisorGuidedMappingRevisions(jobId) {
  return request(`/filings/jobs/${jobId}/supervisor-guided-mapping-revisions`);
}

export async function remapWithSupervisorFeedback(jobId, suggestionId) {
  return request(
    `/filings/jobs/${jobId}/suggestions/${suggestionId}/remap-with-supervisor-feedback`,
    { method: "POST" },
  );
}

export async function acceptAiMappingSuggestion(itemId, suggestionId) {
  return request(
    `/filings/extracted-data/${itemId}/ai-mapping-suggestions/${suggestionId}/accept`,
    {
      method: "POST",
    },
  );
}

export async function ignoreAiMappingSuggestion(itemId, suggestionId) {
  return request(
    `/filings/extracted-data/${itemId}/ai-mapping-suggestions/${suggestionId}/ignore`,
    {
      method: "POST",
    },
  );
}

export async function uploadJob(formData) {
  return request("/filings/upload", {
    method: "POST",
    body: formData,
  });
}

export async function deleteFilingJob(jobId) {
  return request(`/filings/jobs/${jobId}`, {
    method: "DELETE",
  });
}

export async function fetchDashboardStats() {
  return request("/filings/dashboard/stats");
}

export async function fetchTemplates() {
  return request("/xbrl-templates/");
}

export async function fetchTemplate(templateCode) {
  return request(`/xbrl-templates/${templateCode}`);
}

export async function validateXbrl(jobId) {
  return request(`/filings/jobs/${jobId}/validate-xbrl`);
}

export async function searchTaxonomy(query) {
  return request(`/taxonomy/search?q=${encodeURIComponent(query)}`);
}

export async function fetchTaxonomyStatus() {
  return request("/taxonomy/status");
}

export async function bulkUpdateExtractedItems(items) {
  return request("/filings/extracted-data/bulk-update", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ items }),
  });
}

export async function createExtractedItem(pageId, itemData) {
  return request(`/filings/extracted-data/create?page_id=${pageId}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(itemData),
  });
}

export async function downloadXbrlPackage(jobId) {
  const response = await fetch(
    `${API_BASE}/filings/jobs/${jobId}/download-xbrl?force=true`,
    withAuth(),
  );

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || body.error || detail;
    } catch (error) {
      // Keep fallback detail.
    }
    throw new Error(detail);
  }

  return response.blob();
}

export async function fetchPageImageBlob(jobId, pageNumber) {
  const response = await fetch(
    `${API_BASE}/filings/jobs/${jobId}/pages/${pageNumber}/image`,
    withAuth(),
  );

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || body.error || detail;
    } catch (error) {
      // Keep fallback detail.
    }
    throw new Error(detail);
  }

  return response.blob();
}
