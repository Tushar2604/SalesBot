import clsx from "clsx";
import type { LinkedInAccountStatus } from "@/lib/api";

/**
 * Status is the most important thing on the accounts page, so it gets colour
 * that maps to urgency rather than to a palette: red means outreach has stopped
 * and a human is needed.
 */
const STYLES: Record<LinkedInAccountStatus, { label: string; className: string }> = {
  active: { label: "Active", className: "border-state-ok/40 bg-state-ok/10 text-state-ok" },
  connecting: {
    label: "Connecting…",
    className: "border-accent/40 bg-accent/10 text-accent",
  },
  pending_2fa: {
    label: "Code required",
    className: "border-state-warn/40 bg-state-warn/10 text-state-warn",
  },
  pending_email_pin: {
    label: "Code required",
    className: "border-state-warn/40 bg-state-warn/10 text-state-warn",
  },
  challenge: {
    label: "Verification needed",
    className: "border-state-warn/40 bg-state-warn/10 text-state-warn",
  },
  paused: { label: "Paused", className: "border-slate-200 bg-slate-100 text-slate-500" },
  disconnected: {
    label: "Not connected",
    className: "border-slate-200 bg-slate-100 text-slate-500",
  },
  disabled: { label: "Disabled", className: "border-slate-200 bg-slate-100 text-slate-500" },
  auth_lost: {
    label: "Session expired",
    className: "border-state-bad/40 bg-state-bad/10 text-state-bad",
  },
  blocked: {
    label: "Restricted by LinkedIn",
    className: "border-state-bad/40 bg-state-bad/10 text-state-bad",
  },
};

export function StatusPill({ status }: { status: LinkedInAccountStatus }) {
  const style = STYLES[status] ?? STYLES.disconnected;
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium",
        style.className,
      )}
    >
      {style.label}
    </span>
  );
}

export function HealthBar({ score }: { score: number }) {
  const tone =
    score >= 70 ? "bg-state-ok" : score >= 40 ? "bg-state-warn" : "bg-state-bad";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-200">
        <div className={clsx("h-full rounded-full", tone)} style={{ width: `${score}%` }} />
      </div>
      <span className="text-xs text-slate-500">{score}</span>
    </div>
  );
}
