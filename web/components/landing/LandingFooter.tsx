const COLUMNS = [
  {
    title: "Product",
    links: ["LinkedIn Automation", "AI Appointment Setter", "Cold Email", "Whitelabel", "Pricing"],
  },
  {
    title: "Company",
    links: ["About", "Careers", "Affiliates", "Contact"],
  },
  {
    title: "Resources",
    links: ["Blog", "Help Center", "API Docs", "Status"],
  },
  {
    title: "Legal",
    links: ["Privacy Policy", "Terms of Service", "Security"],
  },
];

const SOCIALS = ["in", "X", "yt"];

export function LandingFooter() {
  return (
    <footer className="bg-ink-950 pt-16 text-slate-400">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-8 sm:p-10">
          <div className="flex flex-col items-start justify-between gap-6 sm:flex-row sm:items-center">
            <div>
              <h3 className="font-display text-xl font-bold text-white">Stay updated with our latest content</h3>
              <p className="mt-1.5 text-[14px] text-slate-400">LinkedIn &amp; email outreach tips, twice a month.</p>
            </div>
            <form className="flex w-full max-w-sm gap-2" onSubmit={(e) => e.preventDefault()}>
              <input
                type="email"
                required
                placeholder="you@company.com"
                className="w-full rounded-full border border-white/15 bg-white/5 px-4 py-2.5 text-[14px] text-white placeholder:text-slate-500 focus:border-brand-400 focus:outline-none"
              />
              <button
                type="submit"
                className="shrink-0 rounded-full bg-brand-600 px-5 py-2.5 text-[13.5px] font-bold text-white hover:bg-brand-700"
              >
                Subscribe
              </button>
            </form>
          </div>
        </div>

        <div className="mt-14 grid grid-cols-2 gap-10 pb-10 sm:grid-cols-4">
          {COLUMNS.map((col) => (
            <div key={col.title}>
              <h4 className="text-[12.5px] font-bold uppercase tracking-wider text-slate-500">{col.title}</h4>
              <ul className="mt-4 flex flex-col gap-2.5">
                {col.links.map((l) => (
                  <li key={l}>
                    <a href="#top" className="text-[13.5px] text-slate-400 hover:text-white">
                      {l}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="flex flex-col items-center justify-between gap-4 border-t border-white/10 py-8 sm:flex-row">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand-600 text-[13px] font-black text-white">
              S
            </span>
            <span className="font-display text-[15px] font-extrabold text-white">SalesBot</span>
          </div>
          <p className="text-[13px] text-slate-500">&copy; {new Date().getFullYear()} SalesBot. All rights reserved.</p>
          <div className="flex items-center gap-3">
            {SOCIALS.map((s) => (
              <span
                key={s}
                className="flex h-8 w-8 items-center justify-center rounded-full border border-white/15 text-[11px] font-bold text-slate-300"
              >
                {s}
              </span>
            ))}
          </div>
        </div>
      </div>
    </footer>
  );
}
