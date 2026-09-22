const ROWS = [
  { name: "Priya Nair", role: "VP Sales, Northwind", state: "Replied", color: "bg-emerald-500" },
  { name: "Marcus Webb", role: "Founder, Loopline", state: "Meeting booked", color: "bg-brand-500" },
  { name: "Elena Ruiz", role: "Head of Growth, Fenwick", state: "Connected", color: "bg-amber-500" },
  { name: "Sam Okafor", role: "CRO, Basalt", state: "Replied", color: "bg-emerald-500" },
];

export function DashboardMock() {
  return (
    <div className="relative rounded-2xl border border-slate-200 bg-white p-2.5 shadow-[0_30px_80px_-30px_rgba(15,23,42,0.35)] sm:p-3">
      <div className="flex items-center gap-1.5 px-2 pb-2.5 pt-1">
        <span className="h-2.5 w-2.5 rounded-full bg-rose-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-amber-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-300" />
        <span className="ml-3 h-6 flex-1 rounded-md bg-slate-100" />
      </div>
      <div className="grid grid-cols-[minmax(0,150px)_1fr] gap-3 rounded-xl bg-slate-50/70 p-3 sm:grid-cols-[170px_1fr]">
        <div className="hidden flex-col gap-1 sm:flex">
          {["Overview", "Campaigns", "Leads", "Inbox", "Sequences", "Team"].map((item, i) => (
            <div
              key={item}
              className={`rounded-lg px-3 py-2 text-[13px] font-medium ${
                i === 1 ? "bg-white text-ink-950 shadow-sm" : "text-slate-500"
              }`}
            >
              {item}
            </div>
          ))}
        </div>
        <div className="rounded-xl bg-white p-3 shadow-sm sm:p-4">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <p className="text-[13px] font-semibold text-ink-950">Q3 Outbound &mdash; Series A SaaS</p>
              <p className="text-[11.5px] text-slate-400">412 leads &middot; running on autopilot</p>
            </div>
            <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-600">
              Active
            </span>
          </div>
          <div className="mb-4 grid grid-cols-3 gap-2">
            {[
              { label: "Sent", value: "3,204" },
              { label: "Reply rate", value: "44.5%" },
              { label: "Booked", value: "58" },
            ].map((s) => (
              <div key={s.label} className="rounded-lg border border-slate-100 bg-slate-50/60 p-2.5">
                <p className="text-[10.5px] font-medium uppercase tracking-wide text-slate-400">{s.label}</p>
                <p className="font-display text-[17px] font-extrabold text-ink-950">{s.value}</p>
              </div>
            ))}
          </div>
          <div className="flex flex-col gap-2">
            {ROWS.map((r) => (
              <div key={r.name} className="flex items-center justify-between rounded-lg border border-slate-100 px-2.5 py-2">
                <div className="flex items-center gap-2.5">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-ink-950 text-[11px] font-bold text-white">
                    {r.name.split(" ").map((n) => n[0]).join("")}
                  </span>
                  <div>
                    <p className="text-[12.5px] font-semibold text-ink-950">{r.name}</p>
                    <p className="text-[11px] text-slate-400">{r.role}</p>
                  </div>
                </div>
                <span className={`flex items-center gap-1.5 text-[11.5px] font-semibold text-slate-500`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${r.color}`} />
                  {r.state}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
