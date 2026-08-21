import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  acceptAiMappingSuggestion,
  adminChangeUserPassword,
  adminClearUserTasks,
  adminDeleteUser,
  AUTH_TOKEN_STORAGE_KEY,
  buildAuthHeaders,
  changePassword,
  clearStoredAuthToken,
  createAdminUser,
  deleteAccount,
  fetchAiMappingSuggestions,
  fetchAiMappingSuggestionsStatus,
  fetchAdminUsers,
  fetchRankedCandidateCapabilities,
  fetchSupervisorOrchestrationCapabilities,
  fetchSupervisorOrchestrationPlan,
  fetchSupervisorMapperFeedbackCapabilities,
  getSupervisorReview,
  getAuthPath,
  getStoredAuthToken,
  ignoreAiMappingSuggestion,
  listSupervisorReviews,
  listSupervisorGuidedMappingRevisions,
  registerUser,
  runBatchSupervisorReviews,
  runAiMappingSuggestions,
  runRankedCandidateDryRun,
  runSupervisorReview,
  remapWithSupervisorFeedback,
  storeAuthToken,
  withAuth,
} from "../src/api.js";
import {
  rankedCandidateRunErrorMessage,
  rankedCandidateSafetyViolation,
} from "../src/ranked-candidate-advisory-ui.js";
import {
  SUPERVISOR_ORCHESTRATION_FILTERS,
  buildSupervisorOrchestrationItemMap,
  eligibleUnreviewedSuggestions,
  filterSuggestionsByOrchestration,
  supervisorOrchestrationSafetyViolation,
} from "../src/supervisor-orchestration-ui.js";

function installStorage() {
  const values = new Map();
  global.window = {
    localStorage: {
      getItem(key) {
        return values.get(key) || null;
      },
      setItem(key, value) {
        values.set(key, String(value));
      },
      removeItem(key) {
        values.delete(key);
      },
    },
  };
  return values;
}

test("auth token storage stores, reads, and clears the bearer token", () => {
  const values = installStorage();

  assert.equal(getStoredAuthToken(), "");
  storeAuthToken("token-123");

  assert.equal(values.get(AUTH_TOKEN_STORAGE_KEY), "token-123");
  assert.equal(getStoredAuthToken(), "token-123");

  clearStoredAuthToken();
  assert.equal(getStoredAuthToken(), "");
});

test("buildAuthHeaders adds bearer auth without replacing explicit authorization", () => {
  const headers = buildAuthHeaders(
    { headers: { "Content-Type": "application/json" } },
    "abc",
  );

  assert.equal(headers.get("Authorization"), "Bearer abc");
  assert.equal(headers.get("Content-Type"), "application/json");

  const explicit = buildAuthHeaders(
    { headers: { Authorization: "Bearer custom" } },
    "abc",
  );
  assert.equal(explicit.get("Authorization"), "Bearer custom");
});

test("withAuth preserves request options and attaches the stored token", () => {
  installStorage();
  storeAuthToken("stored-token");

  const options = withAuth({
    method: "PUT",
    body: "payload",
  });

  assert.equal(options.method, "PUT");
  assert.equal(options.body, "payload");
  assert.equal(options.headers.get("Authorization"), "Bearer stored-token");
});

test("auth paths match the React shell routes", () => {
  assert.equal(getAuthPath(), "/app/login");
  assert.equal(getAuthPath("login"), "/app/login");
  assert.equal(getAuthPath("register"), "/app/login");
});

test("registerUser surfaces the disabled public registration message", async () => {
  const values = installStorage();
  global.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/auth/register");
    assert.equal(options.method, "POST");
    return new Response(
      JSON.stringify({
        detail: "Public registration is disabled. Please contact an administrator.",
      }),
      {
        status: 403,
        headers: { "content-type": "application/json" },
      },
    );
  };

  await assert.rejects(
    () => registerUser({
      email: "user@example.com",
      password: "long-password",
    }),
    /Public registration is disabled\. Please contact an administrator\./,
  );

  assert.equal(values.get(AUTH_TOKEN_STORAGE_KEY), undefined);
  delete global.fetch;
});

test("changePassword uses the authenticated API path", async () => {
  const values = installStorage();
  storeAuthToken("stored-token");
  global.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/auth/change-password");
    assert.equal(options.method, "POST");
    assert.equal(options.headers.get("Authorization"), "Bearer stored-token");
    assert.equal(options.headers.get("Content-Type"), "application/json");
    assert.deepEqual(JSON.parse(options.body), {
      current_password: "old-password",
      new_password: "new-password",
      confirm_password: "new-password",
    });
    return new Response(
      JSON.stringify({
        success: true,
        message: "Password changed successfully.",
      }),
      {
        status: 200,
        headers: { "content-type": "application/json" },
      },
    );
  };

  const result = await changePassword({
    current_password: "old-password",
    new_password: "new-password",
    confirm_password: "new-password",
  });

  assert.equal(result.success, true);
  assert.equal(values.get(AUTH_TOKEN_STORAGE_KEY), undefined);
  delete global.fetch;
});

test("React normal workspace exposes sign out without account dropdown actions", () => {
  const source = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf-8");
  const workspaceHeader = source.slice(
    source.indexOf('<header className="relative z-[100]'),
    source.indexOf('<main className="flex-1 overflow-y-auto'),
  );

  assert.match(workspaceHeader, /Sign Out/);
  assert.match(workspaceHeader, /<LogOut className="h-4 w-4" \/>[\s\S]*Sign Out/);
  assert.match(workspaceHeader, /title="Toggle theme"/);
  assert.doesNotMatch(workspaceHeader, /aria-haspopup="menu"|role="menu"|accountMenuOpen|UserCircle2|Change password|Delete account/);
  assert.match(source, /setCurrentUser\(null\)/);
  assert.match(source, /setAuthMode\("login"\)/);
  assert.match(source, /replaceAppPath\("\/app\/login"\)/);
});

test("React auth screens expose the existing theme toggle without auth token use", () => {
  const source = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf-8");
  const authScreen = source.slice(
    source.indexOf("function AuthScreen"),
    source.indexOf("function replaceAppPath"),
  );

  assert.match(authScreen, /theme,/);
  assert.match(authScreen, /onThemeToggle,/);
  assert.match(authScreen, /title="Toggle theme"/);
  assert.match(authScreen, /aria-label="Toggle theme"/);
  assert.match(authScreen, /theme === "dark"/);
  assert.match(authScreen, /<Sun className="h-4 w-4" \/>/);
  assert.match(authScreen, /<Moon className="h-4 w-4" \/>/);
  assert.match(source, /localStorage\.setItem\("taxonomyflow-theme", theme\)/);
  assert.match(source, /onThemeToggle=\{handleThemeToggle\}/);
  assert.doesNotMatch(authScreen, /getStoredAuthToken|fetchCurrentUser|Authorization|Bearer/);
  assert.doesNotMatch(authScreen, /Create a new account|Create account|UserPlus/);
  assert.doesNotMatch(source, /registerUser/);
});

test("React routes admins to user management and normal users to workspace", () => {
  const source = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf-8");
  const adminSource = readFileSync(
    new URL("../src/admin-user-management.jsx", import.meta.url),
    "utf-8",
  );

  assert.match(source, /AdminUserManagement/);
  assert.match(adminSource, /User Management/);
  assert.match(adminSource, /Manage user accounts and filing data\./);
  assert.match(source, /currentUser\.is_admin/);
  assert.match(source, /user\.is_admin \? "\/app\/admin" : "\/app"/);
  assert.match(source, /result\.user\?\.is_admin \? "\/app\/admin" : "\/app"/);
  assert.match(adminSource, /Sign Out/);
  assert.doesNotMatch(source, /Admin console will be added in the next feature\./);
});

test("admin user management source exposes required controls and task status table headers", () => {
  const adminSource = readFileSync(
    new URL("../src/admin-user-management.jsx", import.meta.url),
    "utf-8",
  );
  const headerMatches = [...adminSource.matchAll(/<th className="[^"]*">([^<]+)<\/th>/g)]
    .map((match) => match[1]);

  assert.match(adminSource, /User Management/);
  assert.match(adminSource, /Create Account/);
  assert.match(adminSource, /Refresh/);
  assert.match(adminSource, /Sign Out/);
  assert.deepEqual(headerMatches, [
    "User Email",
    "Registered Date",
    "Type",
    "Successful Tasks",
    "Processing Tasks",
    "Error Tasks",
  ]);
  assert.doesNotMatch(adminSource, /<th className="[^"]*">Task Count<\/th>/);
  assert.doesNotMatch(adminSource, /<th className="[^"]*">Actions<\/th>/);
  assert.match(adminSource, /aria-label=\{`Open user menu for \$\{user\.email\}`\}/);
  assert.match(adminSource, /Change Password/);
  assert.match(adminSource, /Clear Task Data/);
  assert.match(adminSource, /Delete Account/);
  assert.match(adminSource, /user_type/);
  assert.match(adminSource, /successful_task_count/);
  assert.match(adminSource, /processing_task_count/);
  assert.match(adminSource, /error_task_count/);
  assert.match(adminSource, /users\.filter\(\(user\) => !user\.is_admin && user\.user_type !== "ADMIN"\)/);
  assert.match(adminSource, /No user accounts yet\./);
  assert.match(adminSource, /Create an account to get started\./);
  assert.match(
    adminSource,
    /This will permanently delete all tasks, PDFs, extracted data, generated files, and AI suggestions for this user\. The user account will remain\./,
  );
  assert.match(
    adminSource,
    /This will permanently delete the user account, all tasks, PDFs, extracted data, generated files, and AI suggestions\. This action cannot be undone\./,
  );
});

test("deleteAccount uses the authenticated API path and clears the stored token", async () => {
  const values = installStorage();
  storeAuthToken("stored-token");
  global.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/auth/delete-account");
    assert.equal(options.method, "POST");
    assert.equal(options.headers.get("Authorization"), "Bearer stored-token");
    assert.equal(options.headers.get("Content-Type"), "application/json");
    assert.deepEqual(JSON.parse(options.body), {
      email_confirmation: "user@example.com",
      current_password: "current-password",
      confirm_password: "current-password",
    });
    return new Response(
      JSON.stringify({
        success: true,
        message: "Your account and all filing data have been permanently deleted.",
      }),
      {
        status: 200,
        headers: { "content-type": "application/json" },
      },
    );
  };

  const result = await deleteAccount({
    email_confirmation: "user@example.com",
    current_password: "current-password",
    confirm_password: "current-password",
  });

  assert.equal(result.success, true);
  assert.equal(values.get(AUTH_TOKEN_STORAGE_KEY), undefined);
  delete global.fetch;
});

test("AI mapping suggestion helpers use authenticated filing API paths", async () => {
  installStorage();
  storeAuthToken("stored-token");
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, method: options.method || "GET", auth: options.headers.get("Authorization") });
    return new Response(JSON.stringify({ suggestions: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await fetchAiMappingSuggestions(31);
  await fetchAiMappingSuggestionsStatus(31);
  await runAiMappingSuggestions(31);
  await acceptAiMappingSuggestion("item-1", "suggestion-1");
  await ignoreAiMappingSuggestion("item-1", "suggestion-1");

  assert.deepEqual(calls, [
    {
      url: "/api/v1/filings/jobs/31/ai-mapping-suggestions",
      method: "GET",
      auth: "Bearer stored-token",
    },
    {
      url: "/api/v1/filings/jobs/31/ai-mapping-suggestions/status",
      method: "GET",
      auth: "Bearer stored-token",
    },
    {
      url: "/api/v1/filings/jobs/31/ai-mapping-suggestions/run",
      method: "POST",
      auth: "Bearer stored-token",
    },
    {
      url: "/api/v1/filings/extracted-data/item-1/ai-mapping-suggestions/suggestion-1/accept",
      method: "POST",
      auth: "Bearer stored-token",
    },
    {
      url: "/api/v1/filings/extracted-data/item-1/ai-mapping-suggestions/suggestion-1/ignore",
      method: "POST",
      auth: "Bearer stored-token",
    },
  ]);
  delete global.fetch;
});

test("ranked candidate helpers use authenticated read-only advisory API paths", async () => {
  installStorage();
  storeAuthToken("stored-token");
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({
      url,
      method: options.method || "GET",
      auth: options.headers.get("Authorization"),
      contentType: options.headers.get("Content-Type"),
      body: options.body ? JSON.parse(options.body) : null,
    });
    return new Response(JSON.stringify({ enabled: false, rows: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await fetchRankedCandidateCapabilities(31);
  await runRankedCandidateDryRun(31, {
    profile: "recall",
    maxCandidatesPerRow: 9,
    maxCandidatesCap: 5,
  });

  assert.deepEqual(calls, [
    {
      url: "/api/v1/filings/jobs/31/ranked-candidates/capabilities",
      method: "GET",
      auth: "Bearer stored-token",
      contentType: null,
      body: null,
    },
    {
      url: "/api/v1/filings/jobs/31/ranked-candidates/run",
      method: "POST",
      auth: "Bearer stored-token",
      contentType: "application/json",
      body: {
        mode: "dry_run",
        profile: "recall",
        max_candidates_per_row: 5,
      },
    },
  ]);
  delete global.fetch;
});

test("ranked candidate dry-run helper defaults to balanced dry-run mode", async () => {
  installStorage();
  storeAuthToken("stored-token");
  let requestBody = null;
  global.fetch = async (_url, options) => {
    requestBody = JSON.parse(options.body);
    return new Response(JSON.stringify({ rows: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await runRankedCandidateDryRun(31);

  assert.deepEqual(requestBody, {
    mode: "dry_run",
    profile: "balanced",
    max_candidates_per_row: 5,
  });
  delete global.fetch;
});

test("ranked candidate UI safety guard blocks every unsafe response shape", () => {
  const safeResult = {
    safety: {
      safe_for_auto_apply_count: 0,
      confirmed_tag_id_mutations: 0,
      final_mapping_mutations: 0,
      persistence_writes: 0,
      ai_suggestion_table_writes: 0,
    },
    rows: [{ candidates: [{ safe_for_auto_apply: false, requires_human_review: true, recommended_action: "review_candidate" }] }],
  };
  assert.equal(rankedCandidateSafetyViolation(safeResult), false);

  for (const unsafeResult of [
    { ...safeResult, safety: { ...safeResult.safety, safe_for_auto_apply_count: 1 } },
    { ...safeResult, safety: { ...safeResult.safety, confirmed_tag_id_mutations: 1 } },
    { ...safeResult, safety: { ...safeResult.safety, final_mapping_mutations: 1 } },
    { ...safeResult, safety: { ...safeResult.safety, persistence_writes: 1 } },
    { ...safeResult, rows: [{ candidates: [{ safe_for_auto_apply: true, requires_human_review: true, recommended_action: "review_candidate" }] }] },
    { ...safeResult, rows: [{ candidates: [{ safe_for_auto_apply: false, requires_human_review: false, recommended_action: "review_candidate" }] }] },
    { ...safeResult, rows: [{ candidates: [{ safe_for_auto_apply: false, requires_human_review: true, recommended_action: "apply" }] }] },
  ]) {
    assert.equal(rankedCandidateSafetyViolation(unsafeResult), true);
  }
});

test("ranked candidate UI error copy fails closed for expected smoke failures", () => {
  assert.match(rankedCandidateRunErrorMessage(new Error("HTTP 403")), /disabled by the backend/);
  assert.match(rankedCandidateRunErrorMessage(new Error("Ranked candidate taxonomy metadata is unavailable.")), /local ranked-candidate artifacts are unavailable/);
  assert.match(rankedCandidateRunErrorMessage(new Error("Unknown ranked candidate profile: unsafe")), /not supported by the backend/);
  assert.match(rankedCandidateRunErrorMessage(new Error("Failed to fetch")), /could not reach the backend/);
});

test("Supervisor review helpers use authenticated filing API paths with explicit modes", async () => {
  installStorage();
  storeAuthToken("stored-token");
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({
      url,
      method: options.method || "GET",
      auth: options.headers.get("Authorization"),
      contentType: options.headers.get("Content-Type"),
      body: options.body ? JSON.parse(options.body) : null,
    });
    return new Response(JSON.stringify([]), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await listSupervisorReviews(31);
  await getSupervisorReview(31, "review-1");
  await runSupervisorReview(31, "suggestion-1");
  await runBatchSupervisorReviews(31);
  await runSupervisorReview(31, "suggestion-live", { mode: "live", forceRefresh: true });
  await runBatchSupervisorReviews(31, { mode: "live", forceRefresh: true });
  await fetchSupervisorMapperFeedbackCapabilities(31);
  await listSupervisorGuidedMappingRevisions(31);
  await remapWithSupervisorFeedback(31, "suggestion-live");

  assert.deepEqual(calls, [
    {
      url: "/api/v1/filings/jobs/31/supervisor-reviews",
      method: "GET",
      auth: "Bearer stored-token",
      contentType: null,
      body: null,
    },
    {
      url: "/api/v1/filings/jobs/31/supervisor-reviews/review-1",
      method: "GET",
      auth: "Bearer stored-token",
      contentType: null,
      body: null,
    },
    {
      url: "/api/v1/filings/jobs/31/supervisor-reviews/run",
      method: "POST",
      auth: "Bearer stored-token",
      contentType: "application/json",
      body: {
        llm_mapping_suggestion_id: "suggestion-1",
        mode: "mock",
        force_refresh: false,
      },
    },
    {
      url: "/api/v1/filings/jobs/31/supervisor-reviews/run-batch",
      method: "POST",
      auth: "Bearer stored-token",
      contentType: "application/json",
      body: {
        mode: "mock",
        force_refresh: false,
      },
    },
    {
      url: "/api/v1/filings/jobs/31/supervisor-reviews/run",
      method: "POST",
      auth: "Bearer stored-token",
      contentType: "application/json",
      body: {
        llm_mapping_suggestion_id: "suggestion-live",
        mode: "live",
        force_refresh: true,
      },
    },
    {
      url: "/api/v1/filings/jobs/31/supervisor-reviews/run-batch",
      method: "POST",
      auth: "Bearer stored-token",
      contentType: "application/json",
      body: {
        mode: "live",
        force_refresh: true,
      },
    },
    {
      url: "/api/v1/filings/jobs/31/supervisor-mapper-feedback/capabilities",
      method: "GET",
      auth: "Bearer stored-token",
      contentType: null,
      body: null,
    },
    {
      url: "/api/v1/filings/jobs/31/supervisor-guided-mapping-revisions",
      method: "GET",
      auth: "Bearer stored-token",
      contentType: null,
      body: null,
    },
    {
      url: "/api/v1/filings/jobs/31/suggestions/suggestion-live/remap-with-supervisor-feedback",
      method: "POST",
      auth: "Bearer stored-token",
      contentType: null,
      body: null,
    },
  ]);
  delete global.fetch;
});

test("Supervisor orchestration helpers use authenticated read-only paths and ID-bounded batch payloads", async () => {
  installStorage();
  storeAuthToken("stored-token");
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({
      url,
      method: options.method || "GET",
      auth: options.headers.get("Authorization"),
      body: options.body ? JSON.parse(options.body) : null,
    });
    return new Response(JSON.stringify({}), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await fetchSupervisorOrchestrationCapabilities(31);
  await fetchSupervisorOrchestrationPlan(31);
  await runBatchSupervisorReviews(31, {
    mode: "live",
    suggestionIds: ["suggestion-2", "suggestion-1", "suggestion-2"],
  });

  assert.deepEqual(calls, [
    {
      url: "/api/v1/filings/jobs/31/supervisor-orchestration/capabilities",
      method: "GET",
      auth: "Bearer stored-token",
      body: null,
    },
    {
      url: "/api/v1/filings/jobs/31/supervisor-orchestration/plan",
      method: "GET",
      auth: "Bearer stored-token",
      body: null,
    },
    {
      url: "/api/v1/filings/jobs/31/supervisor-reviews/run-batch",
      method: "POST",
      auth: "Bearer stored-token",
      body: {
        mode: "live",
        force_refresh: false,
        suggestion_ids: ["suggestion-2", "suggestion-1"],
      },
    },
  ]);
  delete global.fetch;
});

test("Supervisor orchestration filters isolate eligible unreviewed and terminal states", () => {
  const suggestions = [
    { id: "eligible-high", status: "rejected" },
    { id: "eligible-medium", status: "suggested" },
    { id: "reviewed", status: "suggested" },
    { id: "remapping", status: "suggested" },
    { id: "remapping-blocked", status: "rejected" },
    { id: "revised", status: "suggested" },
    { id: "not-eligible", status: "suggested" },
    { id: "accepted", status: "accepted" },
    { id: "ignored", status: "ignored" },
  ];
  const itemMap = buildSupervisorOrchestrationItemMap([
    {
      suggestion_id: "eligible-high",
      mapper_status: "rejected",
      is_human_terminal: false,
      supervisor_eligibility: "eligible",
      supervisor_review_executable: true,
      supervisor_action_block_reason: null,
      batch_review_executable: true,
      priority: "high",
      remapping_eligible: false,
      remapping_executable: false,
      blocking_reasons: [],
    },
    {
      suggestion_id: "reviewed",
      mapper_status: "suggested",
      is_human_terminal: false,
      supervisor_eligibility: "already_reviewed",
      supervisor_review_executable: false,
      supervisor_action_block_reason: "already_reviewed",
      batch_review_executable: false,
      priority: "medium",
      existing_supervisor_review_id: "review-1",
      remapping_eligible: false,
      remapping_executable: false,
      blocking_reasons: [],
    },
    {
      suggestion_id: "eligible-medium",
      mapper_status: "suggested",
      is_human_terminal: false,
      supervisor_eligibility: "eligible",
      supervisor_review_executable: true,
      supervisor_action_block_reason: null,
      batch_review_executable: true,
      priority: "medium",
      remapping_eligible: false,
      remapping_executable: false,
      blocking_reasons: [],
    },
    {
      suggestion_id: "remapping",
      mapper_status: "suggested",
      is_human_terminal: false,
      supervisor_eligibility: "already_reviewed",
      supervisor_review_executable: false,
      supervisor_action_block_reason: "already_reviewed",
      batch_review_executable: false,
      priority: "medium",
      existing_supervisor_review_id: "review-2",
      remapping_eligibility: "remapping_available",
      remapping_eligible: true,
      remapping_executable: true,
      remapping_action_block_reason: null,
      blocking_reasons: [],
    },
    {
      suggestion_id: "remapping-blocked",
      mapper_status: "rejected",
      is_human_terminal: false,
      supervisor_eligibility: "already_reviewed",
      supervisor_review_executable: false,
      supervisor_action_block_reason: "already_reviewed",
      batch_review_executable: false,
      priority: "medium",
      existing_supervisor_review_id: "review-4",
      remapping_eligibility: "remapping_not_executable",
      remapping_eligible: false,
      remapping_executable: false,
      remapping_action_block_reason: "concrete_suggestion_required",
      blocking_reasons: [],
    },
    {
      suggestion_id: "revised",
      mapper_status: "suggested",
      is_human_terminal: false,
      supervisor_eligibility: "already_reviewed",
      supervisor_review_executable: false,
      supervisor_action_block_reason: "already_reviewed",
      batch_review_executable: false,
      priority: "high",
      existing_supervisor_review_id: "review-3",
      existing_revision_id: "revision-1",
      remapping_eligible: false,
      remapping_executable: false,
      blocking_reasons: [],
    },
    {
      suggestion_id: "not-eligible",
      mapper_status: "suggested",
      is_human_terminal: false,
      supervisor_eligibility: "not_eligible",
      supervisor_review_executable: false,
      supervisor_action_block_reason: "policy_not_eligible",
      batch_review_executable: false,
      priority: "none",
      remapping_eligible: false,
      remapping_executable: false,
      blocking_reasons: [],
    },
    {
      suggestion_id: "accepted",
      mapper_status: "accepted",
      is_human_terminal: true,
      supervisor_eligibility: "terminal",
      supervisor_review_executable: false,
      supervisor_action_block_reason: "human_terminal",
      batch_review_executable: false,
      priority: "none",
      remapping_eligible: false,
      remapping_executable: false,
      blocking_reasons: [],
    },
    {
      suggestion_id: "ignored",
      mapper_status: "ignored",
      is_human_terminal: true,
      supervisor_eligibility: "terminal",
      supervisor_review_executable: false,
      supervisor_action_block_reason: "human_terminal",
      batch_review_executable: false,
      priority: "none",
      remapping_eligible: false,
      remapping_executable: false,
      blocking_reasons: [],
    },
  ]);

  assert.deepEqual(
    eligibleUnreviewedSuggestions(suggestions, itemMap).map((row) => row.id),
    ["eligible-high", "eligible-medium"],
  );
  assert.deepEqual(
    filterSuggestionsByOrchestration(suggestions, itemMap, "medium").map((row) => row.id),
    ["eligible-medium"],
  );
  assert.deepEqual(
    filterSuggestionsByOrchestration(suggestions, itemMap, "high").map((row) => row.id),
    ["eligible-high"],
  );
  assert.deepEqual(
    filterSuggestionsByOrchestration(suggestions, itemMap, "reviewed").map((row) => row.id),
    ["reviewed", "remapping", "remapping-blocked", "revised"],
  );
  assert.deepEqual(
    filterSuggestionsByOrchestration(suggestions, itemMap, "remapping").map((row) => row.id),
    ["remapping"],
  );
  assert.deepEqual(
    filterSuggestionsByOrchestration(suggestions, itemMap, "revised").map((row) => row.id),
    ["revised"],
  );
  assert.deepEqual(
    filterSuggestionsByOrchestration(suggestions, itemMap, "not_eligible").map((row) => row.id),
    ["not-eligible", "accepted", "ignored"],
  );
  assert.deepEqual(
    SUPERVISOR_ORCHESTRATION_FILTERS.map((filter) => filter.label),
    [
      "All suggestions",
      "Supervisor eligible",
      "High priority",
      "Medium priority",
      "Already reviewed",
      "Remapping available",
      "Revision completed",
      "Not eligible",
    ],
  );
});

test("Supervisor orchestration safety validation fails closed on automatic behavior", () => {
  const capabilities = {
    plan_only: true,
    mode: "manual",
    auto_review: false,
    auto_remap: false,
    unsafe_configuration_reasons: [],
  };
  const plan = {
    orchestration_enabled: true,
    mode: "plan_only",
    eligible_count: 1,
    policy_eligible_count: 1,
    review_executable_count: 1,
    batch_review_executable_count: 1,
    high_priority_count: 1,
    medium_priority_count: 0,
    already_reviewed_count: 0,
    not_eligible_count: 0,
    remapping_executable_count: 0,
    revision_completed_count: 0,
    safety_summary: {
      planning_live_calls: 0,
      auto_review_calls: 0,
      auto_remap_calls: 0,
      confirmed_tag_id_mutations: 0,
      final_mapping_mutations: 0,
      safe_for_auto_apply_count: 0,
      human_review_required: true,
    },
    items: [
      {
        mapper_status: "rejected",
        is_human_terminal: false,
        supervisor_eligibility: "eligible",
        priority: "high",
        supervisor_review_executable: true,
        supervisor_action_block_reason: null,
        batch_review_executable: true,
        remapping_eligible: false,
        remapping_executable: false,
        remapping_action_block_reason: "concrete_suggestion_required",
        requires_human_review: true,
        safe_for_auto_apply: false,
      },
    ],
  };

  assert.equal(supervisorOrchestrationSafetyViolation(capabilities, plan), "");
  assert.match(
    supervisorOrchestrationSafetyViolation(
      capabilities,
      {
        ...plan,
        safety_summary: { ...plan.safety_summary, auto_review_calls: 1 },
      },
    ),
    /unsafe automatic call or mapping mutation/,
  );
  assert.match(
    supervisorOrchestrationSafetyViolation(
      capabilities,
      {
        ...plan,
        items: [{ ...plan.items[0], safe_for_auto_apply: true }],
      },
    ),
    /non-advisory/,
  );
  assert.match(
    supervisorOrchestrationSafetyViolation(
      capabilities,
      {
        ...plan,
        remapping_executable_count: 1,
        items: [
          {
            ...plan.items[0],
            remapping_eligible: true,
            remapping_executable: true,
            remapping_action_block_reason: null,
          },
        ],
      },
    ),
    /contradict persisted queue state/,
  );
});

test("admin user management helpers use authenticated admin API paths", async () => {
  installStorage();
  storeAuthToken("stored-token");
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({
      url,
      method: options.method || "GET",
      auth: options.headers.get("Authorization"),
      contentType: options.headers.get("Content-Type"),
      body: options.body ? JSON.parse(options.body) : null,
    });
    return new Response(JSON.stringify({ success: true, users: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await fetchAdminUsers();
  await createAdminUser({
    email: "user@example.com",
    password: "new-password",
    confirm_password: "new-password",
  });
  await adminChangeUserPassword(12, {
    new_password: "changed-password",
    confirm_password: "changed-password",
  });
  await adminClearUserTasks(12);
  await adminDeleteUser(12);

  assert.deepEqual(calls, [
    {
      url: "/api/v1/admin/users",
      method: "GET",
      auth: "Bearer stored-token",
      contentType: null,
      body: null,
    },
    {
      url: "/api/v1/admin/users",
      method: "POST",
      auth: "Bearer stored-token",
      contentType: "application/json",
      body: {
        email: "user@example.com",
        password: "new-password",
        confirm_password: "new-password",
      },
    },
    {
      url: "/api/v1/admin/users/12/change-password",
      method: "POST",
      auth: "Bearer stored-token",
      contentType: "application/json",
      body: {
        new_password: "changed-password",
        confirm_password: "changed-password",
      },
    },
    {
      url: "/api/v1/admin/users/12/clear-tasks",
      method: "POST",
      auth: "Bearer stored-token",
      contentType: null,
      body: null,
    },
    {
      url: "/api/v1/admin/users/12",
      method: "DELETE",
      auth: "Bearer stored-token",
      contentType: null,
      body: null,
    },
  ]);
  delete global.fetch;
});

test("React review workspace exposes AI suggestion confirmation controls", () => {
  const source = readFileSync(new URL("../src/review-workspace.jsx", import.meta.url), "utf-8");

  assert.match(source, /AI Mapping Suggestions/);
  assert.match(source, /VITE_SHOW_AI_SUGGESTION_PANEL/);
  assert.match(source, /SHOW_AI_SUGGESTION_PANEL \? \(/);
  assert.doesNotMatch(source, /Run AI Mapping Suggestions/);
  assert.doesNotMatch(source, /handleRunAiSuggestions|runningAiSuggestions/);
  assert.match(source, /fetchAiMappingSuggestionsStatus/);
  assert.match(source, /AI mapping suggestions are being generated\.\.\./);
  assert.match(source, /AI mapping suggestions will appear automatically after processing\./);
  assert.match(source, /No AI suggestions were generated\./);
  assert.match(source, /AI provider is temporarily rate limited\. Please wait a few minutes and try again\./);
  assert.match(source, /AI mapping suggestions could not be generated automatically\./);
  assert.match(source, /window\.setInterval/);
  assert.match(source, /const shouldPollAiSuggestions =/);
  assert.match(source, /aiMappingStatusValue === "running"/);
  assert.match(source, /aiMappingStatusValue === "not_started" \|\| aiMappingStatusValue === "completed"/);
  assert.match(source, /nextStatus\.ai_mapping_status === "completed"/);
  assert.match(source, /AI suggestion/);
  assert.match(source, /Requires confirmation/);
  assert.match(source, /High confidence/);
  assert.match(source, /Medium confidence/);
  assert.match(source, /Low confidence/);
  assert.match(source, /Pending AI suggestions/);
  assert.match(source, /Accepted AI suggestions/);
  assert.match(source, /Rejected AI suggestions/);
  assert.match(source, /No safe AI mapping \/ rejected/);
  assert.match(source, /Accept suggestion/);
  assert.match(source, /Reject/);
  assert.match(source, /confidenceChipLabel/);
  assert.match(source, /No safe AI suggestion/);
  assert.match(source, /acceptAiMappingSuggestion/);
  assert.match(source, /ignoreAiMappingSuggestion/);
});

test("React review workspace gates Supervisor controls with frontend visibility flags", () => {
  const source = readFileSync(new URL("../src/review-workspace.jsx", import.meta.url), "utf-8");
  const envExample = readFileSync(new URL("../.env.example", import.meta.url), "utf-8");
  const panelSource = source.slice(
    source.indexOf("function AiMappingSuggestionsPanel"),
    source.indexOf("export function ReviewWorkspace"),
  );

  assert.match(source, /VITE_SHOW_AI_SUGGESTION_PANEL/);
  assert.match(source, /VITE_SHOW_SUPERVISOR_LIVE_CONTROLS/);
  assert.match(source, /const SHOW_AI_SUGGESTION_PANEL = readFrontendFlag\("VITE_SHOW_AI_SUGGESTION_PANEL", true\)/);
  assert.match(source, /const SHOW_SUPERVISOR_LIVE_CONTROLS = readFrontendFlag\("VITE_SHOW_SUPERVISOR_LIVE_CONTROLS", false\)/);
  assert.match(panelSource, /showSupervisorLiveControls/);
  assert.match(panelSource, /Run Supervisor review/);
  assert.match(panelSource, /Run Supervisor reviews for all/);
  assert.doesNotMatch(source, /SHOW_SUPERVISOR_MOCK_CONTROLS/);
  assert.doesNotMatch(panelSource, /showSupervisorTestControls/);
  assert.doesNotMatch(panelSource, /Run mock Supervisor review/);
  assert.doesNotMatch(panelSource, /Run mock Supervisor reviews for all/);
  assert.doesNotMatch(panelSource, /Run live Supervisor review/);
  assert.match(panelSource, /test-stage visibility controls only/);
  assert.match(panelSource, /backend feature flag and permissions remain authoritative/);
  assert.match(envExample, /VITE_SHOW_AI_SUGGESTION_PANEL=true/);
  assert.match(envExample, /VITE_SHOW_SUPERVISOR_MOCK_CONTROLS=false/);
  assert.match(envExample, /application renders no mock controls/);
  assert.match(envExample, /VITE_SHOW_SUPERVISOR_LIVE_CONTROLS=false/);
  assert.match(envExample, /not security controls/);
});

test("React review workspace integrates a disabled-by-default read-only Supervisor orchestration queue", () => {
  const source = readFileSync(new URL("../src/review-workspace.jsx", import.meta.url), "utf-8");
  const envExample = readFileSync(new URL("../.env.example", import.meta.url), "utf-8");
  const panelSource = source.slice(
    source.indexOf("function AiMappingSuggestionsPanel"),
    source.indexOf("export function ReviewWorkspace"),
  );
  const planLoaderSource = source.slice(
    source.indexOf("const reloadSupervisorOrchestration"),
    source.indexOf("useEffect(() =>", source.indexOf("const reloadSupervisorOrchestration")),
  );
  const actionSource = source.slice(
    source.indexOf("const handleRunSupervisorReview"),
    source.indexOf("const handleSave"),
  );

  assert.match(source, /VITE_SHOW_SUPERVISOR_ORCHESTRATION_QUEUE/);
  assert.match(source, /const SHOW_SUPERVISOR_ORCHESTRATION_QUEUE = readFrontendFlag\([\s\S]*false/);
  assert.match(envExample, /VITE_SHOW_SUPERVISOR_ORCHESTRATION_QUEUE=false/);
  assert.match(source, /fetchSupervisorOrchestrationCapabilities\(job\.id\)/);
  assert.match(source, /fetchSupervisorOrchestrationPlan\(job\.id\)/);
  assert.doesNotMatch(planLoaderSource, /runSupervisorReview|runBatchSupervisorReviews|remapWithSupervisorFeedback|acceptAiMappingSuggestion|ignoreAiMappingSuggestion/);
  assert.match(panelSource, /Supervisor review queue/);
  assert.match(panelSource, /SUPERVISOR_ORCHESTRATION_FILTERS\.map/);
  assert.match(panelSource, /Supervisor orchestration eligibility/);
  assert.match(panelSource, /Structural review signals indicate review priority only/);
  assert.match(panelSource, /Eligibility reasons:/);
  assert.match(panelSource, /Blocking reasons:/);
  assert.match(panelSource, /Human review required\. No automatic action is permitted\./);
  assert.match(panelSource, /Supervisor orchestration is disabled by the backend/);
  assert.match(panelSource, /Safety warning:/);
  assert.match(panelSource, /Run Supervisor reviews for eligible suggestions/);
  assert.match(panelSource, /boundedEligibleBatchSuggestions\.map/);
  assert.match(actionSource, /suggestionIds/);
  assert.match(actionSource, /eligible, unreviewed suggestions/);
  assert.match(actionSource, /reloadSupervisorOrchestration/);
  assert.doesNotMatch(panelSource, /confirmed_tag_id/);
});

test("React review workspace exposes a gated read-only ranked candidate dry-run panel", () => {
  const source = readFileSync(new URL("../src/review-workspace.jsx", import.meta.url), "utf-8");
  const envExample = readFileSync(new URL("../.env.example", import.meta.url), "utf-8");
  const panelSource = source.slice(
    source.indexOf("function RankedCandidateTestPanel"),
    source.indexOf("function AiMappingSuggestionsPanel"),
  );

  assert.match(source, /VITE_SHOW_RANKED_CANDIDATE_TEST_PANEL/);
  assert.match(source, /const SHOW_RANKED_CANDIDATE_TEST_PANEL = readFrontendFlag\([\s\S]*"VITE_SHOW_RANKED_CANDIDATE_TEST_PANEL"[\s\S]*false/);
  assert.match(source, /SHOW_RANKED_CANDIDATE_TEST_PANEL \? \(/);
  assert.match(envExample, /VITE_SHOW_RANKED_CANDIDATE_TEST_PANEL=false/);
  assert.match(source, /<RankedCandidateTestPanel jobId=\{job\.id\} \/>/);
  assert.match(panelSource, /fetchRankedCandidateCapabilities\(jobId\)/);
  assert.match(panelSource, /runRankedCandidateDryRun\(jobId/);
  assert.match(panelSource, /Run Ranked Candidate Dry-Run/);
  assert.match(panelSource, /Internal test-only preview\. Ranked candidates are advisory only\. Dry-run preview only\. Human review required\. No auto-apply\. No confirmed_tag_id mutation\. No final mapping mutation\./);
  assert.match(panelSource, /Running dry-run preview/);
  assert.match(panelSource, /Ranked candidate advisory is disabled by the backend/);
  assert.match(source, /rankedCandidateRunErrorMessage/);
  assert.match(panelSource, /rankedCandidateSafetyViolation/);
  assert.match(panelSource, /safe_for_auto_apply_count/);
  assert.match(panelSource, /confirmed_tag_id mutations/);
  assert.match(panelSource, /Final mapping mutations/);
  assert.match(panelSource, /Persistence writes/);
  assert.match(panelSource, /AI suggestion writes/);
  assert.match(panelSource, /Recommended action:.*read-only label/);
  assert.match(panelSource, /Candidate rows are not rendered as actionable results/);
  assert.match(panelSource, /No ranked candidates are available for this dry-run/);
  assert.doesNotMatch(panelSource, /acceptAiMappingSuggestion|ignoreAiMappingSuggestion|bulkUpdateExtractedItems|createExtractedItem|confirmed_tag_id:\s*/);
  assert.doesNotMatch(panelSource, /<button[^>]*>[\s\S]*?(Apply|Accept|Confirm|Save Mapping|Auto-map)/);
});

test("React review workspace displays persisted Supervisor reviews as advisory only", () => {
  const source = readFileSync(new URL("../src/review-workspace.jsx", import.meta.url), "utf-8");
  const panelSource = source.slice(
    source.indexOf("function AiMappingSuggestionsPanel"),
    source.indexOf("export function ReviewWorkspace"),
  );
  const supervisorHandlerSource = source.slice(
    source.indexOf("const handleRunSupervisorReview"),
    source.indexOf("const handleAcceptAiSuggestion"),
  );

  assert.match(source, /listSupervisorReviews/);
  assert.match(source, /runSupervisorReview/);
  assert.match(source, /runBatchSupervisorReviews/);
  assert.match(source, /buildSupervisorReviewMap/);
  assert.match(source, /supervisorReviewsBySuggestion\[suggestion\.id\]/);
  assert.match(source, /Supervisor: Safe to accept \(advisory\)/);
  assert.match(source, /Supervisor: Review needed/);
  assert.match(source, /Supervisor: High risk/);
  assert.match(source, /Supervisor: Better candidate needed/);
  assert.match(source, /Supervisor: Unsupported candidate/);
  assert.match(source, /Supervisor: Ambiguous label/);
  assert.match(panelSource, /Supervisor advisory details/);
  assert.match(panelSource, /Decision:/);
  assert.match(panelSource, /Risk:/);
  assert.match(panelSource, /Recommended action:/);
  assert.match(panelSource, /Safe to accept:/);
  assert.match(panelSource, /Calibrated safe:/);
  assert.match(panelSource, /advisory only/);
  assert.match(panelSource, /safeWithheldExplanation/);
  assert.match(source, /Safe flag withheld by guardrail/);
  assert.match(source, /Safe flag withheld by Supervisor response/);
  assert.match(panelSource, /Issues:/);
  assert.match(panelSource, /Reason:/);
  assert.match(panelSource, /Source:/);
  assert.match(panelSource, /Model:/);
  assert.match(panelSource, /Run Supervisor review/);
  assert.match(panelSource, /Run Supervisor reviews for all/);
  assert.doesNotMatch(panelSource, /Run mock Supervisor review/);
  assert.doesNotMatch(panelSource, /Run mock Supervisor reviews for all/);
  assert.doesNotMatch(panelSource, /Run live Supervisor review/);
  assert.match(source, /window\.confirm/);
  assert.match(source, /normalizeSupervisorReviewMode/);
  assert.match(source, /runSupervisorReview\(job\.id, suggestion\.id, \{ mode: normalizedMode \}\)/);
  assert.match(source, /runBatchSupervisorReviews\(job\.id, options\)/);
  assert.match(source, /Mock Supervisor advisory review completed\. No mapping was applied automatically\./);
  assert.match(source, /Mock Supervisor advisory reviews completed\. No mappings were applied automatically\./);
  assert.match(source, /Live Supervisor advisory review completed\. No mapping was applied automatically\./);
  assert.match(source, /Live Supervisor advisory reviews completed\. No mappings were applied automatically\./);
  assert.match(source, /Supervisor advisory reviews could not be loaded\./);
  assert.match(source, /No Supervisor review yet\. Run a live advisory review to see Supervisor status\./);
  assert.doesNotMatch(panelSource, /raw_payload|raw_prompt|raw_response|auditor_xml|parsed_xml|gold_answer|target_correct_qname|evaluation_label|confirmed_tag_id/);
  assert.doesNotMatch(supervisorHandlerSource, /acceptAiMappingSuggestion|ignoreAiMappingSuggestion|bulkUpdateExtractedItems|confirmed_tag_id|template_field_id|is_reviewed/);
});

test("React review workspace exposes only bounded manual Supervisor-guided remapping", () => {
  const source = readFileSync(new URL("../src/review-workspace.jsx", import.meta.url), "utf-8");
  const envExample = readFileSync(new URL("../.env.example", import.meta.url), "utf-8");
  const panelSource = source.slice(
    source.indexOf("function AiMappingSuggestionsPanel"),
    source.indexOf("export function ReviewWorkspace"),
  );
  const supervisorRunHandlerSource = source.slice(
    source.indexOf("const handleRunSupervisorReview"),
    source.indexOf("const handleRunBatchSupervisorReviews"),
  );
  const supervisorBatchHandlerSource = source.slice(
    source.indexOf("const handleRunBatchSupervisorReviews"),
    source.indexOf("const handleRemapWithSupervisorFeedback"),
  );
  const correctionHandlerSource = source.slice(
    source.indexOf("const handleRemapWithSupervisorFeedback"),
    source.indexOf("const handleAcceptAiSuggestion"),
  );
  const primaryActionsSource = panelSource.slice(
    panelSource.indexOf('className="suggestion-primary-actions'),
    panelSource.indexOf('className="suggestion-secondary-actions'),
  );
  const secondaryActionsSource = panelSource.slice(
    panelSource.indexOf('className="suggestion-secondary-actions'),
    panelSource.indexOf('className="rounded-lg border border-slate-200/70'),
  );
  const suggestionHeaderSource = panelSource.slice(
    panelSource.indexOf('className="suggestion-card-header'),
    panelSource.indexOf('className="rounded-lg border border-slate-200/70'),
  );
  const actionColumnSource = suggestionHeaderSource.slice(
    suggestionHeaderSource.indexOf('className="suggestion-action-column'),
  );

  assert.match(source, /VITE_SHOW_SUPERVISOR_MAPPER_FEEDBACK/);
  assert.match(source, /const SHOW_SUPERVISOR_MAPPER_FEEDBACK = readFrontendFlag\([\s\S]*false/);
  assert.match(envExample, /VITE_SHOW_SUPERVISOR_MAPPER_FEEDBACK=false/);
  assert.match(primaryActionsSource, /Accept suggestion/);
  assert.match(primaryActionsSource, /Reject/);
  assert.match(primaryActionsSource, /Run Supervisor review/);
  assert.doesNotMatch(primaryActionsSource, /Re-run mapping with Supervisor feedback/);
  assert.match(secondaryActionsSource, /Re-run mapping with Supervisor feedback/);
  assert.match(secondaryActionsSource, /suggestion-secondary-actions flex min-h-0 max-w-full flex-wrap items-center justify-end/);
  assert.match(panelSource, /const showCorrectionSecondaryRow = showCorrectionAction \|\| correctionCompleted/);
  assert.match(panelSource, /\{showCorrectionSecondaryRow \? \([\s\S]*suggestion-secondary-actions/);
  assert.match(suggestionHeaderSource, /suggestion-card-header grid min-w-0 gap-3 sm:grid-cols-\[minmax\(0,1fr\)_auto\] sm:items-start/);
  assert.match(suggestionHeaderSource, /suggestion-card-summary min-w-0 space-y-2/);
  assert.match(actionColumnSource, /suggestion-action-column flex min-w-0 max-w-full flex-col items-end gap-2[\s\S]*suggestion-primary-actions[\s\S]*\{showCorrectionSecondaryRow \? \([\s\S]*suggestion-secondary-actions/);
  assert.doesNotMatch(suggestionHeaderSource, /suggestion-action-stack/);
  assert.doesNotMatch(secondaryActionsSource, / w-full(?: |")|col-span|grid-column/);
  assert.match(panelSource, /supervisorCorrectionEligibility\(supervisorReview\)/);
  assert.match(source, /review\.review_status !== "completed"/);
  assert.match(source, /review\.supervisor_decision === "agree"/);
  assert.match(secondaryActionsSource, /Correction attempt \{latestRevision\.correction_attempt\} completed/);
  assert.match(panelSource, /const correctionCompleted = latestRevision\?\.status === "completed"/);
  assert.match(secondaryActionsSource, /disabled=\{correctionBusy \|\| correctionRetryReached\}/);
  assert.doesNotMatch(supervisorRunHandlerSource, /confirmBatchSupervisorRun|window\.confirm/);
  assert.doesNotMatch(correctionHandlerSource, /confirmBatchSupervisorRun|window\.confirm/);
  assert.match(supervisorBatchHandlerSource, /confirmBatchSupervisorRun/);
  assert.match(source, /function confirmBatchSupervisorRun\(message\)[\s\S]*window\.confirm/);
  assert.match(panelSource, /Running Supervisor review\.\.\./);
  assert.match(panelSource, /Re-running mapping\.\.\./);
  assert.match(supervisorRunHandlerSource, /supervisorReviewPendingIds\.has\(suggestion\.id\)/);
  assert.match(supervisorRunHandlerSource, /supervisorReviewPendingIds\.add\(suggestion\.id\)/);
  assert.match(supervisorRunHandlerSource, /finally \{[\s\S]*supervisorReviewPendingIds\.delete\(suggestion\.id\)[\s\S]*setSupervisorReviewActionId\(""\)/);
  assert.match(correctionHandlerSource, /supervisorCorrectionPendingIds\.has\(suggestion\.id\)/);
  assert.match(correctionHandlerSource, /supervisorCorrectionPendingIds\.add\(suggestion\.id\)/);
  assert.match(correctionHandlerSource, /finally \{[\s\S]*supervisorCorrectionPendingIds\.delete\(suggestion\.id\)[\s\S]*setSupervisorCorrectionActionId\(""\)/);
  assert.match(correctionHandlerSource, /remapWithSupervisorFeedback\(job\.id, suggestion\.id\)/);
  assert.match(panelSource, /Initial suggestion/);
  assert.match(panelSource, /Revised suggestion/);
  assert.match(panelSource, /What changed:/);
  assert.match(panelSource, /original_suggested_qname === latestRevision\.revised_suggested_qname/);
  assert.match(panelSource, /Original suggestion retained after Supervisor-guided review\./);
  assert.match(panelSource, /\{"\\u2192"\}/);
  assert.doesNotMatch(panelSource, /original_suggested_qname \|\| "No initial concept"\} to/);
  assert.match(panelSource, /Correction attempt/);
  assert.match(panelSource, /Addressed Supervisor issues:/);
  assert.match(panelSource, /Remaining ambiguities:/);
  assert.match(panelSource, /Human review required/);
  assert.match(panelSource, /onClick=\{\(\) => onRunSupervisorReview\(suggestion, "live"\)\}/);
  assert.doesNotMatch(panelSource, /Run mock Supervisor review/);
  assert.match(envExample, /VITE_SHOW_SUPERVISOR_MOCK_CONTROLS=false/);
  assert.doesNotMatch(supervisorRunHandlerSource, /remapWithSupervisorFeedback/);
  assert.doesNotMatch(correctionHandlerSource, /acceptAiMappingSuggestion|ignoreAiMappingSuggestion|onAccept\(|onIgnore\(/);
  assert.doesNotMatch(panelSource, /Run live Supervisor review/);
});

test("React app refreshes selected workspace when processing reaches terminal review state", () => {
  const source = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf-8");

  assert.match(source, /TERMINAL_JOB_STATUSES = new Set\(\["REVIEW", "COMPLETED", "ERROR"\]\)/);
  assert.match(source, /function isTerminalJobStatus\(status\)/);
  assert.match(source, /const latestSelectedSummary = refreshedJobs\.find\(\(job\) => job\.id === selectedJobId\)/);
  assert.match(source, /const previousSelectedStatus = selectedJob\?\.status/);
  assert.match(source, /previousSelectedStatus === "PROCESSING"[\s\S]*isTerminalJobStatus\(latestSummaryStatus\)/);
  assert.match(source, /refreshSelectedJobAfterProcessing\(latestSummaryStatus, latestSelectedSummary\)/);
  assert.match(source, /isTerminalJobStatus\(status\.status\)/);
  assert.match(source, /refreshSelectedJobAfterProcessing\(status\.status, latestSelectedSummary\)/);
  assert.match(source, /fetchJob\(selectedJobId\)/);
  assert.match(source, /setReviewState\(null\)/);
  assert.match(source, /setWorkspaceRefreshKey\(\(current\) => current \+ 1\)/);
  assert.match(source, /setAiSuggestionPostCompletionRefreshKey\(\(current\) => current \+ 1\)/);
  assert.match(source, /refreshKey=\{workspaceRefreshKey\}/);
  assert.match(source, /postCompletionAiRefreshKey=\{aiSuggestionPostCompletionRefreshKey\}/);
  assert.match(source, /workspaceAutoRefreshing \? "Loading extracted results\.\.\." : "Loading selected task"/);
});

test("React review workspace shows loading state and refreshes AI suggestions on completion", () => {
  const source = readFileSync(new URL("../src/review-workspace.jsx", import.meta.url), "utf-8");

  assert.match(source, /AI_SUGGESTION_POST_COMPLETION_GRACE_MS = 90_000/);
  assert.match(source, /AI_SUGGESTION_POLL_INTERVAL_MS = 3_000/);
  assert.match(source, /AI_SUGGESTION_TERMINAL_JOB_STATUSES = new Set\(\["REVIEW", "COMPLETED"\]\)/);
  assert.match(source, /postCompletionAiRefreshKey = 0/);
  assert.match(source, /setPostCompletionAiPollingActive\(true\)/);
  assert.match(source, /setPostCompletionAiPollingExpired\(true\)/);
  assert.match(source, /loadingBase \? \(/);
  assert.match(source, /Loading extracted results\.\.\./);
  assert.match(source, /Loading review data/);
  assert.match(source, /fetchAiMappingSuggestionsStatus\(job\.id\)/);
  assert.match(source, /Promise\.all\(\[[\s\S]*fetchAiMappingSuggestionsStatus\(job\.id\)[\s\S]*fetchAiMappingSuggestions\(job\.id\)/);
  assert.match(source, /const shouldPollAiSuggestions =[\s\S]*postCompletionAiPollingActive[\s\S]*visibleAiSuggestionCount === 0/);
  assert.match(source, /Checking for AI mapping suggestions\.\.\./);
  assert.match(source, /postCompletionSuggestionGraceExpired/);
  assert.match(source, /nextStatus\.ai_mapping_status === "not_started" && nextSuggestions\.length > 0/);
  assert.match(source, /setAiSuggestions\(response\?\.suggestions \|\| \[\]\)/);
  assert.doesNotMatch(source, /Run AI Mapping Suggestions/);
  assert.doesNotMatch(source, /handleRunAiSuggestions|runningAiSuggestions/);
  assert.doesNotMatch(source, /runAiMappingSuggestions/);
});

test("React normal workspace does not expose account management actions", () => {
  const source = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf-8");

  assert.doesNotMatch(source, /accountMenuOpen|accountMenuRef|ChangePasswordModal|DeleteAccountModal/);
  assert.doesNotMatch(source, /setChangePasswordOpen|setDeleteAccountOpen|handleChangePasswordSubmit|handleDeleteAccountSubmit/);
  assert.doesNotMatch(source, /Change password|Delete account\?|Type your email to confirm|Confirm current password/);
  assert.doesNotMatch(source, /permanently delete your account, all filing tasks/);
  assert.doesNotMatch(source, /Your account and all filing data have been permanently deleted\./);
});
