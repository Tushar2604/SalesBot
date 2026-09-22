const POSTS = [
  {
    title: "25 LinkedIn Connection Messages That Get Accepted",
    date: "September 18, 2026",
    color: "from-sky-400 to-indigo-500",
  },
  {
    title: "Best LinkedIn Automation for SaaS: 10 Tools That Actually Work",
    date: "September 18, 2026",
    color: "from-violet-400 to-fuchsia-500",
  },
  {
    title: "Waalaxy Review 2026: Pricing, Features & Verdict",
    date: "September 18, 2026",
    color: "from-amber-400 to-orange-500",
  },
];

export function Insights() {
  return (
    <section id="insights" className="bg-white py-16 sm:py-24">
      <div className="landing-wrap">
        <div className="flex items-end justify-between">
          <h2 className="text-[28px] font-semibold tracking-tight text-ink-950 sm:text-[36px]">Thoughts &amp; Insights</h2>
          <a href="#insights" className="hidden text-[14px] font-semibold text-sky-600 hover:text-sky-700 sm:inline-flex">
            Read all blogs
          </a>
        </div>
        <div className="mt-10 grid gap-6 md:grid-cols-3">
          {POSTS.map((p) => (
            <a
              key={p.title}
              href="#insights"
              className="group overflow-hidden rounded-[22px] border border-slate-200 bg-white transition-shadow hover:shadow-card"
            >
              <div className={`h-40 bg-gradient-to-br ${p.color}`} />
              <div className="p-5">
                <h3 className="text-[16px] font-semibold leading-snug text-ink-950 group-hover:text-sky-700">{p.title}</h3>
                <p className="mt-3 text-[12.5px] text-slate-400">{p.date}</p>
              </div>
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}
