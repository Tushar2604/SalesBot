"use client";

/**
 * Multi-step "Create Campaign" wizard: Details → Add People → Review.
 *
 * "Add People" reuses the real CSV import pipeline (a new lead list is
 * created and imported through the existing `/leads/import-csv` endpoint) or
 * an existing lead list — then Review creates the campaign and, if a list was
 * chosen, enrolls it in one action. Nothing here is simulated: every button
 * calls a real endpoint that already exists elsewhere in the app.
 */

import { useEffect, useState } from "react";
import { ApiError, linkedinApi, type LinkedInAccount } from "@/lib/api";
import { campaignsApi, leadsApi, type LeadList, type StepInput } from "@/lib/outreach-api";
import { CsvImportDialog } from "@/components/CsvImportDialog";
import { SequenceBuilder, defaultSequence } from "@/components/SequenceBuilder";
import { IconCheckCircle, IconClose } from "@/components/app/icons";
import clsx from "clsx";

type Step = "details" | "people" | "review";

const STEPS: { key: Step; label: string }[] = [
  { key: "details", label: "Details" },
  { key: "people", label: "Add People" },
  { key: "review", label: "Review & Sequence" },
];

export function CampaignWizard({
  workspaceId,
  accounts,
  initialSteps,
  onClose,
  onCreated,
}: {
  workspaceId: string;
  accounts: LinkedInAccount[];
  initialSteps?: StepInput[];
  onClose: () => void;
  onCreated: (campaignId: string) => void;
}) {
  const [step, setStep] = useState<Step>("details");

  const [name, setName] = useState("");
  const [accountId, setAccountId] = useState(accounts[0]?.id ?? "");
  const [stopOnReply, setStopOnReply] = useState(true);
  const [steps, setSteps] = useState<StepInput[]>(initialSteps ?? defaultSequence());

  const [lists, setLists] = useState<LeadList[]>([]);
  const [selectedListId, setSelectedListId] = useState<string>("");
  const [importing, setImporting] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void leadsApi.lists(workspaceId).then(setLists).catch(() => undefined);
  }, [workspaceId]);

  const stepIndex = STEPS.findIndex((s) => s.key === step);
  const detailsValid = name.trim().length > 0 && Boolean(accountId);

  async function finish() {
    setError(null);
    setProblems([]);
    setBusy(true);
    try {
      const campaign = await campaignsApi.create(workspaceId, {
        name,
        linkedin_account_id: accountId,
        steps,
        stop_on_reply: stopOnReply,
      });
      if (selectedListId) {
        await campaignsApi.enroll(workspaceId, campaign.id, { list_id: selectedListId });
      }
      onCreated(campaign.id);
    } catch (err) {
      if (err instanceof ApiError) {
        const list = (err.details?.problems as string[] | undefined) ?? [];
        setProblems(list);
        if (list.length === 0) setError(err.message);
      } else {
        setError("Could not create that campaign");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/60 p-4 py-8">
      <div className="w-full max-w-3xl rounded-xl border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-5">
          <h2 className="text-lg font-bold text-ink-950">Create Campaign</h2>
          <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-ink-950">
            <IconClose className="h-4 w-4" />
          </button>
        </div>

        <div className="flex">
          <nav className="w-44 shrink-0 border-r border-slate-100 p-5">
            {STEPS.map((s, i) => (
              <button
                key={s.key}
                onClick={() => i <= stepIndex && setStep(s.key)}
                disabled={i > stepIndex}
                className={clsx(
                  "mb-3 flex w-full items-center gap-2 text-left text-[13.5px] font-semibold",
                  i === stepIndex ? "text-brand-600" : i < stepIndex ? "text-ink-950" : "text-slate-300",
                )}
              >
                <span
                  className={clsx(
                    "flex h-2 w-2 shrink-0 rounded-full",
                    i === stepIndex ? "bg-brand-600" : i < stepIndex ? "bg-ink-950" : "bg-slate-300",
                  )}
                />
                {s.label}
              </button>
            ))}
          </nav>

          <div className="flex-1 p-6">
            {error && <p className="mb-4 text-sm text-state-bad">{error}</p>}
            {problems.length > 0 && (
              <ul className="mb-4 space-y-1 rounded-md border border-state-warn/40 bg-state-warn/5 p-3">
                {problems.map((p) => (
                  <li key={p} className="text-xs text-state-warn">
                    {p}
                  </li>
                ))}
              </ul>
            )}

            {step === "details" && (
              <div className="space-y-4">
                <div>
                  <label className="label">Campaign name</label>
                  <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Q4 founders — India" autoFocus />
                </div>
                <div>
                  <label className="label">Send from</label>
                  <select className="input" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.label || a.full_name} ({a.status})
                      </option>
                    ))}
                  </select>
                </div>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={stopOnReply} onChange={(e) => setStopOnReply(e.target.checked)} />
                  Stop a lead&apos;s sequence the moment they reply
                </label>
              </div>
            )}

            {step === "people" && (
              <div>
                <h3 className="mb-1 font-semibold text-ink-950">Add people to your campaign</h3>
                <p className="mb-4 text-sm text-slate-500">
                  Choose an existing lead list, or import a new one from CSV now — enrollment happens
                  automatically once the campaign is created.
                </p>

                {lists.length > 0 && (
                  <div className="mb-4">
                    <label className="label">Existing lead list</label>
                    <select className="input" value={selectedListId} onChange={(e) => setSelectedListId(e.target.value)}>
                      <option value="">— none, enroll later —</option>
                      {lists.map((l) => (
                        <option key={l.id} value={l.id}>
                          {l.name} ({l.imported_count})
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <button className="btn-ghost" onClick={() => setImporting(true)}>
                  Upload CSV
                </button>

                {selectedListId && (
                  <p className="mt-3 flex items-center gap-1.5 text-xs text-emerald-600">
                    <IconCheckCircle className="h-3.5 w-3.5" />
                    Will enroll {lists.find((l) => l.id === selectedListId)?.name} right after creation.
                  </p>
                )}
              </div>
            )}

            {step === "review" && (
              <div>
                <h3 className="mb-3 font-semibold text-ink-950">Sequence</h3>
                <SequenceBuilder workspaceId={workspaceId} steps={steps} onChange={setSteps} />
                <div className="mt-5 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                  <p>
                    <strong>{name || "Untitled campaign"}</strong> from{" "}
                    {accounts.find((a) => a.id === accountId)?.label || "—"} · {steps.length} steps
                    {selectedListId && <> · enrolling {lists.find((l) => l.id === selectedListId)?.name}</>}
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-slate-100 px-6 py-4">
          <button
            className="btn-ghost"
            onClick={() => (stepIndex === 0 ? onClose() : setStep(STEPS[stepIndex - 1].key))}
          >
            {stepIndex === 0 ? "Cancel" : "Back"}
          </button>
          {step !== "review" ? (
            <button
              className="btn-primary"
              disabled={step === "details" && !detailsValid}
              onClick={() => setStep(STEPS[stepIndex + 1].key)}
            >
              Continue
            </button>
          ) : (
            <button className="btn-primary" disabled={busy} onClick={() => void finish()}>
              {busy ? "Creating…" : "Create campaign"}
            </button>
          )}
        </div>
      </div>

      {importing && (
        <CsvImportDialog
          workspaceId={workspaceId}
          onClose={() => setImporting(false)}
          onImported={() => {
            void leadsApi.lists(workspaceId).then((next) => {
              setLists(next);
              if (next[0]) setSelectedListId(next[0].id);
            });
          }}
        />
      )}
    </div>
  );
}
