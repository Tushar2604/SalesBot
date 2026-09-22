"use client";

/**
 * Content calendar: month, week and list views.
 *
 * Every entry is placed by the *local date the API computed* for the chosen
 * timezone, never by re-deriving one in the browser. Doing the conversion in one
 * place is what stops a post scheduled for 11:30pm IST appearing on the previous
 * day for a viewer in London.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import clsx from "clsx";
import { ApiError } from "@/lib/api";
import {
  browserTimezone,
  contentApi,
  STATUS_LABELS,
  STATUS_STYLES,
  timezoneOptions,
  type CalendarEntry,
} from "@/lib/content-api";
import { useSession } from "@/lib/session";
import { EmptyState, useToast } from "@/components/content/ContentUi";
import { IconChevronLeft, IconPlus } from "@/components/app/icons";

type View = "month" | "week" | "list";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function toKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate(),
  ).padStart(2, "0")}`;
}

/** Monday-first start of the grid containing `date`. */
function startOfWeek(date: Date): Date {
  const copy = new Date(date);
  const offset = (copy.getDay() + 6) % 7;
  copy.setDate(copy.getDate() - offset);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

function buildRange(view: View, anchor: Date): { start: Date; end: Date; days: Date[] } {
  if (view === "week") {
    const start = startOfWeek(anchor);
    const days = Array.from({ length: 7 }, (_, index) => {
      const day = new Date(start);
      day.setDate(start.getDate() + index);
      return day;
    });
    return { start, end: days[6], days };
  }

  // Month (and list) cover the whole grid, so trailing days of the previous
  // month that share a row still show their posts.
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
  const start = startOfWeek(first);
  const end = new Date(startOfWeek(last));
  end.setDate(end.getDate() + 6);

  const days: Date[] = [];
  for (let day = new Date(start); day <= end; day.setDate(day.getDate() + 1)) {
    days.push(new Date(day));
  }
  return { start, end, days };
}

export default function CalendarPage() {
  const { workspace } = useSession();
  const workspaceId = workspace?.id ?? null;
  const router = useRouter();
  const toast = useToast();

  const [view, setView] = useState<View>("month");
  const [anchor, setAnchor] = useState(() => new Date());
  const [timezone, setTimezone] = useState(browserTimezone);
  const [entries, setEntries] = useState<CalendarEntry[] | null>(null);
  const [error, setError] = useState("");

  const zones = useMemo(timezoneOptions, []);
  const { start, end, days } = useMemo(() => buildRange(view, anchor), [view, anchor]);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    setError("");
    try {
      const page = await contentApi.calendar(workspaceId, toKey(start), toKey(end), timezone);
      setEntries(page.entries);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the calendar.");
      setEntries([]);
    }
  }, [workspaceId, start, end, timezone]);

  useEffect(() => {
    void load();
  }, [load]);

  const byDay = useMemo(() => {
    const map = new Map<string, CalendarEntry[]>();
    (entries ?? []).forEach((entry) => {
      const bucket = map.get(entry.local_date) ?? [];
      bucket.push(entry);
      map.set(entry.local_date, bucket);
    });
    return map;
  }, [entries]);

  const shift = (direction: -1 | 1) => {
    const next = new Date(anchor);
    if (view === "week") next.setDate(next.getDate() + direction * 7);
    else next.setMonth(next.getMonth() + direction);
    setAnchor(next);
  };

  const heading =
    view === "week"
      ? `${start.toLocaleDateString(undefined, { day: "numeric", month: "short" })} – ${end.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}`
      : anchor.toLocaleDateString(undefined, { month: "long", year: "numeric" });

  if (!workspaceId) {
    return <EmptyState title="No workspace selected" body="Pick a workspace to see its calendar." />;
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => shift(-1)}
            aria-label="Previous"
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-300 text-slate-500 hover:border-slate-400 hover:text-ink-950"
          >
            <IconChevronLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => shift(1)}
            aria-label="Next"
            className="flex h-8 w-8 rotate-180 items-center justify-center rounded-lg border border-slate-300 text-slate-500 hover:border-slate-400 hover:text-ink-950"
          >
            <IconChevronLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setAnchor(new Date())}
            className="btn-ghost !py-1.5 text-[13px]"
          >
            Today
          </button>
        </div>

        <h2 className="font-display text-lg font-bold text-ink-950">{heading}</h2>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <select
            value={timezone}
            onChange={(event) => setTimezone(event.target.value)}
            className="input !w-auto !py-1.5 text-[13px]"
            aria-label="Calendar timezone"
          >
            {zones.map((zone) => (
              <option key={zone} value={zone}>
                {zone}
              </option>
            ))}
          </select>
          <div className="flex rounded-lg border border-slate-200 bg-slate-100/70 p-0.5">
            {(["month", "week", "list"] as View[]).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setView(option)}
                className={clsx(
                  "rounded-md px-3 py-1.5 text-[12.5px] font-semibold capitalize",
                  view === option ? "bg-white text-ink-950 shadow-sm" : "text-slate-500",
                )}
              >
                {option}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && <p className="mb-3 text-[13px] text-state-bad">{error}</p>}

      {view === "list" ? (
        <ListView
          entries={entries}
          onOpen={(id) => router.push(`/content/${id}`)}
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <div className="min-w-[44rem]">
            <div className="grid grid-cols-7 border-b border-slate-200 bg-slate-50">
              {WEEKDAYS.map((day) => (
                <div
                  key={day}
                  className="px-2 py-2 text-center text-[11.5px] font-bold uppercase tracking-wider text-slate-500"
                >
                  {day}
                </div>
              ))}
            </div>
            <div className="grid grid-cols-7">
              {days.map((day) => {
                const key = toKey(day);
                const items = byDay.get(key) ?? [];
                const inMonth = view === "week" || day.getMonth() === anchor.getMonth();
                const isToday = key === toKey(new Date());

                return (
                  <div
                    key={key}
                    className={clsx(
                      "min-h-[7rem] border-b border-r border-slate-100 p-1.5",
                      !inMonth && "bg-slate-50/60",
                      view === "week" && "min-h-[14rem]",
                    )}
                  >
                    <div className="mb-1 flex items-center justify-between">
                      <span
                        className={clsx(
                          "flex h-6 w-6 items-center justify-center rounded-full text-[12px] font-semibold",
                          isToday
                            ? "bg-accent text-white"
                            : inMonth
                              ? "text-slate-700"
                              : "text-slate-400",
                        )}
                      >
                        {day.getDate()}
                      </span>
                      <Link
                        href="/content/new"
                        aria-label={`Create a post for ${key}`}
                        title="Create a post"
                        className="rounded p-0.5 text-slate-300 hover:bg-slate-100 hover:text-accent"
                      >
                        <IconPlus className="h-3.5 w-3.5" />
                      </Link>
                    </div>

                    <ul className="space-y-1">
                      {items.map((entry) => (
                        <li key={entry.id}>
                          <button
                            type="button"
                            onClick={() => router.push(`/content/${entry.id}`)}
                            className={clsx(
                              "w-full rounded-md border px-1.5 py-1 text-left transition-colors hover:brightness-95",
                              STATUS_STYLES[entry.status],
                            )}
                          >
                            <span className="block text-[10.5px] font-bold uppercase tracking-wide">
                              {entry.local_time} · {STATUS_LABELS[entry.status]}
                            </span>
                            <span className="mt-0.5 block truncate text-[11.5px] font-medium">
                              {entry.excerpt || "Empty draft"}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {entries !== null && entries.length === 0 && view !== "list" && (
        <p className="mt-4 text-center text-[13px] text-slate-500">
          Nothing on the calendar for this period.{" "}
          <Link href="/content/new" className="font-semibold text-accent hover:underline">
            Create a post
          </Link>
          .
        </p>
      )}
    </div>
  );
}

function ListView({
  entries,
  onOpen,
}: {
  entries: CalendarEntry[] | null;
  onOpen: (id: string) => void;
}) {
  if (entries === null) {
    return (
      <div className="space-y-2" aria-hidden>
        {[0, 1, 2].map((index) => (
          <div key={index} className="h-14 animate-pulse rounded-xl bg-slate-100" />
        ))}
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <EmptyState
        title="Nothing in this period"
        body="Posts you schedule or publish appear here in order."
        action={
          <Link href="/content/new" className="btn-primary">
            Create post
          </Link>
        }
      />
    );
  }

  return (
    <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white">
      {entries.map((entry) => (
        <li key={entry.id}>
          <button
            type="button"
            onClick={() => onOpen(entry.id)}
            className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50"
          >
            <span className="w-28 shrink-0 text-[12.5px] font-semibold text-slate-700">
              {entry.local_date}
              <span className="block font-normal text-slate-500">{entry.local_time}</span>
            </span>
            <span
              className={clsx(
                "shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold",
                STATUS_STYLES[entry.status],
              )}
            >
              {STATUS_LABELS[entry.status]}
            </span>
            <span className="min-w-0 flex-1 truncate text-[13.5px] text-slate-700">
              {entry.excerpt || "Empty draft"}
            </span>
            {entry.account_label && (
              <span className="hidden shrink-0 text-[12px] text-slate-400 sm:block">
                {entry.account_label}
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}
