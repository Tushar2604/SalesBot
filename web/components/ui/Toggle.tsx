"use client";

import clsx from "clsx";

/**
 * The one on/off switch used across the app.
 *
 * The knob is anchored with `left-0.5` and moved a fixed 20px, so the gap
 * around it is 2px on both sides in either position (44px track, 20px knob).
 * Every switch used to be built slightly differently, which is why they sat at
 * different positions from screen to screen.
 */
export function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  /** Accessible name; the visible text usually sits next to the switch. */
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={clsx(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-brand-600" : "bg-slate-300",
      )}
    >
      <span
        aria-hidden
        className={clsx(
          "absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform duration-150",
          checked ? "translate-x-5" : "translate-x-0",
        )}
      />
    </button>
  );
}

/** A switch with its title and explanation, aligned as one row. */
export function ToggleRow({
  title,
  description,
  checked,
  onChange,
  disabled,
}: {
  title: string;
  description?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink-950">{title}</p>
        {description && <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{description}</p>}
      </div>
      <Toggle checked={checked} onChange={onChange} disabled={disabled} label={title} />
    </div>
  );
}
