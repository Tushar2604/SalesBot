"use client";

import { useState } from "react";

const FAQS = [
  {
    q: "How do I get started?",
    a: "Sign up for the 14-day free trial, connect your LinkedIn and email accounts, and launch your first campaign in minutes &mdash; no setup calls required.",
  },
  {
    q: "Is it safe to use SalesBot?",
    a: "Yes. SalesBot mimics human behavior with randomized delays, daily safety limits, and dedicated IPs per account to keep your profiles secure.",
  },
  {
    q: "Do I need LinkedIn Premium?",
    a: "No. SalesBot works with a free LinkedIn account, though Sales Navigator unlocks more advanced lead search and filtering.",
  },
  {
    q: "What makes SalesBot better than Expandi or Dripify?",
    a: "Built-in AI voice and video notes, an AI appointment setter, unlimited cold email, and whitelabel mode &mdash; all in one platform at one price.",
  },
  {
    q: "Will my LinkedIn account get banned?",
    a: "SalesBot is engineered around LinkedIn's rate limits and behavioral patterns. Thousands of active accounts run safely on the platform every day.",
  },
  {
    q: "What can I expect from my list?",
    a: "You can import leads from LinkedIn search, Sales Navigator, or CSV, and expect enriched, deduplicated lists ready for outreach.",
  },
  {
    q: "How does it work with LinkedIn limits?",
    a: "Daily action limits are configurable and default to safe thresholds recommended by our team, based on account age and warmup status.",
  },
  {
    q: "How many LinkedIn accounts can I use?",
    a: "As many as you need. SalesBot supports unlimited connected accounts on every plan, with per-account dashboards and reporting.",
  },
  {
    q: "Can I use it with my CRM?",
    a: "Yes. Native integrations with HubSpot, Salesforce, Pipedrive, and Zapier keep your CRM in sync automatically.",
  },
];

export function Faq() {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  return (
    <section id="faq" className="bg-slate-50/70 py-20 sm:py-28">
      <div className="mx-auto max-w-3xl px-5 sm:px-8">
        <h2 className="text-center font-display text-3xl font-extrabold tracking-tight text-ink-950 sm:text-4xl">
          Frequently asked questions
        </h2>

        <div className="mt-10 flex flex-col gap-3">
          {FAQS.map((item, i) => {
            const isOpen = openIndex === i;
            return (
              <div
                key={item.q}
                className={`rounded-2xl border bg-white transition-colors ${isOpen ? "border-brand-200" : "border-slate-200"}`}
              >
                <button
                  onClick={() => setOpenIndex(isOpen ? null : i)}
                  className="flex w-full items-center justify-between gap-4 px-6 py-5 text-left"
                  aria-expanded={isOpen}
                >
                  <span className="text-[15px] font-semibold text-ink-950">{item.q}</span>
                  <span
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-slate-200 text-brand-600 transition-transform ${
                      isOpen ? "rotate-45 border-brand-200 bg-brand-50" : ""
                    }`}
                    aria-hidden
                  >
                    +
                  </span>
                </button>
                {isOpen && (
                  <p
                    className="px-6 pb-5 text-[14.5px] leading-relaxed text-slate-600"
                    dangerouslySetInnerHTML={{ __html: item.a }}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
