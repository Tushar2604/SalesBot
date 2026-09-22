import type { StepInput } from "@/lib/outreach-api";
import provenJson from "@/lib/proven-templates.json";

export type SavedTemplate = {
  id: string;
  name: string;
  description: string;
  steps: StepInput[];
  createdAt: string;
};

/** A ready-made sequence that ships with the app. Read-only; "Select" copies it. */
export type ProvenTemplate = {
  id: string;
  name: string;
  description: string;
  best_for: string;
  steps: StepInput[];
};

/**
 * The library. Kept in JSON so the same file can be validated against the
 * backend's own sequence rules (ordering, note length, template syntax).
 */
export const PROVEN_TEMPLATES = provenJson as ProvenTemplate[];

/** sessionStorage key used to hand a template's steps to the campaign wizard. */
export const TEMPLATE_HANDOFF_KEY = "salesrobo.template-handoff";

/** A copy that is safe to edit: never hand out the library's own step objects. */
export function cloneSteps(steps: StepInput[]): StepInput[] {
  return steps.map((step) => ({ ...step }));
}

/** What a user starts from when they pick "From scratch". */
export function scratchSteps(): StepInput[] {
  return [
    {
      step_type: "view_profile",
      delay_hours: 0,
      only_if: "always",
      on_condition_fail: "skip",
      template: "",
      timing: "smart",
    },
  ];
}
