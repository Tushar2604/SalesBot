"use client";

/**
 * The composer's AI panel.
 *
 * Deliberately a *suggestion* surface: every result lands in the editor and
 * waits for the writer. Nothing here can schedule or publish, and the buttons
 * say "Use this", never "Post this".
 */

import { useState } from "react";
import clsx from "clsx";
import { ApiError } from "@/lib/api";
import { contentApi } from "@/lib/content-api";
import { Modal } from "@/components/content/ContentUi";
import { IconSparkle } from "@/components/app/icons";

const IMPROVE_ACTIONS: { key: string; label: string }[] = [
  { key: "rewrite", label: "Rewrite" },
  { key: "shorter", label: "Make shorter" },
  { key: "longer", label: "Make longer" },
  { key: "professional", label: "Make professional" },
  { key: "conversational", label: "Make conversational" },
  { key: "hook", label: "Improve hook" },
  { key: "cta", label: "Add a CTA" },
  { key: "hashtags", label: "Generate hashtags" },
  { key: "grammar", label: "Fix grammar" },
  { key: "variations", label: "Create variations" },
];

const TONES = ["Professional", "Casual", "Technical", "Thought leadership"];
const GOALS = ["Engagement", "Education", "Lead generation", "Announcement"];

export function AiAssistant({
  workspaceId,
  content,
  disabled = false,
  onApply,
}: {
  workspaceId: string;
  content: string;
  disabled?: boolean;
  onApply: (text: string) => void;
}) {
  const [open, setOpen] = useState<null | "improve" | "generate">(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [variants, setVariants] = useState<string[]>([]);
  const [note, setNote] = useState("");

  const [topic, setTopic] = useState("");
  const [audience, setAudience] = useState("");
  const [tone, setTone] = useState(TONES[0]);
  const [goal, setGoal] = useState(GOALS[0]);

  const run = async (label: string, call: () => Promise<{ variants: string[]; note: string }>) => {
    setBusy(label);
    setError("");
    setVariants([]);
    try {
      const result = await call();
      setVariants(result.variants);
      setNote(result.note);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The AI assistant could not be reached.");
    } finally {
      setBusy("");
    }
  };

  const close = () => {
    setOpen(null);
    setVariants([]);
    setError("");
    setNote("");
  };

  const apply = (text: string) => {
    onApply(text);
    close();
  };

  return (
    <>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled || !content.trim()}
          onClick={() => setOpen("improve")}
          title={content.trim() ? undefined : "Write something first"}
          className="btn-ghost !py-1.5 text-[13px]"
        >
          <IconSparkle className="h-4 w-4 text-accent" />
          Improve with AI
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() => setOpen("generate")}
          className="btn-ghost !py-1.5 text-[13px]"
        >
          <IconSparkle className="h-4 w-4 text-violet-500" />
          Generate post
        </button>
      </div>

      {open === "improve" && (
        <Modal
          title="Improve with AI"
          description="Pick a change. The result lands in the editor for you to review."
          wide
          onClose={close}
        >
          <div className="flex flex-wrap gap-2">
            {IMPROVE_ACTIONS.map((action) => (
              <button
                key={action.key}
                type="button"
                disabled={Boolean(busy)}
                onClick={() =>
                  void run(action.key, () =>
                    contentApi.aiImprove(workspaceId, content, action.key),
                  )
                }
                className={clsx(
                  "rounded-full border px-3 py-1.5 text-[12.5px] font-semibold transition-colors",
                  busy === action.key
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-400",
                )}
              >
                {busy === action.key ? "Working…" : action.label}
              </button>
            ))}
          </div>

          <AiResults
            busy={Boolean(busy)}
            error={error}
            note={note}
            variants={variants}
            onApply={apply}
          />
        </Modal>
      )}

      {open === "generate" && (
        <Modal
          title="Generate a post"
          description="Describe what you want to say. You review it before anything is scheduled."
          wide
          onClose={close}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block sm:col-span-2">
              <span className="label">Topic</span>
              <input
                value={topic}
                onChange={(event) => setTopic(event.target.value)}
                placeholder="What we learned migrating 40 customers off spreadsheets"
                className="input"
              />
            </label>
            <label className="block sm:col-span-2">
              <span className="label">Audience</span>
              <input
                value={audience}
                onChange={(event) => setAudience(event.target.value)}
                placeholder="Heads of sales at 50-200 person B2B companies"
                className="input"
              />
            </label>
            <label className="block">
              <span className="label">Tone</span>
              <select value={tone} onChange={(e) => setTone(e.target.value)} className="input">
                {TONES.map((option) => (
                  <option key={option}>{option}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="label">Goal</span>
              <select value={goal} onChange={(e) => setGoal(e.target.value)} className="input">
                {GOALS.map((option) => (
                  <option key={option}>{option}</option>
                ))}
              </select>
            </label>
          </div>

          <button
            type="button"
            disabled={Boolean(busy) || !topic.trim()}
            onClick={() =>
              void run("generate", () =>
                contentApi.aiGenerate(workspaceId, {
                  topic,
                  audience,
                  tone: tone.toLowerCase(),
                  goal: goal.toLowerCase(),
                }),
              )
            }
            className="btn-primary mt-4"
          >
            {busy ? "Generating…" : "Generate"}
          </button>

          <AiResults
            busy={Boolean(busy)}
            error={error}
            note={note}
            variants={variants}
            onApply={apply}
          />
        </Modal>
      )}
    </>
  );
}

function AiResults({
  busy,
  error,
  note,
  variants,
  onApply,
}: {
  busy: boolean;
  error: string;
  note: string;
  variants: string[];
  onApply: (text: string) => void;
}) {
  if (error) {
    return <p className="mt-4 text-[13px] text-state-bad">{error}</p>;
  }
  if (busy) {
    return (
      <div className="mt-4 space-y-2" aria-hidden>
        <div className="h-2.5 w-full animate-pulse rounded bg-slate-100" />
        <div className="h-2.5 w-10/12 animate-pulse rounded bg-slate-100" />
        <div className="h-2.5 w-7/12 animate-pulse rounded bg-slate-100" />
      </div>
    );
  }
  if (variants.length === 0) return null;

  return (
    <div className="mt-4 space-y-3">
      {note && <p className="text-[12.5px] text-slate-500">{note}</p>}
      {variants.map((variant, index) => (
        <div key={index} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-slate-800">
            {variant}
          </p>
          <div className="mt-2.5 flex items-center justify-between">
            <span className="text-[12px] text-slate-500">{variant.length} characters</span>
            <button
              type="button"
              onClick={() => onApply(variant)}
              className="btn-primary !py-1.5 text-[13px]"
            >
              Use this
            </button>
          </div>
        </div>
      ))}
      <p className="text-[12px] text-slate-500">
        Nothing is published automatically. Review the text, then schedule or publish it yourself.
      </p>
    </div>
  );
}
