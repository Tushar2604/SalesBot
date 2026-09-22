import Link from "next/link";
import { DashboardMock } from "./mock/DashboardMock";

export function Hero() {
  return (
    <section id="top" className="relative overflow-hidden bg-gradient-to-b from-brand-50 via-white to-white">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-32 left-1/2 h-[520px] w-[900px] -translate-x-1/2 rounded-full bg-brand-200/40 blur-3xl"
      />
      <div className="relative mx-auto max-w-7xl px-5 pb-16 pt-14 sm:px-8 sm:pt-20 lg:pb-24 lg:pt-24">
        <div className="mx-auto max-w-4xl text-center">
          <div className="mx-auto mb-6 flex w-fit items-center gap-2 rounded-full border border-brand-200 bg-white/80 px-4 py-1.5 text-[13px] font-semibold text-brand-700 shadow-sm">
            <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />
            AI Sales &amp; GTM Automation
          </div>

          <h1 className="font-display text-[2.5rem] font-extrabold leading-[1.08] tracking-tight text-ink-950 sm:text-6xl lg:text-[4rem]">
            Message 100s of people on LinkedIn
            <br className="hidden sm:block" /> and cold email.{" "}
            <span className="relative whitespace-nowrap text-brand-600">
              Every week.
              <svg
                aria-hidden
                viewBox="0 0 300 12"
                className="absolute -bottom-1 left-0 h-3 w-full text-brand-300"
                preserveAspectRatio="none"
              >
                <path d="M2 9 C 80 2, 220 2, 298 9" stroke="currentColor" strokeWidth="5" fill="none" strokeLinecap="round" />
              </svg>
            </span>{" "}
            Automatically.
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-[17px] leading-relaxed text-slate-600 sm:text-lg">
            Join the SalesBot family of 4,100+ users and lead-gen agencies who fill their pipeline
            on LinkedIn and email without lifting a finger.
          </p>

          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href="/signup"
              className="w-full rounded-full bg-brand-600 px-7 py-3.5 text-center text-[15px] font-bold text-white shadow-lg shadow-brand-600/25 transition-transform hover:-translate-y-0.5 hover:bg-brand-700 sm:w-auto"
            >
              Free Trial (14 days)
            </Link>
            <a
              href="#cta"
              className="w-full rounded-full border border-slate-300 bg-white px-7 py-3.5 text-center text-[15px] font-bold text-ink-950 transition-transform hover:-translate-y-0.5 hover:border-slate-400 sm:w-auto"
            >
              Book a demo
            </a>
          </div>
          <p className="mt-4 text-[13px] text-slate-400">No credit card required &middot; Cancel anytime</p>
        </div>

        <div className="mx-auto mt-14 max-w-4xl lg:mt-16">
          <DashboardMock />
        </div>
      </div>
    </section>
  );
}
