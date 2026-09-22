"use client";

/** Leads: lists, the lead table, and the workspace blocklist. */

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import {
  leadsApi,
  type BlocklistEntry,
  type BlocklistKind,
  type Lead,
  type LeadList,
} from "@/lib/outreach-api";
import { AddLeadsDialog } from "@/components/AddLeadsDialog";
import { hasRole, useSession } from "@/lib/session";

const BLOCKLIST_LABELS: Record<BlocklistKind, string> = {
  domain: "Email domain",
  company: "Company name",
  profile: "LinkedIn profile",
};

export default function LeadsPage() {
  const { workspace, role } = useSession();
  const workspaceId = workspace?.id ?? null;
  const isAdmin = hasRole(role, "admin");

  const [lists, setLists] = useState<LeadList[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedList, setSelectedList] = useState<string>("");
  const [search, setSearch] = useState("");
  const [blocklist, setBlocklist] = useState<BlocklistEntry[]>([]);
  const [showBlocklist, setShowBlocklist] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [blockKind, setBlockKind] = useState<BlocklistKind>("domain");
  const [blockValue, setBlockValue] = useState("");

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const [nextLists, page, nextBlocklist] = await Promise.all([
        leadsApi.lists(workspaceId),
        leadsApi.leads(workspaceId, {
          listId: selectedList || undefined,
          search: search || undefined,
          limit: 50,
        }),
        leadsApi.blocklist(workspaceId),
      ]);
      setLists(nextLists);
      setLeads(page.items);
      setTotal(page.total);
      setBlocklist(nextBlocklist);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load leads");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, selectedList, search]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-ink-950">Leads</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Anyone already contacted by any account in this workspace is skipped on import and
            on enrollment — two of your reps reaching the same prospect is the complaint that
            loses a customer.
          </p>
        </div>
        <button className="btn-primary shrink-0" onClick={() => setImporting(true)}>
          Add leads
        </button>
      </header>

      {error && (
        <p
          role="alert"
          className="mb-6 rounded-md border border-state-bad/40 bg-state-bad/10 px-4 py-3 text-sm text-state-bad"
        >
          {error}
        </p>
      )}

      {lists.length > 0 && (
        <section className="card mb-6">
          <h2 className="mb-3 font-medium text-slate-900">Lists</h2>
          <ul className="divide-y divide-slate-200">
            {lists.map((list) => (
              <li key={list.id} className="flex flex-wrap items-center gap-3 py-2.5">
                <button
                  className={`min-w-0 flex-1 text-left text-sm ${
                    selectedList === list.id ? "text-accent" : "text-slate-800 hover:text-slate-900"
                  }`}
                  onClick={() => setSelectedList(selectedList === list.id ? "" : list.id)}
                >
                  <span className="truncate">{list.name}</span>
                  <span className="ml-2 text-xs text-slate-500">
                    {list.imported_count} imported
                    {list.skipped_count > 0 && ` · ${list.skipped_count} skipped`}
                  </span>
                </button>
                {isAdmin && (
                  <button
                    className="btn-ghost"
                    onClick={() => {
                      if (
                        window.confirm(
                          `Delete "${list.name}" and its leads? Campaign history is kept.`,
                        )
                      ) {
                        void leadsApi.deleteList(workspaceId, list.id, true).then(load);
                      }
                    }}
                  >
                    Delete
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card mb-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-medium text-slate-900">
            {selectedList ? "Leads in this list" : "All leads"}{" "}
            <span className="text-sm font-normal text-slate-500">({total})</span>
          </h2>
          <input
            className="input w-56"
            placeholder="Search name, company, handle"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {loading ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : leads.length === 0 ? (
          <p className="text-sm text-slate-500">
            No leads yet. Import a CSV with a column of LinkedIn profile URLs.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="pb-2 pr-3">Name</th>
                  <th className="pb-2 pr-3">Company</th>
                  <th className="pb-2 pr-3">Title</th>
                  <th className="pb-2">Profile</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {leads.map((lead) => (
                  <tr key={lead.id}>
                    <td className="py-2 pr-3 text-slate-800">{lead.full_name || "—"}</td>
                    <td className="py-2 pr-3 text-slate-500">{lead.company || "—"}</td>
                    <td className="max-w-56 truncate py-2 pr-3 text-slate-500">
                      {lead.title || lead.headline || "—"}
                    </td>
                    <td className="py-2">
                      <a
                        href={lead.profile_url}
                        target="_blank"
                        rel="noreferrer"
                        className="font-mono text-xs text-accent hover:underline"
                      >
                        /in/{lead.public_id}
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-medium text-slate-900">Blocklist</h2>
            <p className="mt-1 text-sm text-slate-500">
              Never contact these. Checked at import and again at enrollment.
            </p>
          </div>
          <button className="btn-ghost shrink-0" onClick={() => setShowBlocklist((v) => !v)}>
            {showBlocklist ? "Hide" : `Manage (${blocklist.length})`}
          </button>
        </div>

        {showBlocklist && (
          <div className="mt-4">
            {isAdmin && (
              <form
                className="mb-4 flex flex-wrap items-end gap-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  void leadsApi
                    .addBlocklist(workspaceId, { kind: blockKind, value: blockValue })
                    .then(() => {
                      setBlockValue("");
                      return load();
                    })
                    .catch((err) =>
                      setError(err instanceof ApiError ? err.message : "Could not add that"),
                    );
                }}
              >
                <div>
                  <label className="label" htmlFor="block-kind">
                    Type
                  </label>
                  <select
                    id="block-kind"
                    className="input w-40"
                    value={blockKind}
                    onChange={(e) => setBlockKind(e.target.value as BlocklistKind)}
                  >
                    {(Object.keys(BLOCKLIST_LABELS) as BlocklistKind[]).map((kind) => (
                      <option key={kind} value={kind}>
                        {BLOCKLIST_LABELS[kind]}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="min-w-56 flex-1">
                  <label className="label" htmlFor="block-value">
                    Value
                  </label>
                  <input
                    id="block-value"
                    className="input"
                    value={blockValue}
                    onChange={(e) => setBlockValue(e.target.value)}
                    placeholder={
                      blockKind === "domain"
                        ? "competitor.com"
                        : blockKind === "company"
                          ? "Competitor Inc"
                          : "linkedin.com/in/someone"
                    }
                    required
                  />
                </div>
                <button type="submit" className="btn-primary">
                  Add
                </button>
              </form>
            )}

            {blocklist.length === 0 ? (
              <p className="text-sm text-slate-500">Nothing blocked yet.</p>
            ) : (
              <ul className="divide-y divide-slate-200">
                {blocklist.map((entry) => (
                  <li key={entry.id} className="flex items-center gap-3 py-2">
                    <span className="badge">{BLOCKLIST_LABELS[entry.kind]}</span>
                    <span className="min-w-0 flex-1 truncate font-mono text-xs text-slate-700">
                      {entry.value}
                    </span>
                    {isAdmin && (
                      <button
                        className="btn-ghost"
                        onClick={() =>
                          void leadsApi.removeBlocklist(workspaceId, entry.id).then(load)
                        }
                      >
                        Remove
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      {importing && (
        <AddLeadsDialog
          workspaceId={workspaceId}
          onClose={() => setImporting(false)}
          onImported={() => void load()}
        />
      )}
    </div>
  );
}
