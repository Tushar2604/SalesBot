"use client";

import { useState } from "react";

const STEPS = [
  {
    n: "1",
    title: "Import leads from LinkedIn Search, Sales Navigator Search, Recruiter and more!",
    preview: "Paste a search URL or upload a CSV. Duplicates are skipped workspace-wide.",
  },
  {
    n: "2",
    title: "Write high converting LinkedIn messages and emails with SalesBot’s AI, or craft your own.",
    note: "👀 Psst… you can also send personalised voice notes and videos.",
    preview: "Sequence builder with spintax, voice notes, video, and gated follow-ups.",
  },
  {
    n: "3",
    title: "Let SalesBot's AI manage your inbox and book you meetings (or manage it yourself if you want)",
    preview: "Unified inbox with AI replies, labels, snooze, and calendar booking.",
  },
];

export function HowItWorks() {
  const [active, setActive] = useState(0);
  const current = STEPS[active];

  return (
    <section id="how" className="bg-[#f7f9fc] py-16 sm:py-24">
      <div className="landing-wrap">
        <h2 className="landing-h2">It&apos;s as easy as</h2>
        <div className="mt-12 grid items-start gap-8 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="flex flex-col gap-4">
            {STEPS.map((step, i) => {
              const selected = i === active;
              return (
                <button
                  key={step.n}
                  onClick={() => setActive(i)}
                  className={`flex items-start gap-4 rounded-[22px] border px-5 py-5 text-left transition-colors ${
                    selected ? "border-ink-950 bg-white shadow-card" : "border-transparent bg-white/70 hover:border-slate-200"
                  }`}
                >
                  <span
                    className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[14px] font-semibold ${
                      selected ? "bg-ink-950 text-white" : "bg-slate-100 text-slate-500"
                    }`}
                  >
                    {step.n}
                  </span>
                  <span>
                    <span className="block text-[15px] font-medium leading-snug text-ink-950">{step.title}</span>
                    {step.note && <span className="mt-2 block text-[13px] text-slate-500">{step.note}</span>}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-card">
            <div className="flex h-64 items-center justify-center rounded-2xl bg-gradient-to-br from-[#e8f4ff] to-[#f6efff] text-center">
              <div>
                <p className="text-[13px] font-semibold uppercase tracking-wider text-slate-400">Step {current.n}</p>
                <p className="mx-auto mt-3 max-w-sm text-[16px] font-medium leading-relaxed text-ink-950">{current.preview}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
