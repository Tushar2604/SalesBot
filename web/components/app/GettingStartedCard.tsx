"use client";

import Link from "next/link";
import { IconArrowRight } from "@/components/app/icons";
import { useLocalState } from "@/lib/localSettings";
import { ONBOARDING_STEPS } from "@/lib/onboarding";
import { trialDaysLeft } from "@/components/app/AppTopbar";
import { useSession } from "@/lib/session";

const STEPS = ONBOARDING_STEPS;

export function GettingStartedCard({
  workspaceId,
  onContinue,
  doneCount = 0,
}: {
  workspaceId: string | null;
  onContinue: () => void;
  doneCount?: number;
}) {
  const { me } = useSession();
  const [hidden, setHidden] = useLocalState(workspaceId, "getting-started-hidden", false);
  const days = trialDaysLeft(me?.user.created_at);

  if (doneCount >= STEPS.length) return null;

  if (hidden) {
    return (
      <button
        onClick={() => setHidden(false)}
        className="mb-6 flex items-center gap-2 text-[13.5px] font-medium text-slate-500 hover:text-ink-950"
      >
        Show getting started guide
      </button>
    );
  }

  return (
    <div className="relative mb-7 overflow-hidden rounded-2xl border border-slate-100 bg-white px-6 py-6 shadow-[0_8px_30px_-18px_rgba(15,23,42,0.18)]">
      <div
        aria-hidden
        className="pointer-events-none absolute -right-6 -top-8 h-28 w-48 rotate-[28deg] rounded-3xl bg-[#7ad8ff]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute right-10 top-10 h-20 w-36 rotate-[28deg] rounded-3xl bg-[#7c6bff]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -right-10 bottom-2 h-16 w-40 rotate-[28deg] rounded-3xl bg-[#3bdcff]"
      />

      <h2 className="text-[22px] font-semibold tracking-tight text-ink-950">Getting Started guide</h2>

      <div className="mt-4 flex max-w-xl gap-2">
        {STEPS.map((_, i) => (
          <span
            key={i}
            className={`h-1.5 flex-1 rounded-full ${i < doneCount ? "bg-accent" : "bg-slate-200"}`}
          />
        ))}
      </div>

      <p className="mt-4 max-w-2xl text-[14px] font-medium text-[#ef4444]">
        You have {days} days remaining in your trial. {STEPS[doneCount] ?? STEPS[0]} to get started.
      </p>

      <div className="mt-5 flex items-center gap-3">
        <button
          onClick={() => setHidden(true)}
          className="rounded-xl border border-slate-200 bg-white px-5 py-2.5 text-[14px] font-medium text-slate-600 hover:border-slate-300"
        >
          Hide
        </button>
        <button
          onClick={onContinue}
          className="inline-flex items-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-[14px] font-medium text-white hover:bg-accent-hover"
        >
          Continue Setup
          <IconArrowRight className="h-3.5 w-3.5" />
        </button>
        <Link href="/guide" className="text-[13px] font-semibold text-accent hover:underline">
          Full walkthrough
        </Link>
      </div>
    </div>
  );
}
