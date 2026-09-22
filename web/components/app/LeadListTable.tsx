"use client";

import { useCallback, useEffect, useState } from "react";
import { leadsApi, type LeadList } from "@/lib/outreach-api";
import { AddLeadsDialog } from "@/components/AddLeadsDialog";

/** Real lead-list data, shared by Campaigns' "Lead List" tab and Agency View's "Lead List" tab. */
export function LeadListTable({ workspaceId }: { workspaceId: string }) {
  const [lists, setLists] = useState<LeadList[]>([]);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setLists(await leadsApi.lists(workspaceId));
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <div className="mb-4 flex justify-end">
        <button
          onClick={() => setImporting(true)}
          className="btn-primary"
        >
          Create New Lead List
        </button>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/70">
              {["Name", "Source", "Import progress", "Actions"].map((h) => (
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
            ) : lists.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-16 text-center text-sm text-slate-400">
                  No lead lists yet. Create one from a CSV.
                </td>
              </tr>
            ) : (
              lists.map((list) => (
                <tr key={list.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70">
                  <td className="px-4 py-3.5 text-[13.5px] font-semibold text-ink-950">{list.name}</td>
                  <td className="px-4 py-3.5 text-[13px] text-slate-600">{list.source.replace("_", " ")}</td>
                  <td className="px-4 py-3.5 text-[13px] text-slate-600">
                    {list.imported_count}/{list.total_rows} imported
                    {list.skipped_count > 0 && ` · ${list.skipped_count} skipped`}
                  </td>
                  <td className="px-4 py-3.5">
                    <button
                      onClick={() => {
                        if (window.confirm(`Delete "${list.name}" and its leads? Campaign history is kept.`)) {
                          void leadsApi.deleteList(workspaceId, list.id, true).then(load);
                        }
                      }}
                      className="text-[12px] font-semibold text-rose-600 hover:underline"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {importing && (
        <AddLeadsDialog workspaceId={workspaceId} onClose={() => setImporting(false)} onImported={() => void load()} />
      )}
    </>
  );
}
