"use client";

/**
 * Sequence templates.
 *
 * There's no `templates` table in the API yet, so a user's own templates persist
 * to localStorage (per workspace) — but it is a working save/reuse loop: build or
 * pick a sequence in the wizard, save it here, and "Use template" carries its
 * steps into a new campaign via `sessionStorage` (read once by CampaignsPage).
 * The platform's proven templates ship with the app and are read-only.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { useSession } from "@/lib/session";
import { useLocalState } from "@/lib/localSettings";
import { TemplateWizard } from "@/components/templates/TemplateWizard";
import { StepIcons } from "@/components/templates/StepIcons";
import type { StepInput } from "@/lib/outreach-api";
import { cloneSteps, PROVEN_TEMPLATES, TEMPLATE_HANDOFF_KEY, type SavedTemplate } from "@/lib/templates";
import { IconCopy, IconLayers, IconSearch, IconTrash } from "@/components/app/icons";

type Row = {
  id: string;
  name: string;
  description: string;
  steps: StepInput[];
  owner: "platform" | "mine";
  createdBy: string;
  createdAt: string | null;
};

export default function TemplatesPage() {
  const { workspace, me } = useSession();
  const workspaceId = workspace?.id ?? null;
  const author = me?.user.full_name || me?.user.email || "You";

  const [templates, setTemplates] = useLocalState<SavedTemplate[]>(workspaceId, "templates", []);
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);

  const rows: Row[] = useMemo(() => {
    const platform: Row[] = PROVEN_TEMPLATES.map((t) => ({
      id: `platform-${t.id}`,
      name: t.name,
      description: t.description,
      steps: t.steps,
      owner: "platform",
      createdBy: "SalesBot",
      createdAt: null,
    }));
    const own: Row[] = templates.map((t) => ({
      id: t.id,
      name: t.name,
      description: t.description,
      steps: t.steps,
      owner: "mine",
      createdBy: author,
      createdAt: t.createdAt,
    }));
    const q = search.trim().toLowerCase();
    return [...own, ...platform].filter((r) => !q || r.name.toLowerCase().includes(q) || r.description.toLowerCase().includes(q));
  }, [templates, search, author]);

  function saveNew(input: { name: string; description: string; steps: StepInput[] }) {
    const template: SavedTemplate = {
      id: crypto.randomUUID(),
      name: input.name,
      description: input.description,
      steps: input.steps,
      createdAt: new Date().toISOString(),
    };
    setTemplates((prev) => [template, ...prev]);
    setCreating(false);
  }

  function duplicate(row: Row) {
    const copy: SavedTemplate = {
      id: crypto.randomUUID(),
      name: `${row.name} (copy)`,
      description: row.description,
      steps: cloneSteps(row.steps),
      createdAt: new Date().toISOString(),
    };
    setTemplates((prev) => [copy, ...prev]);
  }

  function remove(id: string) {
    setTemplates((prev) => prev.filter((t) => t.id !== id));
  }

  function applyTemplate(row: Row) {
    try {
      window.sessionStorage.setItem(TEMPLATE_HANDOFF_KEY, JSON.stringify(cloneSteps(row.steps)));
    } catch {
      /* non-fatal */
    }
    window.location.href = "/campaigns?new=1";
  }

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-ink-950">Templates</h1>
          <p className="mt-1 text-sm text-slate-500">
            Start a campaign from a proven sequence, or save your own and reuse it without rebuilding steps.
          </p>
        </div>
        <button className="btn-primary" onClick={() => setCreating(true)}>
          + Create Template
        </button>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 sm:max-w-md">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-[12.5px] font-medium text-slate-500">Total templates</p>
          <p className="font-display text-xl font-extrabold text-ink-950">{PROVEN_TEMPLATES.length + templates.length}</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-[12.5px] font-medium text-slate-500">My templates</p>
          <p className="font-display text-xl font-extrabold text-ink-950">{templates.length}</p>
        </div>
      </div>

      <div className="relative mb-4 max-w-sm">
        <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search in the list..." className="input pl-9" />
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full min-w-[820px] text-left">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/70 text-[11px] font-bold uppercase tracking-wider text-slate-500">
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Steps</th>
              <th className="px-4 py-3">Owner</th>
              <th className="px-4 py-3">Created by</th>
              <th className="px-4 py-3">Created on</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-16 text-center">
                  <IconLayers className="mx-auto mb-3 h-8 w-8 text-slate-300" />
                  <p className="text-sm text-slate-400">No templates match your search.</p>
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70">
                  <td className="max-w-sm px-4 py-3.5">
                    <p className="text-[13.5px] font-semibold text-ink-950">{row.name}</p>
                    <p className="mt-0.5 line-clamp-2 text-[12.5px] text-slate-500">{row.description || "—"}</p>
                  </td>
                  <td className="px-4 py-3.5">
                    <StepIcons steps={row.steps} />
                  </td>
                  <td className="px-4 py-3.5">
                    <span
                      className={`rounded-md px-2 py-1 text-[12px] font-semibold ${
                        row.owner === "platform" ? "bg-slate-100 text-slate-600" : "bg-brand-50 text-brand-700"
                      }`}
                    >
                      {row.owner === "platform" ? "Platform" : "Mine"}
                    </span>
                  </td>
                  <td className="px-4 py-3.5 text-[13px] text-slate-500">{row.createdBy}</td>
                  <td className="px-4 py-3.5 text-[13px] text-slate-500">
                    {row.createdAt ? new Date(row.createdAt).toLocaleDateString() : "Built in"}
                  </td>
                  <td className="px-4 py-3.5">
                    <div className="flex items-center justify-end gap-2">
                      <button className="btn-ghost px-3 py-1.5 text-xs" onClick={() => applyTemplate(row)}>
                        Use template
                      </button>
                      <button aria-label="Duplicate" title="Duplicate" className="text-slate-400 hover:text-brand-600" onClick={() => duplicate(row)}>
                        <IconCopy className="h-4 w-4" />
                      </button>
                      {row.owner === "mine" && (
                        <button aria-label="Delete" title="Delete" className="text-slate-400 hover:text-state-bad" onClick={() => remove(row.id)}>
                          <IconTrash className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-slate-400">
        Your own templates are stored in this browser for now. Looking to build a campaign directly?{" "}
        <Link href="/campaigns?new=1" className="text-brand-600 hover:underline">
          Create a campaign
        </Link>
        .
      </p>

      {creating && (
        <TemplateWizard workspaceId={workspaceId} mine={templates} onClose={() => setCreating(false)} onSave={saveNew} />
      )}
    </div>
  );
}
