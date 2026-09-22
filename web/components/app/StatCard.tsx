const PASTELS: Record<string, string> = {
  cyan: "bg-[#e8f7ff] text-[#0ea5e9]",
  rose: "bg-[#ffe8ee] text-[#f43f5e]",
  emerald: "bg-[#e8fbf3] text-[#10b981]",
  violet: "bg-[#eee8ff] text-[#7c6bff]",
};

export function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone: keyof typeof PASTELS;
}) {
  return (
    <div className={`flex items-center gap-3 rounded-2xl px-4 py-4 ${PASTELS[tone]}`}>
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/80">
        <span className="h-4 w-4 rounded-[3px] bg-current opacity-70" />
      </span>
      <div className="min-w-0">
        <p className="truncate text-[12.5px] font-medium text-slate-500">{label}</p>
        <p className="text-xl font-semibold text-ink-950">{value}</p>
      </div>
    </div>
  );
}
