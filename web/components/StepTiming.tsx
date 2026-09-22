"use client";

/**
 * "When should this step run?" — the control that lets a user decide, instead
 * of the scheduler picking a random moment for them.
 *
 * Four modes, each with its own input:
 *  Smart      a natural time in working hours, after N hours/days (recommended)
 *  ASAP       the moment the account's limits allow
 *  After      an exact wait in minutes/hours/days
 *  At a time  a specific date and time
 *
 * Every mode still passes through the account's safety limits (working hours,
 * daily caps, spacing between actions). The note under the control says so, so
 * "send immediately" never promises something the engine will not do.
 */

import { describeTiming, type StepInput, type StepTiming } from "@/lib/outreach-api";

const MODES: { key: StepTiming; label: string; hint: string }[] = [
  { key: "smart", label: "Smart", hint: "Natural time" },
  { key: "asap", label: "ASAP", hint: "Right away" },
  { key: "delay", label: "After a wait", hint: "Exact delay" },
  { key: "at", label: "Specific time", hint: "Date & time" },
];

type Unit = "minutes" | "hours" | "days";
const UNIT_MINUTES: Record<Unit, number> = { minutes: 1, hours: 60, days: 1440 };

function splitMinutes(total: number): { value: number; unit: Unit } {
  if (total > 0 && total % 1440 === 0) return { value: total / 1440, unit: "days" };
  if (total > 0 && total % 60 === 0) return { value: total / 60, unit: "hours" };
  return { value: total, unit: "minutes" };
}

/** ISO string -> the "YYYY-MM-DDTHH:mm" a datetime-local input wants, in local time. */
function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function StepTiming({
  step,
  isFirst,
  disabled,
  onChange,
}: {
  step: StepInput;
  isFirst: boolean;
  disabled: boolean;
  onChange: (patch: Partial<StepInput>) => void;
}) {
  const mode: StepTiming = step.timing ?? "smart";
  const wait = splitMinutes(step.delay_minutes ?? 0);
  const smartUnitIsDays = step.delay_hours > 0 && step.delay_hours % 24 === 0;

  function setMode(next: StepTiming) {
    if (next === mode) return;
    onChange({
      timing: next,
      delay_minutes: next === "delay" ? (step.delay_minutes ?? 10) : null,
      send_at: next === "at" ? (step.send_at ?? null) : null,
    });
  }

  return (
    <div className="mb-3 rounded-lg border border-slate-200 bg-white p-3">
      <p className="label">When to send</p>

      <div role="radiogroup" aria-label="When to send" className="mb-3 grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        {MODES.map((m) => {
          const active = mode === m.key;
          return (
            <button
              key={m.key}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={disabled}
              onClick={() => setMode(m.key)}
              className={`rounded-lg border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed ${
                active
                  ? "border-brand-500 bg-brand-50 ring-1 ring-brand-500"
                  : "border-slate-200 bg-white hover:border-slate-300"
              }`}
            >
              <span className={`block text-[13px] font-semibold ${active ? "text-brand-700" : "text-slate-700"}`}>
                {m.label}
              </span>
              <span className="block text-[11px] text-slate-400">{m.hint}</span>
            </button>
          );
        })}
      </div>

      {mode === "smart" && (
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
          Wait
          <input
            type="number"
            min={0}
            className="input w-20 py-1"
            disabled={disabled}
            aria-label="Wait before this step"
            value={smartUnitIsDays ? step.delay_hours / 24 : step.delay_hours}
            onChange={(e) => {
              const n = Math.max(0, Number(e.target.value) || 0);
              onChange({ delay_hours: smartUnitIsDays ? n * 24 : n });
            }}
          />
          <select
            className="input w-24 py-1"
            disabled={disabled}
            aria-label="Wait unit"
            value={smartUnitIsDays ? "days" : "hours"}
            onChange={(e) =>
              onChange({
                delay_hours:
                  e.target.value === "days"
                    ? Math.max(1, Math.round(step.delay_hours / 24)) * 24
                    : step.delay_hours,
              })
            }
          >
            <option value="hours">hours</option>
            <option value="days">days</option>
          </select>
          then send at a natural moment inside working hours.
        </div>
      )}

      {mode === "asap" && (
        <p className="text-sm text-slate-600">
          Runs as soon as the account is allowed to act — no random spreading.
        </p>
      )}

      {mode === "delay" && (
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
          Wait exactly
          <input
            type="number"
            min={0}
            className="input w-20 py-1"
            disabled={disabled}
            aria-label="Exact wait"
            value={wait.value}
            onChange={(e) =>
              onChange({
                delay_minutes: Math.max(0, Number(e.target.value) || 0) * UNIT_MINUTES[wait.unit],
              })
            }
          />
          <select
            className="input w-28 py-1"
            disabled={disabled}
            aria-label="Exact wait unit"
            value={wait.unit}
            onChange={(e) =>
              onChange({ delay_minutes: wait.value * UNIT_MINUTES[e.target.value as Unit] })
            }
          >
            <option value="minutes">minutes</option>
            <option value="hours">hours</option>
            <option value="days">days</option>
          </select>
          {isFirst ? "after the campaign starts." : "after the previous step finishes."}
        </div>
      )}

      {mode === "at" && (
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
          Send on
          <input
            type="datetime-local"
            className="input w-56 py-1"
            disabled={disabled}
            aria-label="Send at"
            value={toLocalInput(step.send_at)}
            onChange={(e) =>
              onChange({ send_at: e.target.value ? new Date(e.target.value).toISOString() : null })
            }
          />
          <span className="text-xs text-slate-400">
            your local time ({Intl.DateTimeFormat().resolvedOptions().timeZone})
          </span>
        </div>
      )}

      <p className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-500">
        <span className="font-semibold text-slate-700">Runs:</span> {describeTiming(step, isFirst)}.{" "}
        Working hours, daily limits and the gap between actions still apply — they are what keep the
        account safe, so &quot;immediately&quot; means &quot;the first moment they allow&quot;.
      </p>
    </div>
  );
}
