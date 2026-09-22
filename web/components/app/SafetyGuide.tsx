"use client";

/**
 * "Stay Safe" — a top-bar tab that opens a slide-over guide to keeping a
 * LinkedIn account healthy while using automation.
 *
 * Written to be honest: LinkedIn's terms prohibit automation, so no habit here
 * can promise an account is never restricted. The guide lowers the risk, and
 * each rule names the exact screen in this app where it is applied. Numbers
 * for the warm-up plan match what the engine actually enforces
 * (api/app/linkedin/caps.py).
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { IconClose, IconShield } from "@/components/app/icons";

type Rule = {
  title: string;
  body: string;
  where?: { label: string; href: string };
};

type Section = {
  id: string;
  title: string;
  blurb: string;
  tone: "emerald" | "brand" | "amber" | "rose";
  rules: Rule[];
};

const SECTIONS: Section[] = [
  {
    id: "warmup",
    title: "1 · Warm the account up",
    blurb: "A new or quiet account that suddenly sends a lot is the fastest way to a restriction.",
    tone: "emerald",
    rules: [
      {
        title: "Keep Test mode ON for the first 1–2 weeks",
        body: "It caps the day at 3–5 connection requests and 2 messages. Those numbers are small on purpose: they look like a person getting started.",
        where: { label: "Accounts → your account → Test mode", href: "/accounts" },
      },
      {
        title: "Then let the ramp-up raise limits, don't jump ahead",
        body: "After Test mode the engine ramps invites from about 12/day in week 1, to 25, 40 and up to the platform ceiling. You can only ever lower these limits, never raise them past the ceiling.",
        where: { label: "Accounts → limits", href: "/accounts" },
      },
      {
        title: "Use LinkedIn yourself, too",
        body: "Log in on your phone, read the feed, reply to real people. An account that only ever sends outreach looks different from one that is lived in.",
      },
    ],
  },
  {
    id: "identity",
    title: "2 · One account, one stable identity",
    blurb: "LinkedIn watches where and how an account signs in. Changing that often is a warning sign.",
    tone: "brand",
    rules: [
      {
        title: "Use a residential proxy in the same country as the profile",
        body: "A data-centre or shared IP is scored poorly, and every account on the same IP is linked together. Bind one proxy per account and leave it alone.",
        where: { label: "Accounts → Connect → Bind proxy", href: "/accounts" },
      },
      {
        title: "Connect through “Sign in with browser”",
        body: "It signs in from the account's own proxy with a fixed browser identity, and you complete any 2FA yourself. Avoid pasting cookies from another device.",
        where: { label: "Accounts → Connect session", href: "/accounts" },
      },
      {
        title: "Don't sign in from many places at once",
        body: "While a campaign runs, avoid logging into the same account from new devices or countries. If you travel, pause the campaign first.",
      },
      {
        title: "Run only one automation tool per account",
        body: "Two tools acting on the same account double the activity and clash on timing. Turn off browser extensions and other LinkedIn tools while using this one.",
      },
    ],
  },
  {
    id: "behaviour",
    title: "3 · Act like a person",
    blurb: "Volume matters less than pattern. Steady, irregular and modest beats bursts.",
    tone: "amber",
    rules: [
      {
        title: "Leave the timing on “Smart”",
        body: "Smart picks a natural moment inside working hours. Use ASAP or a fixed time only when you need it, for a test or a launch date; the limits still apply.",
        where: { label: "Campaign → sequence → When to send", href: "/campaigns" },
      },
      {
        title: "Weekdays and working hours only",
        body: "Keep the account's working hours and “weekdays only” on. Activity at 3 a.m. on a Sunday is not how most people use LinkedIn.",
      },
      {
        title: "Stay well under the weekly invitation limit",
        body: "LinkedIn allows roughly 100 requests a week and can lower it per account. Running near the limit every week is riskier than 40–60. Start low and raise slowly.",
      },
      {
        title: "Don't over-use profile views and messages",
        body: "Views and messages are limited too. A few dozen views a day is plenty; long streaks of identical messages are what get reported.",
      },
    ],
  },
  {
    id: "content",
    title: "4 · Write for people, target well",
    blurb: "The most common cause of restriction is people hitting “I don't know this person” or “Spam”.",
    tone: "rose",
    rules: [
      {
        title: "Connect with people who'll plausibly accept",
        body: "Same industry, same city, mutual interests. A low acceptance rate (under about 25–30%) tells LinkedIn your requests are unwanted.",
        where: { label: "Leads → import a tight list", href: "/leads" },
      },
      {
        title: "Short, specific, no pitch in the first note",
        body: "Say who you are and why them, in a sentence or two. Save the offer for after they accept. Avoid links and all-caps in the first message.",
        where: { label: "Campaign → sequence → preview", href: "/campaigns" },
      },
      {
        title: "Vary the wording",
        body: "Use {{first_name}}, {{company}} and spin like {Hi|Hello}. Sending the identical text hundreds of times is easy to detect.",
      },
      {
        title: "Withdraw old pending invitations",
        body: "A large pile of unanswered requests lowers your standing. Withdraw ones older than a few weeks from LinkedIn's Sent invitations page.",
      },
    ],
  },
  {
    id: "react",
    title: "5 · If LinkedIn warns you",
    blurb: "How you react to the first warning matters more than anything before it.",
    tone: "rose",
    rules: [
      {
        title: "Stop all campaigns straight away",
        body: "If you see “unusual activity”, a verification request or a restriction notice, pause every campaign on that account. The app also opens its circuit breaker and stops work automatically.",
        where: { label: "Campaigns → Pause", href: "/campaigns" },
      },
      {
        title: "Verify on LinkedIn itself, once",
        body: "Complete the check in your own browser or phone. Don't retry logins repeatedly from this app: repeated attempts make it worse.",
      },
      {
        title: "Rest the account for several days",
        body: "After a warning, wait at least a few days, then restart from Test mode limits and rebuild slowly.",
      },
    ],
  },
];

const TONES: Record<Section["tone"], { chip: string; dot: string }> = {
  emerald: { chip: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500" },
  brand: { chip: "bg-brand-50 text-brand-700", dot: "bg-brand-500" },
  amber: { chip: "bg-amber-50 text-amber-700", dot: "bg-amber-500" },
  rose: { chip: "bg-rose-50 text-rose-700", dot: "bg-rose-500" },
};

const RAMP: { when: string; invites: string; messages: string }[] = [
  { when: "Test mode (first 1–2 weeks)", invites: "3–5 / day", messages: "2 / day" },
  { when: "Week 1 after Test mode", invites: "up to 12 / day", messages: "start low, raise slowly" },
  { when: "Week 2", invites: "up to 25 / day", messages: "≈ 10–20 / day" },
  { when: "Week 3", invites: "up to 40 / day", messages: "≈ 20–30 / day" },
  { when: "Week 4 onward", invites: "up to 75 / day, 100 / week", messages: "keep it steady" },
];

export function SafetyGuide() {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<string>("warmup");
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        aria-label="Stay safe"
        className="hidden h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-ink-950 sm:flex"
      >
        <IconShield className="h-4 w-4" />
      </button>

      {open && (
        <div className="fixed inset-0 z-50">
          <button
            aria-label="Close safety guide"
            className="absolute inset-0 bg-ink-950/40 backdrop-blur-[1px]"
            onClick={() => setOpen(false)}
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-label="How to keep your LinkedIn account safe"
            className="absolute right-0 top-0 flex h-full w-full max-w-[460px] flex-col bg-white shadow-2xl"
          >
            <header className="flex items-start justify-between gap-3 border-b border-slate-200 bg-gradient-to-br from-emerald-50 to-white px-5 py-4">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-600 text-white">
                  <IconShield className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="text-[16px] font-bold text-ink-950">Keep your LinkedIn account safe</h2>
                  <p className="text-[12.5px] text-slate-500">
                    Five habits that lower the risk of a restriction.
                  </p>
                </div>
              </div>
              <button
                ref={closeRef}
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="flex h-8 w-8 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100"
              >
                <IconClose className="h-4 w-4" />
              </button>
            </header>

            <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
              <p className="rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-3 text-[12.5px] leading-relaxed text-amber-800">
                <span className="font-semibold">Be realistic:</span> LinkedIn&apos;s terms don&apos;t allow
                automation, so nothing can guarantee an account is never restricted. These habits
                lower the risk a lot, they don&apos;t remove it. Only use an account you can afford
                to have limited.
              </p>

              {SECTIONS.map((section) => {
                const isOpen = expanded === section.id;
                const tone = TONES[section.tone];
                return (
                  <section key={section.id} className="rounded-xl border border-slate-200">
                    <button
                      onClick={() => setExpanded(isOpen ? "" : section.id)}
                      aria-expanded={isOpen}
                      className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
                    >
                      <span>
                        <span className="block text-[14px] font-bold text-ink-950">{section.title}</span>
                        <span className="block text-[12px] text-slate-500">{section.blurb}</span>
                      </span>
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone.chip}`}>
                        {section.rules.length} tips
                      </span>
                    </button>

                    {isOpen && (
                      <ol className="space-y-3 border-t border-slate-100 px-4 py-3">
                        {section.rules.map((rule) => (
                          <li key={rule.title} className="flex gap-3">
                            <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${tone.dot}`} />
                            <div className="min-w-0">
                              <p className="text-[13px] font-semibold text-slate-900">{rule.title}</p>
                              <p className="mt-0.5 text-[12.5px] leading-relaxed text-slate-600">{rule.body}</p>
                              {rule.where && (
                                <Link
                                  href={rule.where.href}
                                  onClick={() => setOpen(false)}
                                  className="mt-1.5 inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 text-[11.5px] font-semibold text-slate-600 hover:bg-slate-200"
                                >
                                  Where: {rule.where.label} →
                                </Link>
                              )}
                            </div>
                          </li>
                        ))}
                      </ol>
                    )}
                  </section>
                );
              })}

              <section className="rounded-xl border border-slate-200 p-4">
                <h3 className="mb-2 text-[14px] font-bold text-ink-950">Suggested daily volume</h3>
                <div className="overflow-hidden rounded-lg border border-slate-200 text-[12px]">
                  <div className="grid grid-cols-[1.4fr_1fr_1fr] bg-slate-50 px-3 py-2 font-semibold uppercase tracking-wide text-slate-500">
                    <span>Stage</span>
                    <span>Invites</span>
                    <span>Messages</span>
                  </div>
                  {RAMP.map((row) => (
                    <div
                      key={row.when}
                      className="grid grid-cols-[1.4fr_1fr_1fr] gap-2 border-t border-slate-100 px-3 py-2 text-slate-700"
                    >
                      <span className="font-medium">{row.when}</span>
                      <span>{row.invites}</span>
                      <span>{row.messages}</span>
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-[11.5px] text-slate-400">
                  Invite numbers are the limits this app enforces. Staying below them is safer than
                  reaching them.
                </p>
              </section>
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
