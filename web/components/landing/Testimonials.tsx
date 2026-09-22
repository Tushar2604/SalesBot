const TESTIMONIALS = [
  {
    name: "Alex Gardino",
    role: "Founder, Growthline Agency",
    quote:
      "Response rate went from 5% to 34.5% in 10 days. SalesBot's sequencing is the only reason we hit our Q1 pipeline number.",
    stat: "34.5% response rate",
    initials: "AG",
    color: "bg-rose-400",
  },
  {
    name: "Priya Desai",
    role: "Head of SDR, Fenwick",
    quote:
      "We cut SDR headcount by half and doubled booked meetings. The AI voice notes on LinkedIn feel genuinely personal.",
    stat: "49% response rate",
    initials: "PD",
    color: "bg-brand-400",
  },
  {
    name: "Noah Keller",
    role: "GTM Lead, Basalt Labs",
    quote:
      "Setup took an afternoon. Two weeks later we had more qualified meetings than the previous quarter combined.",
    stat: "2x meetings booked",
    initials: "NK",
    color: "bg-amber-400",
  },
];

export function Testimonials() {
  return (
    <section className="bg-white py-20 sm:py-28">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <h2 className="text-center font-display text-3xl font-extrabold tracking-tight text-ink-950 sm:text-4xl">
          Meet some SalesBot users
        </h2>

        <div className="mt-12 grid gap-6 md:grid-cols-3">
          {TESTIMONIALS.map((t) => (
            <figure
              key={t.name}
              className="flex flex-col rounded-2xl border border-slate-200 bg-slate-50/60 p-7 transition-shadow hover:shadow-lg hover:shadow-slate-200/60"
            >
              <div className="mb-4 flex gap-0.5 text-amber-400">
                {Array.from({ length: 5 }).map((_, i) => (
                  <svg key={i} viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                    <path d="M10 1.5l2.6 5.6 6.1.6-4.6 4.1 1.3 6-5.4-3.1-5.4 3.1 1.3-6-4.6-4.1 6.1-.6z" />
                  </svg>
                ))}
              </div>
              <blockquote className="flex-1 text-[15px] leading-relaxed text-slate-600">
                &ldquo;{t.quote}&rdquo;
              </blockquote>
              <div className="mt-6 flex items-center gap-3 border-t border-slate-200 pt-5">
                <span className={`flex h-10 w-10 items-center justify-center rounded-full text-[13px] font-bold text-white ${t.color}`}>
                  {t.initials}
                </span>
                <div>
                  <figcaption className="text-[14px] font-semibold text-ink-950">{t.name}</figcaption>
                  <p className="text-[12.5px] text-slate-400">{t.role}</p>
                </div>
                <span className="ml-auto rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-bold text-emerald-600">
                  {t.stat}
                </span>
              </div>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}
