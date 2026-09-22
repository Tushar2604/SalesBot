"use client";

import { useState } from "react";
import Link from "next/link";
import { DashboardMock } from "./mock/DashboardMock";

const TABS = [
  {
    key: "setter",
    label: "AI Appointment Setter",
    title: "AI Appointment Setter",
    body: "If you don't reply to leads within 5 mins, your chances of converting them fall by 50%. Our AI replies on your behalf instantly! (and yes, you can train it)",
  },
  {
    key: "voice",
    label: "Videos and Voice Notes",
    title: "Videos and Voice Notes",
    body: "Wow your leads by cloning yourself and sending personalized videos and voice notes to each lead on LinkedIn.",
  },
  {
    key: "whitelabel",
    label: "Whitelabel",
    title: "Whitelabel",
    body: "Want to resell SalesBot under your own brand? You can! Over 110 marketing agencies have done that and are making over $10k a month in profit.",
  },
  {
    key: "linkedin",
    label: "LinkedIn Automation",
    title: "LinkedIn Automation",
    body: "Send connection requests, LinkedIn messages and InMails in bulk. Messaging stops once the lead replies with Smart Reply Detection (TM)",
  },
  {
    key: "email",
    label: "Unlimited Cold Email Automation",
    title: "Unlimited Cold Email Automation",
    body: "Send cold emails without landing in spam. Use GMail, Outlook or Custom SMTP, we support it all.",
  },
];

export function WhatWeOffer() {
  const [active, setActive] = useState(TABS[0].key);
  const current = TABS.find((t) => t.key === active) ?? TABS[0];

  return (
    <section id="offer" className="bg-white py-16 sm:py-24">
      <div className="landing-wrap">
        <h2 className="landing-h2">What we offer</h2>

        <div className="mt-10 flex flex-wrap justify-center gap-2">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActive(tab.key)}
              className={`rounded-full border px-4 py-2 text-[13.5px] font-medium transition-colors ${
                active === tab.key
                  ? "border-ink-950 bg-ink-950 text-white"
                  : "border-slate-200 text-slate-600 hover:border-slate-300 hover:text-ink-950"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="mt-12 grid items-center gap-10 lg:grid-cols-2 lg:gap-16">
          <div>
            <h3 className="text-[28px] font-semibold leading-tight tracking-tight text-ink-950">{current.title}</h3>
            <p className="mt-4 max-w-md text-[15px] leading-relaxed text-slate-600">{current.body}</p>
            <Link href="/signup" className="mt-7 inline-flex items-center gap-2 text-[14.5px] font-semibold text-sky-600 hover:text-sky-700">
              View {current.title}
              <span aria-hidden>→</span>
            </Link>
          </div>
          <DashboardMock />
        </div>
      </div>
    </section>
  );
}
