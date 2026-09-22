const STEPS = [
  "Add linkedin account",
  "Create campaign",
  "Details",
  "Add profiles",
  "Review",
  "Configure",
  "Import",
  "Start campaign",
  "Configure settings",
];

const NODES = [
  { x: "8%", y: "18%", name: "Ava Chen", role: "VP Sales" },
  { x: "72%", y: "10%", name: "Marcus W.", role: "Founder" },
  { x: "6%", y: "62%", name: "Elena R.", role: "Head of Growth" },
  { x: "70%", y: "68%", name: "Sam Okafor", role: "CRO" },
];

export function DashboardMock() {
  return (
    <div className="relative overflow-hidden rounded-[28px] border border-white/70 bg-white/80 shadow-hero backdrop-blur">
      <div className="flex items-center gap-6 border-b border-slate-100 px-5 py-3">
        <span className="text-[13px] font-semibold text-ink-950">Campaign</span>
        <span className="text-[13px] font-medium text-slate-400">Sequence</span>
      </div>
      <div className="grid min-h-[420px] grid-cols-1 md:grid-cols-[210px_1fr]">
        <aside className="hidden border-r border-slate-100 p-4 md:block">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Setup</p>
          <ol className="flex flex-col gap-1">
            {STEPS.map((step, i) => (
              <li
                key={step}
                className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-[12.5px] ${
                  i === 1 ? "bg-slate-50 font-semibold text-ink-950" : "text-slate-500"
                }`}
              >
                <span
                  className={`flex h-4 w-4 items-center justify-center rounded-full text-[9px] ${
                    i < 2 ? "bg-robot text-ink-950" : "border border-slate-200 text-slate-400"
                  }`}
                >
                  {i < 2 ? "✓" : i + 1}
                </span>
                {step}
              </li>
            ))}
          </ol>
        </aside>

        <div className="relative overflow-hidden bg-gradient-to-br from-[#eef7ff] via-white to-[#f6efff] p-6">
          <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
            <path d="M90 90 C 180 70, 240 140, 250 190" fill="none" stroke="#c7d6ea" strokeWidth="2" strokeDasharray="4 6" />
            <path d="M90 250 C 160 220, 210 210, 250 190" fill="none" stroke="#c7d6ea" strokeWidth="2" strokeDasharray="4 6" />
            <path d="M410 80 C 330 90, 290 140, 250 190" fill="none" stroke="#c7d6ea" strokeWidth="2" strokeDasharray="4 6" />
            <path d="M410 270 C 330 250, 290 220, 250 190" fill="none" stroke="#c7d6ea" strokeWidth="2" strokeDasharray="4 6" />
          </svg>

          {NODES.map((n) => (
            <div
              key={n.name}
              className="absolute flex items-center gap-2 rounded-full border border-white bg-white px-2 py-1.5 shadow-sm"
              style={{ left: n.x, top: n.y }}
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-ink-950 text-[11px] font-semibold text-white">
                {n.name
                  .split(" ")
                  .map((p) => p[0])
                  .join("")}
              </span>
              <span className="pr-2">
                <span className="block text-[11.5px] font-semibold leading-tight text-ink-950">{n.name}</span>
                <span className="block text-[10px] text-slate-400">{n.role}</span>
              </span>
            </div>
          ))}

          <div className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-3">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-white shadow-card ring-4 ring-white">
              <svg viewBox="0 0 40 40" className="h-10 w-10" aria-hidden>
                <circle cx="11" cy="5" r="2.3" fill="#3BDCFF" />
                <circle cx="29" cy="5" r="2.3" fill="#3BDCFF" />
                <path d="M11 7v5.2M29 7v5.2" stroke="#3BDCFF" strokeWidth="2.2" strokeLinecap="round" />
                <rect x="4" y="12.5" width="32" height="23.5" rx="11.5" fill="#3BDCFF" />
                <circle cx="14.8" cy="24.2" r="3.15" fill="#0f172a" />
                <circle cx="25.2" cy="24.2" r="3.15" fill="#0f172a" />
              </svg>
            </div>
            <div className="flex gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#0a66c2] text-[11px] font-bold text-white">
                in
              </span>
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-amber-400 text-[11px] font-bold text-white">
                @
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
