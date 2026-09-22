const REVIEWS = [
  {
    source: "G2",
    title: "Intuitive UI and Time-Saving Automation",
    body: "SalesBot’s intuitive UI makes launching campaigns effortless, while its smart automation and AI reply management save hours of manual work.",
    author: "Giorgos G. · Founder",
  },
  {
    source: "G2",
    title: "Innovative Features and Responsive Team",
    body: "I really like SalesBot’s responsive demo team and AI features. It delivers great value, handles most workloads, and helped us gain 95 customers in three months.",
    author: "Flora R.",
  },
  {
    source: "AppSumo",
    title: "V2 is an absolute game-changer (Totally worth the upgrade!)",
    body: "SalesBot is one of my best investments, with V2 features like voice notes, video, and an AI appointment setter that takes over conversations and books meetings on autopilot.",
    author: "megatester",
  },
  {
    source: "G2",
    title: "Revolutionized Our LinkedIn Outreach",
    body: "SalesBot handles LinkedIn outreach effortlessly with AI follow-ups and easy setup. It keeps conversations on track, and the team provides quick, reliable support.",
    author: "Tiffany S.",
  },
  {
    source: "Capterra",
    title: "SalesBot is great",
    body: "SalesBot is great, with unique features its competitors don’t offer. After 6–12 months of use, it stands out as a reliable and effective outreach tool.",
    author: "Tom · Business Development",
  },
  {
    source: "G2",
    title: "Lifesaving outbound campaign!",
    body: "SalesBot has been a lifesaver for our outbound, automating LinkedIn and email outreach while we focus on building. It works like a full-time SDR and keeps leads coming in.",
    author: "Delaney T. · Founder",
  },
];

export function Ratings() {
  return (
    <section id="ratings" className="bg-white py-16 sm:py-24">
      <div className="landing-wrap">
        <h2 className="landing-h2 mx-auto max-w-3xl">
          Highest Rated Across G2, AppSumo, and Capterra by Real Customers
        </h2>
        <div className="mt-12 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {REVIEWS.map((r) => (
            <article key={r.title} className="rounded-[22px] border border-slate-200 bg-[#f7f9fc] p-6">
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-semibold uppercase tracking-wider text-slate-400">{r.source}</span>
                <div className="flex gap-0.5 text-amber-400">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <svg key={i} viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5">
                      <path d="M10 1.5l2.6 5.6 6.1.6-4.6 4.1 1.3 6-5.4-3.1-5.4 3.1 1.3-6-4.6-4.1 6.1-.6z" />
                    </svg>
                  ))}
                </div>
              </div>
              <h3 className="mt-3 text-[16px] font-semibold leading-snug text-ink-950">“{r.title}”</h3>
              <p className="mt-3 text-[14px] leading-relaxed text-slate-600">{r.body}</p>
              <p className="mt-4 text-[12.5px] font-medium text-slate-400">{r.author}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
