"use client";

import Link from "next/link";
import { IconArrowRight, IconChevronDown } from "@/components/app/icons";
import { useLocalState } from "@/lib/localSettings";
import { ONBOARDING_STEPS } from "@/lib/onboarding";

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
  const [hidden, setHidden] = useLocalState(workspaceId, "getting-started-hidden", false);

  if (doneCount >= STEPS.length) return null;

  if (hidden) {
    return (
      <button
        onClick={() => setHidden(false)}
        className="mb-6 flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-[13px] font-semibold text-slate-600 hover:border-slate-300"
      >
        Show getting started guide
      </button>
    );
  }

  return (
    <div className="card relative mb-6 overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute -right-6 -top-10 h-40 w-56 rotate-[18deg] rounded-[2rem] bg-gradient-to-br from-brand-400 to-violet-400 opacity-90"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -right-2 top-6 h-24 w-40 rotate-[18deg] rounded-[1.5rem] bg-gradient-to-br from-violet-500 to-brand-600 opacity-80"
      />

      <h2 className="font-display text-xl font-extrabold tracking-tight text-ink-950">Getting Started guide</h2>

      <div className="mt-4 flex gap-1.5">
        {STEPS.map((_, i) => (
          <span
            key={i}
            className={`h-1.5 flex-1 rounded-full ${i < doneCount ? "bg-brand-600" : "bg-slate-200"}`}
          />
        ))}
      </div>

      <p className="mt-4 text-[14px] font-semibold text-ink-950">Step {doneCount + 1}: {STEPS[doneCount] ?? STEPS[STEPS.length - 1]}</p>

      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={() => setHidden(true)}
          className="flex items-center gap-1.5 rounded-full border border-slate-200 px-4 py-2 text-[13px] font-semibold text-slate-600 hover:border-slate-300"
        >
          <IconChevronDown className="h-3.5 w-3.5 rotate-180" />
          Hide
        </button>
        <button
          onClick={onContinue}
          className="flex items-center gap-1.5 rounded-full bg-brand-600 px-4 py-2 text-[13px] font-bold text-white hover:bg-brand-700"
        >
          Continue Setup
          <IconArrowRight className="h-3.5 w-3.5" />
        </button>
        <Link href="/guide" className="text-[13px] font-semibold text-brand-600 hover:underline">
          Full walkthrough
        </Link>
      </div>
    </div>
  );
}
