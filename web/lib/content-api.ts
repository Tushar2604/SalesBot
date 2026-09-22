/**
 * Content Studio API client.
 *
 * Same shape as `lib/outreach-api.ts`: thin typed wrappers over `apiFetch`, so
 * every call inherits the in-memory access token and the single-flight refresh.
 * Media goes through `uploadForm`, which lets the browser set the multipart
 * boundary.
 */

import { apiFetch, uploadForm } from "@/lib/api";

export type PostStatus =
  | "draft"
  | "pending_approval"
  | "approved"
  | "scheduled"
  | "publishing"
  | "published"
  | "failed"
  | "cancelled";

export type PostVisibility = "PUBLIC" | "CONNECTIONS";
export type MediaKind = "image" | "video" | "document";

/** Why publishing is or is not possible. `remedy` tells the UI what to offer. */
export type PublishingCapability = {
  code: string;
  available: boolean;
  message: string;
  /** "" | "configure" | "authorize" */
  remedy: string;
};

export type MediaAsset = {
  id: string;
  kind: MediaKind;
  filename: string;
  content_type: string;
  size_bytes: number;
  width: number;
  height: number;
  /** Short-lived presigned URL; the bucket itself is private. */
  url: string;
  created_at: string;
};

export type PostMedia = {
  id: string;
  position: number;
  alt_text: string;
  asset: MediaAsset;
};

export type PostAccountSummary = {
  id: string;
  label: string;
  full_name: string;
  headline: string;
  avatar_url: string;
  profile_url: string;
  can_publish: boolean;
  capability: PublishingCapability;
};

export type PostAnalytics = {
  available: boolean;
  message: string;
  impressions: number | null;
  likes: number | null;
  comments: number | null;
  reposts: number | null;
  clicks: number | null;
  engagement_rate: number | null;
  updated_at: string | null;
};

export type Post = {
  id: string;
  workspace_id: string;
  created_by_id: string | null;
  created_by_name: string;
  account: PostAccountSummary;
  content: string;
  visibility: PostVisibility;
  status: PostStatus;
  is_editable: boolean;
  character_count: number;
  word_count: number;
  hashtags: string[];
  scheduled_at: string | null;
  scheduled_timezone: string;
  queue_position: number | null;
  published_at: string | null;
  linkedin_post_id: string;
  linkedin_url: string;
  failure_reason: string;
  error_code: string;
  request_id: string;
  failed_at: string | null;
  attempts: number;
  submitted_for_approval_at: string | null;
  approved_at: string | null;
  approved_by_id: string | null;
  review_note: string;
  media: PostMedia[];
  analytics: PostAnalytics;
  created_at: string;
  updated_at: string;
};

export type PostPage = {
  items: Post[];
  total: number;
  limit: number;
  offset: number;
  counts: Record<string, number>;
};

export type CalendarEntry = {
  id: string;
  status: PostStatus;
  excerpt: string;
  at: string;
  local_date: string;
  local_time: string;
  timezone: string;
  account_label: string;
  has_media: boolean;
};

export type CalendarPage = {
  start: string;
  end: string;
  timezone: string;
  entries: CalendarEntry[];
};

export type Template = {
  id: string;
  name: string;
  content: string;
  media: MediaAsset[];
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
};

export type QueueSlot = { weekday: number; time: string };

export type Queue = {
  paused: boolean;
  timezone: string;
  slots: QueueSlot[];
  items: Post[];
  next_slot_at: string | null;
};

export type MediaLimits = {
  limits: {
    image: { content_types: string[]; max_bytes: number; max_per_post: number };
    video: { content_types: string[]; max_bytes: number; max_per_post: number };
    document: { content_types: string[]; max_bytes: number; max_per_post: number };
    max_commentary_chars: number;
  };
};

export type MediaInput = { media_asset_id: string; alt_text?: string };

export type PostFilters = {
  status?: PostStatus[];
  account_id?: string;
  author_id?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
};

function query(filters: PostFilters): string {
  const params = new URLSearchParams();
  (filters.status ?? []).forEach((s) => params.append("status", s));
  if (filters.account_id) params.set("account_id", filters.account_id);
  if (filters.author_id) params.set("author_id", filters.author_id);
  if (filters.search?.trim()) params.set("search", filters.search.trim());
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  params.set("limit", String(filters.limit ?? 25));
  params.set("offset", String(filters.offset ?? 0));
  return params.toString();
}

const base = (ws: string) => `/workspaces/${ws}/content`;

export const contentApi = {
  // ── posts ──────────────────────────────────────────────────────────────────
  posts: (ws: string, filters: PostFilters = {}) =>
    apiFetch<PostPage>(`${base(ws)}/posts?${query(filters)}`),

  post: (ws: string, id: string) => apiFetch<Post>(`${base(ws)}/posts/${id}`),

  createPost: (
    ws: string,
    body: {
      linkedin_account_id: string;
      content?: string;
      visibility?: PostVisibility;
      media?: MediaInput[];
    },
  ) => apiFetch<Post>(`${base(ws)}/posts`, { method: "POST", body }),

  /** Also the autosave call. */
  updatePost: (
    ws: string,
    id: string,
    patch: {
      linkedin_account_id?: string;
      content?: string;
      visibility?: PostVisibility;
      media?: MediaInput[];
    },
  ) => apiFetch<Post>(`${base(ws)}/posts/${id}`, { method: "PATCH", body: patch }),

  deletePost: (ws: string, id: string) =>
    apiFetch<void>(`${base(ws)}/posts/${id}`, { method: "DELETE" }),

  duplicate: (ws: string, id: string) =>
    apiFetch<Post>(`${base(ws)}/posts/${id}/duplicate`, { method: "POST" }),

  repurpose: (ws: string, id: string) =>
    apiFetch<Post>(`${base(ws)}/posts/${id}/repurpose`, { method: "POST" }),

  schedule: (
    ws: string,
    id: string,
    body: { scheduled_date: string; scheduled_time: string; timezone: string },
  ) => apiFetch<Post>(`${base(ws)}/posts/${id}/schedule`, { method: "POST", body }),

  cancel: (ws: string, id: string) =>
    apiFetch<Post>(`${base(ws)}/posts/${id}/cancel`, { method: "POST" }),

  publishNow: (ws: string, id: string) =>
    apiFetch<Post>(`${base(ws)}/posts/${id}/publish`, { method: "POST" }),

  retry: (ws: string, id: string) =>
    apiFetch<Post>(`${base(ws)}/posts/${id}/retry`, { method: "POST" }),

  // ── approval ───────────────────────────────────────────────────────────────
  submitForApproval: (ws: string, id: string) =>
    apiFetch<Post>(`${base(ws)}/posts/${id}/submit`, { method: "POST" }),

  approve: (ws: string, id: string, note = "") =>
    apiFetch<Post>(`${base(ws)}/posts/${id}/approve`, { method: "POST", body: { note } }),

  requestChanges: (ws: string, id: string, note = "") =>
    apiFetch<Post>(`${base(ws)}/posts/${id}/request-changes`, { method: "POST", body: { note } }),

  approvalSettings: (ws: string) =>
    apiFetch<{ approval_required: boolean; can_approve: boolean }>(
      `${base(ws)}/settings/approval`,
    ),

  setApprovalSettings: (ws: string, approval_required: boolean) =>
    apiFetch<{ approval_required: boolean; can_approve: boolean }>(
      `${base(ws)}/settings/approval`,
      { method: "PUT", body: { approval_required } },
    ),

  // ── calendar ───────────────────────────────────────────────────────────────
  calendar: (ws: string, start: string, end: string, timezone: string) =>
    apiFetch<CalendarPage>(
      `${base(ws)}/calendar?start=${start}&end=${end}&timezone=${encodeURIComponent(timezone)}`,
    ),

  // ── media ──────────────────────────────────────────────────────────────────
  mediaLimits: (ws: string) => apiFetch<MediaLimits>(`${base(ws)}/media/limits`),

  uploadMedia: (ws: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return uploadForm<MediaAsset>(`${base(ws)}/media`, form);
  },

  deleteMedia: (ws: string, id: string) =>
    apiFetch<void>(`${base(ws)}/media/${id}`, { method: "DELETE" }),

  // ── templates ──────────────────────────────────────────────────────────────
  templates: (ws: string) => apiFetch<Template[]>(`${base(ws)}/templates`),

  createTemplate: (ws: string, body: { name: string; content: string; media_asset_ids?: string[] }) =>
    apiFetch<Template>(`${base(ws)}/templates`, { method: "POST", body }),

  updateTemplate: (
    ws: string,
    id: string,
    patch: { name?: string; content?: string; media_asset_ids?: string[] },
  ) => apiFetch<Template>(`${base(ws)}/templates/${id}`, { method: "PATCH", body: patch }),

  deleteTemplate: (ws: string, id: string) =>
    apiFetch<void>(`${base(ws)}/templates/${id}`, { method: "DELETE" }),

  // ── queue ──────────────────────────────────────────────────────────────────
  queue: (ws: string) => apiFetch<Queue>(`${base(ws)}/queue`),

  updateQueue: (
    ws: string,
    patch: { paused?: boolean; timezone?: string; slots?: QueueSlot[] },
  ) => apiFetch<Queue>(`${base(ws)}/queue`, { method: "PATCH", body: patch }),

  addToQueue: (ws: string, id: string, linkedin_account_id?: string) =>
    apiFetch<Queue>(`${base(ws)}/posts/${id}/queue`, {
      method: "POST",
      body: { linkedin_account_id: linkedin_account_id ?? null },
    }),

  moveInQueue: (ws: string, id: string, direction: "up" | "down") =>
    apiFetch<Queue>(`${base(ws)}/posts/${id}/queue/move`, {
      method: "POST",
      body: { direction },
    }),

  removeFromQueue: (ws: string, id: string) =>
    apiFetch<Queue>(`${base(ws)}/posts/${id}/queue`, { method: "DELETE" }),

  // ── AI ─────────────────────────────────────────────────────────────────────
  aiImprove: (ws: string, content: string, action: string) =>
    apiFetch<{ variants: string[]; note: string }>(`${base(ws)}/ai/improve`, {
      method: "POST",
      body: { content, action },
    }),

  aiGenerate: (
    ws: string,
    body: { topic: string; audience: string; tone: string; goal: string },
  ) => apiFetch<{ variants: string[]; note: string }>(`${base(ws)}/ai/generate`, {
    method: "POST",
    body,
  }),
};

// ── publishing authorization (on the LinkedIn account) ───────────────────────

export const publishingApi = {
  authorizeUrl: (ws: string, accountId: string) =>
    apiFetch<{ authorize_url: string }>(
      `/workspaces/${ws}/linkedin-accounts/${accountId}/publishing/authorize`,
      { method: "POST" },
    ),

  revoke: (ws: string, accountId: string) =>
    apiFetch<unknown>(`/workspaces/${ws}/linkedin-accounts/${accountId}/publishing`, {
      method: "DELETE",
    }),
};

// ── display helpers ──────────────────────────────────────────────────────────

export const STATUS_LABELS: Record<PostStatus, string> = {
  draft: "Draft",
  pending_approval: "Pending approval",
  approved: "Approved",
  scheduled: "Scheduled",
  publishing: "Publishing…",
  published: "Published",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const STATUS_STYLES: Record<PostStatus, string> = {
  draft: "border-slate-200 bg-slate-100 text-slate-600",
  pending_approval: "border-state-warn/40 bg-state-warn/10 text-state-warn",
  approved: "border-violet-200 bg-violet-50 text-violet-700",
  scheduled: "border-accent/40 bg-accent/10 text-accent",
  publishing: "border-accent/40 bg-accent/10 text-accent",
  published: "border-state-ok/40 bg-state-ok/10 text-state-ok",
  failed: "border-state-bad/40 bg-state-bad/10 text-state-bad",
  cancelled: "border-slate-200 bg-slate-100 text-slate-500",
};

/** The zone list offered in the scheduler, plus whatever the browser reports. */
export function timezoneOptions(): string[] {
  const common = [
    "UTC",
    "Asia/Kolkata",
    "Asia/Singapore",
    "Asia/Dubai",
    "Europe/London",
    "Europe/Berlin",
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Australia/Sydney",
  ];
  let local = "UTC";
  try {
    local = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    /* some environments have no zone database */
  }
  return common.includes(local) ? common : [local, ...common];
}

export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** Formats a UTC instant in a named zone, for "9:30 AM Asia/Kolkata" strings. */
export function formatInZone(iso: string | null, timezone: string): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: timezone || "UTC",
    }).format(new Date(iso));
  } catch {
    return new Date(iso).toLocaleString();
  }
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(Math.abs(diff) / 60000);
  const past = diff >= 0;
  const render = (value: number, unit: string) =>
    past ? `${value}${unit} ago` : `in ${value}${unit}`;

  if (minutes < 1) return past ? "just now" : "in a moment";
  if (minutes < 60) return render(minutes, "m");
  const hours = Math.round(minutes / 60);
  if (hours < 24) return render(hours, "h");
  return render(Math.round(hours / 24), "d");
}
