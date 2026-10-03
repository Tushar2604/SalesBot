/** Platform admin panel: every workspace's LinkedIn accounts and their ban risk. */

import { apiFetch, type LinkedInAccountStatus, type RiskLevel } from "@/lib/api";

export type AdminMember = { user_id: string; email: string; full_name: string; role: string };

export type AdminAccount = {
  id: string;
  label: string;
  full_name: string;
  public_id: string;
  profile_url: string;
  status: LinkedInAccountStatus;
  status_detail: string;
  health_score: number;
  test_mode: boolean;
  proxy: string;
  last_action_at: string | null;
  connected_at: string;
  workspace_id: string;
  workspace_name: string;
  connected_by_email: string;
  connected_by_name: string;
  members: AdminMember[];
  warning_count: number;
  warning_limit: number;
  risk_level: RiskLevel;
  last_warning: string;
  last_warning_at: string | null;
  active_campaigns: number;
};

export type AdminRiskEvent = {
  id: string;
  source: "linkedin" | "override" | string;
  kind: string;
  strikes: number;
  detail: string;
  actor_email: string;
  created_at: string;
  cleared_at: string | null;
  /** Still counts toward the automatic pause (recent and not cleared). */
  counts: boolean;
};

const action = (id: string, verb: "pause" | "revoke" | "restore", reason: string) =>
  apiFetch<AdminAccount>(`/admin/linkedin-accounts/${id}/${verb}`, {
    method: "POST",
    body: { reason },
  });

export const adminApi = {
  accounts: () => apiFetch<AdminAccount[]>("/admin/linkedin-accounts"),
  events: (id: string) => apiFetch<AdminRiskEvent[]>(`/admin/linkedin-accounts/${id}/events`),
  pause: (id: string, reason = "") => action(id, "pause", reason),
  revoke: (id: string, reason = "") => action(id, "revoke", reason),
  restore: (id: string, reason = "") => action(id, "restore", reason),
  clearEvent: (eventId: string) =>
    apiFetch<AdminRiskEvent>(`/admin/risk-events/${eventId}/clear`, { method: "POST" }),
};
