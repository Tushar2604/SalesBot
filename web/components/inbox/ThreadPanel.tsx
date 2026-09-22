"use client";

import { useEffect, useRef, useState } from "react";
import type { Conversation, ConversationLabel, Message } from "@/lib/inbox-api";
import type { AssistantMode } from "@/lib/assistant-api";
import { LabelPicker } from "@/components/inbox/LabelPicker";
import { SnoozeMenu } from "@/components/inbox/SnoozeMenu";
import { IconArchive, IconChevronLeft, IconSend, IconSparkle } from "@/components/app/icons";

// While someone types, tell the server every few seconds so the assistant
// holds off; the server-side hold lapses on its own shortly after they stop.
const TYPING_PING_MS = 15_000;

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

const AUTHOR_TAG: Record<string, string> = { bot: "Assistant", campaign: "Campaign", human: "You" };

function BotBar({
  mode,
  conversation,
  onToggle,
}: {
  mode: AssistantMode | null;
  conversation: Conversation;
  onToggle: (paused: boolean) => void;
}) {
  if (mode === null) return null;
  if (mode === "off") {
    return (
      <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50 px-5 py-2 text-[12.5px] text-slate-500">
        <IconSparkle className="h-4 w-4" />
        The assistant is off for this workspace.
        <a href="/assistant" className="font-semibold text-brand-600 hover:underline">
          Set it up
        </a>
      </div>
    );
  }
  const paused = conversation.bot_paused;
  return (
    <div
      className={`flex flex-wrap items-center gap-2 border-b px-5 py-2 text-[12.5px] ${
        paused ? "border-amber-200 bg-amber-50 text-amber-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"
      }`}
    >
      <IconSparkle className="h-4 w-4 shrink-0" />
      <span className="min-w-0 flex-1">
        {paused ? (
          <>
            <span className="font-semibold">Assistant paused here</span>
            {conversation.bot_pause_reason && <> · {conversation.bot_pause_reason}</>}
          </>
        ) : (
          <>
            <span className="font-semibold">
              Assistant {mode === "auto" ? "replies automatically" : "drafts replies for you"}
            </span>{" "}
            · it stops the moment you type or reply.
          </>
        )}
      </span>
      <button
        onClick={() => onToggle(!paused)}
        className={`rounded-md px-2.5 py-1 text-[12px] font-semibold ${
          paused ? "bg-amber-600 text-white hover:bg-amber-700" : "border border-emerald-300 bg-white hover:bg-emerald-100"
        }`}
      >
        {paused ? "Resume assistant" : "Pause here"}
      </button>
    </div>
  );
}

export function ThreadPanel({
  conversation,
  messages,
  loading,
  onBack,
  onLabel,
  onSnooze,
  onUnsnooze,
  onSend,
  sending,
  archived = false,
  onToggleArchive,
  assistantMode = null,
  onBotToggle,
  onSendDraft,
  onDiscardDraft,
  onTyping,
}: {
  conversation: Conversation;
  messages: Message[];
  loading: boolean;
  onBack?: () => void;
  onLabel: (label: ConversationLabel) => void;
  onSnooze: (until: string) => void;
  onUnsnooze: () => void;
  onSend: (text: string) => void;
  sending: boolean;
  archived?: boolean;
  onToggleArchive?: () => void;
  assistantMode?: AssistantMode | null;
  onBotToggle?: (paused: boolean) => void;
  onSendDraft?: (text: string) => void;
  onDiscardDraft?: () => void;
  onTyping?: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [botText, setBotText] = useState(conversation.bot_draft);
  const lastPing = useRef(0);
  const name = conversation.lead_name || conversation.participant_name || "LinkedIn member";
  const facts = Object.entries(conversation.bot_extracted || {});

  useEffect(() => setBotText(conversation.bot_draft), [conversation.id, conversation.bot_draft]);

  function pingTyping() {
    const now = Date.now();
    if (onTyping && now - lastPing.current > TYPING_PING_MS) {
      lastPing.current = now;
      onTyping();
    }
  }

  function submit() {
    const text = draft.trim();
    if (!text || sending) return;
    onSend(text);
    setDraft("");
  }

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-slate-200 px-4 py-3 sm:px-5 sm:py-4">
        {onBack && (
          <button onClick={onBack} className="text-slate-400 hover:text-ink-950 md:hidden" aria-label="Back">
            <IconChevronLeft className="h-5 w-5" />
          </button>
        )}
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink-950 text-[12px] font-bold text-white">
          {name[0]?.toUpperCase()}
        </span>
        <div className="min-w-0 flex-1 basis-32">
          <p className="truncate text-[14.5px] font-bold text-ink-950">{name}</p>
          <p className="hidden truncate text-[12px] text-slate-400 sm:block">
            via {conversation.linkedin_account_label || "LinkedIn"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <SnoozeMenu snoozedUntil={conversation.snoozed_until} onSnooze={onSnooze} onUnsnooze={onUnsnooze} />
          <LabelPicker value={conversation.label} onChange={onLabel} />
          {onToggleArchive && (
            <button
              onClick={onToggleArchive}
              title={archived ? "Unarchive" : "Archive"}
              className={`flex h-8 w-8 items-center justify-center rounded-lg border ${
                archived ? "border-brand-200 bg-brand-50 text-brand-600" : "border-slate-200 text-slate-500 hover:text-ink-950"
              }`}
            >
              <IconArchive className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {onBotToggle && <BotBar mode={assistantMode} conversation={conversation} onToggle={onBotToggle} />}

      {facts.length > 0 && (
        <div className="border-b border-slate-200 bg-white px-5 py-2.5">
          <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">They shared</p>
          <div className="flex flex-wrap gap-1.5">
            {facts.map(([field, value]) => (
              <span key={field} className="rounded-md bg-slate-100 px-2 py-1 text-[12px] text-slate-700">
                <span className="font-semibold">{field.replace(/_/g, " ")}:</span> {value}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto bg-slate-50/50 px-5 py-4">
        {loading ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : messages.length === 0 ? (
          <p className="text-sm text-slate-400">No messages in this thread yet.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {messages.map((m) => (
              <div key={m.id} className={`flex ${m.direction === "outbound" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-[13.5px] leading-relaxed ${
                    m.direction === "outbound"
                      ? m.author === "bot"
                        ? "rounded-br-sm bg-violet-600 text-white"
                        : "rounded-br-sm bg-brand-600 text-white"
                      : "rounded-bl-sm bg-white text-ink-950 shadow-sm"
                  }`}
                >
                  <p className="whitespace-pre-wrap">{m.body}</p>
                  <p className={`mt-1 text-[10.5px] ${m.direction === "outbound" ? "text-white/70" : "text-slate-400"}`}>
                    {m.direction === "outbound" && m.author && AUTHOR_TAG[m.author] && <>{AUTHOR_TAG[m.author]} · </>}
                    {formatTime(m.sent_at)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {conversation.bot_draft && onSendDraft && (
        <div className="border-t border-violet-200 bg-violet-50/60 px-4 py-3">
          <p className="mb-1.5 flex items-center gap-1.5 text-[12px] font-semibold text-violet-700">
            <IconSparkle className="h-3.5 w-3.5" />
            {assistantMode === "auto" && !conversation.bot_paused
              ? "Assistant will send this shortly. Editing or discarding it stops that."
              : "Suggested reply"}
          </p>
          <textarea
            value={botText}
            onChange={(e) => {
              setBotText(e.target.value);
              // Editing means a person has taken this one: stop the automatic send.
              if (assistantMode === "auto" && !conversation.bot_paused) onBotToggle?.(true);
            }}
            rows={3}
            className="input mb-2 resize-none bg-white"
          />
          <div className="flex flex-wrap justify-end gap-2">
            <button className="btn-ghost px-3 py-1.5 text-xs" onClick={onDiscardDraft}>
              Discard
            </button>
            <button
              className="btn-primary px-3 py-1.5 text-xs"
              disabled={!botText.trim() || sending}
              onClick={() => onSendDraft(botText.trim())}
            >
              Send this reply
            </button>
          </div>
        </div>
      )}

      <div className="border-t border-slate-200 p-4">
        <div className="flex items-end gap-2">
          <textarea
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              pingTyping();
            }}
            onFocus={pingTyping}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="Write a reply… (the assistant steps back while you type)"
            rows={2}
            className="input flex-1 resize-none"
            disabled={sending}
          />
          <button onClick={submit} disabled={sending || !draft.trim()} className="btn-primary shrink-0">
            {sending ? "Sending…" : "Send"}
            <IconSend className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
