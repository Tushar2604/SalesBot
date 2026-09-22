"use client";

/**
 * CSV import in two steps: confirm the column mapping, then import.
 *
 * The preview step exists because the single most common failure is a profile
 * URL column named something we did not guess. Finding that out after a 5,000
 * row import wastes the user's time; finding out before costs one request.
 *
 * `CsvImportPanel` is the content only (no modal chrome), so it can be reused
 * inside `AddLeadsDialog`'s tab shell; `CsvImportDialog` wraps it as a
 * standalone modal for callers that just want CSV import on its own.
 */

import { useState } from "react";
import { ApiError } from "@/lib/api";
import { leadsApi, type CsvPreview, type ImportReport } from "@/lib/outreach-api";

export function CsvImportPanel({
  workspaceId,
  onImported,
  onDone,
}: {
  workspaceId: string;
  onImported: () => void;
  onDone: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [listName, setListName] = useState("");
  const [skipContacted, setSkipContacted] = useState(true);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const mapsProfile = Object.values(mapping).includes("public_id");

  async function choose(selected: File) {
    setError(null);
    setFile(selected);
    setBusy(true);
    try {
      const result = await leadsApi.previewCsv(workspaceId, selected);
      setPreview(result);
      setMapping(result.guessed_mapping);
      setListName(selected.name.replace(/\.csv$/i, ""));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not read that file");
      setFile(null);
    } finally {
      setBusy(false);
    }
  }

  async function runImport() {
    if (!file) return;
    setError(null);
    setBusy(true);
    try {
      setReport(
        await leadsApi.importCsv(workspaceId, file, {
          listName,
          mapping,
          skipContacted,
        }),
      );
      onImported();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The import failed");
    } finally {
      setBusy(false);
    }
  }

  if (report) {
    return (
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-4">
          {[
            { label: "Rows", value: report.total_rows },
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
          <div>
            <p className="mb-2 text-sm text-slate-700">
              Why rows were skipped — every row is accounted for:
            </p>
            <div className="max-h-56 overflow-y-auto rounded-md border border-slate-200">
              <table className="w-full text-xs">
                <thead className="bg-slate-100 text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left">Row</th>
                    <th className="px-3 py-2 text-left">Profile</th>
                    <th className="px-3 py-2 text-left">Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {report.problems.map((problem) => (
                    <tr key={`${problem.row_number}-${problem.reason}`}>
                      <td className="px-3 py-1.5 text-slate-500">{problem.row_number}</td>
                      <td className="px-3 py-1.5 font-mono text-slate-500">
                        {problem.public_id || "—"}
                      </td>
                      <td className="px-3 py-1.5 text-slate-700">{problem.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div className="flex justify-end">
          <button className="btn-primary" onClick={onDone}>
            Done
          </button>
        </div>
      </div>
    );
  }

  if (!preview) {
    return (
      <div>
        <p className="mb-4 text-sm text-slate-500">
          One column must hold LinkedIn profile URLs. Everything else is optional and becomes
          available to your message templates.
        </p>
        <label className="label" htmlFor="csv">
          CSV file
        </label>
        <input
          id="csv"
          type="file"
          accept=".csv,text/csv"
          className="input"
          disabled={busy}
          onChange={(e) => {
            const selected = e.target.files?.[0];
            if (selected) void choose(selected);
          }}
        />
        {error && (
          <p role="alert" className="mt-3 text-sm text-state-bad">
            {error}
          </p>
        )}
        {busy && <p className="mt-3 text-sm text-slate-500">Reading…</p>}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="list-name">
            List name
          </label>
          <input
            id="list-name"
            className="input"
            value={listName}
            onChange={(e) => setListName(e.target.value)}
          />
        </div>
        <label className="flex items-end gap-2 pb-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={skipContacted}
            onChange={(e) => setSkipContacted(e.target.checked)}
          />
          Skip anyone this workspace already contacted
        </label>
      </div>

      <div>
        <p className="label">Column mapping</p>
        <div className="max-h-64 overflow-y-auto rounded-md border border-slate-200">
          <table className="w-full text-xs">
            <thead className="bg-slate-100 text-slate-500">
              <tr>
                <th className="px-3 py-2 text-left">CSV column</th>
                <th className="px-3 py-2 text-left">Sample</th>
                <th className="px-3 py-2 text-left">Maps to</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {preview.headers.map((header) => (
                <tr key={header}>
                  <td className="px-3 py-1.5 text-slate-800">{header}</td>
                  <td className="max-w-48 truncate px-3 py-1.5 text-slate-500">
                    {preview.sample_rows[0]?.[header] ?? ""}
                  </td>
                  <td className="px-3 py-1.5">
                    <select
                      className="input py-1 text-xs"
                      value={mapping[header] ?? ""}
                      aria-label={`Map column ${header}`}
                      onChange={(e) =>
                        setMapping((prev) => {
                          const next = { ...prev };
                          if (e.target.value) next[header] = e.target.value;
                          else delete next[header];
                          return next;
                        })
                      }
                    >
                      <option value="">— custom field —</option>
                      {preview.mappable_fields.map((field) => (
                        <option key={field} value={field}>
                          {field}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!mapsProfile && (
          <p className="mt-2 text-xs text-state-warn">
            Map one column to <code>public_id</code> — the column containing LinkedIn profile
            URLs. Without it there is no way to act on these people.
          </p>
        )}
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
        <button className="btn-primary" disabled={busy || !mapsProfile} onClick={() => void runImport()}>
          {busy ? "Importing…" : "Import"}
        </button>
      </div>
    </div>
  );
}

export function CsvImportDialog({
  workspaceId,
  onClose,
  onImported,
}: {
  workspaceId: string;
  onClose: () => void;
  onImported: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 py-10">
      <div className="w-full max-w-3xl rounded-lg border border-slate-200 bg-white p-6">
        <div className="mb-5 flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold text-slate-900">Import leads from CSV</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700" aria-label="Close">
            ✕
          </button>
        </div>
        <CsvImportPanel workspaceId={workspaceId} onImported={onImported} onDone={onClose} />
      </div>
    </div>
  );
}
