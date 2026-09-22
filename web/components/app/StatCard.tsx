const COLORS: Record<string, string> = {
  cyan: "from-cyan-400 to-brand-500",
  rose: "from-rose-400 to-pink-500",
  emerald: "from-emerald-400 to-teal-500",
  violet: "from-violet-400 to-fuchsia-500",
};

export function StatCard({ label, value, tone }: { label: string; value: number | string; tone: keyof typeof COLORS }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-4">
      <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${COLORS[tone]}`}>
        <span className="h-4 w-4 rounded-[3px] bg-white/90" />
      </span>
      <div className="min-w-0">
        <p className="truncate text-[12.5px] font-medium text-slate-500">{label}</p>
        <p className="font-display text-xl font-extrabold text-ink-950">{value}</p>
      </div>
    </div>
  );
}
