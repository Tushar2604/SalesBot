"use client";

/**
 * AI Assistant — how the inbox bot behaves.
 *
 *  Mode         off / draft (suggests, you send) / auto (sends by itself)
 *  Who it is    the person or team it speaks for, tone, topics to hand off
 *  Knowledge    what it may share: job descriptions, FAQs, product facts
 *  Limits       reply pace and daily caps
 *  Try it       a pretend conversation to see its decision; sends nothing
 *
 * The bot only ever runs in workers; this page configures it.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import {
  assistantApi,
  type AssistantMode,
  type AssistantSettings,
  type KnowledgeItem,
  type TryResult,
  type TryTurn,
} from "@/lib/assistant-api";
import { IconSparkle, IconTrash } from "@/components/app/icons";

const MODES: { key: AssistantMode; title: string; body: string }[] = [
  { key: "off", title: "Off", body: "The assistant does nothing. You handle every message." },
  {
    key: "draft",
    title: "Draft replies",
    body: "It writes a reply for each new message. You read it, edit if needed, and send. Best way to start.",
  },
  {
    key: "auto",
    title: "Reply automatically",
    body: "It sends replies itself after a short, human-like pause, and stops as soon as you step in.",
  },
];

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="card">
      <h2 className="text-[15px] font-bold text-ink-950">{title}</h2>
      {hint && <p className="mb-4 mt-0.5 text-[13px] text-slate-500">{hint}</p>}
      {!hint && <div className="mb-4" />}
      {children}
    </section>
  );
}

function KnowledgeRow({
  item,
  onSave,
  onDelete,
}: {
  item: KnowledgeItem;
  onSave: (patch: Partial<KnowledgeItem>) => Promise<void>;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [content, setContent] = useState(item.content);
  const dirty = title !== item.title || content !== item.content;

  return (
    <li className="rounded-lg border border-slate-200">
      <div className="flex items-center gap-3 px-3 py-2.5">
        <button onClick={() => setOpen((v) => !v)} className="min-w-0 flex-1 text-left">
          <p className={`truncate text-[13.5px] font-semibold ${item.enabled ? "text-ink-950" : "text-slate-400 line-through"}`}>
            {item.title}
          </p>
          <p className="truncate text-[12px] text-slate-400">{item.content.slice(0, 120)}</p>
        </button>
        <label className="flex items-center gap-1.5 text-[12px] text-slate-500">
          <input type="checkbox" checked={item.enabled} onChange={(e) => void onSave({ enabled: e.target.checked })} />
          Use
        </label>
        <button aria-label="Delete" className="text-slate-400 hover:text-state-bad" onClick={onDelete}>
          <IconTrash className="h-4 w-4" />
        </button>
      </div>
      {open && (
        <div className="space-y-2 border-t border-slate-100 p-3">
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
          <textarea className="input h-40" value={content} onChange={(e) => setContent(e.target.value)} />
          <div className="flex justify-end">
            <button
              className="btn-primary px-3 py-1.5 text-xs"
              disabled={!dirty || !title.trim() || !content.trim()}
              onClick={() => void onSave({ title: title.trim(), content: content.trim() })}
            >
              Save changes
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

function TryIt({ workspaceId }: { workspaceId: string }) {
  const [turns, setTurns] = useState<TryTurn[]>([
    { from_me: true, text: "Hi! We're hiring a Backend Engineer at our company — would you be open to hearing more?" },
  ]);
  const [message, setMessage] = useState("Yes, can you share the job description? My email is ravi@example.com");
  const [result, setResult] = useState<TryResult | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    if (!message.trim()) return;
    const convo = [...turns, { from_me: false, text: message.trim() }];
    setBusy(true);
    setResult(null);
    try {
      const r = await assistantApi.tryIt(workspaceId, convo);
      setTurns(r.action === "reply" ? [...convo, { from_me: true, text: r.reply }] : convo);
      setResult(r);
      setMessage("");
    } catch (err) {
      setResult({ action: "unavailable", reply: "", handoff_reason: err instanceof ApiError ? err.message : "", shared_facts: [] });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="mb-3 max-h-80 space-y-2 overflow-y-auto rounded-lg bg-slate-50 p-3">
        {turns.map((t, i) => (
          <div key={i} className={`flex ${t.from_me ? "justify-end" : "justify-start"}`}>
            <p
              className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-[13px] ${
                t.from_me ? "rounded-br-sm bg-violet-600 text-white" : "rounded-bl-sm bg-white text-ink-950 shadow-sm"
              }`}
            >
              {t.text}
            </p>
          </div>
        ))}
      </div>

      {result && result.action !== "reply" && (
        <p
          className={`mb-3 rounded-md px-3 py-2 text-[12.5px] ${
            result.action === "handoff" ? "bg-amber-50 text-amber-800" : "bg-slate-100 text-slate-600"
          }`}
        >
          {result.action === "handoff" && <>It would hand this to you: {result.handoff_reason}</>}
          {result.action === "no_reply" && <>It would not reply: nothing needs saying.</>}
          {result.action === "unavailable" && (
            <>The assistant couldn&apos;t answer. Most often no OpenAI or Gemini key is set, or both providers failed.</>
          )}
        </p>
      )}
      {result && result.shared_facts.length > 0 && (
        <p className="mb-3 text-[12.5px] text-slate-600">
          <span className="font-semibold">It noted:</span>{" "}
          {result.shared_facts.map((f) => `${f.field.replace(/_/g, " ")}: ${f.value}`).join(" · ")}
        </p>
      )}

      <div className="flex gap-2">
        <input
          className="input flex-1"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void run()}
          placeholder="Write as the prospect…"
        />
        <button className="btn-primary shrink-0" disabled={busy || !message.trim()} onClick={() => void run()}>
          {busy ? "Thinking…" : "Try"}
        </button>
        <button className="btn-ghost shrink-0" onClick={() => { setTurns([]); setResult(null); }}>
          Reset
        </button>
      </div>
      <p className="mt-2 text-[11.5px] text-slate-400">Nothing here is sent to LinkedIn.</p>
    </div>
  );
}

export default function AssistantPage() {
  const { workspace } = useSession();
  const workspaceId = workspace?.id ?? null;

  const [settings, setSettings] = useState<AssistantSettings | null>(null);
  const [form, setForm] = useState<AssistantSettings | null>(null);
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const [s, k] = await Promise.all([assistantApi.settings(workspaceId), assistantApi.knowledge(workspaceId)]);
      setSettings(s);
      setForm(s);
      setItems(k);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the assistant settings");
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(patch: Partial<AssistantSettings>) {
    if (!workspaceId) return;
    try {
      const { ai_available: _ignored, ...rest } = { ...form!, ...patch };
      const next = await assistantApi.saveSettings(workspaceId, rest);
      setSettings(next);
      setForm(next);
      setError(null);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save");
    }
  }

  async function addItem() {
    if (!workspaceId || !newTitle.trim() || !newContent.trim()) return;
    try {
      const item = await assistantApi.createKnowledge(workspaceId, { title: newTitle.trim(), content: newContent.trim() });
      setItems((prev) => [item, ...prev]);
      setNewTitle("");
      setNewContent("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add it");
    }
  }

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;
  if (!form || !settings) return <p className="text-sm text-slate-400">{error ?? "Loading…"}</p>;

  const dirty = JSON.stringify(form) !== JSON.stringify(settings);
  const field = <K extends keyof AssistantSettings>(key: K, value: AssistantSettings[K]) =>
    setForm({ ...form, [key]: value });

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-ink-950">
            <IconSparkle className="h-6 w-6 text-violet-600" /> AI Assistant
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Answers your LinkedIn messages using what you teach it, and hands anything else to you.
          </p>
        </div>
        {saved && <span className="rounded-full bg-emerald-50 px-3 py-1 text-[12px] font-semibold text-emerald-700">Saved</span>}
      </div>

      {!settings.ai_available && (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <span className="font-semibold">No AI provider connected yet.</span> Set <code>OPENAI_API_KEY</code> (and
          optionally <code>GEMINI_API_KEY</code> as a fallback) in the server&apos;s <code>.env</code>, then restart the
          api and worker. Until then the assistant stays silent.
        </p>
      )}
      {error && <p className="rounded-md border border-state-bad/40 bg-state-bad/10 px-4 py-3 text-sm text-state-bad">{error}</p>}

      <Section title="Mode" hint="Whatever the mode, the assistant steps back in a conversation the moment you type or reply there.">
        <div className="grid gap-3 sm:grid-cols-3">
          {MODES.map((m) => {
            const active = settings.mode === m.key;
            return (
              <button
                key={m.key}
                onClick={() => void save({ mode: m.key })}
                className={`rounded-xl border p-4 text-left transition-colors ${
                  active ? "border-violet-500 bg-violet-50 ring-1 ring-violet-500" : "border-slate-200 hover:border-slate-300"
                }`}
              >
                <p className={`text-[14px] font-bold ${active ? "text-violet-700" : "text-ink-950"}`}>{m.title}</p>
                <p className="mt-1 text-[12.5px] text-slate-500">{m.body}</p>
              </button>
            );
          })}
        </div>
      </Section>

      <Section title="Who it speaks as" hint="Replies go out under your name, so tell it who you are and how you write.">
        <label className="label">About you</label>
        <textarea
          className="input mb-4 h-24"
          value={form.persona}
          onChange={(e) => field("persona", e.target.value)}
          placeholder="e.g. I'm Priya, the talent acquisition lead at Acme. We're hiring engineers in Bengaluru and remote."
        />
        <label className="label">How to reply</label>
        <textarea
          className="input mb-4 h-24"
          value={form.instructions}
          onChange={(e) => field("instructions", e.target.value)}
          placeholder="e.g. Friendly and brief. If someone is interested, ask for their CV and notice period. Sign off with 'Priya'."
        />
        <label className="label">Always hand these to me</label>
        <input
          className="input"
          value={form.handoff_topics}
          onChange={(e) => field("handoff_topics", e.target.value)}
          placeholder="e.g. salary negotiation, offer letters, visa questions, complaints"
        />
        <div className="mt-4 flex justify-end">
          <button className="btn-primary" disabled={!dirty} onClick={() => void save({})}>
            Save
          </button>
        </div>
      </Section>

      <Section
        title="Knowledge"
        hint="The only things it may share. Add each job description, FAQ answer or product detail as its own item. Anything not covered here gets handed to you."
      >
        <div className="mb-4 space-y-2 rounded-lg border border-dashed border-slate-300 p-3">
          <input
            className="input"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="Title, e.g. Job description — Backend Engineer"
          />
          <textarea
            className="input h-32"
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            placeholder="Paste the content: responsibilities, requirements, location, how to apply…"
          />
          <div className="flex justify-end">
            <button className="btn-primary px-3 py-1.5 text-xs" disabled={!newTitle.trim() || !newContent.trim()} onClick={() => void addItem()}>
              Add to knowledge
            </button>
          </div>
        </div>
        {items.length === 0 ? (
          <p className="text-[13px] text-slate-400">Nothing yet. With an empty knowledge base it hands every question to you.</p>
        ) : (
          <ul className="space-y-2">
            {items.map((item) => (
              <KnowledgeRow
                key={item.id}
                item={item}
                onSave={async (patch) => {
                  const updated = await assistantApi.updateKnowledge(workspaceId, item.id, patch);
                  setItems((prev) => prev.map((i) => (i.id === item.id ? updated : i)));
                }}
                onDelete={() =>
                  void assistantApi
                    .deleteKnowledge(workspaceId, item.id)
                    .then(() => setItems((prev) => prev.filter((i) => i.id !== item.id)))
                }
              />
            ))}
          </ul>
        )}
      </Section>

      <Section title="Pace and limits" hint="Keeps replies looking human and stops a runaway conversation.">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Wait before replying (minutes)</label>
            <div className="flex items-center gap-2">
              <input type="number" min={1} className="input w-24" value={form.reply_delay_min_minutes}
                onChange={(e) => field("reply_delay_min_minutes", Number(e.target.value))} />
              <span className="text-sm text-slate-500">to</span>
              <input type="number" min={1} className="input w-24" value={form.reply_delay_max_minutes}
                onChange={(e) => field("reply_delay_max_minutes", Number(e.target.value))} />
            </div>
          </div>
          <div>
            <label className="label">Only during working hours</label>
            <label className="flex items-center gap-2 text-sm text-slate-600">
              <input type="checkbox" checked={form.working_hours_only} onChange={(e) => field("working_hours_only", e.target.checked)} />
              Hold replies until the account&apos;s working hours
            </label>
          </div>
          <div>
            <label className="label">Replies per conversation per day</label>
            <input type="number" min={1} max={20} className="input w-24" value={form.max_replies_per_thread_per_day}
              onChange={(e) => field("max_replies_per_thread_per_day", Number(e.target.value))} />
          </div>
          <div>
            <label className="label">Automatic replies per account per day</label>
            <input type="number" min={1} max={100} className="input w-24" value={form.max_replies_per_account_per_day}
              onChange={(e) => field("max_replies_per_account_per_day", Number(e.target.value))} />
            <p className="mt-1 text-[11.5px] text-slate-400">Past this, new replies are saved as drafts for you.</p>
          </div>
        </div>
        <div className="mt-4 flex justify-end">
          <button className="btn-primary" disabled={!dirty} onClick={() => void save({})}>
            Save
          </button>
        </div>
      </Section>

      <Section title="Try it" hint="Play the prospect and see what the assistant would do with your current settings and knowledge.">
        <TryIt workspaceId={workspaceId} />
      </Section>
    </div>
  );
}
