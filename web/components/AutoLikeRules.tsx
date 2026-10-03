"use client";

/**
 * What auto-like may pick: any post, or only posts about chosen topics, and
 * never posts about excluded ones. "Check my feed" shows what the rules would
 * do with the posts cached right now, without liking anything.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  linkedinApi,
  type AutoLikePreview,
  type AutoLikeRules as Rules,
  type AutoLikeRulesResponse,
} from "@/lib/api";

function ChipInput({
  label,
  hint,
  value,
  onChange,
  suggestions,
  tone,
}: {
  label: string;
  hint: string;
  value: string[];
  onChange: (next: string[]) => void;
  suggestions: string[];
  tone: "brand" | "rose";
}) {
  const [draft, setDraft] = useState("");
  const chip = tone === "brand" ? "bg-violet-100 text-violet-800" : "bg-rose-100 text-rose-800";
  function add(text: string) {
    const t = text.trim().slice(0, 60);
    if (!t || value.some((v) => v.toLowerCase() === t.toLowerCase()) || value.length >= 20) return;
    onChange([...value, t]);
    setDraft("");
  }
  const unused = suggestions.filter((s) => !value.some((v) => v.toLowerCase() === s.toLowerCase()));
  return (
    <div>
      <p className="label">{label}</p>
      <p className="mb-2 text-[12px] text-slate-500">{hint}</p>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {value.map((item) => (
          <span key={item} className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-semibold ${chip}`}>
            {item}
            <button type="button" aria-label={`Remove ${item}`} className="opacity-60 hover:opacity-100" onClick={() => onChange(value.filter((v) => v !== item))}>
              ✕
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          className="input min-w-0 flex-1"
          value={draft}
          maxLength={60}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add(draft);
            }
          }}
          placeholder="Type a topic and press Enter"
        />
        <button type="button" className="btn-ghost" disabled={!draft.trim()} onClick={() => add(draft)}>
          Add
        </button>
      </div>
      {unused.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {unused.map((s) => (
            <button
              key={s}
              type="button"
              className="rounded-full border border-dashed border-slate-300 px-2.5 py-0.5 text-[12px] text-slate-600 hover:border-slate-400"
              onClick={() => add(s)}
            >
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function AutoLikeRules({ workspaceId, accountId }: { workspaceId: string; accountId: string }) {
  const [saved, setSaved] = useState<AutoLikeRulesResponse | null>(null);
  const [rules, setRules] = useState<Rules | null>(null);
  const [preview, setPreview] = useState<AutoLikePreview | null>(null);
  const [busy, setBusy] = useState<"save" | "preview" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await linkedinApi.autoLikeRules(workspaceId, accountId);
      setSaved(r);
      setRules({ mode: r.mode, topics: r.topics, exclude: r.exclude, use_ai: r.use_ai });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the like rules");
    }
  }, [workspaceId, accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!rules || !saved) return error ? <p className="text-sm text-state-bad">{error}</p> : null;

  const dirty =
    JSON.stringify(rules) !==
    JSON.stringify({ mode: saved.mode, topics: saved.topics, exclude: saved.exclude, use_ai: saved.use_ai });
  const set = (patch: Partial<Rules>) => {
    setRules({ ...rules, ...patch });
    setPreview(null);
    setNotice(null);
  };

  async function save() {
    if (!rules) return;
    setBusy("save");
    setError(null);
    try {
      const r = await linkedinApi.saveAutoLikeRules(workspaceId, accountId, rules);
      setSaved(r);
      setRules({ mode: r.mode, topics: r.topics, exclude: r.exclude, use_ai: r.use_ai });
      setNotice("Saved. Auto-like will only pick posts these rules allow.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save");
    } finally {
      setBusy(null);
    }
  }

  async function check() {
    if (!rules) return;
    setBusy("preview");
    setError(null);
    try {
      setPreview(await linkedinApi.previewAutoLikeRules(workspaceId, accountId, rules));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not check the feed");
    } finally {
      setBusy(null);
    }
  }

  const topicsMissing = rules.mode === "topics" && rules.topics.length === 0;

  return (
    <div className="mt-4 border-t border-slate-100 pt-4">
      <h3 className="text-[14px] font-bold text-ink-950">What to like</h3>
      <p className="mb-3 text-[12.5px] text-slate-500">
        Choose the kind of posts auto-like may pick. Posts you like yourself with the button below aren&apos;t
        affected.
      </p>

      <div className="mb-4 grid gap-2 sm:grid-cols-2">
        {(
          [
            ["any", "Any post in my feed", "Picks from everything, except the topics you exclude below."],
            ["topics", "Only posts about my topics", "Picks only posts about the topics you list. Nothing else."],
          ] as const
        ).map(([mode, title, body]) => (
          <button
            key={mode}
            type="button"
            onClick={() => set({ mode })}
            className={`rounded-xl border p-3 text-left ${
              rules.mode === mode ? "border-violet-500 bg-violet-50 ring-1 ring-violet-500" : "border-slate-200 hover:border-slate-300"
            }`}
          >
            <p className={`text-[13.5px] font-bold ${rules.mode === mode ? "text-violet-700" : "text-ink-950"}`}>{title}</p>
            <p className="mt-0.5 text-[12px] text-slate-500">{body}</p>
          </button>
        ))}
      </div>

      <div className="space-y-4">
        {rules.mode === "topics" && (
          <ChipInput
            label="Like posts about"
            hint="A post matches if it's mainly about one of these."
            value={rules.topics}
            onChange={(topics) => set({ topics })}
            suggestions={saved.suggested_topics}
            tone="brand"
          />
        )}
        <ChipInput
          label="Never like posts about"
          hint="Always wins, in both modes. Worth keeping sensitive topics here."
          value={rules.exclude}
          onChange={(exclude) => set({ exclude })}
          suggestions={saved.suggested_excludes}
          tone="rose"
        />
        <label className="flex items-start gap-2 text-[13px] text-slate-700">
          <input type="checkbox" className="mt-0.5" checked={rules.use_ai} onChange={(e) => set({ use_ai: e.target.checked })} />
          <span>
            Understand topics with AI
            <span className="block text-[12px] text-slate-500">
              {saved.ai_available
                ? "Matches by meaning: a post about LLMs counts as “AI” even without the word. Off = exact keywords only."
                : "No AI provider is connected, so topics are matched by keywords for now."}
            </span>
          </span>
        </label>
      </div>

      {error && <p className="mt-3 rounded-md border border-state-bad/40 bg-state-bad/10 px-3 py-2 text-sm text-state-bad">{error}</p>}
      {notice && <p className="mt-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{notice}</p>}

      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <button className="btn-ghost" disabled={busy !== null || topicsMissing} onClick={() => void check()}>
          {busy === "preview" ? "Checking…" : "Check against my feed"}
        </button>
        <button className="btn-primary" disabled={!dirty || busy !== null || topicsMissing} onClick={() => void save()}>
          {busy === "save" ? "Saving…" : "Save rules"}
        </button>
      </div>
      {topicsMissing && <p className="mt-2 text-right text-[12px] text-amber-700">Add at least one topic.</p>}

      {preview && (
        <div className="mt-4 rounded-lg border border-slate-200">
          <p className="border-b border-slate-100 px-3 py-2 text-[13px] font-semibold text-ink-950">
            {preview.posts.length === 0
              ? "No posts cached yet. Refresh the feed first."
              : `${preview.matching} of ${preview.posts.length} posts in your current feed would be eligible`}
          </p>
          <ul className="max-h-80 divide-y divide-slate-100 overflow-y-auto">
            {preview.posts.map((post) => (
              <li key={post.urn} className="flex items-start gap-2 px-3 py-2">
                <span className={`mt-0.5 shrink-0 text-[13px] font-bold ${post.would_like ? "text-emerald-600" : "text-slate-300"}`}>
                  {post.would_like ? "✓" : "✕"}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[12px] font-semibold text-slate-700">{post.author_name || "Unknown author"}</p>
                  <p className="line-clamp-2 text-[12px] text-slate-500">{post.text || "(no text)"}</p>
                  <p className="mt-0.5 text-[11.5px] text-slate-400">
                    {post.would_like ? (post.topic ? `About “${post.topic}”` : "Allowed") : post.reason}
                    {post.matched_by === "ai" && " · judged by AI"}
                    {post.liked && " · already liked"}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
