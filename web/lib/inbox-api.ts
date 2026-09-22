/**
 * Inbox API surface (Phase 5): LinkedIn conversations and messages.
 *
 * Split from `api.ts` to keep that file about transport and auth, matching
 * how `outreach-api.ts` splits off leads and campaigns.
 */

import { apiFetch } from "@/lib/api";

export type ConversationLabel =
  | "none"
  | "interested"
  | "not_interested"
  | "out_of_office"
  | "question"
  | "other";

export type LabelSource = "manual" | "ai";
export type MessageDirection = "inbound" | "outbound";

export type Conversation = {
  id: string;
  linkedin_account_id: string;
  linkedin_account_label: string;
  lead_id: string | null;
  lead_name: string;
  lead_public_id: string;
  campaign_lead_id: string | null;
  participant_urn: string;
  participant_name: string;
  last_message_at: string | null;
  last_message_text: string;
  last_message_from_me: boolean;
  unread: boolean;
  label: ConversationLabel;
  label_source: LabelSource;
  snoozed_until: string | null;
  created_at: string;
  // AI assistant
  bot_paused: boolean;
  bot_pause_reason: string;
  bot_draft: string;
  bot_draft_at: string | null;
  bot_extracted: Record<string, string>;
};

export type ConversationPage = {
  items: Conversation[];
  total: number;
  limit: number;
  offset: number;
};

export type Message = {
  id: string;
  direction: MessageDirection;
  body: string;
  sent_at: string;
  ai_label: ConversationLabel | null;
  /** "bot" | "human" | "campaign", or "" when unknown / inbound. */
  author?: string;
};

export const inboxApi = {
  conversations: (
    ws: string,
    params: {
      label?: ConversationLabel;
      unreadOnly?: boolean;
      accountId?: string;
      limit?: number;
      offset?: number;
    } = {},
  ) => {
    const query = new URLSearchParams();
    if (params.label) query.set("label", params.label);
    if (params.unreadOnly) query.set("unread_only", "true");
    if (params.accountId) query.set("account_id", params.accountId);
    query.set("limit", String(params.limit ?? 50));
    query.set("offset", String(params.offset ?? 0));
    return apiFetch<ConversationPage>(`/workspaces/${ws}/conversations?${query.toString()}`);
  },

  conversation: (ws: string, id: string) =>
    apiFetch<Conversation>(`/workspaces/${ws}/conversations/${id}`),

  messages: (ws: string, id: string) =>
    apiFetch<Message[]>(`/workspaces/${ws}/conversations/${id}/messages`),

  reply: (ws: string, id: string, text: string) =>
    apiFetch<Conversation>(`/workspaces/${ws}/conversations/${id}/reply`, {
      method: "POST",
      body: { text },
    }),

  setLabel: (ws: string, id: string, label: ConversationLabel) =>
    apiFetch<Conversation>(`/workspaces/${ws}/conversations/${id}/label`, {
      method: "POST",
      body: { label },
    }),

  snooze: (ws: string, id: string, until: string | null) =>
    apiFetch<Conversation>(`/workspaces/${ws}/conversations/${id}/snooze`, {
      method: "POST",
      body: { until },
    }),

  markRead: (ws: string, id: string) =>
    apiFetch<Conversation>(`/workspaces/${ws}/conversations/${id}/read`, { method: "POST" }),

  /** Holds the assistant off while a person is typing in this thread. */
  typing: (ws: string, id: string) =>
    apiFetch<void>(`/workspaces/${ws}/conversations/${id}/typing`, { method: "POST" }),

  setBotPaused: (ws: string, id: string, paused: boolean) =>
    apiFetch<Conversation>(`/workspaces/${ws}/conversations/${id}/bot`, {
      method: "POST",
      body: { paused },
    }),

  sendDraft: (ws: string, id: string, text: string) =>
    apiFetch<Conversation>(`/workspaces/${ws}/conversations/${id}/bot/send-draft`, {
      method: "POST",
      body: { text },
    }),

  discardDraft: (ws: string, id: string) =>
    apiFetch<Conversation>(`/workspaces/${ws}/conversations/${id}/bot/discard-draft`, {
      method: "POST",
    }),
};

// ── shared display helpers ───────────────────────────────────────────────────

export const LABEL_META: Record<ConversationLabel, { text: string; className: string; dot: string }> = {
  none: { text: "No label", className: "bg-slate-100 text-slate-500", dot: "bg-slate-400" },
  interested: {
    text: "Interested",
    className: "bg-emerald-50 text-emerald-600",
    dot: "bg-emerald-500",
  },
  not_interested: {
    text: "Not interested",
    className: "bg-rose-50 text-rose-600",
    dot: "bg-rose-500",
  },
  out_of_office: {
    text: "Out of office",
    className: "bg-amber-50 text-amber-600",
    dot: "bg-amber-500",
  },
  question: { text: "Question", className: "bg-brand-50 text-brand-600", dot: "bg-brand-500" },
  other: { text: "Other", className: "bg-slate-100 text-slate-500", dot: "bg-slate-400" },
};

export const LABEL_OPTIONS: ConversationLabel[] = [
  "none",
  "interested",
  "not_interested",
  "out_of_office",
  "question",
  "other",
];
