"use client";

/**
 * Campaign tracking: where every lead stands, and everything that happened to them.
 *
 * The funnel answers "how is this campaign doing"; the table answers "what about
 * this person"; the timeline answers "what exactly happened, and when". All three
 * read from the same append-only history, so nothing here is a guess at the past.
 */

import { Fragment, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import clsx from "clsx";
import { ApiError } from "@/lib/api";
import {
  campaignsApi,
  type LeadEvent,
  type TrackingLead,
  type TrackingStage,
  type TrackingSummary,
} from "@/lib/outreach-api";
import { useSession } from "@/lib/session";

const PAGE_SIZE = 50;
const REFRESH_MS = 30_000;

const STAGE_STYLE: Record<TrackingStage, { badge: string; bar: string }> = {
  queued: { badge: "bg-slate-100 text-slate-600 border-slate-200", bar: "bg-slate-300" },
  profile_viewed: { badge: "bg-sky-50 text-sky-700 border-sky-200", bar: "bg-sky-400" },
  invite_pending: { badge: "bg-amber-50 text-amber-700 border-amber-200", bar: "bg-amber-400" },
  connected: { badge: "bg-emerald-50 text-emerald-700 border-emerald-200", bar: "bg-emerald-500" },
  replied: { badge: "bg-violet-50 text-violet-700 border-violet-200", bar: "bg-violet-500" },
  not_accepted: { badge: "bg-rose-50 text-rose-700 border-rose-200", bar: "bg-rose-500" },
  expired: { badge: "bg-orange-50 text-orange-700 border-orange-200", bar: "bg-orange-400" },
  stopped: { badge: "bg-yellow-50 text-yellow-800 border-yellow-200", bar: "bg-yellow-400" },
  failed: { badge: "bg-red-50 text-red-700 border-red-200", bar: "bg-red-500" },
  skipped: { badge: "bg-slate-50 text-slate-500 border-slate-200", bar: "bg-slate-200" },
};

const EVENT_LABELS: Record<string, string> = {
  enrolled: "Added to the campaign",
  profile_viewed: "Profile viewed",
  invite_sent: "Connection request sent",
  invite_still_pending: "Checked: invite still waiting",
  invite_accepted: "Accepted the connection request",
  invite_not_accepted: "Invite no longer pending, not connected",
  invite_expired: "No response: stopped tracking",
  message_sent: "Message sent",
  replied: "Replied",
  action_failed: "An action failed",
  action_skipped: "An action was skipped",
  sequence_ended: "Sequence ended",
};

const EVENT_DOT: Record<string, string> = {
  invite_accepted: "bg-emerald-500",
  replied: "bg-violet-500",
  invite_not_accepted: "bg-rose-500",
  invite_expired: "bg-orange-400",
  action_failed: "bg-red-500",
  invite_still_pending: "bg-amber-400",
};

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function inFuture(iso: string | null): string {
  if (!iso) return "—";
  const minutes = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  if (minutes <= 1) return "any moment";
  if (minutes < 60) return `in ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `in ${hours} h`;
  return `in ${Math.round(hours / 24)} d`;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function Tile({ label, value, hint, tone }: { label: string; value: string | number; hint?: string; tone: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <p className="text-[12px] font-medium text-slate-500">{label}</p>
      <p className={clsx("font-display text-2xl font-extrabold", tone)}>{value}</p>
      {hint && <p className="mt-0.5 text-[11.5px] text-slate-400">{hint}</p>}
    </div>
  );
}

function Timeline({ events }: { events: LeadEvent[] | "loading" | "error" }) {
  if (events === "loading") return <p className="text-xs text-slate-500">Loading history…</p>;
  if (events === "error") return <p className="text-xs text-red-600">Could not load the history.</p>;
  if (events.length === 0) return <p className="text-xs text-slate-500">No history recorded yet.</p>;
  return (
    <ol className="space-y-2.5">
      {events.map((e) => (
        <li key={e.id} className="flex gap-3">
          <span className={clsx("mt-1.5 h-2 w-2 shrink-0 rounded-full", EVENT_DOT[e.event_type] ?? "bg-slate-400")} />
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-slate-800">
              {EVENT_LABELS[e.event_type] ?? e.event_type}
              <span className="ml-2 text-[11.5px] font-normal text-slate-400">{when(e.occurred_at)}</span>
            </p>
            {e.detail && <p className="text-[12px] text-slate-500">{e.detail}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

export default function CampaignTrackingPage() {
  const params = useParams<{ id: string }>();
  const { workspace } = useSession();
  const workspaceId = workspace?.id ?? null;

  const [summary, setSummary] = useState<TrackingSummary | null>(null);
  const [leads, setLeads] = useState<TrackingLead[]>([]);
  const [total, setTotal] = useState(0);
  const [stage, setStage] = useState<TrackingStage | "">("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const [events, setEvents] = useState<Record<string, LeadEvent[] | "loading" | "error">>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Debounce the search box so typing does not fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const [nextSummary, nextLeads] = await Promise.all([
        campaignsApi.tracking(workspaceId, params.id),
        campaignsApi.trackingLeads(workspaceId, params.id, {
          stage,
          search: query,
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        }),
      ]);
      setSummary(nextSummary);
      setLeads(nextLeads.items);
      setTotal(nextLeads.total);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load tracking for this campaign");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, params.id, stage, query, page]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  async function toggle(lead: TrackingLead) {
    if (openId === lead.id) {
      setOpenId(null);
      return;
    }
    setOpenId(lead.id);
    if (!workspaceId) return;
    setEvents((prev) => ({ ...prev, [lead.id]: "loading" }));
    try {
      const history = await campaignsApi.leadEvents(workspaceId, params.id, lead.id);
      setEvents((prev) => ({ ...prev, [lead.id]: history }));
    } catch {
      setEvents((prev) => ({ ...prev, [lead.id]: "error" }));
    }
  }

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;
  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (!summary) return <p className="text-sm text-red-600">{error ?? "Not found"}</p>;

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const stagesWithLeads = summary.stages.filter((s) => s.count > 0);

  return (
    <div className="mx-auto max-w-6xl">
      <Link
        href={`/campaigns/${summary.campaign_id}`}
        className="mb-4 inline-block text-sm text-slate-500 hover:text-slate-900"
      >
        ← {summary.campaign_name}
      </Link>

      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-ink-950">Tracking</h1>
          <p className="mt-1 text-sm text-slate-500">
            {summary.campaign_name} · {summary.campaign_status} · {plural(summary.total, "lead")}
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={() => void load()}>
            Refresh
          </button>
          <button
            className="btn-ghost"
            onClick={() => void campaignsApi.exportTracking(workspaceId, summary.campaign_id)}
          >
            Export CSV
          </button>
        </div>
      </header>

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </p>
      )}

      <section className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
        <Tile label="Enrolled" value={summary.total} tone="text-ink-950" />
        <Tile label="Profiles viewed" value={summary.viewed} tone="text-sky-600" />
        <Tile label="Invites sent" value={summary.invited} tone="text-ink-950" />
        <Tile
          label="Connected"
          value={summary.connected}
          tone="text-emerald-600"
          hint={
            summary.acceptance_rate !== null
              ? `${Math.round(summary.acceptance_rate * 100)}% accepted` +
                (summary.avg_days_to_accept !== null ? ` · ~${summary.avg_days_to_accept} d` : "")
              : undefined
          }
        />
        <Tile
          label="Still waiting"
          value={summary.still_waiting}
          tone="text-amber-600"
          hint={
            summary.oldest_pending_days !== null
              ? `oldest ${plural(summary.oldest_pending_days, "day")}`
              : undefined
          }
        />
        <Tile
          label="Not accepted"
          value={summary.not_accepted + summary.expired}
          tone="text-rose-600"
          hint={summary.expired > 0 ? `${summary.expired} with no response` : undefined}
        />
      </section>

      {summary.total > 0 && (
        <section className="card mb-6">
          <h2 className="mb-3 font-medium text-slate-900">Where everyone is right now</h2>
          <div className="flex h-3 w-full overflow-hidden rounded-full bg-slate-100">
            {stagesWithLeads.map((s) => (
              <div
                key={s.stage}
                title={`${s.label}: ${s.count}`}
                className={STAGE_STYLE[s.stage].bar}
                style={{ width: `${(s.count / summary.total) * 100}%` }}
              />
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              onClick={() => {
                setStage("");
                setPage(0);
              }}
              className={clsx(
                "rounded-full border px-3 py-1 text-[12px] font-semibold",
                stage === "" ? "border-ink-950 bg-ink-950 text-white" : "border-slate-200 bg-white text-slate-600 hover:border-slate-400",
              )}
            >
              All · {summary.total}
            </button>
            {stagesWithLeads.map((s) => (
              <button
                key={s.stage}
                onClick={() => {
                  setStage(s.stage);
                  setPage(0);
                }}
                className={clsx(
                  "rounded-full border px-3 py-1 text-[12px] font-semibold",
                  STAGE_STYLE[s.stage].badge,
                  stage === s.stage && "ring-2 ring-ink-950/30",
                )}
              >
                {s.label} · {s.count}
              </button>
            ))}
          </div>
          <p className="mt-4 text-[12px] leading-relaxed text-slate-500">
            LinkedIn does not tell you when someone declines a request. <strong>Not accepted</strong> means the
            invite is no longer pending and they are not a connection: it was declined, withdrawn or lapsed.
            Invites nobody answers are checked for {summary.tracking_window_days} days, then marked{" "}
            <strong>No response</strong>.
            {summary.still_waiting > 0 && summary.next_check_at && (
              <> Next check {inFuture(summary.next_check_at)}.</>
            )}
          </p>
        </section>
      )}

      <section className="card">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-medium text-slate-900">
            Leads <span className="text-sm font-normal text-slate-500">({total})</span>
          </h2>
          <input
            className="input max-w-xs"
            placeholder="Search name, company or profile"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {leads.length === 0 ? (
          <p className="text-sm text-slate-500">
            {summary.total === 0 ? "No leads enrolled in this campaign yet." : "No leads match this view."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="pb-2 pr-3">Lead</th>
                  <th className="pb-2 pr-3">Status</th>
                  <th className="pb-2 pr-3">Invite sent</th>
                  <th className="pb-2 pr-3">Checked</th>
                  <th className="pb-2">Latest</th>
                </tr>
              </thead>
              <tbody>
                {leads.map((lead) => (
                  <Fragment key={lead.id}>
                    <tr
                      onClick={() => void toggle(lead)}
                      className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
                    >
                      <td className="py-2.5 pr-3">
                        <p className="font-semibold text-ink-950">{lead.lead_name}</p>
                        <p className="text-[12px] text-slate-500">
                          {[lead.lead_title, lead.lead_company].filter(Boolean).join(" · ") || lead.lead_public_id}
                        </p>
                      </td>
                      <td className="py-2.5 pr-3">
                        <span
                          className={clsx(
                            "inline-flex rounded-full border px-2 py-0.5 text-[11.5px] font-semibold",
                            STAGE_STYLE[lead.stage].badge,
                          )}
                        >
                          {lead.stage_label}
                        </span>
                        {lead.days_waiting !== null && (
                          <p className="mt-0.5 text-[11.5px] text-amber-700">
                            waiting {plural(lead.days_waiting, "day")}
                          </p>
                        )}
                        {lead.reason && <p className="mt-0.5 max-w-52 truncate text-[11.5px] text-slate-500">{lead.reason}</p>}
                      </td>
                      <td className="py-2.5 pr-3 text-slate-600">{when(lead.invite_sent_at)}</td>
                      <td className="py-2.5 pr-3 text-slate-600">
                        {lead.last_checked_at ? when(lead.last_checked_at) : "—"}
                        {lead.next_check_at && (
                          <p className="text-[11.5px] text-slate-400">next {inFuture(lead.next_check_at)}</p>
                        )}
                      </td>
                      <td className="py-2.5 text-slate-600">
                        {lead.last_event_type ? (EVENT_LABELS[lead.last_event_type] ?? lead.last_event_type) : "—"}
                        <p className="text-[11.5px] text-slate-400">{when(lead.last_event_at)}</p>
                      </td>
                    </tr>
                    {openId === lead.id && (
                      <tr className="bg-slate-50/70">
                        <td colSpan={5} className="px-4 py-4">
                          <p className="mb-3 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                            Everything that happened
                          </p>
                          <Timeline events={events[lead.id] ?? "loading"} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {pages > 1 && (
          <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
            <button className="btn-ghost" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
              Previous
            </button>
            <span>
              Page {page + 1} of {pages}
            </span>
            <button className="btn-ghost" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
              Next
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
