import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  KeyRound,
  LoaderCircle,
  LogOut,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import {
  adminChangeUserPassword,
  adminClearUserTasks,
  adminDeleteUser,
  createAdminUser,
  fetchAdminUsers,
} from "./api";

function formatRegisteredDate(value) {
  if (!value) {
    return "Unknown";
  }

  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function AdminDialog({ open, title, description, icon, children }) {
  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-slate-950/75 px-4 py-6 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-2xl dark:border-white/10 dark:bg-slate-950">
        <div className="flex items-start gap-3">
          {icon && (
            <div className="rounded-lg bg-slate-100 p-2 text-slate-700 dark:bg-white/[0.06] dark:text-slate-200">
              {icon}
            </div>
          )}
          <div className="min-w-0">
            <h4 className="text-base font-semibold text-slate-950 dark:text-white">
              {title}
            </h4>
            {description && (
              <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {description}
              </p>
            )}
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}

function CreateAccountModal({ open, submitting, error, onClose, onSubmit }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (open) {
      setEmail("");
      setPassword("");
      setConfirmPassword("");
      setLocalError("");
    }
  }, [open]);

  function handleSubmit(event) {
    event.preventDefault();
    setLocalError("");

    if (password !== confirmPassword) {
      setLocalError("Password and confirmation do not match.");
      return;
    }

    onSubmit({
      email,
      password,
      confirm_password: confirmPassword,
    });
  }

  return (
    <AdminDialog
      open={open}
      title="Create Account"
      description="Create a normal user account for the filing workspace."
      icon={<Plus className="h-5 w-5" />}
    >
      <form onSubmit={handleSubmit} className="mt-6 space-y-4">
        <div>
          <label htmlFor="admin_create_email" className="field-label">
            Email
          </label>
          <input
            id="admin_create_email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="input-base"
            placeholder="user@example.com"
          />
        </div>
        <div>
          <label htmlFor="admin_create_password" className="field-label">
            Password
          </label>
          <input
            id="admin_create_password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="input-base"
          />
        </div>
        <div>
          <label htmlFor="admin_create_confirm_password" className="field-label">
            Confirm password
          </label>
          <input
            id="admin_create_confirm_password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            required
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            className="input-base"
          />
        </div>
        {(localError || error) && (
          <div className="flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
            <AlertCircle className="mt-0.5 h-4 w-4" />
            <span>{localError || error}</span>
          </div>
        )}
        <div className="flex flex-col-reverse gap-3 border-t border-slate-200/70 pt-5 dark:border-white/10 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className="button-secondary" disabled={submitting}>
            Cancel
          </button>
          <button type="submit" className="button-primary" disabled={submitting}>
            {submitting ? (
              <>
                <LoaderCircle className="h-4 w-4 animate-spin" />
                Creating
              </>
            ) : (
              <>
                <Plus className="h-4 w-4" />
                Create Account
              </>
            )}
          </button>
        </div>
      </form>
    </AdminDialog>
  );
}

function ChangeUserPasswordModal({ user, submitting, error, onClose, onSubmit }) {
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (user) {
      setNewPassword("");
      setConfirmPassword("");
      setLocalError("");
    }
  }, [user]);

  function handleSubmit(event) {
    event.preventDefault();
    setLocalError("");

    if (newPassword !== confirmPassword) {
      setLocalError("New password and confirmation do not match.");
      return;
    }

    onSubmit(user, {
      new_password: newPassword,
      confirm_password: confirmPassword,
    });
  }

  return (
    <AdminDialog
      open={Boolean(user)}
      title="Change Password"
      description={user ? `Set a new password for ${user.email}.` : ""}
      icon={<KeyRound className="h-5 w-5" />}
    >
      <form onSubmit={handleSubmit} className="mt-6 space-y-4">
        <div>
          <label htmlFor="admin_change_new_password" className="field-label">
            New password
          </label>
          <input
            id="admin_change_new_password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            required
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            className="input-base"
          />
        </div>
        <div>
          <label htmlFor="admin_change_confirm_password" className="field-label">
            Confirm password
          </label>
          <input
            id="admin_change_confirm_password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            required
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            className="input-base"
          />
        </div>
        {(localError || error) && (
          <div className="flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
            <AlertCircle className="mt-0.5 h-4 w-4" />
            <span>{localError || error}</span>
          </div>
        )}
        <div className="flex flex-col-reverse gap-3 border-t border-slate-200/70 pt-5 dark:border-white/10 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className="button-secondary" disabled={submitting}>
            Cancel
          </button>
          <button type="submit" className="button-primary" disabled={submitting}>
            {submitting ? (
              <>
                <LoaderCircle className="h-4 w-4 animate-spin" />
                Updating
              </>
            ) : (
              <>
                <KeyRound className="h-4 w-4" />
                Change Password
              </>
            )}
          </button>
        </div>
      </form>
    </AdminDialog>
  );
}

function ClearTaskDataModal({ user, submitting, error, onClose, onConfirm }) {
  return (
    <AdminDialog
      open={Boolean(user)}
      title="Clear Task Data"
      description="This will permanently delete all tasks, PDFs, extracted data, generated files, and AI suggestions for this user. The user account will remain."
      icon={<TriangleAlert className="h-5 w-5" />}
    >
      {user && (
        <p className="mt-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200">
          {user.email}
        </p>
      )}
      {error && (
        <div className="mt-5 flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
          <AlertCircle className="mt-0.5 h-4 w-4" />
          <span>{error}</span>
        </div>
      )}
      <div className="mt-6 flex flex-col-reverse gap-3 border-t border-slate-200/70 pt-5 dark:border-white/10 sm:flex-row sm:justify-end">
        <button type="button" onClick={onClose} className="button-secondary" disabled={submitting}>
          Cancel
        </button>
        <button
          type="button"
          onClick={() => onConfirm(user)}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-amber-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-100 focus:ring-offset-2 focus:ring-offset-white disabled:cursor-not-allowed disabled:opacity-50 dark:bg-amber-500 dark:hover:bg-amber-400 dark:focus:ring-amber-500/30 dark:focus:ring-offset-slate-950"
          disabled={submitting}
        >
          {submitting ? (
            <>
              <LoaderCircle className="h-4 w-4 animate-spin" />
              Clearing
            </>
          ) : (
            <>
              <TriangleAlert className="h-4 w-4" />
              Clear Task Data
            </>
          )}
        </button>
      </div>
    </AdminDialog>
  );
}

function DeleteUserModal({ user, submitting, error, onClose, onConfirm }) {
  const [emailConfirmation, setEmailConfirmation] = useState("");
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (user) {
      setEmailConfirmation("");
      setLocalError("");
    }
  }, [user]);

  function handleSubmit(event) {
    event.preventDefault();
    setLocalError("");

    if (emailConfirmation.trim().toLowerCase() !== user.email.toLowerCase()) {
      setLocalError("Email confirmation must match the selected user email.");
      return;
    }

    onConfirm(user);
  }

  return (
    <AdminDialog
      open={Boolean(user)}
      title="Delete Account"
      description="This will permanently delete the user account, all tasks, PDFs, extracted data, generated files, and AI suggestions. This action cannot be undone."
      icon={<Trash2 className="h-5 w-5" />}
    >
      <form onSubmit={handleSubmit} className="mt-6 space-y-4">
        <div>
          <label htmlFor="admin_delete_email_confirmation" className="field-label">
            Type user email to confirm
          </label>
          <input
            id="admin_delete_email_confirmation"
            type="email"
            autoComplete="off"
            required
            value={emailConfirmation}
            onChange={(event) => setEmailConfirmation(event.target.value)}
            className="input-base"
            placeholder={user?.email || "user@example.com"}
          />
        </div>
        {(localError || error) && (
          <div className="flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
            <AlertCircle className="mt-0.5 h-4 w-4" />
            <span>{localError || error}</span>
          </div>
        )}
        <div className="flex flex-col-reverse gap-3 border-t border-slate-200/70 pt-5 dark:border-white/10 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className="button-secondary" disabled={submitting}>
            Cancel
          </button>
          <button
            type="submit"
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-rose-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-rose-500 focus:outline-none focus:ring-2 focus:ring-rose-100 focus:ring-offset-2 focus:ring-offset-white disabled:cursor-not-allowed disabled:opacity-50 dark:bg-rose-500 dark:hover:bg-rose-400 dark:focus:ring-rose-500/30 dark:focus:ring-offset-slate-950"
            disabled={submitting}
          >
            {submitting ? (
              <>
                <LoaderCircle className="h-4 w-4 animate-spin" />
                Deleting
              </>
            ) : (
              <>
                <Trash2 className="h-4 w-4" />
                Delete Account
              </>
            )}
          </button>
        </div>
      </form>
    </AdminDialog>
  );
}

export function AdminUserManagement({ currentUser, onSignOut }) {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState("success");
  const [menuUserId, setMenuUserId] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [createError, setCreateError] = useState("");
  const [passwordUser, setPasswordUser] = useState(null);
  const [passwordSubmitting, setPasswordSubmitting] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [clearUser, setClearUser] = useState(null);
  const [clearSubmitting, setClearSubmitting] = useState(false);
  const [clearError, setClearError] = useState("");
  const [deleteUser, setDeleteUser] = useState(null);
  const [deleteSubmitting, setDeleteSubmitting] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  const listedUsers = useMemo(
    () => users.filter((user) => !user.is_admin && user.user_type !== "ADMIN"),
    [users],
  );

  async function loadAdminUsers() {
    setLoading(true);
    setError("");
    try {
      const result = await fetchAdminUsers();
      setUsers(Array.isArray(result?.users) ? result.users : []);
    } catch (loadError) {
      setError(loadError.message || "Unable to load users.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAdminUsers();
  }, []);

  async function handleCreateAccount(payload) {
    setCreateSubmitting(true);
    setCreateError("");
    setMessage("");
    try {
      const result = await createAdminUser(payload);
      setCreateOpen(false);
      setMessage(result?.message || "User created.");
      setMessageTone("success");
      await loadAdminUsers();
    } catch (createFailure) {
      setCreateError(createFailure.message || "Unable to create account.");
    } finally {
      setCreateSubmitting(false);
    }
  }

  async function handleChangeUserPassword(user, payload) {
    setPasswordSubmitting(true);
    setPasswordError("");
    setMessage("");
    try {
      const result = await adminChangeUserPassword(user.user_id, payload);
      setPasswordUser(null);
      setMessage(result?.message || "User password changed.");
      setMessageTone("success");
    } catch (passwordFailure) {
      setPasswordError(passwordFailure.message || "Unable to change password.");
    } finally {
      setPasswordSubmitting(false);
    }
  }

  async function handleClearUserTasks(user) {
    setClearSubmitting(true);
    setClearError("");
    setMessage("");
    try {
      const result = await adminClearUserTasks(user.user_id);
      setClearUser(null);
      setMessage(
        `${result?.message || "User tasks cleared."} Deleted ${result?.deleted_jobs_count ?? 0} task${result?.deleted_jobs_count === 1 ? "" : "s"}.`,
      );
      setMessageTone("success");
      await loadAdminUsers();
    } catch (clearFailure) {
      setClearError(clearFailure.message || "Unable to clear task data.");
    } finally {
      setClearSubmitting(false);
    }
  }

  async function handleDeleteUserAccount(user) {
    setDeleteSubmitting(true);
    setDeleteError("");
    setMessage("");
    try {
      const result = await adminDeleteUser(user.user_id);
      setDeleteUser(null);
      setMessage(
        `${result?.message || "User deleted."} Deleted ${result?.deleted_jobs_count ?? 0} task${result?.deleted_jobs_count === 1 ? "" : "s"}.`,
      );
      setMessageTone("success");
      await loadAdminUsers();
    } catch (deleteFailure) {
      setDeleteError(deleteFailure.message || "Unable to delete account.");
    } finally {
      setDeleteSubmitting(false);
    }
  }

  function openPasswordDialog(user) {
    setMenuUserId(null);
    setPasswordError("");
    setPasswordUser(user);
  }

  function openClearDialog(user) {
    setMenuUserId(null);
    setClearError("");
    setClearUser(user);
  }

  function openDeleteDialog(user) {
    setMenuUserId(null);
    setDeleteError("");
    setDeleteUser(user);
  }

  return (
    <div className="min-h-screen text-slate-950 dark:text-slate-100">
      <header className="border-b border-slate-200/60 bg-white/70 px-4 py-4 backdrop-blur-xl dark:border-white/10 dark:bg-slate-950/55 sm:px-6">
        <div className="mx-auto flex w-full max-w-[96rem] flex-wrap items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-600 text-white shadow-glow dark:bg-brand-500">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <p className="eyebrow">Admin</p>
              <h1 className="mt-1 text-2xl font-semibold text-slate-950 dark:text-white">
                User Management
              </h1>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                Manage user accounts and filing data.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="button-secondary h-10 px-3 py-0" onClick={loadAdminUsers} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
            <button
              type="button"
              className="button-primary h-10 px-3 py-0"
              onClick={() => {
                setCreateError("");
                setCreateOpen(true);
              }}
            >
              <Plus className="h-4 w-4" />
              Create Account
            </button>
            <button type="button" className="button-secondary h-10 px-3 py-0" onClick={onSignOut}>
              <LogOut className="h-4 w-4" />
              Sign Out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[96rem] px-4 py-6 sm:px-6">
        <section className="panel overflow-visible">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200/70 bg-slate-50/70 px-5 py-4 dark:border-white/10 dark:bg-white/[0.035]">
            <div>
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                User accounts
              </p>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Signed in as {currentUser.email}
              </p>
            </div>
            <span className="metric-pill">
              {listedUsers.length} user{listedUsers.length === 1 ? "" : "s"}
            </span>
          </div>

          {message && (
            <div className={`mx-5 mt-5 flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${messageTone === "error"
              ? "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200"
              : "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200"
              }`}
            >
              {messageTone === "error" ? <AlertCircle className="mt-0.5 h-4 w-4" /> : <CheckCircle2 className="mt-0.5 h-4 w-4" />}
              <span>{message}</span>
            </div>
          )}

          {error && (
            <div className="mx-5 mt-5 flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
              <AlertCircle className="mt-0.5 h-4 w-4" />
              <span>{error}</span>
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center px-5 py-16 text-sm text-slate-500 dark:text-slate-400">
              <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
              Loading users
            </div>
          ) : listedUsers.length === 0 ? (
            <div className="px-5 py-16 text-center">
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                No user accounts yet.
              </p>
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                Create an account to get started.
              </p>
            </div>
          ) : (
            <div className="overflow-visible">
              <table className="w-full border-separate border-spacing-0 text-sm">
                <thead>
                  <tr className="border-b border-slate-200/70 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:border-white/10 dark:text-slate-400">
                    <th className="px-5 py-3">User Email</th>
                    <th className="px-5 py-3">Registered Date</th>
                    <th className="px-5 py-3">Type</th>
                    <th className="px-5 py-3 text-right">Successful Tasks</th>
                    <th className="px-5 py-3 text-right">Processing Tasks</th>
                    <th className="px-5 py-3 text-right">Error Tasks</th>
                  </tr>
                </thead>
                <tbody>
                  {listedUsers.map((user) => (
                    <tr key={user.user_id} className="border-t border-slate-200/70 dark:border-white/10">
                      <td className="relative px-5 py-3">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className="min-w-0 truncate font-medium text-slate-900 dark:text-slate-100">
                            {user.email}
                          </span>
                          <button
                            type="button"
                            aria-haspopup="menu"
                            aria-expanded={menuUserId === user.user_id}
                            aria-label={`Open user menu for ${user.email}`}
                            className="inline-flex h-8 w-8 flex-none items-center justify-center rounded-lg border border-slate-200 bg-white text-sm font-bold text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-800 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-white/10 dark:bg-white/[0.055] dark:text-slate-300 dark:hover:bg-white/[0.09] dark:focus:ring-brand-500/30"
                            onClick={() => setMenuUserId((current) => (current === user.user_id ? null : user.user_id))}
                          >
                            ...
                          </button>
                        </div>
                        <div
                          role="menu"
                          className={`absolute left-5 top-12 z-30 w-56 rounded-lg border border-slate-200 bg-white p-2 shadow-premium transition dark:border-white/10 dark:bg-slate-900 ${menuUserId === user.user_id
                            ? "visible translate-y-0 opacity-100"
                            : "invisible -translate-y-1 opacity-0"
                            }`}
                        >
                          <button
                            type="button"
                            role="menuitem"
                            className="flex w-full items-center gap-2 rounded-md px-3 py-2.5 text-left text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-white/[0.06]"
                            onClick={() => openPasswordDialog(user)}
                          >
                            <KeyRound className="h-4 w-4" />
                            Change Password
                          </button>
                          <button
                            type="button"
                            role="menuitem"
                            className="flex w-full items-center gap-2 rounded-md px-3 py-2.5 text-left text-sm font-medium text-amber-700 transition hover:bg-amber-50 dark:text-amber-200 dark:hover:bg-amber-500/10"
                            onClick={() => openClearDialog(user)}
                          >
                            <TriangleAlert className="h-4 w-4" />
                            Clear Task Data
                          </button>
                          <button
                            type="button"
                            role="menuitem"
                            className="flex w-full items-center gap-2 rounded-md px-3 py-2.5 text-left text-sm font-medium text-rose-700 transition hover:bg-rose-50 dark:text-rose-200 dark:hover:bg-rose-500/10"
                            onClick={() => openDeleteDialog(user)}
                          >
                            <Trash2 className="h-4 w-4" />
                            Delete Account
                          </button>
                        </div>
                      </td>
                      <td className="px-5 py-3 text-slate-600 dark:text-slate-300">
                        {formatRegisteredDate(user.registered_at || user.created_at)}
                      </td>
                      <td className="px-5 py-3">
                        <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${user.user_type === "ADMIN" || user.is_admin
                          ? "border-brand-200 bg-brand-50 text-brand-700 dark:border-brand-400/25 dark:bg-brand-400/10 dark:text-brand-200"
                          : "border-slate-200 bg-slate-50 text-slate-700 dark:border-white/10 dark:bg-white/[0.06] dark:text-slate-200"
                          }`}
                        >
                          {user.user_type || (user.is_admin ? "ADMIN" : "USER")}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-right">
                        <span className="metric-pill justify-center">
                          {user.successful_task_count ?? 0}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-right">
                        <span className="metric-pill justify-center">
                          {user.processing_task_count ?? 0}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-right font-semibold text-slate-900 dark:text-slate-100">
                        <span className="metric-pill justify-center border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200">
                          {user.error_task_count ?? 0}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>

      <CreateAccountModal
        open={createOpen}
        submitting={createSubmitting}
        error={createError}
        onClose={() => {
          if (!createSubmitting) {
            setCreateOpen(false);
            setCreateError("");
          }
        }}
        onSubmit={handleCreateAccount}
      />
      <ChangeUserPasswordModal
        user={passwordUser}
        submitting={passwordSubmitting}
        error={passwordError}
        onClose={() => {
          if (!passwordSubmitting) {
            setPasswordUser(null);
            setPasswordError("");
          }
        }}
        onSubmit={handleChangeUserPassword}
      />
      <ClearTaskDataModal
        user={clearUser}
        submitting={clearSubmitting}
        error={clearError}
        onClose={() => {
          if (!clearSubmitting) {
            setClearUser(null);
            setClearError("");
          }
        }}
        onConfirm={handleClearUserTasks}
      />
      <DeleteUserModal
        user={deleteUser}
        submitting={deleteSubmitting}
        error={deleteError}
        onClose={() => {
          if (!deleteSubmitting) {
            setDeleteUser(null);
            setDeleteError("");
          }
        }}
        onConfirm={handleDeleteUserAccount}
      />
    </div>
  );
}
