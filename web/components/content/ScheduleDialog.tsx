"use client";

/**
 * Scheduling and publish confirmation.
 *
 * The scheduler sends a local date, a local time, and an IANA zone — never a UTC
 * instant computed in the browser. The user's chosen zone is frequently not the
 * browser's, and their choice is the one that must decide when the post goes out.
 */

import { useMemo, useState } from "react";
import { formatInZone, timezoneOptions, type Post } from "@/lib/content-api";
import { LinkedInPreview } from "@/components/content/LinkedInPreview";
import { Modal } from "@/components/content/ContentUi";

/** Today's date in a given zone, so "past" is judged where the user lives. */
function todayIn(timezone: string): string {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

export function ScheduleDialog({
  post,
  defaultTimezone,
  busy = false,
  error = "",
  onSchedule,
  onClose,
}: {
  post: Post;
  defaultTimezone: string;
  busy?: boolean;
  error?: string;
  onSchedule: (input: { scheduled_date: string; scheduled_time: string; timezone: string }) => void;
  onClose: () => void;
}) {
  const zones = useMemo(timezoneOptions, []);

  // Editing an existing schedule starts from its own values.
  const existing = post.scheduled_at ? new Date(post.scheduled_at) : null;
  const initialZone = post.scheduled_timezone || defaultTimezone;
  const [timezone, setTimezone] = useState(initialZone);
  const [day, setDay] = useState(() => {
    if (!existing) {
      const tomorrow = new Date(Date.now() + 24 * 3600 * 1000);
      return tomorrow.toISOString().slice(0, 10);
    }
    try {
      return new Intl.DateTimeFormat("en-CA", { timeZone: initialZone }).format(existing);
    } catch {
      return existing.toISOString().slice(0, 10);
    }
  });
  const [clock, setClock] = useState(() => {
    if (!existing) return "09:30";
    try {
      return new Intl.DateTimeFormat("en-GB", {
        timeZone: initialZone,
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(existing);
    } catch {
      return "09:30";
    }
  });

  const isPast = day < todayIn(timezone);

  return (
    <Modal
      title={post.scheduled_at ? "Reschedule post" : "Schedule post"}
      description="Stored in UTC, shown in the timezone you pick."
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-ghost">
            Cancel
          </button>
          <button
            type="button"
            disabled={busy || isPast}
            onClick={() =>
              onSchedule({ scheduled_date: day, scheduled_time: clock, timezone })
            }
            className="btn-primary"
          >
            {busy ? "Scheduling…" : post.scheduled_at ? "Reschedule" : "Schedule"}
          </button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="label">Date</span>
          <input
            type="date"
            value={day}
            min={todayIn(timezone)}
            onChange={(event) => setDay(event.target.value)}
            className="input"
          />
        </label>
        <label className="block">
          <span className="label">Time</span>
          <input
            type="time"
            value={clock}
            onChange={(event) => setClock(event.target.value)}
            className="input"
          />
        </label>
        <label className="block sm:col-span-2">
          <span className="label">Timezone</span>
          <select
            value={timezone}
            onChange={(event) => setTimezone(event.target.value)}
            className="input"
          >
            {zones.map((zone) => (
              <option key={zone} value={zone}>
                {zone}
              </option>
            ))}
          </select>
        </label>
      </div>

      {isPast && (
        <p className="mt-3 text-[13px] text-state-bad">
          That date has already passed in {timezone}. Pick a future slot.
        </p>
      )}
      {error && <p className="mt-3 text-[13px] text-state-bad">{error}</p>}

      <p className="mt-4 rounded-lg bg-slate-50 px-3 py-2.5 text-[12.5px] text-slate-600">
        Goes out <strong className="font-semibold text-slate-800">{day} at {clock}</strong> in{" "}
        {timezone}. A background worker publishes it — you do not need to keep this page open.
      </p>
    </Modal>
  );
}

export function PublishConfirmDialog({
  post,
  busy = false,
  error = "",
  onPublish,
  onClose,
}: {
  post: Post;
  busy?: boolean;
  error?: string;
  onPublish: () => void;
  onClose: () => void;
}) {
  return (
    <Modal
      title="Publish to LinkedIn"
      description="This posts immediately and cannot be undone from here."
      wide
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-ghost">
            Cancel
          </button>
          <button type="button" disabled={busy} onClick={onPublish} className="btn-primary">
            {busy ? "Publishing…" : "Publish"}
          </button>
        </>
      }
    >
      <div className="mb-4 flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-violet-500 text-[12px] font-bold text-white">
          {(post.account.full_name || post.account.label || "?")[0]?.toUpperCase()}
        </span>
        <div className="min-w-0">
          <p className="text-[12px] font-semibold uppercase tracking-wide text-slate-500">
            Posting as
          </p>
          <p className="truncate text-[13.5px] font-semibold text-slate-800">
            {post.account.full_name || post.account.label}
          </p>
        </div>
      </div>

      <LinkedInPreview
        content={post.content}
        media={post.media}
        authorName={post.account.full_name || post.account.label}
        authorHeadline={post.account.headline}
        avatarUrl={post.account.avatar_url}
        visibility={post.visibility}
      />

      {error && <p className="mt-3 text-[13px] text-state-bad">{error}</p>}
    </Modal>
  );
}

export function ScheduledSummary({ post }: { post: Post }) {
  if (!post.scheduled_at) return null;
  const zone = post.scheduled_timezone || "UTC";
  return (
    <span title={`${new Date(post.scheduled_at).toISOString()} UTC`}>
      {formatInZone(post.scheduled_at, zone)} ({zone})
    </span>
  );
}
