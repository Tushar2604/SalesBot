/** AI assistant: settings, named assistants, knowledge base, and a dry-run "try it". */

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
  /** What the assistant should find out, one question at a time. */
  collect_fields: string[];
  /** False when the server has no Claude API key: the assistant cannot run. */
  ai_available: boolean;
};

/** inherit = follow the workspace mode · draft = never send by itself · off = stay silent */
export type ProfileMode = "inherit" | "draft" | "off";

/** A named assistant ("HR recruiter", "Team follow-up") a campaign can pick. */
export type AssistantProfile = {
  id: string;
  name: string;
  mode: ProfileMode;
  persona: string;
  instructions: string;
  handoff_topics: string;
  collect_fields: string[];
  created_at: string;
  updated_at: string;
};

export type AssistantProfileInput = Pick<
  AssistantProfile,
  "name" | "mode" | "persona" | "instructions" | "handoff_topics" | "collect_fields"
>;

export type KnowledgeItem = {
  id: string;
  title: string;
  content: string;
  enabled: boolean;
  /** LinkedIn accounts this SOP is attached to; empty = every account. */
  linkedin_account_ids: string[];
  /** Assistants this SOP is attached to; empty = shared by every assistant. */
  assistant_ids: string[];
  created_at: string;
  updated_at: string;
};

export type KnowledgeInput = {
  title: string;
  content: string;
  enabled?: boolean;
  linkedin_account_ids?: string[];
  assistant_ids?: string[];
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

  saveSettings: (
    ws: string,
    patch: Partial<Omit<AssistantSettings, "ai_available">>,
    acknowledgeRisk = false,
  ) =>
    apiFetch<AssistantSettings>(`/workspaces/${ws}/assistant/settings`, {
      method: "PUT",
      body: { ...patch, acknowledge_risk: acknowledgeRisk },
    }),

  profiles: (ws: string) => apiFetch<AssistantProfile[]>(`/workspaces/${ws}/assistant/profiles`),

  createProfile: (ws: string, body: AssistantProfileInput) =>
    apiFetch<AssistantProfile>(`/workspaces/${ws}/assistant/profiles`, { method: "POST", body }),

  updateProfile: (ws: string, id: string, patch: Partial<AssistantProfileInput>) =>
    apiFetch<AssistantProfile>(`/workspaces/${ws}/assistant/profiles/${id}`, { method: "PATCH", body: patch }),

  deleteProfile: (ws: string, id: string) =>
    apiFetch<void>(`/workspaces/${ws}/assistant/profiles/${id}`, { method: "DELETE" }),

  knowledge: (ws: string) => apiFetch<KnowledgeItem[]>(`/workspaces/${ws}/assistant/knowledge`),

  createKnowledge: (ws: string, item: KnowledgeInput) =>
    apiFetch<KnowledgeItem>(`/workspaces/${ws}/assistant/knowledge`, { method: "POST", body: item }),

  updateKnowledge: (ws: string, id: string, patch: Partial<KnowledgeInput>) =>
    apiFetch<KnowledgeItem>(`/workspaces/${ws}/assistant/knowledge/${id}`, { method: "PATCH", body: patch }),

  deleteKnowledge: (ws: string, id: string) =>
    apiFetch<void>(`/workspaces/${ws}/assistant/knowledge/${id}`, { method: "DELETE" }),

  /** `linkedinAccountId` answers with that account's SOPs (plus the shared ones);
   *  `assistantId` answers as that named assistant (none = the default one). */
  tryIt: (ws: string, turns: TryTurn[], linkedinAccountId?: string | null, assistantId?: string | null) =>
    apiFetch<TryResult>(`/workspaces/${ws}/assistant/try`, {
      method: "POST",
      body: {
        turns,
        prospect_name: "Sample Prospect",
        linkedin_account_id: linkedinAccountId || null,
        assistant_id: assistantId || null,
      },
    }),
};
