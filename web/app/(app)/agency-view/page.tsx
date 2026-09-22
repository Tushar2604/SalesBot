"use client";

/**
 * Agency View — the same campaigns/prospects/lead-list data as the main
 * Campaigns page, surfaced under bulk-operation framing for someone running
 * outreach across several client accounts. Reuses the real campaigns/leads
 * APIs rather than duplicating state.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError } from "@/lib/api";
import { campaignsApi, type Campaign } from "@/lib/outreach-api";
import { useSession } from "@/lib/session";
import { TabBar } from "@/components/app/TabBar";
import { ProspectsTable } from "@/components/app/ProspectsTable";
import { LeadListTable } from "@/components/app/LeadListTable";
import { IconSearch } from "@/components/app/icons";

const TABS = [
  { key: "bulk-prospects", label: "Bulk Prospects" },
  { key: "bulk-campaign", label: "Bulk Campaign" },
  { key: "leadlist", label: "Lead List" },
];

export default function AgencyViewPage() {
  const { workspace } = useSession();
  const workspaceId = workspace?.id ?? null;

  const [tab, setTab] = useState("bulk-prospects");
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      setCampaigns(await campaignsApi.list(workspaceId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load agency data");
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;

  const filteredCampaigns = campaigns.filter((c) => c.name.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-ink-950">Agency View</h1>
        {tab === "bulk-campaign" && (
          <Link href="/campaigns?new=1" className="btn-primary">
            Create Bulk Campaign
          </Link>
        )}
      </div>

      {error && <p className="mb-4 text-sm text-state-bad">{error}</p>}

      <TabBar className="mb-6" tabs={TABS} active={tab} onChange={setTab} />

      {tab === "bulk-prospects" && <ProspectsTable workspaceId={workspaceId} />}
      {tab === "leadlist" && <LeadListTable workspaceId={workspaceId} />}

      {tab === "bulk-campaign" && (
        <>
          <div className="relative mb-4 max-w-sm">
            <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search campaign by name" className="input pl-9" />
          </div>
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/70 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Source</th>
                  <th className="px-4 py-3">Campaign progress</th>
                  <th className="px-4 py-3">Performance</th>
                </tr>
              </thead>
              <tbody>
                {filteredCampaigns.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-16 text-center text-sm text-slate-400">
                      No campaigns yet across your connected accounts.
                    </td>
                  </tr>
                ) : (
                  filteredCampaigns.map((c) => (
                    <tr key={c.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70">
                      <td className="px-4 py-3">
                        <Link href={`/campaigns/${c.id}`} className="text-[13.5px] font-semibold text-ink-950 hover:text-brand-600">
                          {c.name}
                        </Link>
                      </td>
                      <td className="px-4 py-3 text-[13px] text-slate-500">{c.linkedin_account_label}</td>
                      <td className="px-4 py-3 text-[13px] text-slate-500">
                        {c.stats.completed}/{c.stats.enrolled} enrolled
                      </td>
                      <td className="px-4 py-3 text-[13px] text-slate-500">
                        {c.stats.reply_rate !== null ? `${Math.round(c.stats.reply_rate * 100)}% reply rate` : "—"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

    </div>
  );
}
