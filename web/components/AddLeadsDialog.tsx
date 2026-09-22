"use client";

/**
 * Three ways to add leads: upload a CSV, paste LinkedIn links directly, or
 * search LinkedIn by keyword through a connected account. All three land in
 * the same place — a new `LeadList` plus rows in `leads` — so whichever tab
 * the user picks, the result shows up the same way everywhere else.
 */

import { useEffect, useState } from "react";
import { ApiError, linkedinApi, type LinkedInAccount } from "@/lib/api";
import { leadsApi, type ImportReport, type LeadList } from "@/lib/outreach-api";
import { CsvImportPanel } from "@/components/CsvImportDialog";
import clsx from "clsx";

export type Tab = "csv" | "links";

const TABS: { key: Tab; label: string }[] = [
  { key: "csv", label: "Upload CSV" },
  { key: "links", label: "Paste links" },
];

function PasteLinksPanel({
  workspaceId,
  onImported,
  onDone,
}: {
  workspaceId: string;
  onImported: () => void;
  onDone: () => void;
}) {
  const [urls, setUrls] = useState("");
  const [listName, setListName] = useState("");
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!urls.trim()) return;
    setError(null);
    setBusy(true);
    try {
      const result = await leadsApi.importUrls(workspaceId, urls, listName);
      setReport(result);
      onImported();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not import those links");
    } finally {
      setBusy(false);
    }
  }

  if (report) {
    return (
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-4">
          {[
            { label: "Pasted", value: report.total_rows },
            { label: "Imported", value: report.imported },
            { label: "Updated", value: report.updated },
            { label: "Skipped", value: report.skipped },
          ].map((tile) => (
            <div key={tile.label} className="rounded-md border border-slate-200 bg-slate-50 p-3">
              <p className="text-xs uppercase tracking-wide text-slate-500">{tile.label}</p>
              <p className="mt-1 text-xl font-semibold text-slate-900">{tile.value}</p>
            </div>
          ))}
        </div>
        {report.problems.length > 0 && (
          <ul className="max-h-40 space-y-1 overflow-y-auto text-xs text-slate-500">
            {report.problems.map((p) => (
              <li key={`${p.row_number}-${p.reason}`}>
                {p.public_id || `item ${p.row_number}`}: {p.reason}
              </li>
            ))}
          </ul>
        )}
        <div className="flex justify-end">
          <button className="btn-primary" onClick={onDone}>
            Done
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-500">
        Paste one or more LinkedIn profile links, or bare handles like{" "}
        <code>satyanadella</code> — separated by spaces, commas, or new lines.
      </p>
      <div>
        <label className="label" htmlFor="paste-urls">
          Profile links
        </label>
        <textarea
          id="paste-urls"
          className="input h-32 font-mono text-xs"
          placeholder={"https://www.linkedin.com/in/satyanadella\nhttps://www.linkedin.com/in/jeffweiner08"}
          value={urls}
          onChange={(e) => setUrls(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="paste-list-name">
          List name (optional)
        </label>
        <input
          id="paste-list-name"
          className="input"
          value={listName}
          onChange={(e) => setListName(e.target.value)}
          placeholder="Pasted links"
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-state-bad">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-3">
        <button className="btn-ghost" onClick={onDone}>
          Cancel
        </button>
        <button className="btn-primary" disabled={busy || !urls.trim()} onClick={() => void submit()}>
          {busy ? "Adding…" : "Add leads"}
        </button>
      </div>
    </div>
  );
}

export function AddLeadsDialog({
  workspaceId,
  onClose,
  onImported,
  initialTab = "csv",
}: {
  workspaceId: string;
  onClose: () => void;
  onImported: () => void;
  initialTab?: Tab;
}) {
  const [tab, setTab] = useState<Tab>(initialTab);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 py-10">
      <div className="w-full max-w-3xl rounded-lg border border-slate-200 bg-white p-6">
        <div className="mb-5 flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold text-slate-900">Add leads</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700" aria-label="Close">
            ✕
          </button>
        </div>

        <div className="mb-5 flex gap-1 rounded-xl border border-slate-200 bg-slate-100/70 p-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={clsx(
                "flex-1 rounded-lg px-3 py-2 text-[13px] font-semibold transition-colors",
                tab === t.key ? "bg-white text-ink-950 shadow-sm" : "text-slate-500 hover:text-ink-950",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "csv" && (
          <CsvImportPanel workspaceId={workspaceId} onImported={onImported} onDone={onClose} />
        )}
        {tab === "links" && (
          <PasteLinksPanel workspaceId={workspaceId} onImported={onImported} onDone={onClose} />
        )}
      </div>
    </div>
  );
}
