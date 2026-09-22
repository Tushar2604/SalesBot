"use client";

/**
 * Unified LinkedIn inbox.
 *
 * Sending a reply is dispatched to a worker (the driver is synchronous and
 * needs the account's execution lock), so after `reply()` returns we
 * optimistically show the draft and re-fetch messages shortly after — the
 * worker task, not this request, is what actually talks to LinkedIn.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError } from "@/lib/api";
import { inboxApi, type Conversation, type ConversationLabel, type Message } from "@/lib/inbox-api";
import { assistantApi, type AssistantMode } from "@/lib/assistant-api";
import { ConversationList } from "@/components/inbox/ConversationList";
import { ThreadPanel } from "@/components/inbox/ThreadPanel";
import { IconFilter, IconRefresh, IconSearch } from "@/components/app/icons";
import { useSession } from "@/lib/session";
import { useLocalState } from "@/lib/localSettings";

type FilterKey = ConversationLabel | "all" | "unread" | "replied" | "paused" | "archived";

const LABEL_FILTERS: ConversationLabel[] = ["interested", "question", "not_interested", "out_of_office"];
function isLabelFilter(f: FilterKey): f is ConversationLabel {
  return (LABEL_FILTERS as string[]).includes(f);
}

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "unread", label: "Unread" },
  { key: "replied", label: "Replied" },
  { key: "paused", label: "Paused" },
  { key: "archived", label: "Archived" },
  { key: "interested", label: "Interested" },
  { key: "question", label: "Question" },
  { key: "not_interested", label: "Not interested" },
  { key: "out_of_office", label: "Out of office" },
];

export default function InboxPage() {
  const { workspace } = useSession();
  const workspaceId = workspace?.id ?? null;

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");

  // No `archived` concept in the backend yet — archiving is a real,
  // per-viewer action, just persisted client-side per workspace.
  const [archivedIds, setArchivedIds] = useLocalState<string[]>(workspaceId, "inbox-archived", []);

  const [source, setSource] = useState<"linkedin" | "salesnav">("linkedin");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [assistantMode, setAssistantMode] = useState<AssistantMode | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const page = await inboxApi.conversations(workspaceId, {
        label: isLabelFilter(filter) ? filter : undefined,
        unreadOnly: filter === "unread",
        limit: 100,
      });
      setConversations(page.items);
      setTotal(page.total);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the inbox");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, filter]);

  useEffect(() => {
    void load();
    // Keep drafts, replies and the assistant's state fresh without a reload.
    const timer = setInterval(() => void load(), 30_000);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!workspaceId) return;
    assistantApi
      .settings(workspaceId)
      .then((s) => setAssistantMode(s.mode))
      .catch(() => setAssistantMode(null));
  }, [workspaceId]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return conversations.filter((c) => {
      const isArchived = archivedIds.includes(c.id);
      if (filter === "archived") {
        if (!isArchived) return false;
      } else if (isArchived) {
        return false;
      }

      if (filter === "replied" && c.last_message_from_me) return false;
      if (filter === "paused" && !(c.snoozed_until && new Date(c.snoozed_until).getTime() > Date.now())) return false;

      if (!q) return true;
      return (
        (c.lead_name || c.participant_name).toLowerCase().includes(q) ||
        c.last_message_text.toLowerCase().includes(q)
      );
    });
  }, [conversations, search, filter, archivedIds]);

  const selected = conversations.find((c) => c.id === selectedId) ?? null;

  const loadMessages = useCallback(
    async (id: string) => {
      if (!workspaceId) return;
      setMessagesLoading(true);
      try {
        setMessages(await inboxApi.messages(workspaceId, id));
      } catch {
        setMessages([]);
      } finally {
        setMessagesLoading(false);
      }
    },
    [workspaceId],
  );

  function select(id: string) {
    setSelectedId(id);
    void loadMessages(id);
    if (!workspaceId) return;
    const conversation = conversations.find((c) => c.id === id);
    if (conversation?.unread) {
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, unread: false } : c)));
      void inboxApi.markRead(workspaceId, id);
    }
  }

  async function updateSelected(patch: Partial<Conversation>, action: () => Promise<Conversation>) {
    if (!selectedId) return;
    setConversations((prev) => prev.map((c) => (c.id === selectedId ? { ...c, ...patch } : c)));
    try {
      const updated = await action();
      setConversations((prev) => prev.map((c) => (c.id === selectedId ? updated : c)));
    } catch {
      void load();
    }
  }

  async function send(text: string) {
    if (!workspaceId || !selectedId) return;
    setSending(true);
    setMessages((prev) => [
      ...prev,
      { id: `optimistic-${Date.now()}`, direction: "outbound", body: text, sent_at: new Date().toISOString(), ai_label: null },
    ]);
    // Replying yourself takes this thread over from the assistant.
    setConversations((prev) =>
      prev.map((c) =>
        c.id === selectedId ? { ...c, bot_paused: true, bot_pause_reason: "You replied yourself", bot_draft: "" } : c,
      ),
    );
    try {
      await inboxApi.reply(workspaceId, selectedId, text);
      setTimeout(() => void loadMessages(selectedId), 4000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send the reply");
    } finally {
      setSending(false);
    }
  }

  async function sendDraft(text: string) {
    if (!workspaceId || !selectedId) return;
    setSending(true);
    setMessages((prev) => [
      ...prev,
      { id: `optimistic-${Date.now()}`, direction: "outbound", body: text, sent_at: new Date().toISOString(), ai_label: null, author: "bot" },
    ]);
    setConversations((prev) => prev.map((c) => (c.id === selectedId ? { ...c, bot_draft: "" } : c)));
    try {
      await inboxApi.sendDraft(workspaceId, selectedId, text);
      setTimeout(() => void loadMessages(selectedId), 4000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send the reply");
    } finally {
      setSending(false);
    }
  }

  const stats = useMemo(() => {
    const unread = conversations.filter((c) => c.unread).length;
    const interested = conversations.filter((c) => c.label === "interested").length;
    const snoozed = conversations.filter(
      (c) => c.snoozed_until && new Date(c.snoozed_until).getTime() > Date.now(),
    ).length;
    return { total, unread, interested, snoozed };
  }, [conversations, total]);

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;

  return (
    <div className="flex h-[calc(100vh-7.5rem)] flex-col">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[20px] font-semibold text-ink-950">Your messages</h2>
          <p className="text-[12.5px] text-slate-400">
            {stats.unread} unread · {stats.interested} interested · {stats.snoozed} snoozed
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            aria-label="Refresh inbox"
            onClick={() => void load()}
            className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 text-slate-500 hover:bg-slate-50"
          >
            <IconRefresh className="h-4 w-4" />
          </button>
          <div className="relative">
            <button
              type="button"
              aria-label="Filter conversations"
              onClick={() => setFiltersOpen((v) => !v)}
              className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 text-slate-500 hover:bg-slate-50"
            >
              <IconFilter className="h-4 w-4" />
            </button>
            {filtersOpen && (
              <div className="absolute right-0 top-12 z-20 flex w-56 flex-wrap gap-1.5 rounded-xl border border-slate-200 bg-white p-3 shadow-lg">
                {FILTERS.map((f) => (
                  <button
                    key={f.key}
                    onClick={() => {
                      setFilter(f.key);
                      setFiltersOpen(false);
                    }}
                    className={`rounded-full px-3 py-1.5 text-[12px] font-semibold ${
                      filter === f.key ? "bg-ink-950 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="relative">
            <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search"
              className="input h-10 w-48 py-2 pl-9"
            />
          </div>
          <div className="flex rounded-full bg-[#f3f4f6] p-1">
            {(["linkedin", "salesnav"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setSource(s)}
                className={`rounded-full px-4 py-1.5 text-[13px] font-medium ${
                  source === s ? "bg-white text-ink-950 shadow-sm" : "text-slate-500"
                }`}
              >
                {s === "linkedin" ? "LinkedIn" : "Sales Navigator"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-state-bad/40 bg-state-bad/10 px-4 py-3 text-sm text-state-bad">
          {error}
        </p>
      )}

      <div className="flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-slate-100 bg-white">
        <div className={`flex w-full flex-col border-r border-slate-100 md:w-[360px] md:shrink-0 ${selected ? "hidden md:flex" : "flex"}`}>
          {source === "salesnav" ? (
            <div className="flex flex-1 items-center justify-center p-8 text-center">
              <p className="text-sm text-slate-400">
                Sales Navigator inbox sync isn&apos;t connected in this environment — every
                conversation currently routes through standard LinkedIn messaging.
              </p>
            </div>
          ) : loading ? (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-sm text-slate-400">Loading…</p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-1 items-center justify-center p-8 text-center">
              <p className="text-sm text-slate-400">No conversations yet.</p>
            </div>
          ) : (
            <ConversationList conversations={filtered} selectedId={selectedId} onSelect={select} />
          )}
        </div>

        <div className={`min-w-0 flex-1 ${selected ? "flex" : "hidden md:flex"}`}>
          {selected ? (
            <ThreadPanel
              conversation={selected}
              messages={messages}
              loading={messagesLoading}
              onBack={() => setSelectedId(null)}
              onLabel={(label) => void updateSelected({ label, label_source: "manual" }, () => inboxApi.setLabel(workspaceId, selected.id, label))}
              onSnooze={(until) => void updateSelected({ snoozed_until: until }, () => inboxApi.snooze(workspaceId, selected.id, until))}
              onUnsnooze={() => void updateSelected({ snoozed_until: null }, () => inboxApi.snooze(workspaceId, selected.id, null))}
              onSend={(text) => void send(text)}
              assistantMode={assistantMode}
              onBotToggle={(paused) =>
                void updateSelected(
                  { bot_paused: paused, bot_pause_reason: paused ? "Paused by you" : "" },
                  () => inboxApi.setBotPaused(workspaceId, selected.id, paused),
                )
              }
              onSendDraft={(text) => void sendDraft(text)}
              onDiscardDraft={() =>
                void updateSelected({ bot_draft: "" }, () => inboxApi.discardDraft(workspaceId, selected.id))
              }
              onTyping={() => void inboxApi.typing(workspaceId, selected.id).catch(() => undefined)}
              sending={sending}
              archived={archivedIds.includes(selected.id)}
              onToggleArchive={() =>
                setArchivedIds((prev) =>
                  prev.includes(selected.id) ? prev.filter((id) => id !== selected.id) : [...prev, selected.id],
                )
              }
            />
          ) : (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-sm text-slate-400">Select a conversation to view it.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
