import Link from "next/link";
import { DashboardMock } from "./mock/DashboardMock";

const AVATARS = [
  { initials: "AT", color: "bg-rose-400" },
  { initials: "JK", color: "bg-amber-400" },
  { initials: "CD", color: "bg-sky-400" },
  { initials: "AG", color: "bg-violet-400" },
];

export function Hero() {
  return (
    <section id="top" className="relative overflow-hidden bg-gradient-to-b from-[#d7ecff] via-[#eaf3ff] to-white">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-white/70 to-transparent"
      />

      <div className="landing-wrap relative grid items-center gap-10 pb-16 pt-10 lg:grid-cols-[1.05fr_0.95fr] lg:gap-8 lg:pb-20 lg:pt-14">
        <div className="max-w-xl">
          <h1 className="text-[36px] font-semibold leading-[1.15] tracking-tight text-ink-950 sm:text-[48px] sm:leading-[56px]">
            Message 100s of people on LinkedIn and cold email. Every Week. Automatically.
          </h1>
          <p className="mt-5 text-[16px] leading-relaxed text-slate-600 sm:text-[18px]">
            Join the SalesBot family of 4100+ users and 28 employees
          </p>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <div className="flex -space-x-2">
              {AVATARS.map((a) => (
                <span
                  key={a.initials}
                  className={`flex h-9 w-9 items-center justify-center rounded-full border-2 border-white text-[11px] font-semibold text-white ${a.color}`}
                >
                  {a.initials}
                </span>
              ))}
            </div>
            <div className="text-[13px] text-slate-600">
              <div className="flex items-center gap-1 text-amber-400">
                {Array.from({ length: 5 }).map((_, i) => (
                  <svg key={i} viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5">
                    <path d="M10 1.5l2.6 5.6 6.1.6-4.6 4.1 1.3 6-5.4-3.1-5.4 3.1 1.3-6-4.6-4.1 6.1-.6z" />
                  </svg>
                ))}
              </div>
              <p>
                Rated 4.8 on <span className="font-semibold text-[#ff492c]">G</span> from 57+ reviews
              </p>
            </div>
          </div>

          <div className="mt-8 flex flex-col items-stretch gap-3 sm:flex-row sm:items-center">
            <Link href="/signup" className="btn-navy h-12 px-6 text-[18px] font-medium">
              Free Trial (14 days)
              <span aria-hidden>→</span>
            </Link>
            <a href="#cta" className="btn-outline h-12 px-6 text-[18px] font-medium">
              Book a demo
              <span aria-hidden>→</span>
            </a>
          </div>
          <p className="mt-3 text-[13px] italic text-slate-500">No credit card required</p>
        </div>

        <div className="relative lg:translate-x-6">
          <DashboardMock />
        </div>
      </div>
    </section>
  );
}
