const ROWS = [
  { label: "Total campaigns", value: "250", delta: "1%" },
  { label: "Prospects reached", value: "70", delta: "7%" },
  { label: "New connections", value: "134", delta: "3%" },
];

export function AuthPreview() {
  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-ink-950 shadow-2xl">
      <div className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
        <span className="h-6 w-6 rounded-md bg-brand-500" />
        <span className="text-[13px] font-bold text-white">SalesBot</span>
      </div>
      <div className="grid grid-cols-[130px_1fr]">
        <div className="hidden flex-col gap-3 border-r border-white/10 p-4 sm:flex">
          <div>
            <p className="text-[9.5px] font-bold uppercase tracking-wider text-slate-500">Account</p>
            <div className="mt-2 flex items-center gap-2 rounded-lg bg-white/5 px-2 py-1.5">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-violet-500 text-[9px] font-bold text-white">
                SG
              </span>
              <span>
                <span className="block text-[11px] font-semibold text-white">Saurav Gupta</span>
                <span className="block text-[9.5px] font-medium text-emerald-400">Connected</span>
              </span>
            </div>
          </div>
          <div>
            <p className="text-[9.5px] font-bold uppercase tracking-wider text-slate-500">Menu</p>
            <div className="mt-2 flex flex-col gap-1">
              {["Dashboard", "Campaigns", "Inbox", "Accounts", "Settings", "Sales Console"].map((item, i) => (
                <span
                  key={item}
                  className={`rounded-md px-2 py-1.5 text-[11px] font-medium ${
                    i === 0 ? "bg-white text-ink-950" : "text-slate-400"
                  }`}
                >
                  {item}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="bg-white p-4">
          <p className="text-[11px] font-medium text-slate-400">Dashboard</p>
          <p className="mt-1 font-display text-[15px] font-extrabold text-ink-950">Getting started guide</p>
          <div className="mt-2 flex gap-1">
            {[0, 1, 2, 3].map((i) => (
              <span key={i} className={`h-1 flex-1 rounded-full ${i === 0 ? "bg-brand-600" : "bg-slate-200"}`} />
            ))}
          </div>
          <p className="mt-3 text-[11px] font-semibold text-ink-950">Step 1: Add LinkedIn account</p>
          <span className="mt-2 inline-flex items-center rounded-md bg-brand-600 px-2.5 py-1.5 text-[10.5px] font-bold text-white">
            Add account &rarr;
          </span>

          <p className="mt-4 text-[11px] font-bold text-ink-950">Performance Report</p>
          <div className="mt-2 grid grid-cols-3 gap-1.5">
            {ROWS.map((r) => (
              <div key={r.label} className="rounded-md border border-slate-100 bg-slate-50 p-1.5">
                <p className="truncate text-[8.5px] font-medium text-slate-400">{r.label}</p>
                <p className="text-[12px] font-extrabold text-ink-950">{r.value}</p>
                <span className="text-[8.5px] font-semibold text-emerald-500">&uarr; {r.delta}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
