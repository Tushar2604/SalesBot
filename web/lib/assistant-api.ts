/** AI assistant: settings, knowledge base, and a dry-run "try it". */

import { apiFetch } from "@/lib/api";

export type AssistantMode = "off" | "draft" | "auto";

export type AssistantSettings = {
  mode: AssistantMode;
  persona: string;
  instructions: string;
  handoff_topics: string;
  reply_delay_min_minutes: number;
  reply_delay_max_minutes: number;
  max_replies_per_thread_per_day: number;
  max_replies_per_account_per_day: number;
  working_hours_only: boolean;
  /** False when the server has no Claude API key: the assistant cannot run. */
  ai_available: boolean;
};

export type KnowledgeItem = {
  id: string;
  title: string;
  content: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type TryTurn = { from_me: boolean; text: string };

export type TryResult = {
  action: "reply" | "handoff" | "no_reply" | "unavailable";
  reply: string;
  handoff_reason: string;
  shared_facts: { field: string; value: string }[];
};

export const assistantApi = {
  settings: (ws: string) => apiFetch<AssistantSettings>(`/workspaces/${ws}/assistant/settings`),

  saveSettings: (ws: string, patch: Partial<Omit<AssistantSettings, "ai_available">>) =>
    apiFetch<AssistantSettings>(`/workspaces/${ws}/assistant/settings`, { method: "PUT", body: patch }),

  knowledge: (ws: string) => apiFetch<KnowledgeItem[]>(`/workspaces/${ws}/assistant/knowledge`),

  createKnowledge: (ws: string, item: { title: string; content: string; enabled?: boolean }) =>
    apiFetch<KnowledgeItem>(`/workspaces/${ws}/assistant/knowledge`, { method: "POST", body: item }),

  updateKnowledge: (ws: string, id: string, patch: Partial<Pick<KnowledgeItem, "title" | "content" | "enabled">>) =>
    apiFetch<KnowledgeItem>(`/workspaces/${ws}/assistant/knowledge/${id}`, { method: "PATCH", body: patch }),

  deleteKnowledge: (ws: string, id: string) =>
    apiFetch<void>(`/workspaces/${ws}/assistant/knowledge/${id}`, { method: "DELETE" }),

  tryIt: (ws: string, turns: TryTurn[], prospect_name?: string) =>
    apiFetch<TryResult>(`/workspaces/${ws}/assistant/try`, {
      method: "POST",
      body: { turns, prospect_name: prospect_name || "Sample Prospect" },
    }),
};
