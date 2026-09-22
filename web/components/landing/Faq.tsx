"use client";

import { useState } from "react";

const FAQS = [
  {
    q: "How do I get started ?",
    a: "Just add your LinkedIn account to SalesBot! You'll be up and running in 2 mins.",
  },
  {
    q: "Is it safe to use SalesBot?",
    a: "Yes. SalesBot uses residential IPs and mobile APIs, so your actions look completely natural. This makes it safer than tools like Expandi or Waalaxy, and our users have reported zero bans for months.",
  },
  {
    q: "Do I need LinkedIn Premium?",
    a: "No. SalesBot works smoothly with a free LinkedIn account. Premium can give extra limits, but it is not required.",
  },
  {
    q: "What makes SalesBot better than Expandi, Waalaxy, or Dripify?",
    a: "SalesBot is safer, has stronger AI, and supports more channels. You get LinkedIn, email, voice notes, and a unified inbox, all in one place.",
  },
  {
    q: "Will my LinkedIn account get banned?",
    a: "Very unlikely. SalesBot uses mobile API behavior and real-time throttling to keep your activity natural and within safe limits.",
  },
  {
    q: "What can I expect from my trial?",
    a: "Trials are meant to see the proof of functionality, which in our case means running a campaign. To get the best results, we recommend you spend 5 minutes to set up a campaign after you sign up.",
  },
  {
    q: "How does it work with LinkedIn limits?",
    a: "We fully comply with LinkedIn limits and you can send up to 75 connection requests a day. Additionally you can send up to 40 InMails a day to open profiles without using any InMail credits.",
  },
  {
    q: "How many LinkedIn accounts can I use ?",
    a: "If you've got multiple LinkedIn accounts you want to manage (client accounts for example), you can do that by just adding them like you added the first one.",
  },
  {
    q: "Can I use it with my CRM?",
    a: "Yes! SalesBot will populate your CRM automatically with leads interested in buying, directly from LinkedIn!",
  },
];

export function Faq() {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  return (
    <section id="faq" className="bg-[#f7f9fc] py-16 sm:py-24">
      <div className="landing-wrap max-w-3xl">
        <h2 className="landing-h2">Frequently asked questions</h2>
        <div className="mt-10 flex flex-col gap-3">
          {FAQS.map((item, i) => {
            const isOpen = openIndex === i;
            return (
              <div key={item.q} className="rounded-2xl border border-slate-200 bg-white">
                <button
                  onClick={() => setOpenIndex(isOpen ? null : i)}
                  className="flex w-full items-center justify-between gap-4 px-6 py-5 text-left"
                  aria-expanded={isOpen}
                >
                  <span className="text-[15px] font-medium text-ink-950">{item.q}</span>
                  <span
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-slate-200 text-ink-950 transition-transform ${
                      isOpen ? "rotate-45" : ""
                    }`}
                    aria-hidden
                  >
                    +
                  </span>
                </button>
                {isOpen && <p className="px-6 pb-5 text-[14px] leading-relaxed text-slate-600">{item.a}</p>}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
