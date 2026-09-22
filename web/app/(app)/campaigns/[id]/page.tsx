"use client";

/**
 * Campaign detail: sequence, enrollment, launch, and what the engine actually did.
 *
 * The activity feed matters as much as the stats. When a campaign is quiet the
 * question is always "is it broken or being careful", and a list of real tasks
 * with their scheduled times answers it directly.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import clsx from "clsx";
import { ApiError } from "@/lib/api";
import {
  campaignsApi,
  leadsApi,
  STEP_LABELS,
  toStepInput,
  type ActionTaskRecord,
  type Campaign,
  type Enrollment,
  type EnrollReport,
  type LeadList,
  type StepInput,
} from "@/lib/outreach-api";
import { SequenceBuilder } from "@/components/SequenceBuilder";
import { StatCard } from "@/components/app/StatCard";
import { IconArrowRight, IconTracking } from "@/components/app/icons";
import { useSession } from "@/lib/session";

const STAT_TONES = ["cyan", "rose", "emerald", "violet", "cyan", "rose"] as const;

const STATE_STYLES: Record<string, string> = {
  pending: "text-slate-500",
  running: "text-accent",
  replied: "text-state-ok",
  completed: "text-slate-700",
  stopped: "text-state-warn",
  skipped: "text-slate-500",
  failed: "text-state-bad",
};

const TASK_STYLES: Record<string, string> = {
  succeeded: "text-state-ok",
  pending: "text-slate-500",
  dispatched: "text-accent",
  failed: "text-state-bad",
  skipped: "text-slate-500",
  cancelled: "text-state-warn",
};

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function CampaignDetailPage() {
  const params = useParams<{ id: string }>();
  const { workspace } = useSession();
  const workspaceId = workspace?.id ?? null;

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [enrollments, setEnrollments] = useState<Enrollment[]>([]);
  const [activity, setActivity] = useState<ActionTaskRecord[]>([]);
  const [lists, setLists] = useState<LeadList[]>([]);
  const [enrollReport, setEnrollReport] = useState<EnrollReport | null>(null);
  const [selectedList, setSelectedList] = useState("");
  const [editingSteps, setEditingSteps] = useState<StepInput[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const [next, enrolled, acts, nextLists] = await Promise.all([
        campaignsApi.get(workspaceId, params.id),
        campaignsApi.enrollments(workspaceId, params.id, 100),
        campaignsApi.activity(workspaceId, params.id, 50),
        leadsApi.lists(workspaceId),
      ]);
      setCampaign(next);
      setEnrollments(enrolled.items);
      setActivity(acts);
      setLists(nextLists);
      if (!selectedList && nextLists.length > 0) setSelectedList(nextLists[0].id);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load this campaign");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, params.id, selectedList]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll while running, so queued work becoming real actions is visible.
  useEffect(() => {
    if (campaign?.status !== "running") return;
    const timer = setInterval(() => void load(), 15000);
    return () => clearInterval(timer);
  }, [campaign?.status, load]);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    setProblems([]);
    setBusy(true);
    try {
      await action();
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        const list = (err.details?.problems as string[] | undefined) ?? [];
        setProblems(list);
        if (list.length === 0) setError(err.message);
      } else {
        setError("Something went wrong");
      }
    } finally {
      setBusy(false);
    }
  }

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;
  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (!campaign) return <p className="text-sm text-state-bad">{error ?? "Not found"}</p>;

  const isRunning = campaign.status === "running";
  const canLaunch = campaign.launch_blockers.length === 0;

  return (
    <div className="mx-auto max-w-4xl">
      <Link href="/campaigns" className="mb-4 inline-block text-sm text-slate-500 hover:text-slate-900">
        ← Campaigns
      </Link>

      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-ink-950">{campaign.name}</h1>
          <p className="mt-1 text-sm text-slate-500">
            {campaign.status} · sending from {campaign.linkedin_account_label}
            {campaign.stop_on_reply && " · stops on reply"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href={`/campaigns/${campaign.id}/tracking`}
            className="group inline-flex items-center gap-2 rounded-lg border border-brand-200 bg-brand-50 px-4 py-2 text-sm font-semibold text-brand-700 shadow-sm transition-colors hover:border-brand-600 hover:bg-brand-600 hover:text-white"
          >
            <IconTracking className="h-4 w-4" />
            Track leads
            <IconArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
          </Link>
          {!isRunning ? (
            <button
              className="btn-primary"
              disabled={busy || !canLaunch}
              title={canLaunch ? "" : campaign.launch_blockers.join(" ")}
              onClick={() => void run(() => campaignsApi.setStatus(workspaceId, campaign.id, "running"))}
            >
              Launch
            </button>
          ) : (
            <button
              className="btn-ghost"
              disabled={busy}
              onClick={() => void run(() => campaignsApi.setStatus(workspaceId, campaign.id, "paused"))}
            >
              Pause
            </button>
          )}
        </div>
      </header>

      {error && (
        <p role="alert" className="mb-6 rounded-md border border-state-bad/40 bg-state-bad/10 px-4 py-3 text-sm text-state-bad">
          {error}
        </p>
      )}

      {problems.length > 0 && (
        <ul className="mb-6 space-y-1.5 rounded-md border border-state-warn/40 bg-state-warn/5 p-3">
          {problems.map((problem) => (
            <li key={problem} className="text-xs text-state-warn">
              {problem}
            </li>
          ))}
        </ul>
      )}

      {campaign.launch_blockers.length > 0 && !isRunning && (
        <div className="card mb-6 border-state-warn/40">
          <h2 className="mb-2 font-medium text-state-warn">Before this can launch</h2>
          <ul className="space-y-1 text-sm text-slate-700">
            {campaign.launch_blockers.map((blocker) => (
              <li key={blocker}>• {blocker}</li>
            ))}
          </ul>
        </div>
      )}

      <section className="mb-6 grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {[
          { label: "Enrolled", value: campaign.stats.enrolled },
          { label: "Invites", value: campaign.stats.invites_sent },
          { label: "Accepted", value: campaign.stats.accepted },
          { label: "Messages", value: campaign.stats.messages_sent },
          { label: "Replied", value: campaign.stats.replied },
          { label: "Queued", value: campaign.stats.tasks_pending },
        ].map((tile, i) => (
          <StatCard key={tile.label} label={tile.label} value={tile.value} tone={STAT_TONES[i]} />
        ))}
      </section>

      {(campaign.stats.acceptance_rate !== null || campaign.stats.reply_rate !== null) && (
        <p className="mb-6 text-sm text-slate-500">
          {campaign.stats.acceptance_rate !== null &&
            `Acceptance ${Math.round(campaign.stats.acceptance_rate * 100)}%`}
          {campaign.stats.acceptance_rate !== null && campaign.stats.reply_rate !== null && " · "}
          {campaign.stats.reply_rate !== null &&
            `Reply ${Math.round(campaign.stats.reply_rate * 100)}%`}
        </p>
      )}

      <section className="card mb-6">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="font-medium text-slate-900">Sequence</h2>
          {!isRunning &&
            (editingSteps ? (
              <div className="flex gap-2">
                <button className="btn-ghost" onClick={() => setEditingSteps(null)}>
                  Cancel
                </button>
                <button
                  className="btn-primary"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await campaignsApi.replaceSteps(workspaceId, campaign.id, editingSteps);
                      setEditingSteps(null);
                    })
                  }
                >
                  Save sequence
                </button>
              </div>
            ) : (
              <button
                className="btn-ghost"
                onClick={() =>
                  setEditingSteps(
                    campaign.steps.map(toStepInput),
                  )
                }
              >
                Edit
              </button>
            ))}
        </div>

        <SequenceBuilder
          workspaceId={workspaceId}
          steps={
            editingSteps ??
            campaign.steps.map(toStepInput)
          }
          onChange={setEditingSteps}
          disabled={editingSteps === null}
        />
        {isRunning && (
          <p className="mt-3 text-xs text-slate-500">
            Pause the campaign to change the sequence — editing it mid-flight would move leads
            to steps they have already passed.
          </p>
        )}
      </section>

      <section className="card mb-6">
        <h2 className="mb-3 font-medium text-slate-900">Enroll leads</h2>
        {lists.length === 0 ? (
          <p className="text-sm text-slate-500">
            No lead lists yet. <Link href="/leads" className="text-accent hover:underline">Import a CSV</Link> first.
          </p>
        ) : (
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-56 flex-1">
              <label className="label" htmlFor="enroll-list">
                Lead list
              </label>
              <select
                id="enroll-list"
                className="input"
                value={selectedList}
                onChange={(e) => setSelectedList(e.target.value)}
              >
                {lists.map((list) => (
                  <option key={list.id} value={list.id}>
                    {list.name} ({list.imported_count})
                  </option>
                ))}
              </select>
            </div>
            <button
              className="btn-primary"
              disabled={busy || !selectedList}
              onClick={() =>
                void run(async () => {
                  setEnrollReport(
                    await campaignsApi.enroll(workspaceId, campaign.id, {
                      list_id: selectedList,
                    }),
                  );
                })
              }
            >
              Enroll
            </button>
          </div>
        )}

        {enrollReport && (
          <p className="mt-3 text-sm text-slate-700">
            Enrolled {enrollReport.enrolled}.
            {enrollReport.total_skipped > 0 && (
              <>
                {" "}
                Skipped {enrollReport.total_skipped}:{" "}
                {[
                  enrollReport.skipped_duplicate && `${enrollReport.skipped_duplicate} already contacted`,
                  enrollReport.skipped_already_enrolled && `${enrollReport.skipped_already_enrolled} already in this campaign`,
                  enrollReport.skipped_blocked && `${enrollReport.skipped_blocked} blocklisted`,
                  enrollReport.skipped_no_profile && `${enrollReport.skipped_no_profile} without a profile`,
                ]
                  .filter(Boolean)
                  .join(", ")}
                .
              </>
            )}
          </p>
        )}
      </section>

      <section className="card mb-6">
        <h2 className="mb-3 font-medium text-slate-900">
          What the engine did{" "}
          <span className="text-sm font-normal text-slate-500">({activity.length} recent)</span>
        </h2>
        {activity.length === 0 ? (
          <p className="text-sm text-slate-500">
            Nothing yet. Once launched, the dispatcher materialises actions and schedules each
            one at an irregular time inside the account&apos;s working hours.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="pb-2 pr-3">Action</th>
                  <th className="pb-2 pr-3">Lead</th>
                  <th className="pb-2 pr-3">Status</th>
                  <th className="pb-2 pr-3">Scheduled</th>
                  <th className="pb-2">Finished</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {activity.map((task) => (
                  <tr key={task.id}>
                    <td className="py-2 pr-3 text-slate-700">{STEP_LABELS[task.action_type]}</td>
                    <td className="py-2 pr-3 font-mono text-slate-500">{task.lead_public_id}</td>
                    <td className={clsx("py-2 pr-3", TASK_STYLES[task.status] ?? "text-slate-500")}>
                      {task.status}
                      {task.error_class && (
                        <span className="ml-1 text-slate-500">({task.error_class})</span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-slate-500">{when(task.scheduled_at)}</td>
                    <td className="py-2 text-slate-500">{when(task.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <h2 className="mb-3 font-medium text-slate-900">
          Leads{" "}
          <span className="text-sm font-normal text-slate-500">({enrollments.length} shown)</span>
        </h2>
        {enrollments.length === 0 ? (
          <p className="text-sm text-slate-500">No leads enrolled yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="pb-2 pr-3">Lead</th>
                  <th className="pb-2 pr-3">State</th>
                  <th className="pb-2 pr-3">Step</th>
                  <th className="pb-2 pr-3">Next</th>
                  <th className="pb-2">Notes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {enrollments.map((enrollment) => (
                  <tr key={enrollment.id}>
                    <td className="py-2 pr-3 text-slate-800">
                      {enrollment.lead_name}
                      {enrollment.lead_company && (
                        <span className="text-slate-500"> · {enrollment.lead_company}</span>
                      )}
                    </td>
                    <td
                      className={clsx(
                        "py-2 pr-3",
                        STATE_STYLES[enrollment.state] ?? "text-slate-500",
                      )}
                    >
                      {enrollment.state}
                    </td>
                    <td className="py-2 pr-3 text-slate-500">
                      {enrollment.current_step_index + 1}/{campaign.steps.length}
                    </td>
                    <td className="py-2 pr-3 text-slate-500">{when(enrollment.next_run_at)}</td>
                    <td className="max-w-64 truncate py-2 text-slate-500">
                      {enrollment.stopped_reason || enrollment.last_error || ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
