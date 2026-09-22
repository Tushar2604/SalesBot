const STORIES = [
  {
    stat: "65% response rate | $1mln+ in funding raised",
    quote:
      "We reached out to 400 busy agency owners and received 148 replies—a 65% response rate. SalesBot makes your messages feel human and personal and people actually respond!",
    rate: "65% reply rate",
    tint: "from-fuchsia-200 via-pink-100 to-rose-50",
    banner: "from-[#7c3aed] to-[#fb7185]",
  },
  {
    stat: "57% response rate | 5-10 quality leads per month",
    quote: "I have about 20 different campaigns with SalesBot. I like to try a lot of things, a ton of A/B testing.",
    rate: "57% reply rate",
    tint: "from-sky-100 via-indigo-50 to-white",
    banner: "from-[#2563eb] to-[#38bdf8]",
  },
  {
    stat: "37% response rate | 20+ lead magnet asks per month",
    quote: "SalesBot does have built-in proxy protection, so my LinkedIn campaigns don't get flagged, which is really good.",
    rate: "37% reply rate",
    tint: "from-violet-100 via-fuchsia-50 to-white",
    banner: "from-[#7c3aed] to-[#c084fc]",
  },
  {
    stat: "41% response rate | 36 replies per month",
    quote: "We included a lot of follow up in SalesBot. This was a nine or ten message sequence that kept us top of mind.",
    rate: "41% reply rate",
    tint: "from-amber-50 via-orange-50 to-white",
    banner: "from-[#f59e0b] to-[#fb7185]",
  },
  {
    stat: "48% response rate | 10+ leads per month",
    quote: "SalesBot is not a selling tool, it is a conversation starting tool.",
    rate: "48% reply rate",
    tint: "from-emerald-50 via-teal-50 to-white",
    banner: "from-[#0d9488] to-[#34d399]",
  },
  {
    stat: "54.5% acceptance rate | 40% response rate",
    quote:
      "What worked exceptionally well was connecting SalesBot campaigns to a landing page with a video sales letter that helped bridge the gap.",
    rate: "54.5% accept rate",
    tint: "from-sky-50 via-cyan-50 to-white",
    banner: "from-[#0284c7] to-[#67e8f9]",
  },
];

export function Testimonials() {
  return (
    <section className="bg-white pb-8 pt-4 sm:pb-12">
      <div className="landing-wrap">
        <h2 className="landing-h2">Meet some SalesBot users</h2>
        <div className="mt-10 flex gap-5 overflow-x-auto pb-4 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {STORIES.map((s) => (
            <article
              key={s.stat}
              className={`w-[320px] shrink-0 rounded-[24px] bg-gradient-to-b p-3 ${s.tint} sm:w-[360px]`}
            >
              <div className={`relative overflow-hidden rounded-[18px] bg-gradient-to-br p-5 text-white ${s.banner}`}>
                <p className="text-[13px] font-medium opacity-90">SalesBot Customer of the Week</p>
                <p className="mt-8 text-[28px] font-semibold leading-tight">{s.rate}</p>
              </div>
              <h3 className="mt-4 px-2 text-[16px] font-semibold leading-snug text-ink-950">{s.stat}</h3>
              <p className="mt-3 px-2 pb-3 text-[14px] leading-relaxed text-slate-600">“{s.quote}”</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
