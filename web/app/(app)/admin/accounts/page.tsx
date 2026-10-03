"use client";

/**
 * Platform admin panel: every LinkedIn account across every workspace — who
 * connected it, who can use it, how many safety warnings it has — with the
 * levers to pause it, revoke its access, or restore it.
 *
 * The API enforces superuser-only access; this page just hides itself too.
 */

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { ApiError, type RiskLevel } from "@/lib/api";
import { adminApi, type AdminAccount, type AdminRiskEvent } from "@/lib/admin-api";
import { useSession } from "@/lib/session";
import { StatusPill } from "@/components/StatusPill";
import { WarningBadge } from "@/components/WarningBadge";

type Filter = "all" | "flagged" | "revoked";

function when(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

const RISK_ORDER: Record<RiskLevel, number> = { critical: 0, at_risk: 1, watch: 2, safe: 3 };

function Summary({ accounts }: { accounts: AdminAccount[] }) {
  const counts = {
    total: accounts.length,
    critical: accounts.filter((a) => a.risk_level === "critical").length,
    atRisk: accounts.filter((a) => a.risk_level === "at_risk").length,
    revoked: accounts.filter((a) => a.status === "disabled").length,
  };
  const tiles = [
    { label: "LinkedIn accounts", value: counts.total, tone: "text-ink-950" },
    { label: "Ban risk (3/3)", value: counts.critical, tone: "text-red-600" },
    { label: "At risk (2/3)", value: counts.atRisk, tone: "text-orange-600" },
    { label: "Access revoked", value: counts.revoked, tone: "text-slate-600" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-xl border border-slate-200 p-4">
          <p className="text-xs font-medium text-slate-500">{t.label}</p>
          <p className={clsx("mt-1 text-2xl font-bold", t.tone)}>{t.value}</p>
        </div>
      ))}
    </div>
  );
}

function Events({ accountId, onCleared }: { accountId: string; onCleared: () => void }) {
  const [events, setEvents] = useState<AdminRiskEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    adminApi
      .events(accountId)
      .then(setEvents)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load warnings"));
  }, [accountId]);

  useEffect(load, [load]);

  if (error) return <p className="text-sm text-state-bad">{error}</p>;
  if (!events) return <p className="text-sm text-slate-400">Loading warnings…</p>;
  if (events.length === 0) return <p className="text-sm text-slate-500">No warnings on record.</p>;

  return (
    <ul className="space-y-2">
      {events.map((e) => (
        <li
          key={e.id}
          className={clsx(
            "flex flex-wrap items-start gap-3 rounded-lg border px-3 py-2 text-sm",
            e.counts ? "border-slate-200 bg-white" : "border-slate-100 bg-slate-50 text-slate-400",
          )}
        >
          <span
            className={clsx(
              "rounded-full px-2 py-0.5 text-[11px] font-semibold",
              e.source === "linkedin" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700",
            )}
          >
            {e.source === "linkedin" ? "From LinkedIn" : "Risky override"}
          </span>
          <div className="min-w-0 flex-1">
            <p className={clsx("font-medium", e.counts ? "text-slate-800" : "line-through")}>
              {e.detail || e.kind}
            </p>
            <p className="text-xs text-slate-500">
              {when(e.created_at)} · {e.strikes} {e.strikes === 1 ? "strike" : "strikes"}
              {e.actor_email && ` · by ${e.actor_email}`}
              {e.cleared_at && ` · cleared ${when(e.cleared_at)}`}
              {!e.cleared_at && !e.counts && " · older than 30 days"}
            </p>
          </div>
          {e.counts && (
            <button
              className="text-xs font-semibold text-slate-500 hover:text-ink-950"
              onClick={() =>
                void adminApi.clearEvent(e.id).then(() => {
                  load();
                  onCleared();
                })
              }
            >
              Clear
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function AdminAccountsPage() {
  const { me } = useSession();
  const [accounts, setAccounts] = useState<AdminAccount[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setAccounts(await adminApi.accounts());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load accounts");
    }
  }, []);

  useEffect(() => {
    if (me?.user.is_superuser) void load();
  }, [me?.user.is_superuser, load]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (accounts ?? [])
      .filter((a) =>
        filter === "flagged"
          ? a.risk_level === "critical" || a.risk_level === "at_risk"
          : filter === "revoked"
            ? a.status === "disabled"
            : true,
      )
      .filter(
        (a) =>
          !q ||
          [a.full_name, a.label, a.public_id, a.workspace_name, a.connected_by_email, ...a.members.map((m) => m.email)]
            .join(" ")
            .toLowerCase()
            .includes(q),
      )
      .sort((a, b) => RISK_ORDER[a.risk_level] - RISK_ORDER[b.risk_level] || b.warning_count - a.warning_count);
  }, [accounts, filter, query]);

  async function act(account: AdminAccount, verb: "pause" | "revoke" | "restore") {
    const name = account.full_name || account.label || "this account";
    let reason = "";
    if (verb === "revoke") {
      const answer = window.prompt(
        `Revoke access to ${name}?\n\nThis signs it out, cancels everything queued, and the workspace "${account.workspace_name}" cannot use or reconnect it until you restore it.\n\nReason (shown to the workspace):`,
        account.risk_level === "critical" ? "Too many safety warnings — protecting the account from a ban." : "",
      );
      if (answer === null) return;
      reason = answer;
    }
    setBusy(account.id);
    try {
      const updated = await adminApi[verb](account.id, reason);
      setAccounts((prev) => prev?.map((a) => (a.id === updated.id ? updated : a)) ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That action failed");
    } finally {
      setBusy(null);
    }
  }

  if (!me?.user.is_superuser) {
    return <p className="mt-6 text-sm text-slate-500">This page is for platform administrators.</p>;
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5 pt-2">
      <div>
        <h1 className="text-2xl font-semibold text-ink-950">Admin panel</h1>
        <p className="mt-1 text-sm text-slate-500">
          Every LinkedIn account on the platform, who runs it, and how close it is to a ban. An account
          is paused automatically at 3 warnings in 30 days.
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-state-bad/40 bg-state-bad/10 px-4 py-3 text-sm text-state-bad">{error}</p>
      )}

      {accounts === null ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : (
        <>
          <Summary accounts={accounts} />

          <div className="flex flex-wrap items-center gap-2">
            {(["all", "flagged", "revoked"] as Filter[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={clsx(
                  "rounded-full border px-3 py-1.5 text-[13px] font-medium",
                  filter === f ? "border-ink-950 bg-ink-950 text-white" : "border-slate-200 text-slate-600",
                )}
              >
                {f === "all" ? "All" : f === "flagged" ? "At risk" : "Revoked"}
              </button>
            ))}
            <input
              className="input ml-auto w-full max-w-xs"
              placeholder="Search name, workspace or email…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-semibold">LinkedIn account</th>
                  <th className="px-4 py-3 font-semibold">Handled by</th>
                  <th className="px-4 py-3 font-semibold">Status</th>
                  <th className="px-4 py-3 font-semibold">Warnings</th>
                  <th className="px-4 py-3 font-semibold">Last warning</th>
                  <th className="px-4 py-3 text-right font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {shown.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-slate-400">
                      No accounts match.
                    </td>
                  </tr>
                )}
                {shown.map((a) => (
                  <Fragment key={a.id}>
                    <tr className={clsx(a.risk_level === "critical" && "bg-red-50/40")}>
                      <td className="px-4 py-3 align-top">
                        <p className="font-medium text-ink-950">{a.full_name || a.label || "Unnamed account"}</p>
                        {a.profile_url ? (
                          <a href={a.profile_url} target="_blank" rel="noreferrer" className="text-xs text-brand-600 hover:underline">
                            linkedin.com/in/{a.public_id}
                          </a>
                        ) : (
                          <p className="text-xs text-slate-400">profile not confirmed yet</p>
                        )}
                        <p className="mt-1 text-xs text-slate-500">
                          {a.proxy} · health {a.health_score} · {a.active_campaigns} running campaign
                          {a.active_campaigns === 1 ? "" : "s"}
                        </p>
                      </td>
                      <td className="px-4 py-3 align-top">
                        <p className="font-medium text-slate-800">{a.workspace_name || "—"}</p>
                        <p className="text-xs text-slate-500">
                          connected by {a.connected_by_name || a.connected_by_email || "unknown"}
                          {a.connected_by_name && a.connected_by_email ? ` (${a.connected_by_email})` : ""}
                        </p>
                        <p className="mt-1 text-xs text-slate-400">
                          {a.members.length} {a.members.length === 1 ? "member" : "members"}:{" "}
                          {a.members.map((m) => `${m.email} (${m.role})`).join(", ")}
                        </p>
                      </td>
                      <td className="px-4 py-3 align-top">
                        <StatusPill status={a.status} />
                        {a.status_detail && <p className="mt-1 max-w-[220px] text-xs text-slate-500">{a.status_detail}</p>}
                      </td>
                      <td className="px-4 py-3 align-top">
                        <WarningBadge count={a.warning_count} limit={a.warning_limit} level={a.risk_level} />
                      </td>
                      <td className="px-4 py-3 align-top text-xs text-slate-600">
                        {a.last_warning ? (
                          <>
                            <p className="max-w-[240px]">{a.last_warning}</p>
                            <p className="text-slate-400">{when(a.last_warning_at)}</p>
                          </>
                        ) : (
                          <span className="text-slate-400">none</span>
                        )}
                      </td>
                      <td className="px-4 py-3 align-top">
                        <div className="flex flex-wrap justify-end gap-1.5">
                          <button className="btn-ghost px-2.5 py-1 text-xs" onClick={() => setOpen(open === a.id ? null : a.id)}>
                            {open === a.id ? "Hide history" : "History"}
                          </button>
                          {a.status === "active" && (
                            <button className="btn-ghost px-2.5 py-1 text-xs" disabled={busy === a.id} onClick={() => void act(a, "pause")}>
                              Pause
                            </button>
                          )}
                          {a.status === "disabled" ? (
                            <button className="btn-ghost px-2.5 py-1 text-xs" disabled={busy === a.id} onClick={() => void act(a, "restore")}>
                              Restore
                            </button>
                          ) : (
                            <button
                              className="rounded-lg bg-red-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50"
                              disabled={busy === a.id}
                              onClick={() => void act(a, "revoke")}
                            >
                              Revoke access
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                    {open === a.id && (
                      <tr>
                        <td colSpan={6} className="bg-slate-50/60 px-4 py-4">
                          <Events accountId={a.id} onCleared={() => void load()} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
