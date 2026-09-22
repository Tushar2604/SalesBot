"use client";

/**
 * LinkedIn accounts.
 *
 * Polls while any account is mid-connection, because the sign-in runs in a
 * worker and the status changes out-of-band. Polling stops as soon as nothing
 * is in flight.
 */

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, linkedinApi, type LinkedInAccount, type ProxyRecord } from "@/lib/api";
import { AccountCard } from "@/components/AccountCard";
import { ConnectAccountDialog } from "@/components/ConnectAccountDialog";
import { ProxyPanel } from "@/components/ProxyPanel";
import { StatusPill } from "@/components/StatusPill";
import { StatCard } from "@/components/app/StatCard";
import { IconChevronDown, IconChevronLeft, IconLinkedIn, IconPlus, IconSearch } from "@/components/app/icons";
import { hasRole, useSession } from "@/lib/session";

const POLL_MS = 2500;

export default function AccountsPage() {
  const { workspace, role } = useSession();
  const workspaceId = workspace?.id ?? null;

  const [accounts, setAccounts] = useState<LinkedInAccount[]>([]);
  const [proxies, setProxies] = useState<ProxyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const isAdmin = hasRole(role, "admin");

  // The LinkedIn OAuth callback bounces the browser back here with the outcome
  // in the query string, since that redirect carries no session of its own.
  const router = useRouter();
  const params = useSearchParams();
  const publishingResult = params.get("publishing");
  const publishingMessage = params.get("message") ?? "";

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const [nextAccounts, nextProxies] = await Promise.all([
        linkedinApi.accounts(workspaceId),
        isAdmin ? linkedinApi.proxies(workspaceId) : Promise.resolve<ProxyRecord[]>([]),
      ]);
      setAccounts(nextAccounts);
      setProxies(nextProxies);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load accounts");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, isAdmin]);

  useEffect(() => {
    void load();
  }, [load]);

  // Only poll while a sign-in is actually in flight.
  const pending = accounts.some((a) => a.status === "connecting");
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [pending, load]);

  const stats = useMemo(() => {
    const total = accounts.length;
    const disconnected = accounts.filter((a) => !a.is_connected).length;
    const active = accounts.filter((a) => a.status === "active").length;
    const inactive = accounts.filter((a) => a.status === "paused" || a.status === "disabled").length;
    return { total, disconnected, active, inactive };
  }, [accounts]);

  const filtered = accounts.filter((a) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      (a.label || "").toLowerCase().includes(q) ||
      (a.full_name || "").toLowerCase().includes(q) ||
      (a.login_email || "").toLowerCase().includes(q)
    );
  });

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;

  return (
    <div className="mx-auto max-w-6xl">
      {publishingResult && (
        <div
          className={
            publishingResult === "connected"
              ? "mb-5 rounded-xl border border-state-ok/40 bg-state-ok/5 px-4 py-3"
              : "mb-5 rounded-xl border border-state-warn/40 bg-state-warn/5 px-4 py-3"
          }
          role="status"
        >
          <p className="text-[13.5px] font-semibold text-slate-800">
            {publishingResult === "connected"
              ? "LinkedIn publishing authorized."
              : publishingResult === "denied"
                ? "Authorization was declined on LinkedIn."
                : publishingResult === "missing_scope"
                  ? "Posting permission was not granted."
                  : "The LinkedIn authorization did not complete."}
          </p>
          {publishingMessage && (
            <p className="mt-0.5 text-[13px] text-slate-600">{publishingMessage}</p>
          )}
          <button
            type="button"
            onClick={() => {
              router.replace("/accounts");
              void load();
            }}
            className="mt-2 text-[13px] font-semibold text-accent hover:underline"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="mb-6 flex flex-wrap items-center justify-end gap-3">
        {isAdmin && (
          <button
            onClick={() => setConnecting(true)}
            className="flex items-center gap-1.5 rounded-lg bg-brand-600 px-4 py-2.5 text-[13.5px] font-bold text-white hover:bg-brand-700"
          >
            Add Account
            <IconPlus className="h-4 w-4" />
          </button>
        )}
        <button className="flex items-center gap-1.5 rounded-lg bg-brand-700 px-4 py-2.5 text-[13.5px] font-bold text-white hover:bg-brand-800">
          Buy Subscription
          <span className="text-[15px] leading-none">$</span>
        </button>
      </div>

      <div className="mb-6">
        <span className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-[13.5px] font-semibold text-brand-600">
          <IconLinkedIn className="h-4 w-4" />
          LinkedIn
        </span>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Total" value={stats.total} tone="cyan" />
        <StatCard label="Disconnected" value={stats.disconnected} tone="rose" />
        <StatCard label="Active" value={stats.active} tone="emerald" />
        <StatCard label="Inactive" value={stats.inactive} tone="violet" />
      </div>

      {error && (
        <p
          role="alert"
          className="mb-6 rounded-md border border-state-bad/40 bg-state-bad/10 px-4 py-3 text-sm text-state-bad"
        >
          {error}
        </p>
      )}

      <div className="mb-4 flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search in the list..."
            className="input pl-9"
          />
        </div>
        <div className="ml-auto flex items-center gap-2 text-[13px] text-slate-500">
          <span className="rounded-lg border border-slate-200 bg-white px-3 py-2">10 / page</span>
          <button className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-400 hover:text-ink-950" aria-label="Previous page">
            <IconChevronLeft className="h-4 w-4" />
          </button>
          <button className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-400 hover:text-ink-950" aria-label="Next page">
            <IconChevronLeft className="h-4 w-4 rotate-180" />
          </button>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/70">
              {["Selection", "Account info", "Status", "Daily limits", "Tags", ""].map((h) => (
                <th key={h || "actions"} className="px-4 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-sm text-slate-400">
                  Loading…
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-16 text-center">
                  <p className="mb-1 text-sm font-medium text-slate-500">No accounts yet</p>
                  <p className="mb-4 text-xs text-slate-400">
                    Connect one to start sending. Sign in with email &amp; password for a fresh
                    session that never touches your everyday LinkedIn browser session.
                  </p>
                  {isAdmin && (
                    <button onClick={() => setConnecting(true)} className="btn-primary">
                      Connect your first account
                    </button>
                  )}
                </td>
              </tr>
            ) : (
              filtered.map((account) => (
                <Fragment key={account.id}>
                  <tr
                    className="cursor-pointer border-b border-slate-100 last:border-0 hover:bg-slate-50/70"
                    onClick={() => setExpanded(expanded === account.id ? null : account.id)}
                  >
                    <td className="px-4 py-3.5">
                      <input type="checkbox" onClick={(e) => e.stopPropagation()} className="h-4 w-4 rounded border-slate-300" />
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-2.5">
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink-950 text-[11px] font-bold text-white">
                          {(account.full_name || account.label || "?")[0]?.toUpperCase()}
                        </span>
                        <div className="min-w-0">
                          <p className="truncate text-[13.5px] font-semibold text-ink-950">
                            {account.label || account.full_name || "LinkedIn account"}
                          </p>
                          <p className="truncate text-[12px] text-slate-400">{account.login_email || "—"}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3.5">
                      <StatusPill status={account.status} />
                    </td>
                    <td className="px-4 py-3.5 text-[13px] text-slate-600">
                      {account.caps.daily_invites} invites/day
                    </td>
                    <td className="px-4 py-3.5">
                      {account.test_mode ? <span className="badge">test mode</span> : <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-4 py-3.5 text-right">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setExpanded(expanded === account.id ? null : account.id);
                        }}
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[12px] font-semibold text-slate-600 hover:border-slate-300 hover:text-ink-950"
                      >
                        Manage
                        <IconChevronDown className={`h-3.5 w-3.5 transition-transform ${expanded === account.id ? "rotate-180" : ""}`} />
                      </button>
                    </td>
                  </tr>
                  {expanded === account.id && (
                    <tr className="border-b border-slate-100 bg-slate-50/60 last:border-0">
                      <td colSpan={6} className="p-4">
                        <AccountCard
                          workspaceId={workspaceId}
                          account={account}
                          proxies={proxies}
                          onChanged={() => void load()}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))
            )}
          </tbody>
        </table>
      </div>

      {isAdmin && proxies.length + accounts.length > 0 && (
        <div className="mt-8">
          <ProxyPanel workspaceId={workspaceId} proxies={proxies} onChanged={() => void load()} />
        </div>
      )}

      {connecting && (
        <ConnectAccountDialog
          workspaceId={workspaceId}
          proxies={proxies}
          onClose={() => setConnecting(false)}
          onConnected={() => {
            setConnecting(false);
            void load();
          }}
        />
      )}
    </div>
  );
}
