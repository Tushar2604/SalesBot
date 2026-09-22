const ROWS = [
  { feature: "Unlimited LinkedIn accounts", us: true, them: false },
  { feature: "AI voice & video notes", us: true, them: false },
  { feature: "Built-in AI appointment setter", us: true, them: false },
  { feature: "Unlimited cold email sending", us: true, them: false },
  { feature: "Whitelabel / agency mode", us: true, them: false },
  { feature: "24/7 human support", us: true, them: true },
];

const OTHERS = ["Waalaxy", "Expandi", "Lemlist", "Zopto"];

export function Comparison() {
  return (
    <section className="bg-slate-50/70 py-20 sm:py-28">
      <div className="mx-auto max-w-5xl px-5 sm:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-[13px] font-bold uppercase tracking-wider text-brand-600">Comparison</p>
          <h2 className="mt-3 font-display text-3xl font-extrabold tracking-tight text-ink-950 sm:text-4xl">
            See how SalesBot stacks up against others
          </h2>
          <p className="mt-3 text-[15px] text-slate-500">Compared against {OTHERS.join(", ")}, and more.</p>
        </div>

        <div className="mt-12 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-200">
                <th className="px-6 py-4 text-[13px] font-semibold text-slate-500">Feature</th>
                <th className="px-6 py-4 text-center text-[13.5px] font-bold text-brand-600">SalesBot</th>
                <th className="px-6 py-4 text-center text-[13px] font-semibold text-slate-400">Others</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((r, i) => (
                <tr key={r.feature} className={i !== ROWS.length - 1 ? "border-b border-slate-100" : ""}>
                  <td className="px-6 py-4 text-[14px] font-medium text-ink-950">{r.feature}</td>
                  <td className="px-6 py-4 text-center">
                    <Check ok={r.us} />
                  </td>
                  <td className="px-6 py-4 text-center">
                    <Check ok={r.them} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function Check({ ok }: { ok: boolean }) {
  if (ok) {
    return (
      <svg viewBox="0 0 20 20" fill="none" className="mx-auto h-5 w-5 text-emerald-500">
        <circle cx="10" cy="10" r="10" fill="currentColor" opacity="0.12" />
        <path d="M6 10.5l2.5 2.5 5.5-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 20 20" fill="none" className="mx-auto h-5 w-5 text-slate-300">
      <circle cx="10" cy="10" r="10" fill="currentColor" opacity="0.15" />
      <path d="M7 7l6 6M13 7l-6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
