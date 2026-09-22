"use client";

/**
 * Live preview of how a post will read on LinkedIn.
 *
 * An *approximation*, built from our own primitives — no LinkedIn logo, icon set
 * or typography is reproduced here. What it is faithful about is the things that
 * change a writer's decisions: where the "…see more" fold lands, how hashtags
 * and URLs are coloured, how line breaks collapse, and how a media grid is laid
 * out for one, two, three or many images.
 */

import { useMemo, useState } from "react";
import clsx from "clsx";
import type { PostMedia } from "@/lib/content-api";
import {
  IconComment,
  IconDocument,
  IconRepost,
  IconSend,
  IconThumbUp,
  IconVideo,
} from "@/components/app/icons";

/** LinkedIn collapses the body at roughly this length on a desktop feed. */
const FOLD_CHARS = 210;

const URL_RE = /(https?:\/\/[^\s]+|www\.[^\s]+)/g;
const HASHTAG_RE = /(#[\wÀ-ɏ-]+)/g;
const MENTION_RE = /(@[\w.-]+)/g;

/** Splits body text into plain runs and the runs LinkedIn tints blue. */
function decorate(text: string, keyPrefix: string): React.ReactNode[] {
  const pattern = new RegExp(
    `${URL_RE.source}|${HASHTAG_RE.source}|${MENTION_RE.source}`,
    "g",
  );
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
    nodes.push(
      <span key={`${keyPrefix}-${match.index}`} className="font-medium text-[#0a66c2]">
        {match[0]}
      </span>,
    );
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function MediaGrid({ media }: { media: PostMedia[] }) {
  if (media.length === 0) return null;

  const first = media[0];

  if (first.asset.kind === "video") {
    return (
      <div className="relative flex aspect-video items-center justify-center border-y border-slate-200 bg-slate-900">
        <video
          src={first.asset.url}
          controls
          className="h-full w-full object-contain"
          aria-label={first.alt_text || first.asset.filename}
        />
        {!first.asset.url && (
          <span className="flex items-center gap-2 text-sm text-slate-300">
            <IconVideo className="h-5 w-5" />
            {first.asset.filename}
          </span>
        )}
      </div>
    );
  }

  if (first.asset.kind === "document") {
    return (
      <div className="flex items-center gap-3 border-y border-slate-200 bg-slate-50 px-4 py-5">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-[#0a66c2]/10 text-[#0a66c2]">
          <IconDocument className="h-5 w-5" />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-[13.5px] font-semibold text-slate-900">
            {first.asset.filename}
          </span>
          <span className="block text-[12px] text-slate-500">
            Document &middot; {Math.max(1, Math.round(first.asset.size_bytes / 1024))} KB
          </span>
        </span>
      </div>
    );
  }

  // Images: one full-bleed, two side by side, three as 1 + 2, four or more as a
  // 2x2 grid with a "+N" overlay — which is how LinkedIn arranges them.
  const shown = media.slice(0, 4);
  const overflow = media.length - shown.length;

  return (
    <div
      className={clsx(
        "grid gap-0.5 border-y border-slate-200 bg-white",
        shown.length === 1 && "grid-cols-1",
        shown.length === 2 && "grid-cols-2",
        shown.length === 3 && "grid-cols-2",
        shown.length >= 4 && "grid-cols-2",
      )}
    >
      {shown.map((item, index) => (
        <div
          key={item.id}
          className={clsx(
            "relative overflow-hidden bg-slate-100",
            shown.length === 1 ? "aspect-[4/3]" : "aspect-square",
            shown.length === 3 && index === 0 && "row-span-2 aspect-auto",
          )}
        >
          {item.asset.url ? (
            // Preview thumbnails come from presigned URLs on an arbitrary host,
            // so next/image's loader is not usable here.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={item.asset.url}
              alt={item.alt_text || item.asset.filename}
              className="h-full w-full object-cover"
            />
          ) : (
            <span className="flex h-full w-full items-center justify-center text-xs text-slate-400">
              {item.asset.filename}
            </span>
          )}
          {overflow > 0 && index === shown.length - 1 && (
            <span className="absolute inset-0 flex items-center justify-center bg-black/55 text-lg font-semibold text-white">
              +{overflow}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

export function LinkedInPreview({
  content,
  media,
  authorName,
  authorHeadline,
  avatarUrl,
  timeLabel = "now",
  visibility = "PUBLIC",
}: {
  content: string;
  media: PostMedia[];
  authorName: string;
  authorHeadline: string;
  avatarUrl: string;
  timeLabel?: string;
  visibility?: "PUBLIC" | "CONNECTIONS";
}) {
  const [expanded, setExpanded] = useState(false);

  const { visible, truncated } = useMemo(() => {
    if (expanded || content.length <= FOLD_CHARS) {
      return { visible: content, truncated: false };
    }
    // Cut on a word boundary, the way the real fold behaves.
    const slice = content.slice(0, FOLD_CHARS);
    const lastSpace = slice.lastIndexOf(" ");
    return { visible: slice.slice(0, lastSpace > 120 ? lastSpace : FOLD_CHARS), truncated: true };
  }, [content, expanded]);

  const initials = (authorName || "?")
    .split(" ")
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

  return (
    <article className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-start gap-3 px-4 pb-3 pt-4">
        {avatarUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={avatarUrl}
            alt=""
            className="h-12 w-12 shrink-0 rounded-full object-cover"
          />
        ) : (
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-violet-500 text-sm font-bold text-white">
            {initials || "?"}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14.5px] font-semibold leading-tight text-slate-900">
            {authorName || "Your LinkedIn account"}
          </p>
          {authorHeadline && (
            <p className="truncate text-[12.5px] leading-tight text-slate-500">{authorHeadline}</p>
          )}
          <p className="mt-0.5 flex items-center gap-1 text-[12px] text-slate-500">
            {timeLabel}
            <span aria-hidden>&middot;</span>
            <span title={visibility === "PUBLIC" ? "Anyone" : "Connections only"}>
              {visibility === "PUBLIC" ? "Anyone" : "Connections"}
            </span>
          </p>
        </div>
      </header>

      <div className="px-4 pb-3">
        {content.trim() ? (
          <p className="whitespace-pre-wrap break-words text-[14px] leading-[1.45] text-slate-800">
            {decorate(visible, "run")}
            {truncated && (
              <>
                {"… "}
                <button
                  type="button"
                  onClick={() => setExpanded(true)}
                  className="text-[14px] text-slate-500 hover:text-[#0a66c2] hover:underline"
                >
                  see more
                </button>
              </>
            )}
          </p>
        ) : (
          <p className="text-[14px] italic leading-[1.45] text-slate-400">
            Your post will appear here as you type.
          </p>
        )}
      </div>

      <MediaGrid media={media} />

      <footer className="grid grid-cols-4 border-t border-slate-100 px-2 py-1">
        {[
          { label: "Like", Icon: IconThumbUp },
          { label: "Comment", Icon: IconComment },
          { label: "Repost", Icon: IconRepost },
          { label: "Send", Icon: IconSend },
        ].map(({ label, Icon }) => (
          <span
            key={label}
            // Inert on purpose: this is a rendering of the real post, not a
            // second place to interact with it.
            className="flex items-center justify-center gap-1.5 rounded px-2 py-2.5 text-[13px] font-semibold text-slate-500"
          >
            <Icon className="h-[18px] w-[18px]" />
            <span className="hidden sm:inline">{label}</span>
          </span>
        ))}
      </footer>
    </article>
  );
}
