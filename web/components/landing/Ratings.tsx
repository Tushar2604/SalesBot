const PLATFORMS = [
  { name: "G2", score: "4.8", reviews: "310+ reviews", quote: "Innovative features and a responsive team." },
  { name: "AppSumo", score: "4.9", reviews: "520+ reviews", quote: "V2 is an absolute game-changer, totally worth the upgrade." },
  { name: "Capterra", score: "4.7", reviews: "180+ reviews", quote: "Best value for money in LinkedIn automation, hands down." },
];

export function Ratings() {
  return (
    <section id="ratings" className="bg-white py-20 sm:py-28">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="font-display text-3xl font-extrabold tracking-tight text-ink-950 sm:text-4xl">
            Highest rated across G2, AppSumo, and Capterra by real customers
          </h2>
        </div>

        <div className="mt-14 grid gap-6 md:grid-cols-3">
          {PLATFORMS.map((p) => (
            <div key={p.name} className="rounded-2xl border border-slate-200 bg-slate-50/60 p-7">
              <div className="flex items-center justify-between">
                <span className="font-display text-lg font-extrabold text-ink-950">{p.name}</span>
                <div className="flex gap-0.5 text-amber-400">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <svg key={i} viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                      <path d="M10 1.5l2.6 5.6 6.1.6-4.6 4.1 1.3 6-5.4-3.1-5.4 3.1 1.3-6-4.6-4.1 6.1-.6z" />
                    </svg>
                  ))}
                </div>
              </div>
              <p className="mt-1 text-[13px] text-slate-400">
                {p.score} / 5 &middot; {p.reviews}
              </p>
              <p className="mt-4 text-[15px] italic leading-relaxed text-slate-700">&ldquo;{p.quote}&rdquo;</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
