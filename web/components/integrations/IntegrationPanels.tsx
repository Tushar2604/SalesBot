"use client";

/**
 * Integration layer UI: API keys (inbound REST), webhooks (outbound events),
 * their delivery log, and copy-paste docs. Used by /integrations; the API
 * keys panel is also shown in Admin Settings.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, ApiError } from "@/lib/api";
import {
  integrationsApi,
  type ApiKey,
  type ApiKeyRole,
  type Delivery,
  type EventType,
  type Webhook,
} from "@/lib/integrations-api";
import { IconCopy, IconKey, IconLink, IconRefresh, IconTrash } from "@/components/app/icons";

function when(iso: string | null): string {
  if (!iso) return "never";
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn-ghost shrink-0 px-2.5 py-1.5 text-xs"
      onClick={() => {
        void navigator.clipboard?.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      <IconCopy className="h-3.5 w-3.5" /> {copied ? "Copied" : label}
    </button>
  );
}

/** A secret shown exactly once, with a clear warning. */
function OneTimeSecret({ title, secret, onDone }: { title: string; secret: string; onDone: () => void }) {
  return (
    <div className="mb-4 rounded-lg border border-emerald-300 bg-emerald-50 p-4">
      <p className="mb-1 text-sm font-semibold text-emerald-900">{title}</p>
      <p className="mb-2 text-[12.5px] text-emerald-800">
        Copy it now and store it somewhere safe. It won&apos;t be shown again.
      </p>
      <div className="flex items-center gap-2">
        <code className="input flex-1 select-all overflow-x-auto whitespace-nowrap bg-white font-mono text-xs">{secret}</code>
        <CopyButton text={secret} />
      </div>
      <button className="mt-2 text-[12.5px] font-semibold text-emerald-800 hover:underline" onClick={onDone}>
        I&apos;ve saved it
      </button>
    </div>
  );
}

function ErrorLine({ error }: { error: string | null }) {
  if (!error) return null;
  return <p className="mb-3 rounded-md border border-state-bad/40 bg-state-bad/10 px-3 py-2 text-sm text-state-bad">{error}</p>;
}

// ── API keys ─────────────────────────────────────────────────────────────────

export function ApiKeysPanel({ workspaceId }: { workspaceId: string }) {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [name, setName] = useState("");
  const [role, setRole] = useState<ApiKeyRole>("member");
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setKeys(await integrationsApi.keys(workspaceId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load API keys");
      setKeys([]);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const made = await integrationsApi.createKey(workspaceId, name.trim() || "API key", role);
      setSecret(made.secret);
      setName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the key");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(key: ApiKey) {
    if (!window.confirm(`Revoke "${key.name}"? Anything using it stops working immediately.`)) return;
    try {
      await integrationsApi.revokeKey(workspaceId, key.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not revoke the key");
    }
  }

  const active = (keys ?? []).filter((k) => !k.revoked_at);
  const revoked = (keys ?? []).filter((k) => k.revoked_at);

  return (
    <div>
      <ErrorLine error={error} />
      {secret && <OneTimeSecret title="Your new API key" secret={secret} onDone={() => setSecret(null)} />}

      <div className="mb-4 flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-slate-300 p-3">
        <div className="min-w-0 flex-1">
          <label className="label">Key name</label>
          <input
            className="input"
            value={name}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. HubSpot sync, Zapier, internal dashboard"
          />
        </div>
        <div>
          <label className="label">Access</label>
          <select className="input w-auto" value={role} onChange={(e) => setRole(e.target.value as ApiKeyRole)}>
            <option value="member">Member: leads, campaigns, inbox</option>
            <option value="admin">Admin: also settings and webhooks</option>
          </select>
        </div>
        <button className="btn-primary" disabled={busy} onClick={() => void create()}>
          <IconKey className="h-4 w-4" /> {busy ? "Creating…" : "Create API key"}
        </button>
      </div>

      {keys === null ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : active.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-200 px-4 py-6 text-center text-sm text-slate-400">
          No API keys yet. Create one to let another system use this workspace.
        </p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
          {active.map((key) => (
            <li key={key.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="text-[13.5px] font-semibold text-ink-950">{key.name}</p>
                <p className="text-[12px] text-slate-500">
                  <code className="font-mono">{key.prefix}…</code> · {key.role} · created {when(key.created_at)} · last
                  used {when(key.last_used_at)}
                </p>
              </div>
              <button className="btn-ghost px-2.5 py-1.5 text-xs text-state-bad" onClick={() => void revoke(key)}>
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}
      {revoked.length > 0 && (
        <p className="mt-2 text-[12px] text-slate-400">{revoked.length} revoked key(s) hidden.</p>
      )}
    </div>
  );
}

// ── webhooks ─────────────────────────────────────────────────────────────────

function EventPicker({
  catalog,
  value,
  onChange,
}: {
  catalog: EventType[];
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const all = value.includes("*");
  return (
    <div>
      <label className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-ink-950">
        <input type="checkbox" checked={all} onChange={(e) => onChange(e.target.checked ? ["*"] : [])} />
        All events (including ones added later)
      </label>
      {!all && (
        <div className="grid gap-1.5 sm:grid-cols-2">
          {catalog
            .filter((e) => e.type !== "webhook.test")
            .map((event) => (
              <label key={event.type} className="flex items-start gap-2 rounded-md border border-slate-200 px-2.5 py-2 text-[12.5px]">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={value.includes(event.type)}
                  onChange={(e) =>
                    onChange(e.target.checked ? [...value, event.type] : value.filter((t) => t !== event.type))
                  }
                />
                <span>
                  <code className="font-mono text-[12px] text-ink-950">{event.type}</code>
                  <span className="block text-slate-500">{event.description}</span>
                </span>
              </label>
            ))}
        </div>
      )}
    </div>
  );
}

const STATUS_STYLE: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-700",
  failed: "bg-rose-100 text-rose-700",
  pending: "bg-amber-100 text-amber-700",
  sending: "bg-sky-100 text-sky-700",
};

function DeliveryLog({ workspaceId, webhooks, refreshKey }: { workspaceId: string; webhooks: Webhook[]; refreshKey: number }) {
  const [rows, setRows] = useState<Delivery[] | null>(null);
  const [filter, setFilter] = useState<string>("");
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await integrationsApi.deliveries(workspaceId, { webhookId: filter || undefined, limit: 50 }));
    } catch {
      setRows([]);
    }
  }, [workspaceId, filter]);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 10_000);
    return () => clearInterval(timer);
  }, [load, refreshKey]);

  const urlById = useMemo(() => new Map(webhooks.map((w) => [w.id, w.url])), [webhooks]);

  return (
    <div className="card">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-[15px] font-bold text-ink-950">Recent deliveries</h3>
          <p className="text-[12.5px] text-slate-500">Failed sends are retried for about a day (1m, 5m, 30m, 2h, 6h, 12h).</p>
        </div>
        <div className="flex items-center gap-2">
          <select className="input w-auto" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All webhooks</option>
            {webhooks.map((w) => (
              <option key={w.id} value={w.id}>
                {w.description || w.url}
              </option>
            ))}
          </select>
          <button className="btn-ghost px-2.5" onClick={() => void load()} aria-label="Refresh deliveries">
            <IconRefresh className="h-4 w-4" />
          </button>
        </div>
      </div>
      {rows === null ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-slate-400">No deliveries yet. Send a test event to see one here.</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {rows.map((d) => (
            <li key={d.id} className="py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${STATUS_STYLE[d.status] ?? ""}`}>{d.status}</span>
                <code className="font-mono text-[12.5px] text-ink-950">{d.event_type}</code>
                <span className="min-w-0 flex-1 truncate text-[12px] text-slate-400">{urlById.get(d.endpoint_id)}</span>
                <span className="text-[12px] text-slate-500">
                  {d.response_status ? `HTTP ${d.response_status}` : ""} {d.attempts > 0 && `· try ${d.attempts}`} ·{" "}
                  {when(d.created_at)}
                </span>
                <button className="text-[12px] font-semibold text-brand-600 hover:underline" onClick={() => setOpen(open === d.id ? null : d.id)}>
                  {open === d.id ? "Hide" : "Details"}
                </button>
                {(d.status === "failed" || d.status === "succeeded") && (
                  <button
                    className="text-[12px] font-semibold text-brand-600 hover:underline"
                    onClick={() => void integrationsApi.retryDelivery(workspaceId, d.id).then(load)}
                  >
                    Resend
                  </button>
                )}
              </div>
              {d.error && <p className="mt-1 text-[12px] text-rose-700">{d.error}</p>}
              {open === d.id && (
                <div className="mt-2 grid gap-2 lg:grid-cols-2">
                  <pre className="max-h-64 overflow-auto rounded-md bg-slate-900 p-3 text-[11.5px] text-slate-100">
                    {JSON.stringify(d.payload, null, 2)}
                  </pre>
                  <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-slate-100 p-3 text-[11.5px] text-slate-700">
                    {d.response_body || "(empty response)"}
                  </pre>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function WebhooksPanel({ workspaceId }: { workspaceId: string }) {
  const [hooks, setHooks] = useState<Webhook[] | null>(null);
  const [catalog, setCatalog] = useState<EventType[]>([]);
  const [adding, setAdding] = useState(false);
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [events, setEvents] = useState<string[]>(["reply.received", "invite.accepted"]);
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editEvents, setEditEvents] = useState<string[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    try {
      const [h, c] = await Promise.all([integrationsApi.webhooks(workspaceId), integrationsApi.events(workspaceId)]);
      setHooks(h);
      setCatalog(c);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load webhooks");
      setHooks([]);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<unknown>, done?: string) {
    setError(null);
    setNotice(null);
    try {
      await action();
      if (done) setNotice(done);
      await load();
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    }
  }

  async function create() {
    await run(async () => {
      const made = await integrationsApi.createWebhook(workspaceId, { url: url.trim(), description: description.trim(), events });
      setSecret(made.secret);
      setAdding(false);
      setUrl("");
      setDescription("");
    });
  }

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3 className="text-[15px] font-bold text-ink-950">Webhook endpoints</h3>
            <p className="text-[12.5px] text-slate-500">
              We POST a signed JSON event to each URL when something happens. Works with Zapier, Make, n8n or your own
              server.
            </p>
          </div>
          {!adding && (
            <button className="btn-primary" onClick={() => setAdding(true)}>
              <IconLink className="h-4 w-4" /> Add webhook
            </button>
          )}
        </div>
        <ErrorLine error={error} />
        {notice && <p className="mb-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{notice}</p>}
        {secret && <OneTimeSecret title="Signing secret for this webhook" secret={secret} onDone={() => setSecret(null)} />}

        {adding && (
          <div className="mb-4 space-y-3 rounded-lg border border-dashed border-brand-300 bg-brand-50/30 p-3">
            <div>
              <label className="label">Endpoint URL</label>
              <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://hooks.zapier.com/hooks/catch/…" />
            </div>
            <div>
              <label className="label">Description (optional)</label>
              <input className="input" value={description} maxLength={200} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Push replies to HubSpot" />
            </div>
            <EventPicker catalog={catalog} value={events} onChange={setEvents} />
            <div className="flex justify-end gap-2">
              <button className="btn-ghost" onClick={() => setAdding(false)}>
                Cancel
              </button>
              <button className="btn-primary" disabled={!url.trim() || events.length === 0} onClick={() => void create()}>
                Save webhook
              </button>
            </div>
          </div>
        )}

        {hooks === null ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : hooks.length === 0 ? (
          !adding && (
            <p className="rounded-lg border border-dashed border-slate-200 px-4 py-6 text-center text-sm text-slate-400">
              No webhooks yet.
            </p>
          )
        ) : (
          <ul className="space-y-2">
            {hooks.map((hook) => (
              <li key={hook.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`h-2 w-2 shrink-0 rounded-full ${hook.enabled ? "bg-emerald-500" : "bg-slate-300"}`} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13.5px] font-semibold text-ink-950">{hook.description || hook.url}</p>
                    <p className="truncate text-[12px] text-slate-500">{hook.description ? hook.url : ""}</p>
                  </div>
                  <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => void run(() => integrationsApi.testWebhook(workspaceId, hook.id), "Test event queued. It arrives within about 15 seconds; watch the log below.")}>
                    Send test
                  </button>
                  <button
                    className="btn-ghost px-2.5 py-1.5 text-xs"
                    onClick={() => {
                      setEditing(editing === hook.id ? null : hook.id);
                      setEditEvents(hook.events);
                    }}
                  >
                    Events
                  </button>
                  <button
                    className="btn-ghost px-2.5 py-1.5 text-xs"
                    onClick={() => void run(() => integrationsApi.updateWebhook(workspaceId, hook.id, { enabled: !hook.enabled }))}
                  >
                    {hook.enabled ? "Pause" : "Turn on"}
                  </button>
                  <button
                    className="btn-ghost px-2.5 py-1.5 text-xs"
                    onClick={() => {
                      if (window.confirm("Make a new signing secret? The old one stops working immediately."))
                        void run(async () => setSecret((await integrationsApi.rotateSecret(workspaceId, hook.id)).secret));
                    }}
                  >
                    New secret
                  </button>
                  <button
                    aria-label="Delete webhook"
                    className="text-slate-400 hover:text-state-bad"
                    onClick={() => {
                      if (window.confirm(`Delete the webhook to ${hook.url}?`)) void run(() => integrationsApi.deleteWebhook(workspaceId, hook.id));
                    }}
                  >
                    <IconTrash className="h-4 w-4" />
                  </button>
                </div>
                <p className="mt-1.5 text-[12px] text-slate-500">
                  {hook.events.includes("*") ? "All events" : hook.events.join(", ")} · last success {when(hook.last_success_at)}
                  {hook.failure_streak > 0 && ` · ${hook.failure_streak} failures in a row`}
                </p>
                {hook.disabled_reason && <p className="mt-1 text-[12px] text-rose-700">{hook.disabled_reason}</p>}
                {editing === hook.id && (
                  <div className="mt-3 border-t border-slate-100 pt-3">
                    <EventPicker catalog={catalog} value={editEvents} onChange={setEditEvents} />
                    <div className="mt-2 flex justify-end">
                      <button
                        className="btn-primary px-3 py-1.5 text-xs"
                        disabled={editEvents.length === 0}
                        onClick={() =>
                          void run(async () => {
                            await integrationsApi.updateWebhook(workspaceId, hook.id, { events: editEvents });
                            setEditing(null);
                          })
                        }
                      >
                        Save events
                      </button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {hooks && hooks.length > 0 && <DeliveryLog workspaceId={workspaceId} webhooks={hooks} refreshKey={refreshKey} />}
    </div>
  );
}

// ── docs ─────────────────────────────────────────────────────────────────────

function Code({ children }: { children: string }) {
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-lg bg-slate-900 p-3 pr-20 text-[12px] leading-relaxed text-slate-100">{children}</pre>
      <div className="absolute right-2 top-2">
        <CopyButton text={children} />
      </div>
    </div>
  );
}

export function IntegrationDocs({ workspaceId }: { workspaceId: string }) {
  const root = `${API_BASE}/api/v1/workspaces/${workspaceId}`;
  return (
    <div className="space-y-5">
      <section className="card">
        <h3 className="mb-1 text-[15px] font-bold text-ink-950">REST API</h3>
        <p className="mb-3 text-[13px] text-slate-600">
          Everything the app does is available over HTTP. Send your API key as{" "}
          <code className="font-mono">Authorization: Bearer sr_live_…</code> (or an <code className="font-mono">X-API-Key</code> header).
          Every endpoint, with request and response shapes, is in the{" "}
          <a className="font-semibold text-brand-600 hover:underline" href={`${API_BASE}/docs`} target="_blank" rel="noreferrer">
            interactive API reference
          </a>
          .
        </p>
        <p className="label">Your workspace ID</p>
        <div className="mb-4 flex items-center gap-2">
          <code className="input flex-1 font-mono text-xs">{workspaceId}</code>
          <CopyButton text={workspaceId} />
        </div>
        <p className="label">Check a key</p>
        <Code>{`curl ${root}/integrations/whoami \\
  -H "Authorization: Bearer $SALESROBO_API_KEY"`}</Code>
        <p className="label mt-4">Add leads from LinkedIn profile links</p>
        <Code>{`curl -X POST ${root}/leads/import-urls \\
  -H "Authorization: Bearer $SALESROBO_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"urls": "https://www.linkedin.com/in/someone", "list_name": "From my CRM"}'`}</Code>
        <p className="label mt-4">Pause or resume a campaign</p>
        <Code>{`curl ${root}/campaigns -H "Authorization: Bearer $SALESROBO_API_KEY"   # find its id

curl -X POST ${root}/campaigns/CAMPAIGN_ID/status \\
  -H "Authorization: Bearer $SALESROBO_API_KEY" \\
  -H "Content-Type: application/json" -d '{"status": "paused"}'`}</Code>
        <p className="label mt-4">Read replies</p>
        <Code>{`curl "${root}/conversations?unread_only=true" -H "Authorization: Bearer $SALESROBO_API_KEY"`}</Code>
        <p className="mt-3 text-[12.5px] text-slate-500">
          Limits: 300 requests per minute per key (HTTP 429 above that). A key acts as the person who created it and
          stops working if they leave the workspace. Everything a key triggers on LinkedIn still goes through the same
          safety limits and action gaps as the app itself.
        </p>
      </section>

      <section className="card">
        <h3 className="mb-1 text-[15px] font-bold text-ink-950">Webhook events</h3>
        <p className="mb-3 text-[13px] text-slate-600">Every event has the same envelope. Use <code className="font-mono">id</code> to ignore duplicates.</p>
        <Code>{`POST https://your-server.example/hook
X-SalesRobo-Event: reply.received
X-SalesRobo-Signature: t=1790000000,v1=5f2b…

{
  "id": "6e1c…",
  "type": "reply.received",
  "created_at": "2026-09-28T10:15:00+00:00",
  "workspace_id": "${workspaceId}",
  "data": {
    "conversation_id": "…",
    "text": "Sounds interesting, tell me more",
    "lead": { "first_name": "Priya", "profile_url": "https://www.linkedin.com/in/…", "company": "…" },
    "campaign_id": "…"
  }
}`}</Code>
        <p className="label mt-4">Verify the signature (Node.js)</p>
        <Code>{`import crypto from "node:crypto";

function verify(rawBody, header, secret) {
  const parts = Object.fromEntries(header.split(",").map((p) => p.split("=")));
  if (Math.abs(Date.now() / 1000 - Number(parts.t)) > 300) return false; // replay
  const expected = crypto.createHmac("sha256", secret)
    .update(\`\${parts.t}.\${rawBody}\`).digest("hex");
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(parts.v1));
}`}</Code>
        <p className="label mt-4">Verify the signature (Python)</p>
        <Code>{`import hashlib, hmac, time

def verify(raw_body: bytes, header: str, secret: str) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    if abs(time.time() - int(parts["t"])) > 300:
        return False  # replay
    expected = hmac.new(secret.encode(), f"{parts['t']}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])`}</Code>
        <p className="mt-3 text-[12.5px] text-slate-500">
          Answer with any 2xx within 10 seconds. Anything else is retried with backoff for about a day; redirects are
          not followed. An endpoint that fails 50 times in a row is paused automatically.
        </p>
      </section>
    </div>
  );
}
