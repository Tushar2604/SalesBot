"use client";

/**
 * The guide: the whole product, start to finish, in the order a new customer
 * does things. Setup steps show whether they are already done, read from real
 * data (connected account, imported leads, campaigns) rather than a saved flag.
 */

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import clsx from "clsx";
import { linkedinApi, type LinkedInAccount } from "@/lib/api";
import { campaignsApi, leadsApi, type Campaign, type LeadList } from "@/lib/outreach-api";
import { useSession } from "@/lib/session";
import {
  IconArrowRight,
  IconBolt,
  IconCheckCircle,
  IconInbox,
  IconPencil,
  IconShield,
  IconSparkle,
  IconTracking,
  IconUsers,
} from "@/components/app/icons";

type Status = "done" | "todo" | "info" | "none";

type Step = {
  id: string;
  title: string;
  short: string;
  icon: (props: { className?: string }) => ReactNode;
  summary: string;
  doThis: string[];
  behind: string;
  tip?: string;
  href: string;
  cta: string;
  status: Status;
  statusText?: string;
};

function StatusBadge({ status, text }: { status: Status; text?: string }) {
  if (status === "none") return null;
  const styles: Record<Exclude<Status, "none">, string> = {
    done: "border-emerald-200 bg-emerald-50 text-emerald-700",
    todo: "border-amber-200 bg-amber-50 text-amber-700",
    info: "border-slate-200 bg-slate-50 text-slate-600",
  };
  const label = text ?? (status === "done" ? "Done" : "To do");
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11.5px] font-semibold", styles[status])}>
      {status === "done" && <IconCheckCircle className="h-3.5 w-3.5" />}
      {label}
    </span>
  );
}

const LIMITS: { label: string; value: string; note: string }[] = [
  { label: "Connection requests", value: "~100 / week", note: "LinkedIn's own ceiling per account" },
  { label: "New account warm-up", value: "12 → 25 → 40 / day", note: "weeks 1, 2 and 3; up to 75 from week 4" },
  { label: "Safe Mode", value: "3–5 invites / day", note: "and 2 messages a day while it is on" },
  { label: "Pace", value: "one action / ~4 min", note: "only in working hours, in the account's time zone" },
  { label: "Replies", value: "checked every ~10 min", note: "an inbound reply stops that lead's sequence" },
  { label: "Unanswered invites", value: "tracked 21 days", note: "then marked \"No response\"" },
];

const FAQ: { q: string; a: string }[] = [
  {
    q: "My campaign is running but nothing is sending.",
    a: "That is usually the safety engine holding it, not a fault. Open Campaigns: the box at the top shows today's invite and message counts and whether the account is inside working hours.",
  },
  {
    q: "Why does it say the sign-in was lost?",
    a: "LinkedIn ended the session. Open Accounts and reconnect. Pending actions for that account are cancelled so a backlog does not fire all at once.",
  },
  {
    q: "Someone accepted, but the campaign still says pending.",
    a: "Acceptance is checked on a schedule (every couple of hours on day one, then less often). Open Track leads to see when each lead was last checked.",
  },
  {
    q: "The assistant is not drafting replies.",
    a: "It needs an AI key with credit (Gemini or OpenAI) and the assistant turned on under AI Assistant. Drafts appear as \"Suggested reply\" inside the conversation.",
  },
];

export default function GuidePage() {
  const { workspace } = useSession();
  const workspaceId = workspace?.id ?? null;

  const [accounts, setAccounts] = useState<LinkedInAccount[] | null>(null);
  const [lists, setLists] = useState<LeadList[] | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);

  useEffect(() => {
    if (!workspaceId) return;
    void Promise.allSettled([
      linkedinApi.accounts(workspaceId),
      leadsApi.lists(workspaceId),
      campaignsApi.list(workspaceId),
    ]).then(([a, l, c]) => {
      setAccounts(a.status === "fulfilled" ? a.value : []);
      setLists(l.status === "fulfilled" ? l.value : []);
      setCampaigns(c.status === "fulfilled" ? c.value : []);
    });
  }, [workspaceId]);

  const loaded = accounts !== null && lists !== null && campaigns !== null;
  const account = accounts?.[0];
  const connected = !!accounts?.some((a) => a.is_connected);
  const hasLeads = (lists?.length ?? 0) > 0;
  const hasCampaign = (campaigns?.length ?? 0) > 0;
  const hasRunning = !!campaigns?.some((c) => c.status === "running" || c.status === "completed");
  const hasResults = !!campaigns?.some((c) => c.stats.invites_sent > 0);

  const flag = (done: boolean): Status => (!loaded ? "none" : done ? "done" : "todo");

  const steps: Step[] = [
    {
      id: "connect",
      title: "Connect your LinkedIn account",
      short: "Connect",
      icon: IconUsers,
      summary: "Everything the product does is done as your own LinkedIn account, so this comes first.",
      doThis: [
        "Open Accounts and choose Connect account.",
        "Sign in to LinkedIn in the secure window that opens.",
        "Give the account its own proxy (a fixed, home-style internet address) in the same country as you.",
      ],
      behind:
        "We keep the sign-in session encrypted and act through one fixed address and one browser identity for that account. It never changes, because a changing identity looks like a hijacked account.",
      tip: "One account, one proxy. Never share a proxy between two accounts.",
      href: "/accounts",
      cta: "Open Accounts",
      status: flag(connected),
    },
    {
      id: "safe",
      title: "Keep Safe Mode on while the account warms up",
      short: "Safe Mode",
      icon: IconShield,
      summary: "A new or quiet account that suddenly sends a lot is the fastest way to a LinkedIn restriction.",
      doThis: [
        "Open Settings, then Safe Mode.",
        "Leave it on for the first 1 to 2 weeks. It allows 3 to 5 invites and 2 messages a day.",
        "Turn it off later. The account then warms up on its own: 12, 25, 40 invites a day, up to 75.",
      ],
      behind:
        "Limits are enforced on our servers, not in the browser. You can lower them, but never raise them past the safe ceiling, and a weekly cap of about 100 invites always applies.",
      href: "/settings",
      cta: "Open Safe Mode",
      status: !loaded || !account ? "none" : "info",
      statusText: account ? (account.test_mode ? "Safe Mode is on" : "Safe Mode is off") : undefined,
    },
    {
      id: "leads",
      title: "Add your leads",
      short: "Leads",
      icon: IconUsers,
      summary: "A lead list is the people you want to reach.",
      doThis: [
        "Open Leads and choose Import.",
        "Upload a CSV with a name, a LinkedIn profile link and a company, or paste profile links.",
        "Check the report: it tells you which rows were skipped and why (duplicates, blocked, no profile).",
      ],
      behind:
        "Anyone already contacted by any account in your workspace is skipped automatically, so two campaigns can never message the same person.",
      tip: "Up to 50,000 rows or 10 MB per file.",
      href: "/leads",
      cta: "Open Leads",
      status: flag(hasLeads),
    },
    {
      id: "campaign",
      title: "Build a campaign",
      short: "Campaign",
      icon: IconBolt,
      summary: "A campaign is a short sequence of steps every lead goes through.",
      doThis: [
        "Open Campaigns and choose Create Campaign.",
        "Pick the sender account, then add steps. A good start: view profile, then a connection request, then a message only if they accept.",
        "Write the note or message with variables such as {{first_name}}. The preview shows exactly what one lead would get.",
      ],
      behind:
        "The campaign only records what should happen. The safety engine decides at the last moment whether an action may run, so a launch can never bypass a limit.",
      tip: "Connection notes are limited to 300 characters. A message right after an invite must be set to run only if they accepted.",
      href: "/campaigns?new=1",
      cta: "Create a campaign",
      status: flag(hasCampaign),
    },
    {
      id: "launch",
      title: "Enroll your leads and launch",
      short: "Launch",
      icon: IconBolt,
      summary: "Enrolling puts a lead list into the campaign. Launching starts it.",
      doThis: [
        "Open the campaign and choose your lead list under Enroll leads.",
        "Press Launch. You can Pause at any time.",
        "Expect it to be slow on purpose: about one action every 4 minutes, inside working hours.",
      ],
      behind:
        "Every action is a saved task that can only run once, even if a server restarts. An account does exactly one thing at a time.",
      href: "/campaigns",
      cta: "Open Campaigns",
      status: flag(hasRunning),
    },
    {
      id: "track",
      title: "Track every lead",
      short: "Track",
      icon: IconTracking,
      summary: "Every campaign has a tracking page that shows where each person stands and keeps their full history.",
      doThis: [
        "On the Campaigns list, press Track leads next to a campaign.",
        "Read the funnel: Queued, Profile viewed, Invite pending, Connected, Replied, Not accepted, No response.",
        "Click any lead to see everything that happened to them, with dates. Export the list to CSV if you need it.",
      ],
      behind:
        "LinkedIn never announces a declined request. Not accepted means the invite is no longer pending and they are not connected, confirmed on two checks. Unanswered invites are watched for 21 days, then marked No response.",
      tip: "You get a notification each time someone accepts.",
      href: "/campaigns",
      cta: "Open a campaign's tracking",
      status: flag(hasResults),
      statusText: hasResults ? "Results available" : "Waiting for the first invite",
    },
    {
      id: "inbox",
      title: "Reply from the Inbox",
      short: "Inbox",
      icon: IconInbox,
      summary: "Every conversation lands in one inbox, with a red count in the sidebar for anything unread.",
      doThis: [
        "Open Inbox and pick a conversation. Your messages are on the right, theirs on the left.",
        "Use the Suggested reply the AI assistant writes, edit it, and send.",
        "Under AI Assistant choose Off, Draft (suggests only) or Auto (replies by itself, with delays).",
      ],
      behind:
        "The inbox syncs about every 10 minutes. The assistant steps back the moment you start typing, and an inbound reply stops that lead's sequence.",
      tip: "Start with Draft. Move to Auto only when the drafts are consistently good.",
      href: "/inbox",
      cta: "Open Inbox",
      status: "none",
    },
    {
      id: "content",
      title: "Optional: post from Content Studio",
      short: "Content",
      icon: IconPencil,
      summary: "Write, schedule and publish your own LinkedIn posts.",
      doThis: [
        "Open Content Studio and draft a post, with AI help if you like.",
        "Under Accounts choose Connect for publishing and approve the permission on LinkedIn.",
        "Schedule it or publish now.",
      ],
      behind:
        "Posting uses LinkedIn's official API and needs a LinkedIn developer app, which is set up once by whoever runs the product. Until then you can still draft and schedule.",
      href: "/content",
      cta: "Open Content Studio",
      status: "none",
    },
  ];

  const setupDone = [connected, hasLeads, hasCampaign, hasRunning].filter(Boolean).length;
  const nextStep = !connected ? steps[0] : !hasLeads ? steps[2] : !hasCampaign ? steps[3] : !hasRunning ? steps[4] : steps[5];

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-8">
        <p className="mb-1 text-[12px] font-bold uppercase tracking-wider text-brand-600">Guide</p>
        <h1 className="font-display text-3xl font-extrabold tracking-tight text-ink-950">
          How it works, start to finish
        </h1>
        <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-slate-600">
          From connecting your LinkedIn account to reading replies. Follow the steps in order the first time, then use
          this page as a reference.
        </p>
      </header>

      {loaded && (
        <div className="card mb-8 flex flex-wrap items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-slate-500">Your setup</p>
            <p className="font-display text-xl font-extrabold text-ink-950">
              {setupDone === 4 ? "Setup complete" : `${setupDone} of 4 setup steps done`}
            </p>
            <div className="mt-3 flex w-64 max-w-full gap-1.5">
              {[connected, hasLeads, hasCampaign, hasRunning].map((done, i) => (
                <span key={i} className={clsx("h-1.5 flex-1 rounded-full", done ? "bg-brand-600" : "bg-slate-200")} />
              ))}
            </div>
          </div>
          <Link href={nextStep.href} className="btn-primary">
            {setupDone === 4 ? "Review your results" : `Next: ${nextStep.short}`}
            <IconArrowRight className="h-4 w-4" />
          </Link>
        </div>
      )}

      {/* The whole journey at a glance. */}
      <nav aria-label="The steps" className="mb-10 overflow-x-auto pb-2">
        <ol className="flex min-w-max items-center gap-2">
          {steps.map((step, i) => (
            <li key={step.id} className="flex items-center gap-2">
              <a
                href={`#${step.id}`}
                className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3.5 py-2 text-[13px] font-semibold text-ink-950 shadow-sm transition-colors hover:border-brand-500 hover:text-brand-700"
              >
                <span
                  className={clsx(
                    "flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold",
                    step.status === "done" ? "bg-emerald-500 text-white" : "bg-ink-950 text-white",
                  )}
                >
                  {step.status === "done" ? "✓" : i + 1}
                </span>
                {step.short}
              </a>
              {i < steps.length - 1 && <IconArrowRight className="h-4 w-4 text-slate-300" />}
            </li>
          ))}
        </ol>
      </nav>

      <ol className="relative space-y-6">
        <span aria-hidden className="absolute bottom-6 left-[19px] top-6 hidden w-px bg-slate-200 sm:block" />
        {steps.map((step, i) => {
          const Icon = step.icon;
          return (
            <li key={step.id} id={step.id} className="relative scroll-mt-24 sm:pl-14">
              <span
                className={clsx(
                  "absolute left-0 top-5 hidden h-10 w-10 items-center justify-center rounded-full border-2 border-slate-50 font-display text-base font-extrabold sm:flex",
                  step.status === "done" ? "bg-emerald-500 text-white" : "bg-ink-950 text-white",
                )}
              >
                {step.status === "done" ? "✓" : i + 1}
              </span>

              <div className="card">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                      <Icon className="h-[18px] w-[18px]" />
                    </span>
                    <h2 className="font-display text-lg font-extrabold text-ink-950">{step.title}</h2>
                  </div>
                  <StatusBadge status={step.status} text={step.statusText} />
                </div>

                <p className="mt-3 text-[14px] leading-relaxed text-slate-600">{step.summary}</p>

                <div className="mt-4 grid gap-4 md:grid-cols-5">
                  <div className="md:col-span-3">
                    <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-400">What you do</p>
                    <ol className="space-y-2">
                      {step.doThis.map((line, n) => (
                        <li key={n} className="flex gap-2.5 text-[13.5px] leading-relaxed text-slate-700">
                          <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-bold text-slate-600">
                            {n + 1}
                          </span>
                          <span>{line}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                  <div className="rounded-lg bg-slate-50 p-3.5 md:col-span-2">
                    <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                      <IconSparkle className="h-3.5 w-3.5" />
                      Behind the scenes
                    </p>
                    <p className="text-[12.5px] leading-relaxed text-slate-600">{step.behind}</p>
                  </div>
                </div>

                {step.tip && (
                  <p className="mt-4 rounded-lg border border-brand-100 bg-brand-50/60 px-3.5 py-2.5 text-[12.5px] text-brand-800">
                    <span className="font-bold">Tip: </span>
                    {step.tip}
                  </p>
                )}

                <div className="mt-5">
                  <Link href={step.href} className="btn-ghost">
                    {step.cta}
                    <IconArrowRight className="h-4 w-4" />
                  </Link>
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      <section className="mt-12">
        <h2 className="font-display text-xl font-extrabold text-ink-950">The numbers to know</h2>
        <p className="mt-1 text-sm text-slate-500">These protect your LinkedIn account. They are enforced by the system.</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {LIMITS.map((item) => (
            <div key={item.label} className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-[12px] font-medium text-slate-500">{item.label}</p>
              <p className="font-display text-lg font-extrabold text-ink-950">{item.value}</p>
              <p className="mt-0.5 text-[12px] text-slate-500">{item.note}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-10 mt-12">
        <h2 className="font-display text-xl font-extrabold text-ink-950">If something looks wrong</h2>
        <div className="mt-4 divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
          {FAQ.map((item) => (
            <details key={item.q} className="group px-5 py-4">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-[14px] font-semibold text-ink-950">
                {item.q}
                <IconArrowRight className="h-4 w-4 shrink-0 text-slate-400 transition-transform group-open:rotate-90" />
              </summary>
              <p className="mt-2 text-[13.5px] leading-relaxed text-slate-600">{item.a}</p>
            </details>
          ))}
        </div>
      </section>
    </div>
  );
}
