const ITEMS = [
  {
    title: "Safest LinkedIn Automation tool on the market",
    body: "SalesBot uses LinkedIn mobile app APIs on the backend which reduces LinkedIn Account ban risk to 0.00001% (we did the math)",
    accent: "from-sky-100 to-white",
    icon: "🛡",
  },
  {
    title: "AI Appointment setter (add-on)",
    body: "No other tool on the market nurtures leads, and keeps them engaged on LinkedIn until they are ready to book a meeting with you",
    accent: "from-violet-100 to-white",
    icon: "🤖",
  },
  {
    title: "No other tool allows you to send AI personalized voice notes and videos on LinkedIn",
    body: "SalesBot allows you to send AI personalized voice notes and video messages on LinkedIn. Customers get 40%+ reply rates",
    accent: "from-fuchsia-100 to-white",
    icon: "🎙",
  },
];

export function WhyUse() {
  return (
    <section id="why" className="bg-white py-16 sm:py-24">
      <div className="landing-wrap">
        <h2 className="landing-h2">Why use SalesBot?</h2>
        <div className="mt-12 grid gap-6 md:grid-cols-3">
          {ITEMS.map((item) => (
            <article key={item.title} className={`rounded-[24px] border border-slate-100 bg-gradient-to-b p-6 shadow-sm ${item.accent}`}>
              <div className="mb-8 flex h-40 items-center justify-center rounded-2xl bg-white/70 text-5xl shadow-inner">
                <span aria-hidden>{item.icon}</span>
              </div>
              <h3 className="text-[18px] font-semibold leading-snug text-ink-950">{item.title}</h3>
              <p className="mt-3 text-[14px] leading-relaxed text-slate-600">{item.body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
