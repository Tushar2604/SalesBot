"use client";

/**
 * Create Template — a two-step, full-screen flow.
 *
 *  1 · Create sequence   choose a starting point (proven template or scratch),
 *                        then edit the sequence in the same builder campaigns use
 *  2 · Save template     name it and save
 *
 * The proven library is read-only and "Select" copies it, so editing a copy
 * never changes what the next person picks.
 */

import { useEffect, useMemo, useState } from "react";
import { IconChevronLeft, IconClose, IconLayers, IconSparkle } from "@/components/app/icons";
import { SequenceBuilder } from "@/components/SequenceBuilder";
import { StepIcons } from "@/components/templates/StepIcons";
import type { StepInput } from "@/lib/outreach-api";
import {
  cloneSteps,
  PROVEN_TEMPLATES,
  scratchSteps,
  type SavedTemplate,
} from "@/lib/templates";

type Stage = "choose" | "library" | "edit" | "save";
type OwnerFilter = "all" | "platform" | "mine";

/** Plain-language problems that would stop this sequence being useful. */
function problemsWith(steps: StepInput[]): string[] {
  const problems: string[] = [];
  if (steps.length === 0) problems.push("Add at least one step.");
  steps.forEach((step, i) => {
    if (step.step_type === "message" && !step.template.trim()) {
      problems.push(`Step ${i + 1} is a message with no text.`);
    }
    if (step.timing === "at" && !step.send_at) {
      problems.push(`Step ${i + 1} is set to a specific time but none is chosen.`);
    }
  });
  return problems;
}

export function TemplateWizard({
  workspaceId,
  mine,
  onClose,
  onSave,
}: {
  workspaceId: string;
  mine: SavedTemplate[];
  onClose: () => void;
  onSave: (template: { name: string; description: string; steps: StepInput[] }) => void;
}) {
  const [stage, setStage] = useState<Stage>("choose");
  const [steps, setSteps] = useState<StepInput[]>([]);
  const [filter, setFilter] = useState<OwnerFilter>("all");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [seedName, setSeedName] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows = useMemo(() => {
    const platform = PROVEN_TEMPLATES.map((t) => ({
      key: `p-${t.id}`,
      owner: "platform" as const,
      name: t.name,
      description: t.description,
      bestFor: t.best_for,
      steps: t.steps,
    }));
    const own = mine.map((t) => ({
      key: `m-${t.id}`,
      owner: "mine" as const,
      name: t.name,
      description: t.description,
      bestFor: "Saved by you",
      steps: t.steps,
    }));
    return [...platform, ...own].filter((r) => filter === "all" || r.owner === filter);
  }, [mine, filter]);

  const problems = problemsWith(steps);
  const stepNumber = stage === "save" ? 2 : 1;

  function pick(row: { name: string; description: string; steps: StepInput[] }) {
    setSteps(cloneSteps(row.steps));
    setSeedName(row.name);
    setName(`${row.name} (copy)`);
    setDescription(row.description);
    setStage("edit");
  }

  function back() {
    if (stage === "library" || (stage === "edit" && !seedName)) setStage("choose");
    else if (stage === "edit") setStage("library");
    else if (stage === "save") setStage("edit");
  }

  return (
    <div role="dialog" aria-modal="true" aria-label="Create new template" className="fixed inset-0 z-50 overflow-y-auto bg-white">
      <div className="mx-auto max-w-6xl px-4 pb-16 sm:px-8">
        <header className="sticky top-0 z-10 flex items-center gap-4 border-b border-slate-200 bg-white/95 py-4 backdrop-blur">
          <button
            onClick={onClose}
            aria-label="Close"
            className="flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 text-slate-600 hover:bg-slate-50"
          >
            <IconClose className="h-4 w-4" />
          </button>
          <h1 className="text-xl font-bold text-ink-950">Create New Template</h1>
        </header>

        <div className="mt-6 grid gap-8 md:grid-cols-[200px_1fr]">
          <ol className="flex gap-4 md:flex-col md:gap-3">
            {["Create sequence", "Save template"].map((label, i) => {
              const n = i + 1;
              const active = stepNumber === n;
              const done = stepNumber > n;
              return (
                <li key={label} className="flex items-center gap-3">
                  <span
                    className={`flex h-8 w-8 items-center justify-center rounded-full text-[13px] font-bold ${
                      active
                        ? "bg-brand-600 text-white"
                        : done
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-slate-100 text-slate-500"
                    }`}
                  >
                    {done ? "✓" : n}
                  </span>
                  <span className={`text-[14px] ${active ? "font-semibold text-brand-700" : "text-slate-500"}`}>{label}</span>
                </li>
              );
            })}
          </ol>

          <div className="min-w-0">
            {stage !== "choose" && (
              <button onClick={back} className="mb-4 inline-flex items-center gap-1 text-[13px] font-medium text-slate-500 hover:text-ink-950">
                <IconChevronLeft className="h-4 w-4" /> Back
              </button>
            )}

            {stage === "choose" && (
              <div>
                <h2 className="mb-5 text-2xl font-bold text-ink-950">Create a sequence</h2>
                <div className="grid gap-4 sm:grid-cols-2">
                  <button
                    onClick={() => setStage("library")}
                    className="rounded-2xl border border-slate-200 p-6 text-left transition-shadow hover:border-brand-300 hover:shadow-md"
                  >
                    <span className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
                      <IconSparkle className="h-5 w-5" />
                    </span>
                    <p className="text-[17px] font-bold text-ink-950">Use a proven template</p>
                    <p className="mt-1 text-[13.5px] text-slate-500">
                      Start from one of {PROVEN_TEMPLATES.length} ready-made sequences, or one you saved earlier. You can edit every step.
                    </p>
                  </button>
                  <button
                    onClick={() => {
                      setSteps(scratchSteps());
                      setSeedName("");
                      setName("");
                      setDescription("");
                      setStage("edit");
                    }}
                    className="rounded-2xl border border-slate-200 p-6 text-left transition-shadow hover:border-amber-300 hover:shadow-md"
                  >
                    <span className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-amber-50 text-amber-600">
                      <IconLayers className="h-5 w-5" />
                    </span>
                    <p className="text-[17px] font-bold text-ink-950">From scratch</p>
                    <p className="mt-1 text-[13.5px] text-slate-500">
                      Build the sequence step by step: what to send, in what order, and when.
                    </p>
                  </button>
                </div>
              </div>
            )}

            {stage === "library" && (
              <div>
                <h2 className="mb-1 text-2xl font-bold text-ink-950">Choose a template</h2>
                <p className="mb-4 text-[13.5px] text-slate-500">Selecting one makes a copy you can change freely.</p>

                <div className="mb-4 flex gap-2">
                  {(["all", "platform", "mine"] as OwnerFilter[]).map((f) => (
                    <button
                      key={f}
                      onClick={() => setFilter(f)}
                      className={`rounded-full px-3.5 py-1.5 text-[12.5px] font-semibold ${
                        filter === f ? "bg-ink-950 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                      }`}
                    >
                      {f === "all" ? "All" : f === "platform" ? "Platform" : "Mine"}
                    </button>
                  ))}
                </div>

                <div className="overflow-x-auto rounded-xl border border-slate-200">
                  <table className="w-full min-w-[640px] text-left">
                    <thead>
                      <tr className="border-b border-slate-200 bg-slate-50/70 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                        <th className="px-4 py-3">Name</th>
                        <th className="px-4 py-3">Owner</th>
                        <th className="px-4 py-3">Steps</th>
                        <th className="px-4 py-3">Best for</th>
                        <th className="px-4 py-3" />
                      </tr>
                    </thead>
                    <tbody>
                      {rows.length === 0 && (
                        <tr>
                          <td colSpan={5} className="px-4 py-12 text-center text-sm text-slate-400">
                            Nothing here yet.
                          </td>
                        </tr>
                      )}
                      {rows.map((row) => (
                        <tr key={row.key} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70">
                          <td className="max-w-xs px-4 py-3.5">
                            <p className="text-[14px] font-semibold text-ink-950">{row.name}</p>
                            <p className="mt-0.5 line-clamp-2 text-[12.5px] text-slate-500">{row.description}</p>
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
                          <td className="px-4 py-3.5">
                            <StepIcons steps={row.steps} />
                          </td>
                          <td className="px-4 py-3.5 text-[12.5px] text-slate-500">{row.bestFor}</td>
                          <td className="px-4 py-3.5 text-right">
                            <button className="btn-ghost px-4 py-1.5 text-[13px]" onClick={() => pick(row)}>
                              Select
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {stage === "edit" && (
              <div>
                <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-2xl font-bold text-ink-950">Build your sequence</h2>
                    {seedName && <p className="text-[13px] text-slate-500">Started from “{seedName}”.</p>}
                  </div>
                  <button className="btn-primary" disabled={problems.length > 0} onClick={() => setStage("save")}>
                    Save and continue
                  </button>
                </div>
                {problems.length > 0 && (
                  <ul className="mb-4 list-disc rounded-md border border-amber-200 bg-amber-50 py-2 pl-8 pr-4 text-[12.5px] text-amber-800">
                    {problems.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                )}
                <SequenceBuilder workspaceId={workspaceId} steps={steps} onChange={setSteps} />
              </div>
            )}

            {stage === "save" && (
              <div className="max-w-xl">
                <h2 className="mb-5 text-2xl font-bold text-ink-950">Save template</h2>
                <div className="mb-4">
                  <label className="label">Name</label>
                  <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Founders — warm intro" autoFocus />
                </div>
                <div className="mb-4">
                  <label className="label">Description (optional)</label>
                  <textarea className="input h-20" value={description} onChange={(e) => setDescription(e.target.value)} />
                </div>
                <div className="mb-6 rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <p className="label">Sequence</p>
                  <StepIcons steps={steps} />
                  <p className="mt-2 text-[12px] text-slate-500">{steps.length} step{steps.length === 1 ? "" : "s"}</p>
                </div>
                <button
                  className="btn-primary"
                  disabled={!name.trim()}
                  onClick={() => onSave({ name: name.trim(), description: description.trim(), steps })}
                >
                  Save template
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
