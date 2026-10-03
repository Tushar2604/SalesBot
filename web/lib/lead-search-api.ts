/** AI lead finder: chat to find prospects via people-data providers (never a LinkedIn account). */

import { apiFetch } from "@/lib/api";
import type { ImportReport } from "@/lib/outreach-api";

export type LeadSearchStatus = {
  /** People-data providers with a key, in the order they are tried. */
  providers: string[];
  ready: boolean;
  ai_available: boolean;
  daily_limit: number;
  used_today: number;
};

export type FoundLead = {
  public_id: string;
  profile_url: string;
  first_name: string;
  last_name: string;
  headline: string;
  title: string;
  company: string;
  location: string;
  avatar_url: string;
  provider: string;
  match_reasons: string[];
  score: number;
  in_leads: boolean;
};

export type ChatMessage = { role: "user" | "assistant"; text: string; at: string };

export type LeadSearch = {
  id: string;
  title: string;
  messages: ChatMessage[];
  criteria: Record<string, unknown>;
  criteria_summary: string;
  results: FoundLead[];
  provider: string;
  created_at: string;
  updated_at: string;
};

export type LeadSearchSummary = { id: string; title: string; result_count: number; updated_at: string };

export type ChatResult = {
  search: LeadSearch;
  reply: string;
  needs_clarification: boolean;
  notices: string[];
};

export const PROVIDER_LABELS: Record<string, string> = {
  exa: "Exa",
  pdl: "People Data Labs",
  apollo: "Apollo",
  brave: "Brave Search",
};

export const leadSearchApi = {
  status: (ws: string) => apiFetch<LeadSearchStatus>(`/workspaces/${ws}/lead-search/status`),

  chat: (ws: string, message: string, searchId?: string | null) =>
    apiFetch<ChatResult>(`/workspaces/${ws}/lead-search/chat`, {
      method: "POST",
      body: { message, search_id: searchId || null },
    }),

  searches: (ws: string) => apiFetch<LeadSearchSummary[]>(`/workspaces/${ws}/lead-search/searches`),

  search: (ws: string, id: string) => apiFetch<LeadSearch>(`/workspaces/${ws}/lead-search/searches/${id}`),

  importFound: (ws: string, id: string, publicIds: string[], listName: string) =>
    apiFetch<ImportReport>(`/workspaces/${ws}/lead-search/searches/${id}/import`, {
      method: "POST",
      body: { public_ids: publicIds, list_name: listName },
    }),
};
