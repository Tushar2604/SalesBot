"use client";

/**
 * SOPs: what the inbox assistant answers from.
 *
 * Each SOP is attached to one or more assistants (none = every assistant) and
 * to one or more LinkedIn accounts (none = every account). When an assistant
 * drafts a reply in a thread it reads the SOPs attached to it and to the
 * account that thread is on, plus the shared ones, so the HR recruiter's job
 * descriptions never reach an internal-team conversation.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, linkedinApi, type LinkedInAccount } from "@/lib/api";
import { assistantApi, type AssistantProfile, type KnowledgeItem } from "@/lib/assistant-api";
import { IconPencil, IconSearch, IconTrash, IconUpload } from "@/components/app/icons";

const MAX_CONTENT = 50_000;
// Plain-text formats the browser can read as-is. PDFs and Word files need a
// parser, so for those people paste the text instead.
const UPLOAD_ACCEPT = ".txt,.md,.markdown,.csv,.json,.html,.htm,text/*";

function accountName(a: LinkedInAccount): string {
  return a.label || a.full_name || a.login_email || a.public_id || "LinkedIn account";
}

function AccountPicker({
  accounts,
  value,
  onChange,
}: {
  accounts: LinkedInAccount[];
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const all = value.length === 0;
  const chip = (active: boolean) =>
    `rounded-full border px-3 py-1 text-[12px] font-semibold transition-colors ${
      active ? "border-violet-500 bg-violet-50 text-violet-700" : "border-slate-200 text-slate-600 hover:border-slate-300"
    }`;
  return (
    <div>
      <p className="label">Attach to LinkedIn accounts</p>
      <div className="flex flex-wrap gap-1.5">
        <button type="button" className={chip(all)} onClick={() => onChange([])}>
          All accounts
        </button>
        {accounts.map((a) => {
          const on = value.includes(a.id);
          return (
            <button
              type="button"
              key={a.id}
              className={chip(on)}
              onClick={() => onChange(on ? value.filter((id) => id !== a.id) : [...value, a.id])}
            >
              {accountName(a)}
            </button>
          );
        })}
      </div>
      <p className="mt-1 text-[11.5px] text-slate-400">
        {all
          ? "Used in conversations on every LinkedIn account."
          : "Used only in conversations on the selected accounts."}
      </p>
    </div>
  );
}

function AssistantPicker({
  profiles,
  value,
  onChange,
}: {
  profiles: AssistantProfile[];
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const all = value.length === 0;
  const chip = (active: boolean) =>
    `rounded-full border px-3 py-1 text-[12px] font-semibold transition-colors ${
      active ? "border-violet-500 bg-violet-50 text-violet-700" : "border-slate-200 text-slate-600 hover:border-slate-300"
    }`;
  return (
    <div>
      <p className="label">Used by assistants</p>
      <div className="flex flex-wrap gap-1.5">
        <button type="button" className={chip(all)} onClick={() => onChange([])}>
          All assistants
        </button>
        {profiles.map((p) => {
          const on = value.includes(p.id);
          return (
            <button
              type="button"
              key={p.id}
              className={chip(on)}
              onClick={() => onChange(on ? value.filter((id) => id !== p.id) : [...value, p.id])}
            >
              {p.name}
            </button>
          );
        })}
      </div>
      <p className="mt-1 text-[11.5px] text-slate-400">
        {all
          ? "Shared: every assistant reads it, the Default one included."
          : "Only the selected assistants read it, so only in their campaigns' conversations."}
      </p>
    </div>
  );
}

function readTextFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

type SopValue = { title: string; content: string; linkedin_account_ids: string[]; assistant_ids: string[] };

function SopEditor({
  accounts,
  profiles,
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  accounts: LinkedInAccount[];
  profiles: AssistantProfile[];
  initial: SopValue;
  submitLabel: string;
  onSubmit: (value: SopValue) => Promise<void>;
  onCancel?: () => void;
}) {
  const [title, setTitle] = useState(initial.title);
  const [content, setContent] = useState(initial.content);
  const [accountIds, setAccountIds] = useState<string[]>(initial.linkedin_account_ids);
  const [assistantIds, setAssistantIds] = useState<string[]>(initial.assistant_ids);
  const [busy, setBusy] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setFileError(null);
    if (/\.(pdf|docx?|pptx?|xlsx?)$/i.test(file.name)) {
      setFileError("PDF and Office files can't be read here yet. Open the file, copy its text and paste it below.");
      return;
    }
    try {
      const text = (await readTextFile(file)).trim();
      if (!text) {
        setFileError("That file is empty.");
        return;
      }
      if (text.length > MAX_CONTENT) setFileError(`Only the first ${MAX_CONTENT.toLocaleString()} characters are kept.`);
      setContent(text.slice(0, MAX_CONTENT));
      if (!title.trim()) setTitle(file.name.replace(/\.[^.]+$/, "").slice(0, 200));
    } catch {
      setFileError("Could not read that file.");
    }
  }

  const changed =
    title !== initial.title ||
    content !== initial.content ||
    JSON.stringify([...accountIds].sort()) !== JSON.stringify([...initial.linkedin_account_ids].sort()) ||
    JSON.stringify([...assistantIds].sort()) !== JSON.stringify([...initial.assistant_ids].sort());

  return (
    <div className="space-y-3">
      <input
        className="input"
        value={title}
        maxLength={200}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="SOP name, e.g. Backend Engineer hiring — Acme"
      />
      <div>
        <textarea
          className="input h-40"
          value={content}
          maxLength={MAX_CONTENT}
          onChange={(e) => setContent(e.target.value)}
          placeholder={
            "What the assistant should know and how it should handle conversations, e.g.\n" +
            "• Role: Backend Engineer, Python/FastAPI, 3+ years, remote in India\n" +
            "• If they ask about salary: range is 18–25 LPA, depends on experience\n" +
            "• If interested: ask for their CV and notice period, then hand over"
          }
        />
        <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
          <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={() => fileInput.current?.click()}>
            <IconUpload className="h-3.5 w-3.5" /> Upload a text file
          </button>
          <span className="text-[11.5px] text-slate-400">
            {content.length.toLocaleString()} / {MAX_CONTENT.toLocaleString()}
          </span>
          <input
            ref={fileInput}
            type="file"
            accept={UPLOAD_ACCEPT}
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void upload(file);
              e.target.value = "";
            }}
          />
        </div>
        {fileError && <p className="mt-1 text-[12px] text-amber-700">{fileError}</p>}
      </div>
      {profiles.length > 0 && <AssistantPicker profiles={profiles} value={assistantIds} onChange={setAssistantIds} />}
      <AccountPicker accounts={accounts} value={accountIds} onChange={setAccountIds} />
      <div className="flex justify-end gap-2">
        {onCancel && (
          <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={onCancel}>
            Cancel
          </button>
        )}
        <button
          type="button"
          className="btn-primary px-3 py-1.5 text-xs"
          disabled={busy || !changed || !title.trim() || !content.trim()}
          onClick={async () => {
            setBusy(true);
            try {
              await onSubmit({
                title: title.trim(),
                content: content.trim(),
                linkedin_account_ids: accountIds,
                assistant_ids: assistantIds,
              });
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Saving…" : submitLabel}
        </button>
      </div>
    </div>
  );
}

const EMPTY: SopValue = { title: "", content: "", linkedin_account_ids: [], assistant_ids: [] };

export function SopManager({ workspaceId, profiles = [] }: { workspaceId: string; profiles?: AssistantProfile[] }) {
  const [items, setItems] = useState<KnowledgeItem[] | null>(null);
  const [accounts, setAccounts] = useState<LinkedInAccount[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [accountFilter, setAccountFilter] = useState<string>("");
  const [assistantFilter, setAssistantFilter] = useState<string>("");
  // Remounts the create form after a save, so it starts empty again.
  const [formKey, setFormKey] = useState(0);

  const load = useCallback(async () => {
    try {
      const [k, a] = await Promise.all([assistantApi.knowledge(workspaceId), linkedinApi.accounts(workspaceId)]);
      setItems(k);
      setAccounts(a);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the SOPs");
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const byId = useMemo(() => new Map(accounts.map((a) => [a.id, a])), [accounts]);
  const profileById = useMemo(() => new Map(profiles.map((p) => [p.id, p])), [profiles]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (items ?? []).filter((i) => {
      if (q && !i.title.toLowerCase().includes(q) && !i.content.toLowerCase().includes(q)) return false;
      if (accountFilter) {
        // "What does this account answer from": its own SOPs plus the shared ones.
        const ids = i.linkedin_account_ids ?? [];
        if (!(ids.length === 0 || ids.includes(accountFilter))) return false;
      }
      if (assistantFilter) {
        // Same for an assistant; the Default one reads only the shared SOPs.
        const ids = i.assistant_ids ?? [];
        if (!(ids.length === 0 || ids.includes(assistantFilter))) return false;
      }
      return true;
    });
  }, [items, query, accountFilter, assistantFilter]);

  async function guard(action: () => Promise<void>) {
    try {
      await action();
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the SOP");
      throw err;
    }
  }

  return (
    <div>
      {error && (
        <p className="mb-3 rounded-md border border-state-bad/40 bg-state-bad/10 px-3 py-2 text-sm text-state-bad">{error}</p>
      )}

      {creating ? (
        <div className="mb-4 rounded-lg border border-dashed border-violet-300 bg-violet-50/30 p-3">
          <SopEditor
            key={formKey}
            accounts={accounts}
            profiles={profiles}
            initial={EMPTY}
            submitLabel="Save SOP"
            onCancel={() => setCreating(false)}
            onSubmit={(value) =>
              guard(async () => {
                const item = await assistantApi.createKnowledge(workspaceId, value);
                setItems((prev) => [item, ...(prev ?? [])]);
                setFormKey((k) => k + 1);
                setCreating(false);
              }).catch(() => undefined)
            }
          />
        </div>
      ) : (
        <button className="btn-primary mb-4" onClick={() => setCreating(true)}>
          New SOP
        </button>
      )}

      <div className="mb-3 flex flex-wrap gap-2">
        <div className="relative min-w-0 flex-1">
          <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            className="input pl-9"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search SOPs by name or content…"
          />
        </div>
        {profiles.length > 0 && (
          <select className="input w-auto" value={assistantFilter} onChange={(e) => setAssistantFilter(e.target.value)}>
            <option value="">Every assistant</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                Read by {p.name}
              </option>
            ))}
          </select>
        )}
        {accounts.length > 0 && (
          <select className="input w-auto" value={accountFilter} onChange={(e) => setAccountFilter(e.target.value)}>
            <option value="">Every account</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                Used by {accountName(a)}
              </option>
            ))}
          </select>
        )}
      </div>

      {items === null ? (
        <p className="text-[13px] text-slate-400">Loading…</p>
      ) : visible.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-200 px-4 py-8 text-center text-[13px] text-slate-400">
          {items.length === 0
            ? "No SOPs yet. Without one, the assistant hands every question that needs specific information to you."
            : "No SOPs match."}
        </div>
      ) : (
        <ul className="space-y-2">
          {visible.map((item) => {
            const ids = item.linkedin_account_ids ?? [];
            const aids = item.assistant_ids ?? [];
            const editing = editingId === item.id;
            return (
              <li key={item.id} className="rounded-lg border border-slate-200">
                <div className="flex items-start gap-3 px-3 py-2.5">
                  <button onClick={() => setEditingId(editing ? null : item.id)} className="min-w-0 flex-1 text-left">
                    <p
                      className={`truncate text-[13.5px] font-semibold ${
                        item.enabled ? "text-ink-950" : "text-slate-400 line-through"
                      }`}
                    >
                      {item.title}
                    </p>
                    <p className="truncate text-[12px] text-slate-400">{item.content.slice(0, 140)}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {profiles.length > 0 &&
                        (aids.length === 0 ? (
                          <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold text-slate-600">
                            All assistants
                          </span>
                        ) : (
                          aids.map((id) => (
                            <span
                              key={id}
                              className="rounded-md bg-emerald-100 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-700"
                            >
                              {profileById.get(id)?.name ?? "Removed assistant"}
                            </span>
                          ))
                        ))}
                      {ids.length === 0 ? (
                        <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold text-slate-600">
                          All accounts
                        </span>
                      ) : (
                        ids.map((id) => (
                          <span
                            key={id}
                            className="rounded-md bg-violet-100 px-1.5 py-0.5 text-[11px] font-semibold text-violet-700"
                          >
                            {byId.get(id) ? accountName(byId.get(id)!) : "Removed account"}
                          </span>
                        ))
                      )}
                    </div>
                  </button>
                  <label className="flex shrink-0 items-center gap-1.5 text-[12px] text-slate-500" title="Off = kept, but not used">
                    <input
                      type="checkbox"
                      checked={item.enabled}
                      onChange={(e) =>
                        void guard(async () => {
                          const updated = await assistantApi.updateKnowledge(workspaceId, item.id, {
                            enabled: e.target.checked,
                          });
                          setItems((prev) => (prev ?? []).map((i) => (i.id === item.id ? updated : i)));
                        }).catch(() => undefined)
                      }
                    />
                    Use
                  </label>
                  <button
                    aria-label="Edit"
                    className="shrink-0 text-slate-400 hover:text-ink-950"
                    onClick={() => setEditingId(editing ? null : item.id)}
                  >
                    <IconPencil className="h-4 w-4" />
                  </button>
                  <button
                    aria-label="Delete"
                    className="shrink-0 text-slate-400 hover:text-state-bad"
                    onClick={() => {
                      if (!window.confirm(`Delete the SOP "${item.title}"?`)) return;
                      void guard(async () => {
                        await assistantApi.deleteKnowledge(workspaceId, item.id);
                        setItems((prev) => (prev ?? []).filter((i) => i.id !== item.id));
                      }).catch(() => undefined);
                    }}
                  >
                    <IconTrash className="h-4 w-4" />
                  </button>
                </div>
                {editing && (
                  <div className="border-t border-slate-100 p-3">
                    <SopEditor
                      accounts={accounts}
                      profiles={profiles}
                      initial={{ title: item.title, content: item.content, linkedin_account_ids: ids, assistant_ids: aids }}
                      submitLabel="Save changes"
                      onCancel={() => setEditingId(null)}
                      onSubmit={(value) =>
                        guard(async () => {
                          const updated = await assistantApi.updateKnowledge(workspaceId, item.id, value);
                          setItems((prev) => (prev ?? []).map((i) => (i.id === item.id ? updated : i)));
                          setEditingId(null);
                        }).catch(() => undefined)
                      }
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** The workspace's LinkedIn accounts, e.g. for "try it as this account". */
export function useLinkedInAccounts(workspaceId: string | null): LinkedInAccount[] {
  const [accounts, setAccounts] = useState<LinkedInAccount[]>([]);
  useEffect(() => {
    if (!workspaceId) return;
    linkedinApi
      .accounts(workspaceId)
      .then(setAccounts)
      .catch(() => setAccounts([]));
  }, [workspaceId]);
  return accounts;
}

export { accountName };
