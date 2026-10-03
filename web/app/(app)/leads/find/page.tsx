"use client";

/**
 * AI lead finder — describe who you want, get the top matches, add them to a list.
 *
 * Searches run against licensed people-data providers (Exa, People Data Labs,
 * Apollo, Brave X-ray) on the server — never through a connected LinkedIn
 * account, which is what gets accounts restricted. Found people meet LinkedIn
 * only later, through a campaign's paced profile visits.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { ImportReport } from "@/lib/outreach-api";
import {
  PROVIDER_LABELS,
  leadSearchApi,
  type FoundLead,
  type LeadSearch,
  type LeadSearchStatus,
  type LeadSearchSummary,
} from "@/lib/lead-search-api";
import { IconSend, IconShield, IconSparkle } from "@/components/app/icons";

const EXAMPLES = [
  "15 heads of HR at fintech startups in Bengaluru",
  "CTOs of SaaS companies with 50-200 employees in London",
  "Senior backend engineers with Python and Kafka in Pune",
  "Marketing directors at D2C brands in Mumbai",
];

function fullName(lead: FoundLead): string {
  return `${lead.first_name} ${lead.last_name}`.trim() || lead.public_id;
}

function setUrlSearch(id: string | null) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("search", id);
  else url.searchParams.delete("search");
  window.history.replaceState(null, "", url.toString());
}

export default function FindLeadsPage() {
  const { workspace } = useSession();
  const workspaceId = workspace?.id ?? null;

  const [status, setStatus] = useState<LeadSearchStatus | null>(null);
  const [search, setSearch] = useState<LeadSearch | null>(null);
  const [history, setHistory] = useState<LeadSearchSummary[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notices, setNotices] = useState<string[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [listName, setListName] = useState("");
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState<ImportReport | null>(null);
  const chatEnd = useRef<HTMLDivElement>(null);

  const refreshMeta = useCallback(async () => {
    if (!workspaceId) return;
    const [s, h] = await Promise.all([
      leadSearchApi.status(workspaceId).catch(() => null),
      leadSearchApi.searches(workspaceId).catch(() => []),
    ]);
    setStatus(s);
    setHistory(h);
  }, [workspaceId]);

  const open = useCallback(
    async (id: string) => {
      if (!workspaceId) return;
      try {
        const s = await leadSearchApi.search(workspaceId, id);
        setSearch(s);
        setSelected(new Set(s.results.filter((r) => !r.in_leads).map((r) => r.public_id)));
        setImported(null);
        setNotices([]);
        setUrlSearch(s.id);
      } catch {
        setUrlSearch(null);
      }
    },
    [workspaceId],
  );

  useEffect(() => {
    void refreshMeta();
    const id = typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("search");
    if (id) void open(id);
  }, [refreshMeta, open]);

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ block: "end" });
  }, [search?.messages.length, busy]);

  async function send(text: string) {
    const body = text.trim();
    if (!workspaceId || !body || busy) return;
    setBusy(true);
    setError(null);
    setMessage("");
    // Show the message straight away; the server's copy replaces it.
    setSearch((prev) =>
      prev
        ? { ...prev, messages: [...prev.messages, { role: "user", text: body, at: new Date().toISOString() }] }
        : null,
    );
    try {
      const result = await leadSearchApi.chat(workspaceId, body, search?.id);
      setSearch(result.search);
      setNotices(result.notices);
      setImported(null);
      setSelected(new Set(result.search.results.filter((r) => !r.in_leads).map((r) => r.public_id)));
      if (!listName) setListName(result.search.title ? `AI: ${result.search.title}`.slice(0, 160) : "");
      setUrlSearch(result.search.id);
      void refreshMeta();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The search failed. Try again.");
      setMessage(body);
      if (search) void open(search.id);
      else setSearch(null);
    } finally {
      setBusy(false);
    }
  }

  function newSearch() {
    setSearch(null);
    setSelected(new Set());
    setImported(null);
    setNotices([]);
    setListName("");
    setError(null);
    setUrlSearch(null);
  }

  async function addToLeads() {
    if (!workspaceId || !search || selected.size === 0) return;
    setImporting(true);
    setError(null);
    try {
      const report = await leadSearchApi.importFound(workspaceId, search.id, [...selected], listName);
      setImported(report);
      const fresh = await leadSearchApi.search(workspaceId, search.id);
      setSearch(fresh);
      setSelected(new Set());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add them to your leads");
    } finally {
      setImporting(false);
    }
  }

  const results = useMemo(() => search?.results ?? [], [search]);
  const selectable = useMemo(() => results.filter((r) => !r.in_leads), [results]);
  const allSelected = selectable.length > 0 && selectable.every((r) => selected.has(r.public_id));

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;

  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-ink-950">
            <IconSparkle className="h-6 w-6 text-violet-600" /> Find leads with AI
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Describe who you want to reach. We search B2B data providers for the best matches, and you pick
            who goes into a lead list.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/leads" className="btn-ghost">
            Back to leads
          </Link>
          {search && (
            <button className="btn-ghost" onClick={newSearch}>
              New search
            </button>
          )}
        </div>
      </header>

      <p className="mb-4 flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-[13px] text-emerald-800">
        <IconShield className="mt-0.5 h-4 w-4 shrink-0" />
        <span>
          <span className="font-semibold">Safe for your LinkedIn accounts.</span> Searching never uses a connected
          account, so it can&apos;t get one restricted. People you add are only visited later by a campaign, one at a
          time, within the account&apos;s daily limits.
        </span>
      </p>

      {status && !status.ready && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-900">
          <p className="font-semibold">No lead data provider connected yet.</p>
          <p className="mt-1">
            Add at least one key to the server&apos;s <code>.env</code> and restart the api:{" "}
            <code>EXA_API_KEY</code>, <code>PDL_API_KEY</code>, <code>APOLLO_API_KEY</code> or{" "}
            <code>BRAVE_SEARCH_API_KEY</code>.
          </p>
        </div>
      )}

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-state-bad/40 bg-state-bad/10 px-4 py-3 text-sm text-state-bad">
          {error}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
        {/* ── chat ─────────────────────────────────────────────────────── */}
        <section className="card flex min-h-[420px] flex-col p-0 lg:h-[calc(100vh-17rem)]">
          <div className="flex-1 space-y-2.5 overflow-y-auto p-4">
            {!search || search.messages.length === 0 ? (
              <div>
                <p className="mb-3 text-[13px] text-slate-500">
                  Say the role, industry, location or company size. Then refine: &ldquo;only directors&rdquo;,
                  &ldquo;Pune instead&rdquo;, &ldquo;show me more&rdquo;.
                </p>
                <div className="flex flex-col gap-1.5">
                  {EXAMPLES.map((example) => (
                    <button
                      key={example}
                      className="rounded-lg border border-slate-200 px-3 py-2 text-left text-[13px] text-slate-700 hover:border-violet-300 hover:bg-violet-50"
                      onClick={() => void send(example)}
                      disabled={busy}
                    >
                      {example}
                    </button>
                  ))}
                </div>
                {history.length > 0 && (
                  <div className="mt-5">
                    <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                      Recent searches
                    </p>
                    <ul className="space-y-1">
                      {history.slice(0, 8).map((h) => (
                        <li key={h.id}>
                          <button
                            className="w-full truncate rounded-md px-2 py-1.5 text-left text-[13px] text-slate-600 hover:bg-slate-100"
                            onClick={() => void open(h.id)}
                          >
                            {h.title} <span className="text-slate-400">· {h.result_count}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              search.messages.map((m, i) => (
                <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  <p
                    className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-[13px] ${
                      m.role === "user" ? "rounded-br-sm bg-violet-600 text-white" : "rounded-bl-sm bg-slate-100 text-ink-950"
                    }`}
                  >
                    {m.text}
                  </p>
                </div>
              ))
            )}
            {busy && <p className="text-[12.5px] text-slate-400">Searching…</p>}
            <div ref={chatEnd} />
          </div>
          <div className="border-t border-slate-200 p-3">
            <div className="flex items-end gap-2">
              <textarea
                className="input flex-1 resize-none"
                rows={2}
                value={message}
                maxLength={2000}
                disabled={busy}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send(message);
                  }
                }}
                placeholder={search ? "Refine: only VPs, add Hyderabad, show more…" : "Who are you looking for?"}
              />
              <button className="btn-primary shrink-0" disabled={busy || !message.trim()} onClick={() => void send(message)}>
                <IconSend className="h-4 w-4" />
              </button>
            </div>
            {status && (
              <p className="mt-1.5 text-[11.5px] text-slate-400">
                {status.ready
                  ? `Via ${status.providers.map((p) => PROVIDER_LABELS[p] ?? p).join(" → ")}`
                  : "No provider connected"}{" "}
                · {status.used_today}/{status.daily_limit} searches today
                {!status.ai_available && " · no AI key: your words are searched as keywords"}
              </p>
            )}
          </div>
        </section>

        {/* ── results ──────────────────────────────────────────────────── */}
        <section className="card flex min-h-[420px] flex-col p-0 lg:h-[calc(100vh-17rem)]">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
            <div className="min-w-0">
              <p className="text-[14px] font-bold text-ink-950">
                {results.length ? `${results.length} people` : "Results"}
              </p>
              {search?.criteria_summary && (
                <p className="truncate text-[12px] text-slate-500">{search.criteria_summary}</p>
              )}
            </div>
            {selectable.length > 0 && (
              <label className="flex items-center gap-2 text-[12.5px] text-slate-600">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) =>
                    setSelected(e.target.checked ? new Set(selectable.map((r) => r.public_id)) : new Set())
                  }
                />
                Select all
              </label>
            )}
          </div>

          {notices.length > 0 && (
            <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-[12px] text-amber-800">
              {notices.map((n) => (
                <p key={n}>{n}</p>
              ))}
            </div>
          )}

          <div className="flex-1 overflow-y-auto">
            {results.length === 0 ? (
              <div className="flex h-full items-center justify-center p-8 text-center text-[13px] text-slate-400">
                {busy ? "Searching…" : "Matches will appear here."}
              </div>
            ) : (
              <ul className="divide-y divide-slate-100">
                {results.map((lead) => {
                  const checked = selected.has(lead.public_id);
                  return (
                    <li key={lead.public_id} className="flex items-start gap-3 px-4 py-3">
                      <input
                        type="checkbox"
                        className="mt-2.5"
                        disabled={lead.in_leads}
                        checked={checked}
                        aria-label={`Select ${fullName(lead)}`}
                        onChange={() =>
                          setSelected((prev) => {
                            const next = new Set(prev);
                            if (next.has(lead.public_id)) next.delete(lead.public_id);
                            else next.add(lead.public_id);
                            return next;
                          })
                        }
                      />
                      {lead.avatar_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={lead.avatar_url} alt="" className="h-9 w-9 shrink-0 rounded-full object-cover" />
                      ) : (
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink-950 text-[12px] font-bold text-white">
                          {fullName(lead)[0]?.toUpperCase()}
                        </span>
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <a
                            href={lead.profile_url}
                            target="_blank"
                            rel="noreferrer"
                            className="truncate text-[14px] font-semibold text-ink-950 hover:text-brand-600 hover:underline"
                          >
                            {fullName(lead)}
                          </a>
                          {lead.in_leads && (
                            <span className="rounded-md bg-emerald-100 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-700">
                              In your leads
                            </span>
                          )}
                        </div>
                        <p className="truncate text-[12.5px] text-slate-600">
                          {[lead.title, lead.company].filter(Boolean).join(" · ") || lead.headline || "—"}
                        </p>
                        {lead.location && <p className="truncate text-[12px] text-slate-400">{lead.location}</p>}
                        {lead.match_reasons.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {lead.match_reasons.map((reason) => (
                              <span key={reason} className="rounded-md bg-violet-50 px-1.5 py-0.5 text-[11px] text-violet-700">
                                {reason}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      <span className="hidden shrink-0 text-[11px] text-slate-400 sm:block">
                        {PROVIDER_LABELS[lead.provider] ?? lead.provider}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {imported ? (
            <div className="border-t border-emerald-200 bg-emerald-50 px-4 py-3 text-[13px] text-emerald-800">
              <p>
                <span className="font-semibold">
                  Added {imported.imported + imported.updated} to &ldquo;{imported.list_name}&rdquo;.
                </span>
                {imported.skipped > 0 && ` ${imported.skipped} skipped (blocklisted or not in this search).`}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Link href="/campaigns?new=1" className="btn-primary px-3 py-1.5 text-xs">
                  Create a campaign
                </Link>
                <Link href="/leads" className="btn-ghost px-3 py-1.5 text-xs">
                  View leads
                </Link>
              </div>
            </div>
          ) : (
            results.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 border-t border-slate-200 px-4 py-3">
                <input
                  className="input min-w-0 flex-1"
                  value={listName}
                  maxLength={160}
                  onChange={(e) => setListName(e.target.value)}
                  placeholder="Lead list name"
                />
                <button
                  className="btn-primary shrink-0"
                  disabled={importing || selected.size === 0}
                  onClick={() => void addToLeads()}
                >
                  {importing ? "Adding…" : `Add ${selected.size} to leads`}
                </button>
              </div>
            )
          )}
        </section>
      </div>
    </div>
  );
}
