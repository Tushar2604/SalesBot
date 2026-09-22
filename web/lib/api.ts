/**
 * API client.
 *
 * The access token is held in module memory only — never localStorage, so an
 * XSS payload cannot read it. Longevity comes from the httpOnly refresh cookie,
 * which the browser attaches to /auth/refresh and which JS cannot touch.
 *
 * A 401 triggers exactly one refresh attempt; concurrent 401s share that single
 * in-flight refresh so a page with several queries does not rotate the refresh
 * token N times (which would trip the server's reuse-detection and log the user
 * out of every device).
 */

// Matches the compose port mapping. Not 8000: that port is commonly taken by
// another local dev server, and a wrong fallback would silently send
// authenticated requests to a stranger's API.
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8010";

let accessToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type ApiErrorBody = {
  error?: { code?: string; message?: string; details?: Record<string, unknown> };
  detail?: unknown;
};

async function toApiError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody = {};
  try {
    body = (await response.json()) as ApiErrorBody;
  } catch {
    // Non-JSON error (proxy timeout, HTML error page) — fall through to defaults.
  }

  if (body.error) {
    return new ApiError(
      response.status,
      body.error.code ?? "error",
      body.error.message ?? response.statusText,
      body.error.details ?? {},
    );
  }

  // FastAPI validation errors arrive as `detail`, shaped differently.
  if (Array.isArray(body.detail) && body.detail.length > 0) {
    const first = body.detail[0] as { msg?: string; loc?: unknown[] };
    const field = Array.isArray(first.loc) ? first.loc.slice(1).join(".") : "";
    return new ApiError(
      response.status,
      "validation_failed",
      field ? `${field}: ${first.msg ?? "is invalid"}` : (first.msg ?? "Invalid input"),
    );
  }

  return new ApiError(response.status, "error", response.statusText || "Request failed");
}

function networkError(): ApiError {
  return new ApiError(
    0,
    "network_error",
    `Can't reach the API at ${API_BASE}. Start the backend, then try again.`,
  );
}

async function refreshAccessToken(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const response = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
          method: "POST",
          credentials: "include",
        });
        if (!response.ok) {
          accessToken = null;
          return false;
        }
        const data = (await response.json()) as { access_token: string };
        accessToken = data.access_token;
        return true;
      } catch {
        accessToken = null;
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  /** Set false for calls where a 401 should surface instead of retrying (login). */
  retryOnUnauthorized?: boolean;
};

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, retryOnUnauthorized = true } = options;

  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

    return fetch(`${API_BASE}/api/v1${path}`, {
      method,
      headers,
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  };

  let response: Response;
  try {
    response = await send();
  } catch {
    throw networkError();
  }

  if (response.status === 401 && retryOnUnauthorized && (await refreshAccessToken())) {
    try {
      response = await send();
    } catch {
      throw networkError();
    }
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;

  return (await response.json()) as T;
}

/** Downloads an authenticated file (e.g. a CSV export) through the browser. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const send = () =>
    fetch(`${API_BASE}/api/v1${path}`, {
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
      credentials: "include",
    });
  let response = await send();
  if (response.status === 401 && (await refreshAccessToken())) response = await send();
  if (!response.ok) throw await toApiError(response);

  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * Multipart upload. Cannot go through `apiFetch`, which serialises JSON and
 * would set the wrong Content-Type — the browser has to pick the boundary.
 * Shares the same single-flight refresh so a CSV upload on an expired token
 * recovers instead of failing.
 */
export async function uploadForm<T>(path: string, form: FormData): Promise<T> {
  const send = async () =>
    fetch(`${API_BASE}/api/v1${path}`, {
      method: "POST",
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
      credentials: "include",
      body: form,
    });

  let response = await send();
  if (response.status === 401 && (await refreshAccessToken())) response = await send();

  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

// ── typed endpoints ──────────────────────────────────────────────────────────

export type WorkspaceRole = "owner" | "admin" | "member";

export type Workspace = {
  id: string;
  name: string;
  slug: string;
  outreach_paused: boolean;
  created_at: string;
};

export type User = {
  id: string;
  email: string;
  full_name: string;
  timezone: string;
  is_active: boolean;
  created_at: string;
};

export type Me = {
  user: User;
  workspaces: { workspace: Workspace; role: WorkspaceRole }[];
};

export type Member = {
  id: string;
  user: User;
  role: WorkspaceRole;
  created_at: string;
};

export type Invite = {
  id: string;
  email: string;
  role: WorkspaceRole;
  status: string;
  expires_at: string;
  created_at: string;
};

type TokenResponse = { access_token: string; token_type: string; expires_in: number };

export const api = {
  async signup(input: {
    email: string;
    password: string;
    full_name: string;
    workspace_name: string;
  }): Promise<void> {
    const data = await apiFetch<TokenResponse>("/auth/signup", {
      method: "POST",
      body: input,
      retryOnUnauthorized: false,
    });
    setAccessToken(data.access_token);
  },

  async login(input: { email: string; password: string }): Promise<void> {
    const data = await apiFetch<TokenResponse>("/auth/login", {
      method: "POST",
      body: input,
      retryOnUnauthorized: false,
    });
    setAccessToken(data.access_token);
  },

  async logout(): Promise<void> {
    await apiFetch<void>("/auth/logout", { method: "POST", retryOnUnauthorized: false });
    setAccessToken(null);
  },

  /** Restores a session on page load using the refresh cookie alone. */
  async restoreSession(): Promise<Me | null> {
    if (!accessToken && !(await refreshAccessToken())) return null;
    try {
      return await apiFetch<Me>("/auth/me");
    } catch {
      return null;
    }
  },

  me: () => apiFetch<Me>("/auth/me"),

  acceptInvite: (input: { token: string; password?: string; full_name?: string }) =>
    apiFetch<TokenResponse>("/auth/accept-invite", {
      method: "POST",
      body: input,
      retryOnUnauthorized: false,
    }).then((data) => setAccessToken(data.access_token)),

  createWorkspace: (name: string) =>
    apiFetch<Workspace>("/workspaces", { method: "POST", body: { name } }),

  updateWorkspace: (id: string, patch: { name?: string; outreach_paused?: boolean }) =>
    apiFetch<Workspace>(`/workspaces/${id}`, { method: "PATCH", body: patch }),

  members: (workspaceId: string) => apiFetch<Member[]>(`/workspaces/${workspaceId}/members`),

  updateMemberRole: (workspaceId: string, memberId: string, role: WorkspaceRole) =>
    apiFetch<Member>(`/workspaces/${workspaceId}/members/${memberId}`, {
      method: "PATCH",
      body: { role },
    }),

  removeMember: (workspaceId: string, memberId: string) =>
    apiFetch<void>(`/workspaces/${workspaceId}/members/${memberId}`, { method: "DELETE" }),

  invites: (workspaceId: string) => apiFetch<Invite[]>(`/workspaces/${workspaceId}/invites`),

  createInvite: (workspaceId: string, email: string, role: WorkspaceRole) =>
    apiFetch<Invite & { invite_url: string }>(`/workspaces/${workspaceId}/invites`, {
      method: "POST",
      body: { email, role },
    }),

  revokeInvite: (workspaceId: string, inviteId: string) =>
    apiFetch<void>(`/workspaces/${workspaceId}/invites/${inviteId}`, { method: "DELETE" }),
};

// ── LinkedIn accounts (Phase 2) ──────────────────────────────────────────────

export type LinkedInAccountStatus =
  | "disconnected"
  | "connecting"
  | "pending_2fa"
  | "pending_email_pin"
  | "challenge"
  | "active"
  | "paused"
  | "auth_lost"
  | "blocked"
  | "disabled";

export type WorkingHours = { start: string; end: string };

export type EffectiveCaps = {
  daily_invites: number;
  daily_messages: number;
  daily_views: number;
  weekly_invites: number;
  working_hours: WorkingHours;
  weekdays_only: boolean;
  timezone: string;
  invite_limit_reason: string;
};

/** Whether an account may publish through the official LinkedIn API. */
export type AccountPublishingStatus = {
  code: string;
  available: boolean;
  message: string;
  /** "" | "configure" | "authorize" */
  remedy: string;
  authorized_at: string | null;
  expires_at: string | null;
  scopes: string[];
};

export type LinkedInAccount = {
  id: string;
  label: string;
  login_email: string;
  public_id: string;
  full_name: string;
  headline: string;
  avatar_url: string;
  profile_url: string;
  status: LinkedInAccountStatus;
  status_detail: string;
  needs_user_action: boolean;
  is_connected: boolean;
  health_score: number;
  consecutive_errors: number;
  circuit_open_until: string | null;
  circuit_reason: string;
  test_mode: boolean;
  caps: EffectiveCaps;
  within_working_hours: boolean;
  working_hours_detail: string;
  device: string;
  proxy_label: string;
  proxy_country: string;
  using_direct_connection: boolean;
  warnings: string[];
  publishing: AccountPublishingStatus;
  session_updated_at: string | null;
  last_action_at: string | null;
  next_allowed_at: string | null;
  created_at: string;
};

export type ConnectResponse = {
  account: LinkedInAccount;
  /** "poll" | "code" | "resolve" | "reconnect" | "done" */
  next_step: string;
  message: string;
};

export type ProxyRecord = {
  id: string;
  label: string;
  provider: string;
  public_url: string;
  country: string;
  city: string;
  status: "untested" | "healthy" | "degraded" | "dead";
  last_exit_ip: string;
  last_checked_at: string | null;
  assigned_account_id: string | null;
  created_at: string;
};

export type CapsPatch = {
  daily_invites?: number;
  daily_messages?: number;
  daily_views?: number;
  weekly_invites?: number;
  working_hours?: WorkingHours;
  weekdays_only?: boolean;
  test_mode?: boolean;
  timezone?: string;
  label?: string;
  proxy_id?: string;
};

export const linkedinApi = {
  accounts: (ws: string) => apiFetch<LinkedInAccount[]>(`/workspaces/${ws}/linkedin-accounts`),

  account: (ws: string, id: string) =>
    apiFetch<LinkedInAccount>(`/workspaces/${ws}/linkedin-accounts/${id}`),

  connectWithCookie: (
    ws: string,
    body: {
      label?: string;
      li_at: string;
      jsessionid?: string;
      timezone: string;
      proxy_id?: string | null;
      account_id?: string | null;
    },
  ) =>
    apiFetch<ConnectResponse>(`/workspaces/${ws}/linkedin-accounts/connect/cookie`, {
      method: "POST",
      body,
    }),

  connectWithCredentials: (
    ws: string,
    body: {
      label?: string;
      email: string;
      password: string;
      timezone: string;
      proxy_id?: string | null;
    },
  ) =>
    apiFetch<ConnectResponse>(`/workspaces/${ws}/linkedin-accounts/connect/credentials`, {
      method: "POST",
      body,
    }),

  submitCode: (ws: string, id: string, code: string) =>
    apiFetch<ConnectResponse>(`/workspaces/${ws}/linkedin-accounts/${id}/challenge`, {
      method: "POST",
      body: { code },
    }),

  verify: (ws: string, id: string) =>
    apiFetch<ConnectResponse>(`/workspaces/${ws}/linkedin-accounts/${id}/verify`, {
      method: "POST",
    }),

  update: (ws: string, id: string, patch: CapsPatch) =>
    apiFetch<LinkedInAccount>(`/workspaces/${ws}/linkedin-accounts/${id}`, {
      method: "PATCH",
      body: patch,
    }),

  setPaused: (ws: string, id: string, paused: boolean) =>
    apiFetch<LinkedInAccount>(
      `/workspaces/${ws}/linkedin-accounts/${id}/pause?paused=${paused}`,
      { method: "POST" },
    ),

  disconnect: (ws: string, id: string) =>
    apiFetch<LinkedInAccount>(`/workspaces/${ws}/linkedin-accounts/${id}/disconnect`, {
      method: "POST",
    }),

  remove: (ws: string, id: string) =>
    apiFetch<void>(`/workspaces/${ws}/linkedin-accounts/${id}`, { method: "DELETE" }),

  proxies: (ws: string) => apiFetch<ProxyRecord[]>(`/workspaces/${ws}/proxies`),

  createProxy: (
    ws: string,
    body: {
      label?: string;
      provider?: string;
      scheme?: string;
      host: string;
      port: number;
      username?: string;
      password?: string;
      country?: string;
      city?: string;
      sticky_session_id?: string;
    },
  ) => apiFetch<ProxyRecord>(`/workspaces/${ws}/proxies`, { method: "POST", body }),

  removeProxy: (ws: string, id: string) =>
    apiFetch<void>(`/workspaces/${ws}/proxies/${id}`, { method: "DELETE" }),

  // ── remote-browser login (Phase 1) ──────────────────────────────────────
  // A real, human-driven Chromium session — see api/app/linkedin/remote_browser/.
  // Used only to sign in; once that succeeds the account continues through
  // the same driver every other connect method already uses.

  createRemoteAccount: (
    ws: string,
    body: { label?: string; timezone: string; proxy_id?: string | null },
  ) =>
    apiFetch<LinkedInAccount>(`/workspaces/${ws}/linkedin-accounts/connect/remote-browser`, {
      method: "POST",
      body,
    }),

  startRemoteSession: (ws: string, accountId: string) =>
    apiFetch<{ ticket: string; ws_url: string; expires_in: number }>(
      `/workspaces/${ws}/linkedin-accounts/${accountId}/remote-session`,
      { method: "POST" },
    ),
};

// ── notifications ────────────────────────────────────────────────────────────

export type NotificationType =
  | "inbox_reply"
  | "account_action_needed"
  | "member_joined"
  | "campaign_completed"
  | "invite_update";

export type Notification = {
  id: string;
  type: NotificationType;
  title: string;
  body: string;
  link: string;
  read: boolean;
  created_at: string;
};

export type NotificationPage = {
  items: Notification[];
  total: number;
  unread_count: number;
  limit: number;
  offset: number;
};

export const notificationsApi = {
  list: (ws: string, limit = 30) =>
    apiFetch<NotificationPage>(`/workspaces/${ws}/notifications?limit=${limit}`),

  markRead: (ws: string, id: string) =>
    apiFetch<Notification>(`/workspaces/${ws}/notifications/${id}/read`, { method: "POST" }),

  markAllRead: (ws: string) =>
    apiFetch<{ marked_read: number }>(`/workspaces/${ws}/notifications/read-all`, {
      method: "POST",
    }),
};
