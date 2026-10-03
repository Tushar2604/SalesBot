/** Integration layer: API keys for the REST API, and outbound webhooks. */

import { apiFetch } from "@/lib/api";

export type ApiKeyRole = "member" | "admin";

export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  role: ApiKeyRole;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

export type Webhook = {
  id: string;
  url: string;
  description: string;
  events: string[];
  enabled: boolean;
  failure_streak: number;
  disabled_reason: string;
  last_success_at: string | null;
  last_failure_at: string | null;
  created_at: string;
};

export type DeliveryStatus = "pending" | "sending" | "succeeded" | "failed";

export type Delivery = {
  id: string;
  endpoint_id: string;
  event_id: string;
  event_type: string;
  status: DeliveryStatus;
  attempts: number;
  next_attempt_at: string | null;
  delivered_at: string | null;
  response_status: number | null;
  response_body: string;
  error: string;
  duration_ms: number | null;
  created_at: string;
  payload: Record<string, unknown>;
};

export type EventType = { type: string; description: string };

const base = (ws: string) => `/workspaces/${ws}/integrations`;

export const integrationsApi = {
  events: (ws: string) => apiFetch<EventType[]>(`${base(ws)}/events`),

  keys: (ws: string) => apiFetch<ApiKey[]>(`${base(ws)}/api-keys`),
  createKey: (ws: string, name: string, role: ApiKeyRole) =>
    apiFetch<{ key: ApiKey; secret: string }>(`${base(ws)}/api-keys`, {
      method: "POST",
      body: { name, role },
    }),
  revokeKey: (ws: string, id: string) => apiFetch<ApiKey>(`${base(ws)}/api-keys/${id}`, { method: "DELETE" }),

  webhooks: (ws: string) => apiFetch<Webhook[]>(`${base(ws)}/webhooks`),
  createWebhook: (ws: string, body: { url: string; description: string; events: string[] }) =>
    apiFetch<{ webhook: Webhook; secret: string }>(`${base(ws)}/webhooks`, { method: "POST", body }),
  updateWebhook: (
    ws: string,
    id: string,
    patch: Partial<Pick<Webhook, "url" | "description" | "events" | "enabled">>,
  ) => apiFetch<Webhook>(`${base(ws)}/webhooks/${id}`, { method: "PATCH", body: patch }),
  deleteWebhook: (ws: string, id: string) => apiFetch<void>(`${base(ws)}/webhooks/${id}`, { method: "DELETE" }),
  rotateSecret: (ws: string, id: string) =>
    apiFetch<{ webhook: Webhook; secret: string }>(`${base(ws)}/webhooks/${id}/rotate-secret`, { method: "POST" }),
  testWebhook: (ws: string, id: string) => apiFetch<Delivery>(`${base(ws)}/webhooks/${id}/test`, { method: "POST" }),

  deliveries: (ws: string, params: { webhookId?: string; status?: DeliveryStatus; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.webhookId) q.set("webhook_id", params.webhookId);
    if (params.status) q.set("status", params.status);
    q.set("limit", String(params.limit ?? 50));
    return apiFetch<Delivery[]>(`${base(ws)}/deliveries?${q.toString()}`);
  },
  retryDelivery: (ws: string, id: string) =>
    apiFetch<Delivery>(`${base(ws)}/deliveries/${id}/retry`, { method: "POST" }),
};
