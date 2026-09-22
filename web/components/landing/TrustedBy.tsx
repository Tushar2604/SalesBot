const LOGOS = ["HeyReach", "dux-soup", "ROGII", "Archray", "Meetric", "Fenwick", "Loopline", "Basalt"];

export function TrustedBy() {
  return (
    <section className="border-y border-slate-100 bg-white py-10">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <p className="text-center text-[13px] font-semibold uppercase tracking-wider text-slate-400">
          Trusted by 4,100+ innovative B2B sales teams and lead-gen agencies
        </p>
        <div className="mt-7 flex flex-wrap items-center justify-center gap-x-10 gap-y-5 opacity-70 grayscale sm:gap-x-14">
          {LOGOS.map((name) => (
            <span key={name} className="font-display text-lg font-extrabold tracking-tight text-slate-400">
              {name}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
