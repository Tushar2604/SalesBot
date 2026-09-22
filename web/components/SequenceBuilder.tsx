"use client";

/**
 * Sequence builder.
 *
 * Deliberately a vertical list rather than a node canvas. The branching people
 * actually use is "only message them if they accepted" and "follow up only if
 * they haven't replied" — a per-step gate expresses that exactly, and a list
 * stays readable at a glance, which a graph of five nodes does not.
 *
 * Template length and unsafe variables are surfaced live, because both failure
 * modes (a truncated invite note, a lead skipped for a missing field) are
 * invisible until send time otherwise.
 */

import { useEffect, useState } from "react";
import { MessagePreview } from "@/components/MessagePreview";
import { StepTiming } from "@/components/StepTiming";
import { useSession } from "@/lib/session";
import {
  campaignsApi,
  CONDITION_LABELS,
  STEP_LABELS,
  type ConditionFailAction,
  type StepCondition,
  type StepInput,
  type StepType,
  type TemplatePreview,
} from "@/lib/outreach-api";

const STEP_ORDER: StepType[] = ["view_profile", "invite", "message", "wait"];
const TEMPLATE_STEPS: StepType[] = ["invite", "message"];

export function emptyStep(step_type: StepType = "invite"): StepInput {
  return {
    step_type,
    delay_hours: 0,
    only_if: "always",
    on_condition_fail: "skip",
    template: "",
    timing: "smart",
  };
}

/**
 * A new step of `type` with defaults that make sense for it: a message waits for
 * acceptance, an invite waits a day after viewing, and so on. Message steps
 * placed straight after an invite must be gated, or the server refuses them.
 */
export function newStepFor(type: StepType): StepInput {
  switch (type) {
    case "invite":
      return { ...emptyStep("invite"), delay_hours: 24 };
    case "message":
      return { ...emptyStep("message"), delay_hours: 48, only_if: "if_accepted" };
    case "wait":
      return { ...emptyStep("wait"), delay_hours: 24 };
    default:
      return emptyStep(type);
  }
}

const PALETTE: { type: StepType; label: string; hint: string; tone: string }[] = [
  { type: "view_profile", label: "View profile", hint: "A quiet first touch", tone: "bg-violet-50 text-violet-600" },
  { type: "invite", label: "Connection request", hint: "With or without a note", tone: "bg-rose-50 text-rose-600" },
  { type: "message", label: "Message", hint: "Follow up after they accept", tone: "bg-emerald-50 text-emerald-600" },
  { type: "wait", label: "Wait", hint: "Pause before the next step", tone: "bg-amber-50 text-amber-600" },
];

function StepPalette({ onAdd }: { onAdd: (type: StepType) => void }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-3">
      <p className="label">Add a step</p>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {PALETTE.map((item) => (
          <button
            key={item.type}
            type="button"
            onClick={() => onAdd(item.type)}
            className="flex items-start gap-2.5 rounded-lg border border-slate-200 bg-white p-2.5 text-left transition-colors hover:border-brand-400 hover:bg-brand-50/40"
          >
            <span className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-sm font-bold ${item.tone}`}>
              +
            </span>
            <span>
              <span className="block text-[13px] font-semibold text-slate-800">{item.label}</span>
              <span className="block text-[11px] text-slate-400">{item.hint}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

/** A sane starting sequence, which is also the one the docs describe. */
export function defaultSequence(): StepInput[] {
  return [
    { ...emptyStep("view_profile"), delay_hours: 0 },
    {
      ...emptyStep("invite"),
      delay_hours: 24,
      template: "Hi {{first_name|there}}, I work with teams at companies like {{company|yours}} — thought it would be good to connect.",
    },
    {
      ...emptyStep("message"),
      delay_hours: 48,
      only_if: "if_accepted",
      template: "Thanks for connecting, {{first_name|there}}. What does outbound look like for you at {{company|your company}} right now?",
    },
  ];
}

function TemplateField({
  workspaceId,
  step,
  onChange,
}: {
  workspaceId: string;
  step: StepInput;
  onChange: (template: string) => void;
}) {
  const [preview, setPreview] = useState<TemplatePreview | null>(null);
  const { me } = useSession();
  const senderName = me?.user.full_name || "You";

  // Debounced so typing does not fire a request per keystroke.
  useEffect(() => {
    if (!step.template.trim()) {
      setPreview(null);
      return;
    }
    const timer = setTimeout(() => {
      void campaignsApi
        .previewTemplate(workspaceId, step.template)
        .then(setPreview)
        .catch(() => setPreview(null));
    }, 400);
    return () => clearTimeout(timer);
  }, [step.template, workspaceId]);

  const overLimit = step.step_type === "invite" && (preview?.exceeds_invite_limit ?? false);

  return (
    <div>
      <label className="label">
        {step.step_type === "invite" ? "Note with the request (optional)" : "Message"}
      </label>
      <textarea
        className="input h-24"
        value={step.template}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Hi {{first_name|there}}, …"
      />
      <p className="mt-1.5 text-xs text-slate-500">
        Variables: <code>{"{{first_name}}"}</code>, <code>{"{{company}}"}</code>,{" "}
        <code>{"{{title}}"}</code>, <code>{"{{custom.your_column}}"}</code>. Add a fallback with{" "}
        <code>{"{{company|your team}}"}</code>. Spin wording with{" "}
        <code>{"{Hi|Hello}"}</code>.
      </p>

      {preview && (
        <div className="mt-3">
          <MessagePreview
            kind={step.step_type === "invite" ? "invite" : "message"}
            text={preview.rendered}
            senderName={senderName}
            limit={step.step_type === "invite" ? 300 : undefined}
            overLimit={overLimit}
          />
          {preview.variables_without_fallback.length > 0 && (
            <p className="mt-2 text-xs text-state-warn">
              No fallback for {preview.variables_without_fallback.join(", ")} — leads missing
              that field are skipped rather than sent a half-filled message. Add a fallback
              like <code>{"{{company|your team}}"}</code> to include them.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function SequenceBuilder({
  workspaceId,
  steps,
  onChange,
  disabled = false,
}: {
  workspaceId: string;
  steps: StepInput[];
  onChange: (steps: StepInput[]) => void;
  disabled?: boolean;
}) {
  function update(index: number, patch: Partial<StepInput>) {
    onChange(steps.map((step, i) => (i === index ? { ...step, ...patch } : step)));
  }

  function remove(index: number) {
    onChange(steps.filter((_, i) => i !== index));
  }

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  return (
    <div className="space-y-3">
      {steps.map((step, index) => (
        <div key={index} className="rounded-md border border-slate-200 bg-slate-50 p-4">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent/20 text-xs font-medium text-accent">
              {index + 1}
            </span>
            <select
              className="input w-48 py-1"
              value={step.step_type}
              disabled={disabled}
              aria-label={`Step ${index + 1} type`}
              onChange={(e) => update(index, { step_type: e.target.value as StepType })}
            >
              {STEP_ORDER.map((type) => (
                <option key={type} value={type}>
                  {STEP_LABELS[type]}
                </option>
              ))}
            </select>

            <div className="ml-auto flex gap-1">
              <button
                className="btn-ghost px-2 py-1"
                disabled={disabled || index === 0}
                onClick={() => move(index, -1)}
                aria-label="Move up"
              >
                ↑
              </button>
              <button
                className="btn-ghost px-2 py-1"
                disabled={disabled || index === steps.length - 1}
                onClick={() => move(index, 1)}
                aria-label="Move down"
              >
                ↓
              </button>
              <button
                className="btn-ghost px-2 py-1"
                disabled={disabled}
                onClick={() => remove(index)}
                aria-label="Remove step"
              >
                ✕
              </button>
            </div>
          </div>

          <StepTiming
            step={step}
            isFirst={index === 0}
            disabled={disabled}
            onChange={(patch) => update(index, patch)}
          />

          <div className="mb-3 flex flex-wrap items-center gap-2">
            <select
              className="input w-64 py-1"
              value={step.only_if}
              disabled={disabled}
              aria-label={`Step ${index + 1} condition`}
              onChange={(e) => update(index, { only_if: e.target.value as StepCondition })}
            >
              {(Object.keys(CONDITION_LABELS) as StepCondition[]).map((condition) => (
                <option key={condition} value={condition}>
                  {CONDITION_LABELS[condition]}
                </option>
              ))}
            </select>
            {step.only_if !== "always" && (
              <>
                <span className="text-xs text-slate-500">otherwise</span>
                <select
                  className="input w-44 py-1"
                  value={step.on_condition_fail}
                  disabled={disabled}
                  aria-label={`Step ${index + 1} fallback`}
                  onChange={(e) =>
                    update(index, {
                      on_condition_fail: e.target.value as ConditionFailAction,
                    })
                  }
                >
                  <option value="skip">skip this step</option>
                  <option value="stop">stop the sequence</option>
                </select>
              </>
            )}
          </div>

          {TEMPLATE_STEPS.includes(step.step_type) && !disabled && (
            <TemplateField
              workspaceId={workspaceId}
              step={step}
              onChange={(template) => update(index, { template })}
            />
          )}
          {TEMPLATE_STEPS.includes(step.step_type) && disabled && step.template && (
            <p className="whitespace-pre-wrap text-sm text-slate-700">{step.template}</p>
          )}
        </div>
      ))}

      {!disabled && (
        <StepPalette onAdd={(type) => onChange([...steps, newStepFor(type)])} />
      )}
    </div>
  );
}
