"use client";

import { useCallback, useEffect, useState } from "react";
import { leadsApi, type Lead } from "@/lib/outreach-api";
import { StatCard } from "@/components/app/StatCard";
import { IconSearch } from "@/components/app/icons";

/** Real prospect data + stats, shared by Campaigns' "Prospects" tab and Agency View's "Bulk Prospects" tab. */
export function ProspectsTable({ workspaceId }: { workspaceId: string }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await leadsApi.leads(workspaceId, { search: search || undefined, limit: 50 });
      setLeads(page.items);
      setTotal(page.total);
    } finally {
      setLoading(false);
    }
  }, [workspaceId, search]);

  useEffect(() => {
    void load();
  }, [load]);

  const withEmail = leads.filter((l) => l.email).length;
  const companies = new Set(leads.map((l) => l.company).filter(Boolean)).size;

  return (
    <>
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatCard label="Total" value={total} tone="cyan" />
        <StatCard label="Email available" value={withEmail} tone="emerald" />
        <StatCard label="Companies" value={companies} tone="violet" />
      </div>

      <div className="relative mb-4 max-w-sm">
        <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search prospects by name"
          className="input pl-9"
        />
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/70">
              {["Full name", "Title", "Company", "Source"].map((h) => (
                <th key={h} className="px-4 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={4} className="px-4 py-10 text-center text-sm text-slate-400">
                  Loading…
                </td>
              </tr>
            ) : leads.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-16 text-center text-sm text-slate-400">
                  No prospects yet. Import a CSV from the Lead List tab.
                </td>
              </tr>
            ) : (
              leads.map((lead) => (
                <tr key={lead.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70">
                  <td className="px-4 py-3.5">
                    <p className="text-[13.5px] font-semibold text-ink-950">{lead.full_name || "—"}</p>
                    <a
                      href={lead.profile_url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-mono text-[11px] text-brand-600 hover:underline"
                    >
                      /in/{lead.public_id}
                    </a>
                  </td>
                  <td className="px-4 py-3.5 text-[13px] text-slate-600">{lead.title || lead.headline || "—"}</td>
                  <td className="px-4 py-3.5 text-[13px] text-slate-600">{lead.company || "—"}</td>
                  <td className="px-4 py-3.5 text-[13px] text-slate-500">{lead.source.replace("_", " ")}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
