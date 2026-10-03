"use client";

/**
 * Integrations: connect this workspace to any other website or tool.
 *
 *   In  (they call us)   REST API with API keys: every workspace endpoint
 *   Out (we call them)   webhooks: signed events with retries and a log
 *
 * Zapier, Make, n8n, a CRM or your own server all use the same two pieces.
 */

import { useState } from "react";
import { hasRole, useSession } from "@/lib/session";
import { TabBar } from "@/components/app/TabBar";
import { ApiKeysPanel, IntegrationDocs, WebhooksPanel } from "@/components/integrations/IntegrationPanels";
import { IconKey, IconLink } from "@/components/app/icons";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "api-keys", label: "API keys" },
  { key: "webhooks", label: "Webhooks" },
  { key: "docs", label: "Docs" },
];

const RECIPES = [
  {
    title: "Send replies to your CRM",
    body: "Webhook on reply.received → create or update the contact and log the message in HubSpot, Salesforce or Pipedrive.",
  },
  {
    title: "Add leads from anywhere",
    body: "A form, a spreadsheet row or a CRM list calls POST /leads/import-urls with LinkedIn profile links.",
  },
  {
    title: "Alert your team",
    body: "Webhook on invite.accepted or assistant.handoff → post to Slack or Teams so someone follows up.",
  },
  {
    title: "Stop outreach from your CRM",
    body: "When a deal closes, call POST /campaigns/{id}/status with paused, or remove the person from the list.",
  },
];

export default function IntegrationsPage() {
  const { workspace, role } = useSession();
  const workspaceId = workspace?.id ?? null;
  const isAdmin = hasRole(role, "admin");
  const [tab, setTab] = useState("overview");

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-2xl font-semibold text-ink-950">Integrations</h1>
      <p className="mb-5 mt-1 text-sm text-slate-500">
        Connect this workspace to any other website or tool: they can call our API, and we notify them when things
        happen.
      </p>

      <TabBar tabs={TABS} active={tab} onChange={setTab} />

      {!isAdmin && tab !== "overview" && tab !== "docs" ? (
        <div className="card mt-4">
          <p className="text-sm text-slate-500">Only workspace admins can manage API keys and webhooks.</p>
        </div>
      ) : (
        <div className="mt-4">
          {tab === "overview" && (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <button className="card text-left transition-colors hover:border-brand-300" onClick={() => setTab("api-keys")}>
                  <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-brand-50 text-brand-500">
                    <IconKey className="h-5 w-5" />
                  </span>
                  <h2 className="mb-1 font-medium text-ink-950">REST API</h2>
                  <p className="text-sm text-slate-500">
                    Other systems add leads, run campaigns and read the inbox using an API key, with the same safety
                    limits as the app.
                  </p>
                </button>
                <button className="card text-left transition-colors hover:border-brand-300" onClick={() => setTab("webhooks")}>
                  <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-brand-50 text-brand-500">
                    <IconLink className="h-5 w-5" />
                  </span>
                  <h2 className="mb-1 font-medium text-ink-950">Webhooks</h2>
                  <p className="text-sm text-slate-500">
                    Get a signed POST when a lead replies, accepts an invite, gets labelled and more. Retried for a
                    day if your server is down.
                  </p>
                </button>
              </div>
              <div className="card">
                <h2 className="mb-3 font-medium text-ink-950">What people build with it</h2>
                <div className="grid gap-3 sm:grid-cols-2">
                  {RECIPES.map((recipe) => (
                    <div key={recipe.title} className="rounded-lg border border-slate-200 p-3">
                      <p className="text-[13.5px] font-semibold text-ink-950">{recipe.title}</p>
                      <p className="mt-0.5 text-[12.5px] text-slate-500">{recipe.body}</p>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-[12.5px] text-slate-500">
                  No-code: in Zapier, Make or n8n, use a &ldquo;Webhooks / catch hook&rdquo; trigger for events, and an
                  &ldquo;HTTP request&rdquo; action with your API key to call us.
                </p>
              </div>
            </div>
          )}
          {tab === "api-keys" && (
            <div className="card">
              <ApiKeysPanel workspaceId={workspaceId} />
            </div>
          )}
          {tab === "webhooks" && <WebhooksPanel workspaceId={workspaceId} />}
          {tab === "docs" && <IntegrationDocs workspaceId={workspaceId} />}
        </div>
      )}
    </div>
  );
}
