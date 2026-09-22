import Link from "next/link";

const AVATARS = ["bg-rose-400", "bg-brand-400", "bg-amber-400", "bg-emerald-400", "bg-violet-400"];

export function FinalCta() {
  return (
    <section id="cta" className="relative overflow-hidden bg-ink-950 py-20 text-white sm:py-28">
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-40 left-1/2 h-[420px] w-[800px] -translate-x-1/2 rounded-full bg-brand-600/30 blur-3xl"
      />
      <div className="relative mx-auto max-w-3xl px-5 text-center sm:px-8">
        <div className="mx-auto mb-6 flex w-fit -space-x-2">
          {AVATARS.map((c, i) => (
            <span key={i} className={`h-9 w-9 rounded-full border-2 border-ink-950 ${c}`} />
          ))}
        </div>
        <h2 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
          What are you waiting for?
        </h2>
        <p className="mt-3 text-lg text-slate-300">Start reaching out to your next customer today.</p>
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Link
            href="/signup"
            className="w-full rounded-full bg-brand-600 px-7 py-3.5 text-center text-[15px] font-bold text-white shadow-lg shadow-brand-600/30 transition-transform hover:-translate-y-0.5 hover:bg-brand-700 sm:w-auto"
          >
            Free Trial (14 days)
          </Link>
          <a
            href="#top"
            className="w-full rounded-full border border-white/20 px-7 py-3.5 text-center text-[15px] font-bold text-white transition-transform hover:-translate-y-0.5 hover:border-white/40 sm:w-auto"
          >
            Book a demo
          </a>
        </div>
      </div>
    </section>
  );
}
