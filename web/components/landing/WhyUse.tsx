const ITEMS = [
  {
    tag: "01",
    title: "The smartest LinkedIn automation tool on the market",
    body: "Smart limits, human-like delays, and rotating engagement patterns keep every account warm while you scale outreach volume safely.",
    bullets: ["Safe daily action limits", "Dedicated IP per account", "Auto-warmup for new accounts"],
    align: "left" as const,
  },
  {
    tag: "02",
    title: "AI Appointment Setter, built in",
    body: "Let AI qualify, handle objections, and book meetings straight onto your calendar &mdash; in your voice, around the clock.",
    bullets: ["Objection handling out of the box", "Auto-books to your calendar", "Learns from your best reps"],
    align: "right" as const,
  },
  {
    tag: "03",
    title: "The only tool that sends AI voice and video notes on LinkedIn",
    body: "Stand out in a crowded inbox with personalized voice notes and video messages generated automatically for every lead.",
    bullets: ["Cloned voice, real personalization", "Auto-generated video intros", "3x higher reply rates"],
    align: "left" as const,
  },
];

export function WhyUse() {
  return (
    <section className="bg-slate-50/70 py-20 sm:py-28">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-[13px] font-bold uppercase tracking-wider text-brand-600">Why use SalesBot?</p>
          <h2 className="mt-3 font-display text-3xl font-extrabold tracking-tight text-ink-950 sm:text-4xl">
            Built for teams who live and die by pipeline
          </h2>
        </div>

        <div className="mt-16 flex flex-col gap-16">
          {ITEMS.map((item) => (
            <div
              key={item.tag}
              className={`grid items-center gap-10 lg:grid-cols-2 lg:gap-16 ${
                item.align === "right" ? "lg:[&>*:first-child]:order-2" : ""
              }`}
            >
              <div>
                <span className="font-display text-5xl font-black text-brand-200">{item.tag}</span>
                <h3 className="mt-3 font-display text-2xl font-bold tracking-tight text-ink-950 sm:text-[1.7rem]">
                  {item.title}
                </h3>
                <p className="mt-4 text-[15.5px] leading-relaxed text-slate-600">{item.body}</p>
                <ul className="mt-6 flex flex-col gap-2.5">
                  {item.bullets.map((b) => (
                    <li key={b} className="flex items-center gap-2.5 text-[14.5px] font-medium text-ink-950">
                      <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5 shrink-0 text-brand-600">
                        <circle cx="10" cy="10" r="10" fill="currentColor" opacity="0.12" />
                        <path d="M6 10.5l2.5 2.5 5.5-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      {b}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="aspect-[4/3] rounded-2xl border border-slate-200 bg-gradient-to-br from-white to-brand-50 p-6 shadow-sm">
                <div className="flex h-full w-full flex-col justify-between rounded-xl border border-slate-100 bg-white/70 p-5">
                  <div className="flex items-center justify-between">
                    <span className="h-2.5 w-16 rounded-full bg-slate-200" />
                    <span className="h-6 w-6 rounded-full bg-brand-100" />
                  </div>
                  <div className="space-y-2">
                    <div className="h-2.5 w-3/4 rounded-full bg-slate-200" />
                    <div className="h-2.5 w-1/2 rounded-full bg-slate-100" />
                  </div>
                  <div className="flex items-end gap-2">
                    {[40, 70, 55, 90, 65].map((h, i) => (
                      <span
                        key={i}
                        style={{ height: `${h}%` }}
                        className="w-full rounded-t-md bg-gradient-to-t from-brand-400 to-brand-200"
                      />
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
