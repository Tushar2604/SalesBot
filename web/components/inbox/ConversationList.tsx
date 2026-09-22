"use client";

import { LABEL_META, type Conversation } from "@/lib/inbox-api";

function relative(iso: string | null): string {
  if (!iso) return "";
  const delta = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(delta / 60000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

export function ConversationList({
  conversations,
  selectedId,
  onSelect,
}: {
  conversations: Conversation[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (conversations.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-center">
        <p className="text-sm text-slate-400">No conversations match this view.</p>
      </div>
    );
  }

  return (
    <ul className="flex-1 overflow-y-auto">
      {conversations.map((c) => {
        const name = c.lead_name || c.participant_name || "LinkedIn member";
        const active = c.id === selectedId;
        const snoozed = c.snoozed_until && new Date(c.snoozed_until).getTime() > Date.now();
        return (
          <li key={c.id}>
            <button
              onClick={() => onSelect(c.id)}
              className={`flex w-full items-start gap-3 border-b border-slate-100 px-4 py-3.5 text-left transition-colors ${
                active ? "bg-brand-50" : "hover:bg-slate-50"
              }`}
            >
              <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink-950 text-[11px] font-bold text-white">
                {name[0]?.toUpperCase()}
                {c.unread && (
                  <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-brand-600" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <p className={`truncate text-[13.5px] ${c.unread ? "font-bold text-ink-950" : "font-semibold text-slate-700"}`}>
                    {name}
                  </p>
                  <span className="shrink-0 text-[11px] text-slate-400">{relative(c.last_message_at)}</span>
                </div>
                <p className="mt-0.5 truncate text-[12.5px] text-slate-500">
                  {c.last_message_from_me && <span className="text-slate-400">You: </span>}
                  {c.last_message_text || "No messages yet"}
                </p>
                {(c.label !== "none" || snoozed) && (
                  <div className="mt-1.5 flex items-center gap-1.5">
                    {c.label !== "none" && (
                      <span className={`rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${LABEL_META[c.label].className}`}>
                        {LABEL_META[c.label].text}
                      </span>
                    )}
                    {snoozed && (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10.5px] font-semibold text-amber-600">
                        Snoozed
                      </span>
                    )}
                  </div>
                )}
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
