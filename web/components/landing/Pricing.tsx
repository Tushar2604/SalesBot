"use client";

import { useState } from "react";
import Link from "next/link";

const PLANS = [
  {
    name: "Basic",
    monthly: 59,
    annual: 39,
    blurb: "Great for folks on a budget who are okay with low-volume outreach",
    features: ["1 active campaign", "Limited daily quotas", "Advanced dashboard & reports", "AI Appointment Setter Agent"],
  },
  {
    name: "Advanced",
    monthly: 79,
    annual: 59,
    blurb: "Has almost all the features except team management capabilities",
    featured: true,
    features: [
      "Unlimited active campaigns",
      "Full daily quotas",
      "A/B testing",
      "Personal inbox",
      "Webhook & Zapier integration",
      "Export leads into CSV",
    ],
  },
  {
    name: "Professional",
    monthly: 99,
    annual: 79,
    blurb: "Has all the capabilities and is used by serious agencies and B2B sales teams",
    features: ["Everything in Advanced", "Team management", "Activity control", "Priority support"],
  },
];

export function Pricing() {
  const [annual, setAnnual] = useState(true);

  return (
    <section id="pricing" className="bg-white py-16 sm:py-24">
      <div className="landing-wrap">
        <h2 className="landing-h2">Affordable payment plans for teams of all sizes</h2>
        <p className="mt-3 text-center text-[15px] text-slate-500">How many LinkedIn accounts do you have?</p>

        <div className="mt-6 flex items-center justify-center gap-3 text-[14px]">
          <span className={!annual ? "font-semibold text-ink-950" : "text-slate-400"}>Monthly</span>
          <button
            type="button"
            role="switch"
            aria-checked={annual}
            onClick={() => setAnnual((v) => !v)}
            className={`relative h-7 w-12 rounded-full transition-colors ${annual ? "bg-ink-950" : "bg-slate-300"}`}
          >
            <span className={`absolute top-0.5 h-6 w-6 rounded-full bg-white transition-transform ${annual ? "left-5" : "left-0.5"}`} />
          </button>
          <span className={annual ? "font-semibold text-ink-950" : "text-slate-400"}>
            Annual <span className="ml-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-600">up to 35% off</span>
          </span>
        </div>

        <div className="mt-12 grid gap-5 lg:grid-cols-3">
          {PLANS.map((p) => (
            <article
              key={p.name}
              className={`flex flex-col rounded-[24px] border p-6 ${
                p.featured ? "border-ink-950 bg-ink-950 text-white shadow-hero" : "border-slate-200 bg-[#f7f9fc]"
              }`}
            >
              {p.featured && (
                <span className="mb-3 w-fit rounded-full bg-robot px-2.5 py-1 text-[11px] font-semibold text-ink-950">
                  Best value
                </span>
              )}
              <h3 className="text-[20px] font-semibold">{p.name}</h3>
              <p className={`mt-2 text-[13.5px] leading-relaxed ${p.featured ? "text-slate-300" : "text-slate-500"}`}>{p.blurb}</p>
              <p className="mt-5">
                <span className="text-[36px] font-semibold">${annual ? p.annual : p.monthly}</span>
                <span className={`ml-1 text-[13px] ${p.featured ? "text-slate-400" : "text-slate-500"}`}>/LinkedIn acc/mo</span>
              </p>
              <p className={`text-[12px] ${p.featured ? "text-slate-400" : "text-slate-400"}`}>
                {annual ? "billed annually" : "billed monthly"}
              </p>
              <ul className="mt-6 flex-1 space-y-2.5 text-[13.5px]">
                {p.features.map((f) => (
                  <li key={f} className="flex gap-2">
                    <span className={p.featured ? "text-robot" : "text-emerald-500"}>✓</span>
                    {f}
                  </li>
                ))}
              </ul>
              <Link
                href="/signup"
                className={`mt-7 inline-flex h-11 items-center justify-center rounded-full text-[14px] font-medium ${
                  p.featured ? "bg-white text-ink-950 hover:bg-slate-100" : "bg-ink-950 text-white hover:bg-ink-900"
                }`}
              >
                Free Trial (14 days)
              </Link>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
