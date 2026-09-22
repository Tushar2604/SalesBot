"use client";

/**
 * A compact strip of icons summarising a sequence, one per step:
 * eye = view profile, link = connection request, bubble = message, clock = wait.
 * Lets a template row be read at a glance without opening it.
 */

import { IconClock, IconClose, IconEye, IconLink } from "@/components/app/icons";
import { STEP_LABELS, type StepInput, type StepType } from "@/lib/outreach-api";

function Bubble({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" className={className}>
      <path
        d="M4 4.5h12a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H9l-3.5 3v-3H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1z"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const STYLE: Record<StepType, { tone: string; Icon: (p: { className?: string }) => JSX.Element }> = {
  view_profile: { tone: "bg-violet-50 text-violet-600", Icon: IconEye },
  invite: { tone: "bg-rose-50 text-rose-600", Icon: IconLink },
  message: { tone: "bg-emerald-50 text-emerald-600", Icon: Bubble },
  wait: { tone: "bg-amber-50 text-amber-600", Icon: IconClock },
  withdraw_invite: { tone: "bg-slate-100 text-slate-600", Icon: IconClose },
};

export function StepIcons({ steps }: { steps: StepInput[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      {steps.map((step, index) => {
        const { tone, Icon } = STYLE[step.step_type];
        return (
          <span key={index} className="flex items-center gap-1">
            {index > 0 && <span className="h-px w-2.5 bg-slate-300" />}
            <span
              title={STEP_LABELS[step.step_type]}
              className={`flex h-6 w-6 items-center justify-center rounded-md ${tone}`}
            >
              <Icon className="h-3.5 w-3.5" />
            </span>
          </span>
        );
      })}
    </div>
  );
}
