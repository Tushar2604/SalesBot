/** "Warnings 2/3 · At risk" — the account's ban-risk strikes at a glance. */

import clsx from "clsx";
import type { RiskLevel } from "@/lib/api";

const LEVELS: Record<RiskLevel, { label: string; className: string }> = {
  safe: { label: "Safe", className: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  watch: { label: "Watch", className: "border-amber-200 bg-amber-50 text-amber-700" },
  at_risk: { label: "At risk", className: "border-orange-300 bg-orange-50 text-orange-700" },
  critical: { label: "Ban risk", className: "border-red-300 bg-red-50 text-red-700" },
};

export function WarningBadge({
  count,
  limit,
  level,
}: {
  count: number;
  limit: number;
  level: RiskLevel;
}) {
  const style = LEVELS[level] ?? LEVELS.safe;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold",
        style.className,
      )}
      title="Safety warnings in the last 30 days. The account is paused automatically at the limit."
    >
      <span className="flex gap-0.5" aria-hidden>
        {Array.from({ length: limit }, (_, i) => (
          <span
            key={i}
            className={clsx("h-1.5 w-1.5 rounded-full bg-current", i >= count && "opacity-25")}
          />
        ))}
      </span>
      Warnings {Math.min(count, limit)}/{limit} · {style.label}
    </span>
  );
}
