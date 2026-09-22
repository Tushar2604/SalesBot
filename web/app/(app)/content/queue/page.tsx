"use client";

/**
 * Publishing queue.
 *
 * The queue is a slot generator, not a second scheduler: adding a post resolves
 * the next free slot and writes an ordinary `scheduled_at`, so queued posts are
 * published by exactly the same worker as anything else.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import { ApiError } from "@/lib/api";
import {
  contentApi,
  formatInZone,
  timezoneOptions,
  type Post,
  type Queue,
  type QueueSlot,
} from "@/lib/content-api";
import { useSession } from "@/lib/session";
import { CardSkeleton, EmptyState, PostStatusPill, useToast } from "@/components/content/ContentUi";
import {
  IconArrowDown,
  IconArrowUp,
  IconClose,
  IconPause,
  IconPlay,
  IconPlus,
} from "@/components/app/icons";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export default function QueuePage() {
  const { workspace, role } = useSession();
  const workspaceId = workspace?.id ?? null;
  const router = useRouter();
  const toast = useToast();
  const canPublish = role === "owner" || role === "admin";

  const [queue, setQueue] = useState<Queue | null>(null);
  const [drafts, setDrafts] = useState<Post[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const zones = useMemo(timezoneOptions, []);

  const [newWeekday, setNewWeekday] = useState(0);
  const [newTime, setNewTime] = useState("09:00");

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const [loaded, draftPage] = await Promise.all([
        contentApi.queue(workspaceId),
        contentApi.posts(workspaceId, { status: ["draft", "approved"], limit: 50 }),
      ]);
      setQueue(loaded);
      setDrafts(draftPage.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the queue.");
      setQueue(null);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (label: string, action: () => Promise<Queue>, success: string) => {
    setBusy(true);
    try {
      setQueue(await action());
      toast.success(success);
      // Adding or removing changes what is left in drafts too.
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : `Could not ${label}.`);
    } finally {
      setBusy(false);
    }
  };

  if (!workspaceId) {
    return <EmptyState title="No workspace selected" body="Pick a workspace to see its queue." />;
  }
  if (error) {
    return <EmptyState title="Queue unavailable" body={error} />;
  }
  if (!queue) {
    return <CardSkeleton count={2} />;
  }

  const slots = queue.slots;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
      <section>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <h2 className="font-display text-lg font-bold text-ink-950">Publishing queue</h2>
          {queue.paused ? (
            <span className="rounded-full border border-state-warn/40 bg-state-warn/10 px-2.5 py-0.5 text-[11.5px] font-semibold text-state-warn">
              Paused
            </span>
          ) : (
            <span className="rounded-full border border-state-ok/40 bg-state-ok/10 px-2.5 py-0.5 text-[11.5px] font-semibold text-state-ok">
              Running
            </span>
          )}
          {canPublish && (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void run(
                  "update the queue",
                  () => contentApi.updateQueue(workspaceId, { paused: !queue.paused }),
                  queue.paused ? "Queue resumed." : "Queue paused.",
                )
              }
              className="btn-ghost !py-1.5 text-[13px]"
            >
              {queue.paused ? (
                <>
                  <IconPlay className="h-3.5 w-3.5" />
                  Resume
                </>
              ) : (
                <>
                  <IconPause className="h-3.5 w-3.5" />
                  Pause
                </>
              )}
            </button>
          )}
          {queue.next_slot_at && (
            <span className="ml-auto text-[12.5px] text-slate-500">
              Next slot {formatInZone(queue.next_slot_at, queue.timezone)}
            </span>
          )}
        </div>

        {queue.paused && (
          <p className="mb-4 rounded-xl border border-state-warn/30 bg-state-warn/5 px-4 py-3 text-[13px] text-slate-700">
            The queue is paused. Queued posts keep their scheduled times and will still publish —
            pausing stops new posts being slotted in. Remove a post from the queue to hold it back.
          </p>
        )}

        {queue.items.length === 0 ? (
          <EmptyState
            title="The queue is empty"
            body="Add drafts to the queue and each one takes the next free slot, so you can line up a week of posts without picking times one by one."
            action={
              <Link href="/content/new" className="btn-primary">
                <IconPlus className="h-4 w-4" />
                Create post
              </Link>
            }
          />
        ) : (
          <ol className="space-y-2">
            {queue.items.map((post, index) => (
              <li key={post.id} className="card flex items-start gap-3 py-3">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[12.5px] font-bold text-slate-600">
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <button
                    type="button"
                    onClick={() => router.push(`/content/${post.id}`)}
                    className="block w-full text-left"
                  >
                    <p className="line-clamp-2 text-[13.5px] text-slate-700">
                      {post.content.trim() || (
                        <span className="italic text-slate-400">Empty draft</span>
                      )}
                    </p>
                  </button>
                  <p className="mt-1 flex flex-wrap items-center gap-2 text-[12.5px] text-slate-500">
                    <PostStatusPill status={post.status} />
                    {post.scheduled_at && (
                      <>{formatInZone(post.scheduled_at, queue.timezone)} ({queue.timezone})</>
                    )}
                    <span className="text-slate-400">
                      {post.account.full_name || post.account.label}
                    </span>
                  </p>
                </div>

                {canPublish && (
                  <div className="flex shrink-0 gap-1">
                    <IconButton
                      label="Move up"
                      disabled={busy || index === 0}
                      onClick={() =>
                        void run(
                          "reorder",
                          () => contentApi.moveInQueue(workspaceId, post.id, "up"),
                          "Queue reordered.",
                        )
                      }
                    >
                      <IconArrowUp className="h-3.5 w-3.5" />
                    </IconButton>
                    <IconButton
                      label="Move down"
                      disabled={busy || index === queue.items.length - 1}
                      onClick={() =>
                        void run(
                          "reorder",
                          () => contentApi.moveInQueue(workspaceId, post.id, "down"),
                          "Queue reordered.",
                        )
                      }
                    >
                      <IconArrowDown className="h-3.5 w-3.5" />
                    </IconButton>
                    <IconButton
                      label="Remove from queue"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          "remove from the queue",
                          () => contentApi.removeFromQueue(workspaceId, post.id),
                          "Removed from the queue.",
                        )
                      }
                    >
                      <IconClose className="h-3.5 w-3.5" />
                    </IconButton>
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}

        {canPublish && drafts.length > 0 && (
          <div className="card mt-5">
            <h3 className="font-display text-[15px] font-bold text-ink-950">Add a draft</h3>
            <p className="mt-0.5 text-[12.5px] text-slate-500">
              Each draft you add takes the next free slot.
            </p>
            <ul className="mt-3 space-y-2">
              {drafts.slice(0, 8).map((draft) => (
                <li
                  key={draft.id}
                  className="flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2"
                >
                  <p className="min-w-0 flex-1 truncate text-[13px] text-slate-700">
                    {draft.content.trim() || "Empty draft"}
                  </p>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void run(
                        "queue that post",
                        () => contentApi.addToQueue(workspaceId, draft.id),
                        "Added to the queue.",
                      )
                    }
                    className="btn-ghost !py-1 text-[12.5px]"
                  >
                    Add
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* ── slot configuration ───────────────────────────────────────────── */}
      <aside className="lg:sticky lg:top-6 lg:self-start">
        <div className="card">
          <h3 className="font-display text-[15px] font-bold text-ink-950">Time slots</h3>
          <p className="mt-0.5 text-[12.5px] text-slate-500">
            When queued posts go out, week after week.
          </p>

          <label className="mt-3 block">
            <span className="label">Timezone</span>
            <select
              value={queue.timezone}
              disabled={!canPublish || busy}
              onChange={(event) =>
                void run(
                  "update the timezone",
                  () => contentApi.updateQueue(workspaceId, { timezone: event.target.value }),
                  "Queue timezone updated.",
                )
              }
              className="input"
            >
              {(zones.includes(queue.timezone) ? zones : [queue.timezone, ...zones]).map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </select>
          </label>

          <ul className="mt-3 space-y-1.5">
            {slots.length === 0 && (
              <li className="rounded-lg border border-dashed border-slate-300 px-3 py-3 text-center text-[12.5px] text-slate-500">
                No slots yet. Add one below.
              </li>
            )}
            {slots.map((slot, index) => (
              <li
                key={`${slot.weekday}-${slot.time}-${index}`}
                className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2"
              >
                <span className="flex-1 text-[13px] text-slate-700">
                  {WEEKDAYS[slot.weekday]} at {slot.time}
                </span>
                {canPublish && (
                  <IconButton
                    label={`Remove ${WEEKDAYS[slot.weekday]} ${slot.time}`}
                    disabled={busy}
                    onClick={() =>
                      void run(
                        "remove that slot",
                        () =>
                          contentApi.updateQueue(workspaceId, {
                            slots: slots.filter((_, position) => position !== index),
                          }),
                        "Slot removed.",
                      )
                    }
                  >
                    <IconClose className="h-3.5 w-3.5" />
                  </IconButton>
                )}
              </li>
            ))}
          </ul>

          {canPublish && (
            <div className="mt-3 border-t border-slate-100 pt-3">
              <p className="label">Add a slot</p>
              <div className="flex gap-2">
                <select
                  value={newWeekday}
                  onChange={(event) => setNewWeekday(Number(event.target.value))}
                  className="input"
                  aria-label="Weekday"
                >
                  {WEEKDAYS.map((day, index) => (
                    <option key={day} value={index}>
                      {day}
                    </option>
                  ))}
                </select>
                <input
                  type="time"
                  value={newTime}
                  onChange={(event) => setNewTime(event.target.value)}
                  className="input !w-32"
                  aria-label="Time"
                />
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  const next: QueueSlot[] = [...slots, { weekday: newWeekday, time: newTime }];
                  void run(
                    "add that slot",
                    () => contentApi.updateQueue(workspaceId, { slots: next }),
                    "Slot added.",
                  );
                }}
                className="btn-ghost mt-2 w-full !py-1.5 text-[13px]"
              >
                <IconPlus className="h-3.5 w-3.5" />
                Add slot
              </button>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function IconButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={clsx(
        "flex h-7 w-7 items-center justify-center rounded-lg border border-slate-200 text-slate-500 transition-colors",
        disabled ? "cursor-not-allowed opacity-40" : "hover:border-slate-400 hover:text-ink-950",
      )}
    >
      {children}
    </button>
  );
}
