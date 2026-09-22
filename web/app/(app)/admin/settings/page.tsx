"use client";

/**
 * Admin Settings. Manage Team reuses the real member/invite API. My Plan,
 * My Credits, API Key, Cross Account Settings and AI Config SOPs have no
 * billing/SOP backend in this environment, so they're local-only stubs that
 * still look and behave like the real screens (a generated key persists, a
 * plan can be "selected", etc).
 */

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Invite, type Member, type WorkspaceRole } from "@/lib/api";
import { hasRole, useSession } from "@/lib/session";
import { useLocalState } from "@/lib/localSettings";
import { TabBar } from "@/components/app/TabBar";
import { IconCheckCircle, IconKey, IconTrash } from "@/components/app/icons";

const TABS = [
  { key: "manage-team", label: "Manage Team" },
  { key: "cross-account", label: "Cross Account Settings" },
  { key: "ai-config", label: "AI Config" },
  { key: "my-plan", label: "My Plan" },
  { key: "my-credits", label: "My Credits" },
  { key: "api-key", label: "API Key" },
  { key: "mcp", label: "MCP" },
];

const ROLES: WorkspaceRole[] = ["member", "admin", "owner"];

const PLANS = [
  {
    id: "basic",
    name: "Basic",
    price: 39,
    features: ["1 active campaign", "Limited daily quotas", "Advanced dashboard & reports", "Complete performance automation"],
  },
  {
    id: "advanced",
    name: "Advanced",
    price: 59,
    features: [
      "Unlimited active campaigns",
      "Full daily quotas",
      "Advanced dashboard & reports",
      "Complete performance automation",
      "A/B testing",
      "Personal inbox",
      "Webhook & Zapier integration",
      "Export leads into CSV",
    ],
  },
  {
    id: "professional",
    name: "Professional",
    price: 79,
    features: [
      "Unlimited active campaigns",
      "Full daily quotas",
      "A/B testing",
      "Personal inbox",
      "Webhook & Zapier integration",
      "Export leads into CSV",
      "Team management",
      "Activity control",
    ],
  },
];

function randomKey(): string {
  const bytes = new Uint8Array(24);
  window.crypto.getRandomValues(bytes);
  return "sr_" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export default function AdminSettingsPage() {
  const { workspace } = useSession();
  const workspaceId = workspace?.id ?? null;
  const [tab, setTab] = useState("manage-team");

  const [plan, setPlan] = useLocalState(workspaceId, "admin-plan", { id: "professional", trial: true });
  const [apiKey, setApiKey] = useLocalState<string | null>(workspaceId, "admin-api-key", null);

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-6 text-2xl font-semibold text-ink-950">Admin Settings</h1>

      <TabBar tabs={TABS} active={tab} onChange={setTab} />

      {tab === "manage-team" && <ManageTeamTab workspaceId={workspaceId} />}

      {tab === "cross-account" && (
        <div className="card flex flex-col items-center py-16 text-center">
          <IconCheckCircle className="mb-4 h-10 w-10 text-slate-300" />
          <p className="mb-1 font-medium text-ink-950">No cross account configurations yet</p>
          <p className="text-sm text-slate-500">Once you add LinkedIn account mappings, they will appear here.</p>
        </div>
      )}

      {tab === "ai-config" && (
        <div className="card">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="font-medium text-ink-950">AI Inbox Manager SOP Configuration</h2>
              <p className="text-sm text-slate-500">
                After an SOP is created, it needs to be assigned to a campaign to be used for
                generating AI-powered replies.
              </p>
            </div>
            <div className="flex gap-2">
              <button className="btn-primary" disabled>
                Generate SOP
              </button>
              <button className="btn-ghost" disabled>
                Upload SOP
              </button>
            </div>
          </div>
          <input className="input mb-4" placeholder="Search SOPs by name..." disabled />
          <div className="rounded-lg border border-dashed border-slate-200 px-4 py-10 text-center text-sm text-slate-400">
            No SOPs found. Generating an SOP requires an LLM pipeline, which is not connected in
            this environment.
          </div>
        </div>
      )}

      {tab === "my-plan" && (
        <div className="card">
          <div className="mb-8 text-center">
            <h2 className="font-display text-xl font-extrabold text-ink-950">Simple &amp; transparent pricing</h2>
            <p className="mt-1 text-sm text-slate-500">Pick the plan that matches how much outreach you run.</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            {PLANS.map((p) => (
              <div
                key={p.id}
                className={`rounded-xl border p-5 ${p.id === plan.id ? "border-brand-400 bg-brand-50/40" : "border-slate-200"}`}
              >
                <p className="font-semibold text-ink-950">{p.name}</p>
                <p className="mt-2 text-3xl font-extrabold text-ink-950">
                  ${p.price}
                  <span className="text-sm font-medium text-slate-500"> /mo</span>
                </p>
                <ul className="mt-4 space-y-2">
                  {p.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-xs text-slate-600">
                      <IconCheckCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-500" />
                      {f}
                    </li>
                  ))}
                </ul>
                <button
                  className={`btn mt-5 w-full ${p.id === plan.id ? "bg-brand-100 text-brand-700" : "btn-ghost"}`}
                  onClick={() => setPlan({ id: p.id, trial: false })}
                >
                  {p.id === plan.id ? (plan.trial ? "Current Plan (Free Trial)" : "Current Plan") : "Switch Plan"}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "my-credits" && (
        <div className="card">
          <p className="mb-1 text-sm font-semibold text-emerald-600">
            {plan.trial ? "Free Plan Active" : `${PLANS.find((p) => p.id === plan.id)?.name} Plan Active`}
          </p>
          <p className="mb-4 text-sm text-slate-600">225 credits left this billing period</p>
          <button className="btn-ghost" onClick={() => setTab("my-plan")}>
            Change Plan
          </button>
        </div>
      )}

      {tab === "api-key" && (
        <div className="card">
          {!apiKey ? (
            <div className="flex flex-col items-center py-14 text-center">
              <IconKey className="mb-4 h-10 w-10 text-brand-400" />
              <p className="mb-1 font-medium text-ink-950">No API Key Generated</p>
              <p className="mb-5 max-w-sm text-sm text-slate-500">
                Generate an API key to authenticate and access the exposed API endpoints for your
                account.
              </p>
              <button className="btn-primary" onClick={() => setApiKey(randomKey())}>
                Generate API Key
              </button>
            </div>
          ) : (
            <div>
              <p className="label">Your API key</p>
              <div className="flex items-center gap-2">
                <code className="input flex-1 select-all font-mono text-xs">{apiKey}</code>
                <button className="btn-ghost" onClick={() => navigator.clipboard?.writeText(apiKey)}>
                  Copy
                </button>
                <button className="btn-danger" onClick={() => setApiKey(null)}>
                  Revoke
                </button>
              </div>
            </div>
          )}
          <div className="mt-6 flex items-center justify-between gap-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <div>
              <p className="text-sm font-semibold text-ink-950">API Documentation</p>
              <p className="text-xs text-slate-500">View the full API reference to explore all available endpoints.</p>
            </div>
            <span className="text-xs font-semibold text-brand-600">docs coming soon</span>
          </div>
        </div>
      )}

      {tab === "mcp" && (
        <div className="card">
          <h2 className="mb-1 font-medium text-ink-950">MCP Server</h2>
          <p className="mb-5 text-sm text-slate-500">Connect AI tools like Claude to your workspace data via the Model Context Protocol.</p>

          <p className="label">Server URL</p>
          <div className="mb-5 flex items-center gap-2">
            <code className="input flex-1 font-mono text-xs">https://mcp.salesrobo.local</code>
            <button className="btn-ghost" onClick={() => navigator.clipboard?.writeText("https://mcp.salesrobo.local")}>
              Copy
            </button>
          </div>
          <p className="mb-5 text-xs text-slate-500">
            Your API key is required for authentication — find it in the API Key tab above.
          </p>

          <p className="mb-2 text-sm font-semibold text-ink-950">Setup with Claude</p>
          <ol className="list-decimal space-y-1.5 pl-5 text-sm text-slate-600">
            <li>Open claude.ai, click your profile icon → Settings.</li>
            <li>Navigate to Connectors in the left sidebar.</li>
            <li>Click Add custom connector and paste the server URL above.</li>
            <li>Add your API key when prompted.</li>
            <li>In a conversation, click + → Connectors and toggle this workspace on.</li>
          </ol>
        </div>
      )}
    </div>
  );
}

function ManageTeamTab({ workspaceId }: { workspaceId: string }) {
  const { role, me } = useSession();
  const isAdmin = hasRole(role, "admin");

  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<WorkspaceRole>("member");
  const [lastInviteUrl, setLastInviteUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setMembers(await api.members(workspaceId));
      if (isAdmin) setInvites(await api.invites(workspaceId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the team");
    }
  }, [workspaceId, isAdmin]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<void>) {
    setError(null);
    setBusy(true);
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="mb-5 flex items-center justify-between gap-3">
        <h2 className="font-medium text-ink-950">Team members</h2>
        {isAdmin && (
          <button
            className="btn-primary"
            onClick={() => {
              const el = document.getElementById("invite-form");
              el?.scrollIntoView({ behavior: "smooth" });
            }}
          >
            Invite new user
          </button>
        )}
      </div>

      {error && <p className="mb-4 text-sm text-state-bad">{error}</p>}

      <div className="overflow-hidden rounded-xl border border-slate-200">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/70 text-[11px] font-bold uppercase tracking-wider text-slate-500">
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {members.map((member) => {
              const isSelf = member.user.id === me?.user.id;
              return (
                <tr key={member.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-3 text-[13.5px] font-semibold text-ink-950">
                    {member.user.full_name || member.user.email}
                    {isSelf && <span className="badge ml-2">you</span>}
                  </td>
                  <td className="px-4 py-3 text-[13px] text-slate-500">{member.user.email}</td>
                  <td className="px-4 py-3">
                    {isAdmin ? (
                      <select
                        className="input w-32 py-1"
                        value={member.role}
                        disabled={busy}
                        onChange={(e) =>
                          void run(async () => {
                            await api.updateMemberRole(workspaceId, member.id, e.target.value as WorkspaceRole);
                          })
                        }
                      >
                        {ROLES.filter((r) => r !== "owner" || role === "owner").map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="badge">{member.role}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {isAdmin && !isSelf && (
                      <button className="text-slate-400 hover:text-state-bad" disabled={busy} onClick={() => void run(() => api.removeMember(workspaceId, member.id))}>
                        <IconTrash className="h-4 w-4" />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {isAdmin && (
        <div id="invite-form" className="mt-6 border-t border-slate-100 pt-5">
          <p className="mb-3 text-sm font-semibold text-ink-950">Invite someone</p>
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              void run(async () => {
                const created = await api.createInvite(workspaceId, inviteEmail, inviteRole);
                setLastInviteUrl(created.invite_url);
                setInviteEmail("");
              });
            }}
          >
            <div className="min-w-56 flex-1">
              <label className="label">Email</label>
              <input type="email" className="input" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} required />
            </div>
            <div>
              <label className="label">Role</label>
              <select className="input w-32" value={inviteRole} onChange={(e) => setInviteRole(e.target.value as WorkspaceRole)}>
                {ROLES.filter((r) => r !== "owner" || role === "owner").map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
            <button type="submit" className="btn-primary" disabled={busy}>
              Send invite
            </button>
          </form>

          {lastInviteUrl && (
            <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3">
              <p className="mb-1 text-xs text-slate-500">Share this link. It is shown once.</p>
              <code className="break-all text-xs text-accent">{lastInviteUrl}</code>
            </div>
          )}

          {invites.length > 0 && (
            <ul className="mt-6 divide-y divide-slate-200 border-t border-slate-200">
              {invites.map((invite) => (
                <li key={invite.id} className="flex items-center gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-slate-800">{invite.email}</p>
                    <p className="text-xs text-slate-500">
                      {invite.role} · {invite.status}
                    </p>
                  </div>
                  {invite.status === "pending" && (
                    <button className="btn-ghost" disabled={busy} onClick={() => void run(() => api.revokeInvite(workspaceId, invite.id))}>
                      Revoke
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
