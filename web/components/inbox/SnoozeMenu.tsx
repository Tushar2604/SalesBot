"use client";

import { useState } from "react";
import { IconClock } from "@/components/app/icons";

const PRESETS: { label: string; hours: number }[] = [
  { label: "3 hours", hours: 3 },
  { label: "Tomorrow", hours: 24 },
  { label: "3 days", hours: 72 },
  { label: "1 week", hours: 24 * 7 },
];

export function SnoozeMenu({
  snoozedUntil,
  onSnooze,
  onUnsnooze,
}: {
  snoozedUntil: string | null;
  onSnooze: (until: string) => void;
  onUnsnooze: () => void;
}) {
  const [open, setOpen] = useState(false);
  const isSnoozed = snoozedUntil !== null && new Date(snoozedUntil).getTime() > Date.now();

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12.5px] font-semibold ${
          isSnoozed
            ? "border-amber-200 bg-amber-50 text-amber-600"
            : "border-slate-200 text-slate-600 hover:border-slate-300"
        }`}
      >
        <IconClock className="h-3.5 w-3.5" />
        {isSnoozed ? `Snoozed` : "Snooze"}
      </button>

      {open && (
        <>
          <button
            aria-label="Close"
            className="fixed inset-0 z-10 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 z-20 mt-1.5 w-40 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg">
            {PRESETS.map((preset) => (
              <button
                key={preset.label}
                onClick={() => {
                  const until = new Date(Date.now() + preset.hours * 3600_000).toISOString();
                  onSnooze(until);
                  setOpen(false);
                }}
                className="block w-full px-3 py-2 text-left text-[13px] font-medium text-slate-700 hover:bg-slate-50"
              >
                {preset.label}
              </button>
            ))}
            {isSnoozed && (
              <button
                onClick={() => {
                  onUnsnooze();
                  setOpen(false);
                }}
                className="block w-full border-t border-slate-100 px-3 py-2 text-left text-[13px] font-medium text-rose-600 hover:bg-rose-50"
              >
                Remove snooze
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
