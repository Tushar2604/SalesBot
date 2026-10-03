"use client";

/**
 * Named assistants: one per kind of conversation.
 *
 * An HR campaign, a customer follow-up and an internal-team campaign need
 * different voices, different questions and different SOPs. Each campaign
 * picks one of these; a thread from that campaign is answered by it, from its
 * own SOPs plus the shared ones. Threads from no campaign (or a campaign that
 * picks none) use the Default assistant, whose settings live on the workspace.
 *
 * Pace and daily limits stay workspace-wide, and the workspace mode is the
 * master switch: an assistant can be quieter than it ("draft only", "off"),
 * never louder.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ApiError } from "@/lib/api";
import {
  assistantApi,
  type AssistantProfile,
  type AssistantProfileInput,
  type AssistantSettings,
  type ProfileMode,
} from "@/lib/assistant-api";
import { campaignsApi, type Campaign } from "@/lib/outreach-api";
import { IconPlus, IconTrash } from "@/components/app/icons";

export const DEFAULT_ASSISTANT = "default";

export const PROFILE_MODES: { key: ProfileMode; label: string; hint: string }[] = [
  { key: "inherit", label: "Follow the workspace mode", hint: "Drafts or replies by itself, as set under Mode above." },
  { key: "draft", label: "Draft only", hint: "Always suggests; a person sends. Even when the workspace is on auto." },
  { key: "off", label: "Off", hint: "Stays silent in these conversations. You can still ask it for a draft." },
];

const RECRUITER_FIELDS = [
  "current role",
  "total years of experience",
  "notice period",
  "current location",
  "open to relocation",
  "current CTC",
  "expected CTC",
  "email",
];

type Template = { key: string; label: string; values: Omit<AssistantProfileInput, "name"> };

const TEMPLATES: Template[] = [
  {
    key: "blank",
    label: "Start blank",
    values: { mode: "inherit", persona: "", instructions: "", handoff_topics: "", collect_fields: [] },
  },
  {
    key: "recruiter",
    label: "HR / recruiting",
    values: {
      mode: "inherit",
      persona: "I'm the recruiter hiring for our open roles.",
      instructions:
        "Friendly and brief. If they're interested, share the relevant part of the job description, then find out " +
        "the details below one at a time. If they're not looking, thank them and ask if you can keep in touch.",
      handoff_topics: "salary negotiation, offer letters, visa questions, complaints",
      collect_fields: RECRUITER_FIELDS,
    },
  },
  {
    key: "followup",
    label: "Sales follow-up",
    values: {
      mode: "draft",
      persona: "I work on partnerships and help teams like theirs with our product.",
      instructions:
        "Relaxed and helpful, never pushy. Answer questions from the SOPs, and if they're interested suggest a short " +
        "call. If they say no, accept it warmly.",
      handoff_topics: "pricing not in the SOPs, discounts, contracts, meeting times, complaints",
      collect_fields: ["what they're working on", "best email", "a good time for a short call"],
    },
  },
  {
    key: "team",
    label: "Internal team",
    values: {
      mode: "draft",
      persona: "I'm a teammate checking in with people on our own team.",
      instructions: "Casual and short, like messaging a colleague. Follow the team SOPs for updates and next steps.",
      handoff_topics: "HR matters, performance, anything personal or sensitive",
      collect_fields: [],
    },
  },
];

/** The workspace's named assistants, loaded once and kept in sync by the editor. */
export function useAssistantProfiles(workspaceId: string | null) {
  const [profiles, setProfiles] = useState<AssistantProfile[]>([]);
  const reload = useCallback(async () => {
    if (!workspaceId) return;
    try {
      setProfiles(await assistantApi.profiles(workspaceId));
    } catch {
      setProfiles([]);
    }
  }, [workspaceId]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { profiles, setProfiles, reload };
}

export function CollectFields({ value, onChange }: { value: string[]; onChange: (next: string[]) => void }) {
  const [draft, setDraft] = useState("");
  function add() {
    const item = draft.trim();
    if (!item || value.some((v) => v.toLowerCase() === item.toLowerCase())) return;
    onChange([...value, item].slice(0, 15));
    setDraft("");
  }
  return (
    <div>
      {value.length > 0 ? (
        <ol className="mb-3 space-y-1.5">
          {value.map((item, i) => (
            <li key={item} className="flex items-center gap-2 rounded-md border border-slate-200 px-3 py-1.5 text-sm">
              <span className="w-5 text-slate-400">{i + 1}.</span>
              <span className="flex-1 text-slate-800">{item}</span>
              <button
                type="button"
                className="text-xs text-slate-400 hover:text-slate-700 disabled:opacity-30"
                disabled={i === 0}
                aria-label={`Move ${item} up`}
                onClick={() => {
                  const next = [...value];
                  [next[i - 1], next[i]] = [next[i], next[i - 1]];
                  onChange(next);
                }}
              >
                ↑
              </button>
              <button
                type="button"
                className="text-xs text-slate-400 hover:text-state-bad"
                aria-label={`Remove ${item}`}
                onClick={() => onChange(value.filter((v) => v !== item))}
              >
                ✕
              </button>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mb-3 text-[13px] text-slate-400">Nothing to collect: the assistant just answers questions.</p>
      )}
      <div className="flex flex-wrap gap-2">
        <input
          className="input min-w-0 flex-1"
          value={draft}
          maxLength={80}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder="e.g. notice period"
        />
        <button type="button" className="btn-ghost" onClick={add} disabled={!draft.trim()}>
          Add
        </button>
        <button type="button" className="btn-ghost" onClick={() => onChange(RECRUITER_FIELDS)}>
          Use recruiter preset
        </button>
      </div>
    </div>
  );
}

type Fields = Pick<AssistantProfileInput, "persona" | "instructions" | "handoff_topics" | "collect_fields">;

function fieldsOf(x: Fields): Fields {
  return {
    persona: x.persona,
    instructions: x.instructions,
    handoff_topics: x.handoff_topics,
    collect_fields: x.collect_fields,
  };
}

function NewAssistant({
  onCreate,
  onCancel,
}: {
  onCreate: (input: AssistantProfileInput) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("recruiter");
  const [busy, setBusy] = useState(false);
  return (
    <div className="mb-4 rounded-lg border border-dashed border-violet-300 bg-violet-50/30 p-3">
      <label className="label">Name</label>
      <input
        className="input mb-3"
        value={name}
        maxLength={120}
        autoFocus
        onChange={(e) => setName(e.target.value)}
        placeholder="e.g. HR recruiter, Customer follow-up, Internal team"
      />
      <p className="label">Start from</p>
      <div className="mb-3 flex flex-wrap gap-1.5">
        {TEMPLATES.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTemplate(t.key)}
            className={`rounded-full border px-3 py-1 text-[12px] font-semibold ${
              template === t.key
                ? "border-violet-500 bg-violet-50 text-violet-700"
                : "border-slate-200 text-slate-600 hover:border-slate-300"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="btn-primary px-3 py-1.5 text-xs"
          disabled={busy || !name.trim()}
          onClick={async () => {
            setBusy(true);
            try {
              const values = TEMPLATES.find((t) => t.key === template)?.values ?? TEMPLATES[0].values;
              await onCreate({ name: name.trim(), ...values });
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Creating…" : "Create assistant"}
        </button>
      </div>
    </div>
  );
}

/**
 * The assistants list and the editor for the selected one. The Default
 * assistant's fields are the workspace settings (saved through `onSaveDefault`,
 * which applies the page's risk guard); named ones save to their own rows.
 */
export function AssistantsSection({
  workspaceId,
  settings,
  onSaveDefault,
  profiles,
  setProfiles,
}: {
  workspaceId: string;
  settings: AssistantSettings;
  onSaveDefault: (patch: Fields) => Promise<boolean>;
  profiles: AssistantProfile[];
  setProfiles: (next: AssistantProfile[]) => void;
}) {
  const [selected, setSelected] = useState<string>(DEFAULT_ASSISTANT);
  const [creating, setCreating] = useState(false);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    campaignsApi
      .list(workspaceId)
      .then(setCampaigns)
      .catch(() => setCampaigns([]));
  }, [workspaceId]);

  const profile = profiles.find((p) => p.id === selected) ?? null;
  const isDefault = profile === null;
  const source: Fields = isDefault ? fieldsOf(settings) : fieldsOf(profile);

  const [fields, setFields] = useState<Fields>(source);
  const [name, setName] = useState(profile?.name ?? "");
  const [mode, setMode] = useState<ProfileMode>(profile?.mode ?? "inherit");
  // Re-seed the form whenever a different assistant is picked or it reloads.
  const sourceKey = JSON.stringify([selected, source, profile?.name, profile?.mode]);
  useEffect(() => {
    setFields(source);
    setName(profile?.name ?? "");
    setMode(profile?.mode ?? "inherit");
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceKey]);

  const usedBy = useMemo(
    () =>
      campaigns.filter((c) => (isDefault ? !c.assistant_id : c.assistant_id === selected)).map((c) => c.name),
    [campaigns, isDefault, selected],
  );

  const dirty =
    JSON.stringify(fields) !== JSON.stringify(source) ||
    (!isDefault && (name.trim() !== profile.name || mode !== profile.mode));

  function flash() {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  async function save() {
    setError(null);
    try {
      if (isDefault) {
        if (await onSaveDefault(fields)) flash();
        return;
      }
      const updated = await assistantApi.updateProfile(workspaceId, profile.id, {
        ...fields,
        name: name.trim(),
        mode,
      });
      setProfiles(profiles.map((p) => (p.id === updated.id ? updated : p)));
      flash();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the assistant");
    }
  }

  async function remove() {
    if (!profile) return;
    const note = usedBy.length
      ? `\n\n${usedBy.length} campaign(s) use it and will go back to the Default assistant.`
      : "";
    if (!window.confirm(`Delete the assistant "${profile.name}"?${note}`)) return;
    try {
      await assistantApi.deleteProfile(workspaceId, profile.id);
      setProfiles(profiles.filter((p) => p.id !== profile.id));
      setSelected(DEFAULT_ASSISTANT);
      setCampaigns((prev) => prev.map((c) => (c.assistant_id === profile.id ? { ...c, assistant_id: null } : c)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete the assistant");
    }
  }

  const chip = (active: boolean) =>
    `rounded-full border px-3 py-1.5 text-[12.5px] font-semibold transition-colors ${
      active ? "border-violet-500 bg-violet-50 text-violet-700" : "border-slate-200 text-slate-600 hover:border-slate-300"
    }`;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        <button type="button" className={chip(isDefault)} onClick={() => setSelected(DEFAULT_ASSISTANT)}>
          Default assistant
        </button>
        {profiles.map((p) => (
          <button key={p.id} type="button" className={chip(selected === p.id)} onClick={() => setSelected(p.id)}>
            {p.name}
            {p.mode !== "inherit" && <span className="ml-1 font-normal text-slate-400">· {p.mode === "off" ? "off" : "draft only"}</span>}
          </button>
        ))}
        {!creating && (
          <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={() => setCreating(true)}>
            <IconPlus className="h-3.5 w-3.5" /> New assistant
          </button>
        )}
      </div>

      {creating && (
        <NewAssistant
          onCancel={() => setCreating(false)}
          onCreate={async (input) => {
            try {
              const created = await assistantApi.createProfile(workspaceId, input);
              setProfiles([...profiles, created]);
              setSelected(created.id);
              setCreating(false);
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "Could not create the assistant");
            }
          }}
        />
      )}

      {error && (
        <p className="mb-3 rounded-md border border-state-bad/40 bg-state-bad/10 px-3 py-2 text-sm text-state-bad">{error}</p>
      )}

      <div className="mb-4 rounded-md bg-slate-50 px-3 py-2 text-[12.5px] text-slate-600">
        {isDefault ? (
          <>Answers conversations that didn&apos;t come from a campaign, and campaigns that don&apos;t pick an assistant.</>
        ) : (
          <>Answers leads from the campaigns that pick it, using its own SOPs plus the shared ones.</>
        )}{" "}
        {usedBy.length > 0 ? (
          <span className="font-semibold">Used by: {usedBy.join(", ")}.</span>
        ) : isDefault ? null : (
          <span className="font-semibold">
            No campaign uses it yet: pick it when creating a campaign, or on a campaign&apos;s page under{" "}
            <Link href="/campaigns" className="text-violet-700 hover:underline">
              Campaigns
            </Link>
            .
          </span>
        )}
      </div>

      {!isDefault && (
        <div className="mb-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Name</label>
            <input className="input" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="label">In its conversations</label>
            <select className="input" value={mode} onChange={(e) => setMode(e.target.value as ProfileMode)}>
              {PROFILE_MODES.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11.5px] text-slate-400">{PROFILE_MODES.find((m) => m.key === mode)?.hint}</p>
          </div>
        </div>
      )}

      <label className="label">Who it speaks as</label>
      <textarea
        className="input mb-4 h-20"
        value={fields.persona}
        onChange={(e) => setFields({ ...fields, persona: e.target.value })}
        placeholder="e.g. I'm Priya, the talent acquisition lead at Acme. We're hiring engineers in Bengaluru and remote."
      />
      <label className="label">How to reply</label>
      <textarea
        className="input mb-4 h-24"
        value={fields.instructions}
        onChange={(e) => setFields({ ...fields, instructions: e.target.value })}
        placeholder="e.g. Friendly and brief. If someone is interested, ask for their CV and notice period."
      />
      <label className="label">Always hand these to me</label>
      <input
        className="input mb-4"
        value={fields.handoff_topics}
        onChange={(e) => setFields({ ...fields, handoff_topics: e.target.value })}
        placeholder="e.g. salary negotiation, offer letters, visa questions, complaints"
      />
      <p className="label">What to find out</p>
      <p className="mb-2 text-[12px] text-slate-500">
        One at a time, in this order, woven into the chat. It never re-asks, saves every answer to the lead, and hands
        the conversation to you once everything is collected.
      </p>
      <CollectFields
        value={fields.collect_fields}
        onChange={(next) => setFields({ ...fields, collect_fields: next })}
      />

      <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
        {saved && <span className="mr-auto text-[12px] font-semibold text-emerald-700">Saved</span>}
        {!isDefault && (
          <button type="button" className="btn-ghost mr-auto text-state-bad" onClick={() => void remove()}>
            <IconTrash className="h-4 w-4" /> Delete assistant
          </button>
        )}
        <button className="btn-primary" disabled={!dirty || (!isDefault && !name.trim())} onClick={() => void save()}>
          Save
        </button>
      </div>
    </div>
  );
}

/** A select for "which assistant answers this campaign's leads". */
export function AssistantSelect({
  profiles,
  value,
  onChange,
  disabled,
}: {
  profiles: AssistantProfile[];
  value: string | null;
  onChange: (next: string | null) => void;
  disabled?: boolean;
}) {
  return (
    <select
      className="input"
      value={value ?? DEFAULT_ASSISTANT}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value === DEFAULT_ASSISTANT ? null : e.target.value)}
    >
      <option value={DEFAULT_ASSISTANT}>Default assistant</option>
      {profiles.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
          {p.mode === "off" ? " (off)" : p.mode === "draft" ? " (draft only)" : ""}
        </option>
      ))}
    </select>
  );
}
