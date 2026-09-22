"use client";

/**
 * A faithful-looking preview of what will land on LinkedIn, so the sender sees
 * the message the way the recipient will — not a raw template string.
 *
 * Invites render as the "Add a note to your invitation" card, with the 300
 * character allowance as a live counter. Messages render as a chat thread.
 * The text shown is the server's rendering of the template with sample data.
 */

function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join("") || "?"
  );
}

export function MessagePreview({
  kind,
  text,
  senderName,
  recipientName = "Sample Prospect",
  limit,
  overLimit = false,
}: {
  kind: "invite" | "message";
  text: string;
  senderName: string;
  recipientName?: string;
  limit?: number;
  overLimit?: boolean;
}) {
  const length = text.length;

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-4 py-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          Preview · sample data
        </span>
        <span className="flex items-center gap-1 text-[11px] text-slate-400">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
          {kind === "invite" ? "Connection request" : "Direct message"}
        </span>
      </div>

      {kind === "invite" ? (
        <div className="p-4">
          <p className="mb-3 text-[15px] font-semibold text-slate-900">Add a note to your invitation?</p>
          <div className="rounded-lg border border-slate-300 bg-white p-3">
            <p
              className={`whitespace-pre-wrap text-[13.5px] leading-relaxed ${
                overLimit ? "text-state-bad" : "text-slate-800"
              }`}
            >
              {text}
            </p>
            {limit !== undefined && (
              <p
                className={`mt-2 text-right text-[11px] ${
                  overLimit ? "font-semibold text-state-bad" : "text-slate-400"
                }`}
              >
                {length}/{limit}
              </p>
            )}
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <span className="rounded-full border border-slate-300 px-4 py-1.5 text-[13px] font-semibold text-slate-500">
              Cancel
            </span>
            <span className="rounded-full bg-[#0a66c2] px-4 py-1.5 text-[13px] font-semibold text-white">
              Send
            </span>
          </div>
        </div>
      ) : (
        <div>
          <div className="flex items-center gap-3 border-b border-slate-100 px-4 py-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-200 text-[11px] font-bold text-slate-600">
              {initials(recipientName)}
            </span>
            <div className="leading-tight">
              <p className="text-[13px] font-semibold text-slate-900">{recipientName}</p>
              <p className="text-[11px] text-slate-400">1st · Active now</p>
            </div>
          </div>
          <div className="space-y-3 bg-slate-50/60 px-4 py-4">
            <div className="flex items-start gap-2.5">
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink-950 text-[11px] font-bold text-white">
                {initials(senderName)}
              </span>
              <div className="min-w-0">
                <p className="mb-1 text-[12px] font-semibold text-slate-900">
                  {senderName} <span className="font-normal text-slate-400">· Just now</span>
                </p>
                <p className="whitespace-pre-wrap rounded-2xl rounded-tl-sm bg-white px-3.5 py-2.5 text-[13.5px] leading-relaxed text-slate-800 shadow-sm ring-1 ring-slate-200">
                  {text}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
