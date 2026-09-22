const LEFT = [
  { name: "The Growth Agency", initials: "TG", color: "from-fuchsia-500 to-pink-400" },
  { name: "GrowRevenue Media", initials: "GR", color: "from-sky-600 to-cyan-400" },
  { name: "AI Overlords", initials: "AO", color: "from-slate-900 to-slate-600" },
  { name: "desorbitante", initials: "de", color: "from-ink-950 to-slate-700" },
];

const RIGHT = [
  { name: "IncentAdvisors", initials: "IA", color: "from-ink-950 to-slate-600" },
  { name: "Archway", initials: "Ar", color: "from-indigo-700 to-slate-800" },
  { name: "ROGII", initials: "R", color: "from-orange-500 to-amber-400" },
  { name: "LUNAI", initials: "L", color: "from-orange-500 to-orange-400" },
];

function LogoCard({ name, initials, color }: { name: string; initials: string; color: string }) {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-5">
      <div className={`flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br text-[13px] font-semibold text-white ${color}`}>
        {initials}
      </div>
      <p className="text-center text-[13px] font-medium text-ink-950">{name}</p>
      <a href="#insights" className="rounded-full bg-sky-50 px-3 py-1 text-[12px] font-medium text-sky-600 hover:bg-sky-100">
        Read Story →
      </a>
    </div>
  );
}

export function TrustedBy() {
  return (
    <section className="bg-white py-16 sm:py-20">
      <div className="landing-wrap">
        <h2 className="landing-h2 mx-auto max-w-3xl">
          Trusted by 4100+ innovative B2B sales teams and lead gen agencies
        </h2>

        <div className="mt-12 grid overflow-hidden rounded-[28px] border border-slate-200 md:grid-cols-2">
          <div className="border-b border-slate-200 md:border-b-0 md:border-r">
            <h3 className="px-6 pt-6 text-center text-[18px] font-semibold text-ink-950">Migrated off HeyReach</h3>
            <div className="grid grid-cols-2">
              {LEFT.map((l) => (
                <LogoCard key={l.name} {...l} />
              ))}
            </div>
          </div>
          <div>
            <h3 className="px-6 pt-6 text-center text-[18px] font-semibold text-ink-950">Others</h3>
            <div className="grid grid-cols-2">
              {RIGHT.map((l) => (
                <LogoCard key={l.name} {...l} />
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
