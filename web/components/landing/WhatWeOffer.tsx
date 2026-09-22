"use client";

import { useState } from "react";
import { DashboardMock } from "./mock/DashboardMock";

const TABS = [
  {
    key: "setter",
    label: "AI Appointment Setter",
    title: "Let AI book meetings while you sleep",
    body: "Deploy an AI setter that qualifies leads, answers objections in your tone, and drops meetings straight onto reps' calendars.",
  },
  {
    key: "voice",
    label: "Voice &amp; video notes",
    title: "Personalized voice and video, at scale",
    body: "Record once, and SalesBot generates a unique voice note or video for every lead using their name, role, and company.",
  },
  {
    key: "whitelabel",
    label: "Whitelabel",
    title: "Run it as your own agency platform",
    body: "Full whitelabel: your logo, your domain, your pricing. Resell SalesBot to clients under your own brand.",
  },
  {
    key: "linkedin",
    label: "LinkedIn Automation",
    title: "Automate connections, messages, and follow-ups",
    body: "Multi-step sequences across connection requests, InMail, and messages &mdash; paced to look and feel human.",
  },
  {
    key: "email",
    label: "Unlimited Cold Email",
    title: "Unlimited sending across unlimited inboxes",
    body: "Connect unlimited mailboxes, rotate sends automatically, and keep deliverability high with built-in warmup.",
  },
];

export function WhatWeOffer() {
  const [active, setActive] = useState(TABS[0].key);
  const current = TABS.find((t) => t.key === active) ?? TABS[0];

  return (
    <section id="offer" className="bg-white py-20 sm:py-28">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-[13px] font-bold uppercase tracking-wider text-brand-600">Everything you need</p>
          <h2 className="mt-3 font-display text-3xl font-extrabold tracking-tight text-ink-950 sm:text-4xl">
            What we offer
          </h2>
        </div>

        <div className="mt-10 flex flex-wrap justify-center gap-2 sm:mt-12">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActive(tab.key)}
              className={`rounded-full border px-4 py-2.5 text-[13.5px] font-semibold transition-colors ${
                active === tab.key
                  ? "border-ink-950 bg-ink-950 text-white"
                  : "border-slate-200 text-slate-600 hover:border-slate-300 hover:text-ink-950"
              }`}
              dangerouslySetInnerHTML={{ __html: tab.label }}
            />
          ))}
        </div>

        <div className="mt-14 grid items-center gap-12 lg:grid-cols-2 lg:gap-16">
          <div className="order-2 lg:order-1">
            <h3
              className="font-display text-2xl font-bold tracking-tight text-ink-950 sm:text-3xl"
              dangerouslySetInnerHTML={{ __html: current.title }}
            />
            <p className="mt-4 max-w-md text-[15.5px] leading-relaxed text-slate-600">{current.body}</p>
            <a
              href="/signup"
              className="mt-7 inline-flex items-center gap-2 rounded-full bg-brand-600 px-6 py-3 text-[14.5px] font-bold text-white shadow-md shadow-brand-600/20 transition-transform hover:-translate-y-0.5 hover:bg-brand-700"
            >
              Try it free
              <span aria-hidden>&rarr;</span>
            </a>
          </div>
          <div className="order-1 lg:order-2">
            <DashboardMock />
          </div>
        </div>
      </div>
    </section>
  );
}
