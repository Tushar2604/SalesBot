"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { linkedinApi, type LinkedInAccount } from "@/lib/api";
import { analyticsApi, campaignsApi, leadsApi, type AnalyticsOverview, type Campaign, type LeadList } from "@/lib/outreach-api";
import { useSession } from "@/lib/session";
import { TimelineChart } from "@/components/app/TimelineChart";
import { IconChevronDown } from "@/components/app/icons";

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

const BLOBS = [
  { from: "#7ad8ff", to: "#4c6fff" },
  { from: "#c4b5fd", to: "#7c6bff" },
  { from: "#fda4af", to: "#fb7185" },
  { from: "#6ee7b7", to: "#34d399" },
];

function AnalyticsCard({
  label,
  value,
  blob,
}: {
  label: string;
  value: number | string;
  blob: { from: string; to: string };
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-100 bg-white p-5 shadow-[0_10px_30px_-18px_rgba(15,23,42,0.18)]">
      <svg aria-hidden className="pointer-events-none absolute -right-6 -top-8 h-36 w-40" viewBox="0 0 160 144">
        <defs>
          <linearGradient id={blob.from.replace("#", "g")} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={blob.from} />
            <stop offset="100%" stopColor={blob.to} />
          </linearGradient>
        </defs>
        <rect x="28" y="12" width="110" height="110" rx="28" fill={`url(#${blob.from.replace("#", "g")})`} transform="rotate(18 80 72)" />
        <rect x="18" y="38" width="86" height="86" rx="22" fill={blob.from} opacity="0.55" transform="rotate(-8 60 80)" />
      </svg>
      <p className="relative text-[13px] font-medium text-slate-500">{label}</p>
      <p className="relative mt-6 text-[40px] font-semibold leading-none tracking-tight text-ink-950">{value}</p>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="relative inline-flex min-w-[160px] items-center">
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 w-full appearance-none rounded-xl border border-slate-200 bg-white py-2 pl-3.5 pr-9 text-[13px] font-medium text-slate-700"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <IconChevronDown className="pointer-events-none absolute right-3 h-4 w-4 text-slate-400" />
    </label>
  );
}

export default function DashboardPage() {
  const { me, workspace } = useSession();
  const workspaceId = workspace?.id ?? null;

  const [accounts, setAccounts] = useState<LinkedInAccount[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [leadLists, setLeadLists] = useState<LeadList[]>([]);
  const [analytics, setAnalytics] = useState<AnalyticsOverview | null>(null);
  const [range, setRange] = useState(7);
  const [accountFilter, setAccountFilter] = useState("all");
  const [campaignFilter, setCampaignFilter] = useState("all");
  const [tagFilter, setTagFilter] = useState("all");
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

  const filteredCampaigns = useMemo(() => {
    return campaigns.filter((c) => {
      if (accountFilter !== "all" && c.linkedin_account_id !== accountFilter) return false;
      if (campaignFilter !== "all" && c.id !== campaignFilter) return false;
      return true;
    });
  }, [campaigns, accountFilter, campaignFilter]);

  const totals = {
    campaigns: loading ? "—" : analytics?.total_campaigns ?? campaigns.length,
    connected: loading || !analytics ? "—" : analytics.total_connected,
    replies: loading || !analytics ? "—" : analytics.total_replies,
    reached: loading || !analytics ? "—" : analytics.prospects_reached,
  };

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[20px] font-semibold text-ink-950">Your Analytics</h2>
        <div className="flex flex-wrap items-center gap-2">
          <FilterSelect
            label="LinkedIn Account"
            value={accountFilter}
            onChange={setAccountFilter}
            options={[
              { value: "all", label: "LinkedIn Account" },
              ...accounts.map((a) => ({
                value: a.id,
                label: a.full_name || a.label || "Account",
              })),
            ]}
          />
          <FilterSelect
            label="Campaigns"
            value={campaignFilter}
            onChange={setCampaignFilter}
            options={[
              { value: "all", label: "Campaigns" },
              ...campaigns.map((c) => ({ value: c.id, label: c.name })),
            ]}
          />
          <FilterSelect
            label="Tags"
            value={tagFilter}
            onChange={setTagFilter}
            options={[
              { value: "all", label: "Tags" },
              { value: "saas", label: "SaaS" },
              { value: "agencies", label: "Agencies" },
              { value: "founders", label: "Founders" },
            ]}
          />
          <div className="flex items-center gap-1 rounded-xl border border-slate-200 bg-white p-1">
            {RANGE_OPTIONS.map((opt) => (
              <button
                key={opt}
                onClick={() => setRange(opt)}
                className={`rounded-lg px-3 py-1.5 text-[12.5px] font-medium ${
                  range === opt ? "bg-ink-950 text-white" : "text-slate-500 hover:text-ink-950"
                }`}
              >
                {opt}d
              </button>
            ))}
          </div>
        </div>
      </div>

      <section className="mb-10 grid gap-4 sm:grid-cols-2">
        <AnalyticsCard label="Total Campaigns" value={totals.campaigns} blob={BLOBS[0]} />
        <AnalyticsCard label="Total Connected" value={totals.connected} blob={BLOBS[1]} />
        <AnalyticsCard label="LinkedIn Replies" value={totals.replies} blob={BLOBS[2]} />
        <AnalyticsCard label="Prospects Reached" value={totals.reached} blob={BLOBS[3]} />
      </section>

      {analytics && (
        <>
          <h3 className="mb-4 text-[18px] font-semibold text-ink-950">Recent Activities</h3>
          <div className="mb-10 overflow-x-auto rounded-2xl border border-slate-100 bg-white">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-100">
                  <th className="px-4 py-3 text-[12px] font-semibold text-slate-400"> </th>
                  {analytics.days.map((d) => (
                    <th key={d} className="px-4 py-3 text-[12px] font-semibold text-slate-400">
                      {shortWeekday(d)}
                    </th>
                  ))}
                  <th className="px-4 py-3 text-[12px] font-semibold text-slate-400">TOTAL</th>
                </tr>
              </thead>
              <tbody>
                {analytics.series.map((s) => {
                  const total = s.counts.reduce((sum, n) => sum + n, 0);
                  return (
                    <tr key={s.key} className="border-b border-slate-50 last:border-0">
                      <td className="px-4 py-2.5 text-[13px] font-medium text-ink-950">{s.label}</td>
                      {s.counts.map((c, i) => (
                        <td key={i} className="px-4 py-2.5 text-[13px] text-slate-600">
                          {c}
                        </td>
                      ))}
                      <td className="px-4 py-2.5 text-[13px] font-semibold text-ink-950">{total}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <h3 className="mb-4 text-[18px] font-semibold text-ink-950">Timeline</h3>
          <div className="mb-10 rounded-2xl border border-slate-100 bg-white p-5">
            <TimelineChart days={analytics.days} series={analytics.series} />
          </div>

          <div className="mb-10 grid gap-5 lg:grid-cols-2">
            <section className="rounded-2xl border border-slate-100 bg-white p-5">
              <h3 className="text-[18px] font-semibold text-ink-950">Location Report</h3>
              <p className="mt-1 text-[13px] text-slate-500">
                See where prospects are based and which geos reply most. Available once campaigns start sending.
              </p>
              <div className="mt-4 grid grid-cols-2 gap-2">
                {["United States", "United Kingdom", "India", "Germany"].map((country, i) => (
                  <div key={country} className="rounded-xl bg-slate-50 px-3 py-2.5">
                    <p className="text-[12px] text-slate-500">{country}</p>
                    <p className="text-[15px] font-semibold text-ink-950">
                      {loading ? "—" : i === 0 ? analytics.prospects_reached : "—"}
                    </p>
                  </div>
                ))}
              </div>
            </section>
            <section className="rounded-2xl border border-slate-100 bg-white p-5">
              <h3 className="text-[18px] font-semibold text-ink-950">Lead Tags</h3>
              <p className="mt-1 text-[13px] text-slate-500">
                Industry, job title and company distribution for people who connected or replied.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {["SaaS", "Agencies", "Founders", "VP Sales", "RevOps"].map((tag) => (
                  <span
                    key={tag}
                    className={`rounded-full px-3 py-1 text-[12px] font-medium ${
                      tagFilter !== "all" && tag.toLowerCase() === tagFilter ? "bg-accent text-white" : "bg-sky-50 text-sky-700"
                    }`}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </section>
          </div>
        </>
      )}

      {!loading && filteredCampaigns.length > 0 && (
        <>
          <h2 className="mb-3 text-[18px] font-semibold text-ink-950">Recent campaigns</h2>
          <div className="mb-10 space-y-2">
            {filteredCampaigns.slice(0, 4).map((c) => (
              <Link
                key={c.id}
                href={`/campaigns/${c.id}`}
                className="card flex items-center justify-between py-3 transition-colors hover:border-slate-300"
              >
                <span className="text-sm font-medium text-slate-900">{c.name}</span>
                <span className="badge">{c.status}</span>
              </Link>
            ))}
          </div>
        </>
      )}

      <h2 className="mb-3 text-[18px] font-semibold text-ink-950">Get started</h2>
      <p className="mb-4 hidden text-sm text-slate-500">
        Signed in as {me?.user.email}. Outreach is {workspace?.outreach_paused ? "paused" : "active"}.
      </p>
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
