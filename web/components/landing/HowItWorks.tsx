const STEPS = [
  {
    n: "1",
    title: "Import leads",
    body: "Pull leads straight from LinkedIn search, Sales Navigator, or upload your own CSV list in seconds.",
  },
  {
    n: "2",
    title: "Write your message once",
    body: "Craft a compelling sequence with personalization tokens, voice notes, and follow-ups &mdash; SalesBot handles the rest.",
  },
  {
    n: "3",
    title: "Sit back on autopilot",
    body: "Your accounts message, connect, and follow up automatically. You just show up for the replies.",
  },
];

export function HowItWorks() {
  return (
    <section className="bg-ink-950 py-20 text-white sm:py-28">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-[13px] font-bold uppercase tracking-wider text-brand-400">Getting started</p>
          <h2 className="mt-3 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
            It&rsquo;s as easy as
          </h2>
        </div>

        <div className="relative mt-16 grid gap-10 md:grid-cols-3 md:gap-8">
          <div
            aria-hidden
            className="absolute left-0 right-0 top-7 hidden h-px bg-gradient-to-r from-transparent via-white/15 to-transparent md:block"
          />
          {STEPS.map((s) => (
            <div key={s.n} className="relative flex flex-col items-center text-center md:items-start md:text-left">
              <span className="relative z-10 flex h-14 w-14 items-center justify-center rounded-full bg-brand-500 font-display text-xl font-extrabold shadow-lg shadow-brand-500/30">
                {s.n}
              </span>
              <h3 className="mt-5 font-display text-xl font-bold tracking-tight">{s.title}</h3>
              <p className="mt-2.5 text-[14.5px] leading-relaxed text-slate-400">{s.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
