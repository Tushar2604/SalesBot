"use client";

import { useState } from "react";
import type { DailySeries } from "@/lib/outreach-api";

const COLORS = ["#3b82f6", "#f43f5e", "#10b981", "#8b5cf6", "#f59e0b", "#64748b"];

function shortDay(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: "2-digit", month: "short" });
}

/** Inline-SVG multi-line chart — no charting dependency needed for a handful of short series. */
export function TimelineChart({ days, series }: { days: string[]; series: DailySeries[] }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const visible = series.filter((s) => !hidden.has(s.key));

  const width = 640;
  const height = 220;
  const padding = { top: 12, right: 12, bottom: 28, left: 28 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;

  const max = Math.max(1, ...visible.flatMap((s) => s.counts));
  const stepX = days.length > 1 ? innerW / (days.length - 1) : 0;

  function points(counts: number[]): string {
    return counts
      .map((v, i) => {
        const x = padding.left + i * stepX;
        const y = padding.top + innerH - (v / max) * innerH;
        return `${x},${y}`;
      })
      .join(" ");
  }

  function toggle(key: string) {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Activity over time">
        {[0, 0.5, 1].map((frac) => (
          <line
            key={frac}
            x1={padding.left}
            x2={width - padding.right}
            y1={padding.top + innerH * frac}
            y2={padding.top + innerH * frac}
            stroke="#e2e8f0"
            strokeWidth={1}
          />
        ))}
        {days.map((d, i) => (
          <text
            key={d}
            x={padding.left + i * stepX}
            y={height - 6}
            textAnchor="middle"
            className="fill-slate-400"
            fontSize={10}
          >
            {shortDay(d)}
          </text>
        ))}
        {series.map((s, i) =>
          hidden.has(s.key) ? null : (
            <polyline
              key={s.key}
              points={points(s.counts)}
              fill="none"
              stroke={COLORS[i % COLORS.length]}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ),
        )}
      </svg>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {series.map((s, i) => (
          <button
            key={s.key}
            onClick={() => toggle(s.key)}
            className={`flex items-center gap-1.5 text-[11.5px] font-medium ${hidden.has(s.key) ? "text-slate-300" : "text-slate-600"}`}
          >
            <span className="h-2 w-2 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
            {s.label}
          </button>
        ))}
      </div>
    </div>
  );
}
