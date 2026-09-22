"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { linkedinApi, type LinkedInAccount } from "@/lib/api";
import { analyticsApi, campaignsApi, leadsApi, type AnalyticsOverview, type Campaign, type LeadList } from "@/lib/outreach-api";
import { useSession } from "@/lib/session";
import { StatCard } from "@/components/app/StatCard";
import { TimelineChart } from "@/components/app/TimelineChart";

const NEXT_STEPS = [
  {
    href: "/accounts",
    title: "Connect a LinkedIn account",
    body: "Sign in through a dedicated residential IP. Your session and device identity are frozen to that account.",
  },
  {
    href: "/leads",
    title: "Import leads",
    body: "CSV upload, a LinkedIn search URL, or Sales Navigator. Duplicates are skipped workspace-wide.",
  },
  {
    href: "/campaigns",
    title: "Build a sequence",
    body: "Profile view, invite with an AI-written note, follow-ups — paced inside your working hours.",
  },
];

const RANGE_OPTIONS = [7, 14, 30];

function shortWeekday(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: "short" });
}

export default function DashboardPage() {
  const { me, workspace } = useSession();
  const workspaceId = workspace?.id ?? null;

  const [accounts, setAccounts] = useState<LinkedInAccount[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [leadLists, setLeadLists] = useState<LeadList[]>([]);
  const [analytics, setAnalytics] = useState<AnalyticsOverview | null>(null);
  const [range, setRange] = useState(7);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const [nextAccounts, nextCampaigns, nextLists, nextAnalytics] = await Promise.all([
        linkedinApi.accounts(workspaceId),
        campaignsApi.list(workspaceId),
        leadsApi.lists(workspaceId),
        analyticsApi.overview(workspaceId, range),
      ]);
      setAccounts(nextAccounts);
      setCampaigns(nextCampaigns);
      setLeadLists(nextLists);
      setAnalytics(nextAnalytics);
    } finally {
      setLoading(false);
    }
  }, [workspaceId, range]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold text-ink-950">{workspace?.name ?? "Dashboard"}</h1>
        <p className="mt-1 text-sm text-slate-500">
          Signed in as {me?.user.email}. Outreach is {workspace?.outreach_paused ? "paused" : "active"}.
        </p>
      </header>

      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-bold text-ink-950">Your Analytics</h2>
        <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-1">
          {RANGE_OPTIONS.map((opt) => (
            <button
              key={opt}
              onClick={() => setRange(opt)}
              className={`rounded-md px-3 py-1.5 text-[12.5px] font-semibold ${
                range === opt ? "bg-brand-600 text-white" : "text-slate-500 hover:text-ink-950"
              }`}
            >
              {opt}d
            </button>
          ))}
        </div>
      </div>

      <section className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total campaigns"
          value={loading ? "—" : campaigns.length}
          tone="cyan"
        />
        <StatCard label="Running" value={loading ? "—" : campaigns.filter((c) => c.status === "running").length} tone="violet" />
        <StatCard label="Prospects reached" value={loading || !analytics ? "—" : analytics.prospects_reached} tone="emerald" />
        <StatCard label="LinkedIn replies" value={loading || !analytics ? "—" : analytics.total_replies} tone="rose" />
      </section>

      {analytics && (
        <>
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Recent Activities</h3>
          <div className="mb-10 overflow-x-auto rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/70">
                  <th className="px-4 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-500">Type</th>
                  {analytics.days.map((d) => (
                    <th key={d} className="px-4 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                      {shortWeekday(d)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {analytics.series.map((s) => (
                  <tr key={s.key} className="border-b border-slate-100 last:border-0">
                    <td className="px-4 py-2.5 text-[13px] font-semibold text-ink-950">{s.label}</td>
                    {s.counts.map((c, i) => (
                      <td key={i} className="px-4 py-2.5 text-[13px] text-slate-600">
                        {c}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Timeline</h3>
          <div className="mb-10 rounded-xl border border-slate-200 bg-white p-5">
            <TimelineChart days={analytics.days} series={analytics.series} />
          </div>
        </>
      )}

      {!loading && campaigns.length > 0 && (
        <>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Recent campaigns</h2>
          <div className="mb-10 space-y-2">
            {campaigns.slice(0, 4).map((c) => (
              <Link key={c.id} href={`/campaigns/${c.id}`} className="card flex items-center justify-between py-3 transition-colors hover:border-slate-300">
                <span className="text-sm font-medium text-slate-900">{c.name}</span>
                <span className="badge">{c.status}</span>
              </Link>
            ))}
          </div>
        </>
      )}

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Get started</h2>
      <div className="grid gap-4 md:grid-cols-3">
        {NEXT_STEPS.map((step, i) => {
          const done = i === 0 ? accounts.length > 0 : i === 1 ? leadLists.length > 0 : campaigns.length > 0;
          return (
            <Link key={step.href} href={step.href} className="card transition-colors hover:border-slate-300">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="font-medium text-slate-900">{step.title}</h3>
                {done && <span className="badge text-emerald-600">done</span>}
              </div>
              <p className="text-sm text-slate-500">{step.body}</p>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
