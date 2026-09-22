const POSTS = [
  {
    tag: "LinkedIn",
    title: "How to find clients on LinkedIn (5 different ways)",
    read: "6 min read",
    color: "from-brand-400 to-brand-600",
  },
  {
    tag: "Bots & Automation",
    title: "LinkedIn bots we used: Pricing for 2026",
    read: "8 min read",
    color: "from-rose-400 to-rose-600",
  },
  {
    tag: "Strategy",
    title: "Manage multiple LinkedIn accounts without banned",
    read: "5 min read",
    color: "from-amber-400 to-amber-600",
  },
];

export function Insights() {
  return (
    <section id="insights" className="bg-white py-20 sm:py-28">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <div className="flex items-end justify-between">
          <h2 className="font-display text-3xl font-extrabold tracking-tight text-ink-950 sm:text-4xl">
            Thoughts &amp; insights
          </h2>
          <a href="#insights" className="hidden text-[14px] font-bold text-brand-600 hover:text-brand-700 sm:inline-flex">
            Read all blogs &rarr;
          </a>
        </div>

        <div className="mt-10 grid gap-6 md:grid-cols-3">
          {POSTS.map((p) => (
            <a
              key={p.title}
              href="#insights"
              className="group overflow-hidden rounded-2xl border border-slate-200 bg-white transition-shadow hover:shadow-lg hover:shadow-slate-200/60"
            >
              <div className={`flex h-40 items-center justify-center bg-gradient-to-br ${p.color}`}>
                <span className="font-display text-3xl font-black text-white/90">SR</span>
              </div>
              <div className="p-6">
                <span className="text-[12px] font-bold uppercase tracking-wide text-brand-600">{p.tag}</span>
                <h3 className="mt-2 font-display text-[17px] font-bold leading-snug tracking-tight text-ink-950 group-hover:text-brand-600">
                  {p.title}
                </h3>
                <p className="mt-3 text-[12.5px] font-medium text-slate-400">{p.read}</p>
              </div>
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}
