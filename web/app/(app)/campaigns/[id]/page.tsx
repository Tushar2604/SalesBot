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
import { useRiskGuard } from "@/components/RiskGuard";
import { AssistantSelect, useAssistantProfiles } from "@/components/assistant/Assistants";
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

function ProgressChips({ enrollment }: { enrollment: Enrollment }) {
  const declined =
    enrollment.connection_state === "not_accepted" || enrollment.connection_state === "expired";
  const chips: { label: string; done: boolean; bad?: boolean }[] = [
    { label: "Viewed", done: Boolean(enrollment.viewed_at) },
    { label: "Invited", done: Boolean(enrollment.invite_sent_at) },
    {
      label: declined ? "Not accepted" : "Accepted",
      done: Boolean(enrollment.accepted_at) || declined,
      bad: declined,
    },
    { label: "Replied", done: Boolean(enrollment.replied_at) },
  ];
  return (
    <div className="flex flex-wrap gap-1">
      {chips.map((chip) => (
        <span
          key={chip.label}
          className={clsx(
            "rounded-full px-2 py-0.5 text-[10.5px] font-semibold",
            !chip.done && "bg-slate-100 text-slate-400",
            chip.done && !chip.bad && "bg-emerald-50 text-emerald-700",
            chip.done && chip.bad && "bg-rose-50 text-rose-600",
          )}
        >
          {chip.label}
        </span>
      ))}
    </div>
  );
}

function NextAction({ enrollment }: { enrollment: Enrollment }) {
  if (enrollment.next_action) {
    return (
      <>
        <p className="text-slate-700">{STEP_LABELS[enrollment.next_action]}</p>
        <p className="text-[11px]">{when(enrollment.next_action_at)}</p>
      </>
    );
  }
  if (enrollment.next_run_at) {
    return (
      <>
        <p className="text-slate-700">Next step</p>
        <p className="text-[11px]">from {when(enrollment.next_run_at)}</p>
      </>
    );
  }
  return <span className="text-slate-400">—</span>;
}

const BOT_BADGES: Record<string, { text: string; className: string }> = {
  draft_ready: { text: "Draft ready", className: "bg-violet-50 text-violet-700" },
  reply_scheduled: { text: "Reply scheduled", className: "bg-sky-50 text-sky-700" },
  bot_replied: { text: "Bot replied", className: "bg-emerald-50 text-emerald-700" },
  needs_you: { text: "Needs you", className: "bg-amber-50 text-amber-700" },
  paused: { text: "Paused", className: "bg-slate-100 text-slate-600" },
};

function BotBadge({ enrollment }: { enrollment: Enrollment }) {
  const badge = BOT_BADGES[enrollment.bot_status];
  if (!enrollment.conversation_id) return <span className="text-slate-400">No chat yet</span>;
  return (
    <div>
      {badge ? (
        <span className={clsx("rounded-full px-2 py-0.5 text-[10.5px] font-semibold", badge.className)}>
          {badge.text}
        </span>
      ) : (
        <span className="text-slate-400">Idle</span>
      )}
      {enrollment.bot_status === "reply_scheduled" && enrollment.bot_send_at && (
        <p className="mt-0.5 text-[11px] text-slate-500">at {when(enrollment.bot_send_at)}</p>
      )}
      <Link
        href={`/inbox?conversation=${enrollment.conversation_id}`}
        className="mt-1 block text-[11px] text-accent hover:underline"
      >
        Open chat
      </Link>
    </div>
  );
}

export default function CampaignDetailPage() {
  const { guarded } = useRiskGuard();
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
  // null while untouched, so polling keeps showing the saved brief.
  const [brief, setBrief] = useState<string | null>(null);
  const { profiles } = useAssistantProfiles(workspaceId);
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
                      const saved = await guarded((ack) =>
                        campaignsApi.replaceSteps(workspaceId, campaign.id, editingSteps, ack),
                      );
                      if (saved) setEditingSteps(null);
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
        <h2 className="mb-1 font-medium text-slate-900">AI assistant</h2>
        <p className="mb-3 text-xs text-slate-500">
          Who answers when a lead from this campaign replies: its voice, what it asks, and which
          SOPs it reads. Set assistants up under{" "}
          <Link href="/assistant" className="text-accent hover:underline">
            AI Assistant
          </Link>
          .
        </p>
        <div className="mb-5 max-w-sm">
          <AssistantSelect
            profiles={profiles}
            value={campaign.assistant_id}
            disabled={busy}
            onChange={(next) =>
              void run(() => campaignsApi.update(workspaceId, campaign.id, { assistant_id: next }))
            }
          />
        </div>

        <h3 className="mb-1 text-sm font-medium text-slate-900">What this campaign is about</h3>
        <p className="mb-3 text-xs text-slate-500">
          When a lead from this campaign replies (&ldquo;what are you offering?&rdquo;, &ldquo;why
          did you contact me?&rdquo;), the assistant answers from this, plus its SOPs. It never
          mixes in other campaigns or other conversations. Anything it can&apos;t answer from
          here, it hands to you.
        </p>
        <textarea
          className="input mb-2 min-h-24"
          placeholder="e.g. We're hiring senior backend engineers (Go, remote, EU time zones). Goal: a 15-minute intro call with the hiring manager."
          value={brief ?? campaign.ai_brief}
          maxLength={4000}
          onChange={(e) => setBrief(e.target.value)}
        />
        <div className="flex justify-end">
          <button
            className="btn-primary"
            disabled={busy || brief === null || brief === campaign.ai_brief}
            onClick={() =>
              void run(async () => {
                await campaignsApi.update(workspaceId, campaign.id, { ai_brief: brief ?? "" });
                setBrief(null);
              })
            }
          >
            Save brief
          </button>
        </div>
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
            Nothing yet. Once launched, leads start one after another a few random minutes
            apart, and every action from this account is spaced by a random 2–10 minute gap,
            inside its working hours and daily limits.
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
                    <td className="py-2 pr-3 text-slate-700">{task.lead_name || task.lead_public_id}</td>
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
                  <th className="pb-2 pr-3">Progress</th>
                  <th className="pb-2 pr-3">Next</th>
                  <th className="pb-2 pr-3">Their latest reply</th>
                  <th className="pb-2">AI assistant</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {enrollments.map((enrollment) => (
                  <tr key={enrollment.id} className="align-top">
                    <td className="py-2.5 pr-3 text-slate-800">
                      {enrollment.lead_name}
                      {enrollment.lead_company && (
                        <span className="text-slate-500"> · {enrollment.lead_company}</span>
                      )}
                      <div
                        className={clsx(
                          "mt-0.5 text-[11px]",
                          STATE_STYLES[enrollment.state] ?? "text-slate-500",
                        )}
                      >
                        {enrollment.state} · step {enrollment.current_step_index + 1}/
                        {campaign.steps.length}
                      </div>
                    </td>
                    <td className="py-2.5 pr-3">
                      <ProgressChips enrollment={enrollment} />
                    </td>
                    <td className="py-2.5 pr-3 text-slate-500">
                      <NextAction enrollment={enrollment} />
                    </td>
                    <td className="max-w-64 py-2.5 pr-3 text-slate-700">
                      {enrollment.last_reply_text ? (
                        <>
                          <p className="line-clamp-2">&ldquo;{enrollment.last_reply_text}&rdquo;</p>
                          <p className="mt-0.5 text-[11px] text-slate-400">
                            {when(enrollment.last_reply_at)}
                          </p>
                        </>
                      ) : (
                        <span className="text-slate-400">
                          {enrollment.stopped_reason || enrollment.last_error || "—"}
                        </span>
                      )}
                    </td>
                    <td className="py-2.5">
                      <BotBadge enrollment={enrollment} />
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
