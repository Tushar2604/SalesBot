/**
 * Leads and campaigns API surface (Phases 3 and 4).
 *
 * Split from `api.ts` to keep that file about transport and auth; this one is
 * purely the outreach domain.
 */

import { apiFetch, downloadFile, uploadForm } from "@/lib/api";

// ── leads ────────────────────────────────────────────────────────────────────

export type LeadSource = "csv" | "linkedin_search" | "sales_navigator" | "manual" | "api";

export type Lead = {
  id: string;
  public_id: string;
  profile_url: string;
  first_name: string;
  last_name: string;
  full_name: string;
  headline: string;
  company: string;
  title: string;
  location: string;
  email: string;
  source: LeadSource;
  custom_fields: Record<string, string>;
  list_id: string | null;
  created_at: string;
};

export type LeadPage = { items: Lead[]; total: number; limit: number; offset: number };

export type LeadList = {
  id: string;
  name: string;
  source: LeadSource;
  import_status: "pending" | "running" | "completed" | "failed";
  import_detail: string;
  total_rows: number;
  imported_count: number;
  skipped_count: number;
  created_at: string;
};

export type CsvPreview = {
  headers: string[];
  guessed_mapping: Record<string, string>;
  sample_rows: Record<string, string>[];
  mappable_fields: string[];
};

export type ImportReport = {
  list_id: string;
  list_name: string;
  total_rows: number;
  imported: number;
  updated: number;
  skipped: number;
  problems: { row_number: number; reason: string; public_id: string }[];
};

export type BlocklistKind = "domain" | "company" | "profile";

export type BlocklistEntry = {
  id: string;
  kind: BlocklistKind;
  value: string;
  note: string;
  created_at: string;
};

export const leadsApi = {
  previewCsv: (ws: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return uploadForm<CsvPreview>(`/workspaces/${ws}/leads/preview-csv`, form);
  },

  importCsv: (
    ws: string,
    file: File,
    options: {
      listName?: string;
      mapping?: Record<string, string>;
      skipContacted?: boolean;
    } = {},
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("list_name", options.listName ?? "");
    if (options.mapping) form.append("mapping", JSON.stringify(options.mapping));
    form.append("skip_already_contacted", String(options.skipContacted ?? true));
    return uploadForm<ImportReport>(`/workspaces/${ws}/leads/import-csv`, form);
  },

  leads: (
    ws: string,
    params: { listId?: string; search?: string; limit?: number; offset?: number } = {},
  ) => {
    const query = new URLSearchParams();
    if (params.listId) query.set("list_id", params.listId);
    if (params.search) query.set("search", params.search);
    query.set("limit", String(params.limit ?? 50));
    query.set("offset", String(params.offset ?? 0));
    return apiFetch<LeadPage>(`/workspaces/${ws}/leads?${query.toString()}`);
  },

  importUrls: (ws: string, urls: string, listName = "") =>
    apiFetch<ImportReport>(`/workspaces/${ws}/leads/import-urls`, {
      method: "POST",
      body: { urls, list_name: listName },
    }),

  lists: (ws: string) => apiFetch<LeadList[]>(`/workspaces/${ws}/lead-lists`),

  deleteList: (ws: string, id: string, deleteLeads = false) =>
    apiFetch<void>(`/workspaces/${ws}/lead-lists/${id}?delete_leads=${deleteLeads}`, {
      method: "DELETE",
    }),

  blocklist: (ws: string) => apiFetch<BlocklistEntry[]>(`/workspaces/${ws}/blocklist`),

  addBlocklist: (ws: string, body: { kind: BlocklistKind; value: string; note?: string }) =>
    apiFetch<BlocklistEntry>(`/workspaces/${ws}/blocklist`, { method: "POST", body }),

  removeBlocklist: (ws: string, id: string) =>
    apiFetch<void>(`/workspaces/${ws}/blocklist/${id}`, { method: "DELETE" }),
};

// ── campaigns ────────────────────────────────────────────────────────────────

export type StepType = "view_profile" | "invite" | "message" | "withdraw_invite" | "wait";

export type StepCondition =
  | "always"
  | "if_accepted"
  | "if_not_accepted"
  | "if_replied"
  | "if_not_replied";

export type ConditionFailAction = "skip" | "stop";
export type CampaignStatus = "draft" | "running" | "paused" | "completed" | "archived";

export type EnrollmentState =
  | "pending"
  | "running"
  | "replied"
  | "completed"
  | "stopped"
  | "failed"
  | "skipped";

/**
 * When a step runs.
 *  smart — a natural moment inside working hours, after `delay_hours` (default)
 *  asap  — as soon as the account's limits allow
 *  delay — exactly `delay_minutes` after the previous step
 *  at    — at `send_at`
 */
export type StepTiming = "smart" | "asap" | "delay" | "at";

export type CampaignStep = {
  id: string;
  order_index: number;
  step_type: StepType;
  delay_hours: number;
  only_if: StepCondition;
  on_condition_fail: ConditionFailAction;
  template: string;
  timing: StepTiming;
  delay_minutes: number | null;
  send_at: string | null;
};

export type StepInput = {
  step_type: StepType;
  delay_hours: number;
  only_if: StepCondition;
  on_condition_fail: ConditionFailAction;
  template: string;
  timing?: StepTiming;
  delay_minutes?: number | null;
  send_at?: string | null;
};

/** A saved step as the builder edits it. Keeps timing, which a hand-copy would drop. */
export function toStepInput(step: CampaignStep): StepInput {
  return {
    step_type: step.step_type,
    delay_hours: step.delay_hours,
    only_if: step.only_if,
    on_condition_fail: step.on_condition_fail,
    template: step.template,
    timing: step.timing ?? "smart",
    delay_minutes: step.delay_minutes ?? null,
    send_at: step.send_at ?? null,
  };
}

export type CampaignStats = {
  enrolled: number;
  pending: number;
  running: number;
  completed: number;
  replied: number;
  stopped: number;
  skipped: number;
  failed: number;
  invites_sent: number;
  accepted: number;
  messages_sent: number;
  views: number;
  tasks_pending: number;
  tasks_failed: number;
  acceptance_rate: number | null;
  reply_rate: number | null;
};

export type Campaign = {
  id: string;
  name: string;
  status: CampaignStatus;
  stop_on_reply: boolean;
  linkedin_account_id: string;
  linkedin_account_label: string;
  steps: CampaignStep[];
  stats: CampaignStats;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  /** Plain-language reasons the campaign cannot launch yet. */
  launch_blockers: string[];
};

export type Enrollment = {
  id: string;
  lead_id: string;
  lead_name: string;
  lead_public_id: string;
  lead_company: string;
  state: EnrollmentState;
  current_step_index: number;
  variant: string;
  next_run_at: string | null;
  invite_sent_at: string | null;
  accepted_at: string | null;
  replied_at: string | null;
  last_error: string;
  stopped_reason: string;
};

export type ActionTaskRecord = {
  id: string;
  action_type: StepType;
  status: string;
  scheduled_at: string;
  dispatched_at: string | null;
  finished_at: string | null;
  attempts: number;
  error_class: string;
  error_detail: string;
  lead_public_id: string;
};

export type QuotaStatus = {
  linkedin_account_id: string;
  label: string;
  status: string;
  within_working_hours: boolean;
  working_hours_detail: string;
  next_allowed_at: string | null;
  blocked_reason: string;
  invites_used_today: number;
  invites_limit_today: number;
  invites_used_this_week: number;
  invites_limit_this_week: number;
  invite_limit_reason: string;
  messages_used_today: number;
  messages_limit_today: number;
  views_used_today: number;
  views_limit_today: number;
};

export type TemplatePreview = {
  rendered: string;
  variables: string[];
  variables_without_fallback: string[];
  length: number;
  exceeds_invite_limit: boolean;
};

export type EnrollReport = {
  enrolled: number;
  skipped_duplicate: number;
  skipped_blocked: number;
  skipped_already_enrolled: number;
  skipped_no_profile: number;
  total_skipped: number;
};

export const campaignsApi = {
  list: (ws: string) => apiFetch<Campaign[]>(`/workspaces/${ws}/campaigns`),

  get: (ws: string, id: string) => apiFetch<Campaign>(`/workspaces/${ws}/campaigns/${id}`),

  create: (
    ws: string,
    body: {
      name: string;
      linkedin_account_id: string;
      steps: StepInput[];
      stop_on_reply: boolean;
    },
  ) => apiFetch<Campaign>(`/workspaces/${ws}/campaigns`, { method: "POST", body }),

  update: (ws: string, id: string, patch: { name?: string; stop_on_reply?: boolean }) =>
    apiFetch<Campaign>(`/workspaces/${ws}/campaigns/${id}`, { method: "PATCH", body: patch }),

  replaceSteps: (ws: string, id: string, steps: StepInput[]) =>
    apiFetch<Campaign>(`/workspaces/${ws}/campaigns/${id}/steps`, {
      method: "PUT",
      body: steps,
    }),

  enroll: (ws: string, id: string, body: { list_id?: string; lead_ids?: string[] }) =>
    apiFetch<EnrollReport>(`/workspaces/${ws}/campaigns/${id}/enroll`, {
      method: "POST",
      body,
    }),

  setStatus: (ws: string, id: string, status: CampaignStatus) =>
    apiFetch<Campaign>(`/workspaces/${ws}/campaigns/${id}/status`, {
      method: "POST",
      body: { status },
    }),

  remove: (ws: string, id: string) =>
    apiFetch<void>(`/workspaces/${ws}/campaigns/${id}`, { method: "DELETE" }),

  enrollments: (ws: string, id: string, limit = 50, offset = 0) =>
    apiFetch<{ items: Enrollment[]; total: number }>(
      `/workspaces/${ws}/campaigns/${id}/enrollments?limit=${limit}&offset=${offset}`,
    ),

  activity: (ws: string, id: string, limit = 50) =>
    apiFetch<ActionTaskRecord[]>(`/workspaces/${ws}/campaigns/${id}/activity?limit=${limit}`),

  // ── tracking ──
  tracking: (ws: string, id: string) =>
    apiFetch<TrackingSummary>(`/workspaces/${ws}/campaigns/${id}/tracking`),

  trackingLeads: (
    ws: string,
    id: string,
    params: { stage?: TrackingStage | ""; search?: string; limit?: number; offset?: number } = {},
  ) => {
    const query = new URLSearchParams();
    if (params.stage) query.set("stage", params.stage);
    if (params.search) query.set("search", params.search);
    query.set("limit", String(params.limit ?? 50));
    query.set("offset", String(params.offset ?? 0));
    return apiFetch<{ items: TrackingLead[]; total: number }>(
      `/workspaces/${ws}/campaigns/${id}/tracking/leads?${query.toString()}`,
    );
  },

  leadEvents: (ws: string, id: string, enrollmentId: string) =>
    apiFetch<LeadEvent[]>(`/workspaces/${ws}/campaigns/${id}/enrollments/${enrollmentId}/events`),

  exportTracking: (ws: string, id: string) =>
    downloadFile(`/workspaces/${ws}/campaigns/${id}/tracking/export.csv`, "campaign-tracking.csv"),

  previewTemplate: (ws: string, template: string) =>
    apiFetch<TemplatePreview>(`/workspaces/${ws}/campaigns/preview-template`, {
      method: "POST",
      body: { template },
    }),

  quotaStatus: (ws: string) => apiFetch<QuotaStatus[]>(`/workspaces/${ws}/quota-status`),
};

// ── analytics ────────────────────────────────────────────────────────────────

export type DailySeries = { key: string; label: string; counts: number[] };

export type AnalyticsOverview = {
  days: string[];
  series: DailySeries[];
  total_campaigns: number;
  running_campaigns: number;
  prospects_reached: number;
  total_connected: number;
  total_replies: number;
};

export const analyticsApi = {
  overview: (ws: string, days = 7) =>
    apiFetch<AnalyticsOverview>(`/workspaces/${ws}/analytics/overview?days=${days}`),
};

// ── tracking ─────────────────────────────────────────────────────────────────

export type TrackingStage =
  | "queued"
  | "profile_viewed"
  | "invite_pending"
  | "connected"
  | "replied"
  | "not_accepted"
  | "expired"
  | "stopped"
  | "failed"
  | "skipped";

export type TrackingSummary = {
  campaign_id: string;
  campaign_name: string;
  campaign_status: string;
  total: number;
  /** One bucket per lead; they add up to `total`. */
  stages: { stage: TrackingStage; label: string; count: number }[];
  /** Cumulative: how many ever reached each step. */
  viewed: number;
  invited: number;
  connected: number;
  messaged: number;
  replied: number;
  acceptance_rate: number | null;
  still_waiting: number;
  not_accepted: number;
  expired: number;
  answered: number;
  oldest_pending_days: number | null;
  avg_days_to_accept: number | null;
  next_check_at: string | null;
  tracking_window_days: number;
};

export type TrackingLead = {
  id: string;
  lead_id: string;
  lead_name: string;
  lead_public_id: string;
  lead_company: string;
  lead_title: string;
  stage: TrackingStage;
  stage_label: string;
  reason: string;
  viewed_at: string | null;
  invite_sent_at: string | null;
  days_waiting: number | null;
  accepted_at: string | null;
  resolved_at: string | null;
  last_checked_at: string | null;
  next_check_at: string | null;
  check_count: number;
  replied_at: string | null;
  last_event_type: string;
  last_event_detail: string;
  last_event_at: string | null;
};

export type LeadEvent = {
  id: string;
  event_type: string;
  detail: string;
  occurred_at: string;
  meta: Record<string, unknown>;
};

// ── shared display helpers ───────────────────────────────────────────────────

export const STEP_LABELS: Record<StepType, string> = {
  view_profile: "View profile",
  invite: "Connection request",
  message: "Message",
  withdraw_invite: "Withdraw invite",
  wait: "Wait",
};

export const CONDITION_LABELS: Record<StepCondition, string> = {
  always: "Always",
  if_accepted: "Only if they accepted",
  if_not_accepted: "Only if they have not accepted",
  if_replied: "Only if they replied",
  if_not_replied: "Only if they have not replied",
};

export function describeMinutes(minutes: number): string {
  if (minutes === 0) return "immediately";
  if (minutes < 60) return `${minutes} min`;
  if (minutes % (24 * 60) === 0) {
    const days = minutes / (24 * 60);
    return `${days} day${days === 1 ? "" : "s"}`;
  }
  if (minutes % 60 === 0) return `${minutes / 60} h`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/** One line saying when this step will run, for the builder and summaries. */
export function describeTiming(step: StepInput, isFirst: boolean): string {
  const base = isFirst ? "after the campaign starts" : "after the previous step";
  switch (step.timing ?? "smart") {
    case "asap":
      return "as soon as the account's limits allow";
    case "delay":
      return `${describeMinutes(step.delay_minutes ?? 0)} ${base}`;
    case "at":
      return step.send_at ? `on ${new Date(step.send_at).toLocaleString()}` : "at a time you pick";
    default:
      return `${describeDelay(step.delay_hours)} ${base}, at a natural time in working hours`;
  }
}

export function describeDelay(hours: number): string {
  if (hours === 0) return "immediately";
  if (hours < 24) return `after ${hours}h`;
  const days = Math.round(hours / 24);
  return `after ${days} day${days === 1 ? "" : "s"}`;
}
