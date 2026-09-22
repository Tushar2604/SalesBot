"use client";

/**
 * Drag-and-drop media attachment.
 *
 * Validates against the limits the API reports (`/content/media/limits`) rather
 * than a second hardcoded copy, so a server-side change to what LinkedIn accepts
 * reaches the composer without a frontend release.
 */

import { useCallback, useRef, useState } from "react";
import clsx from "clsx";
import { ApiError } from "@/lib/api";
import { contentApi, type MediaAsset, type MediaLimits, type PostMedia } from "@/lib/content-api";
import {
  IconClose,
  IconDocument,
  IconImage,
  IconUpload,
  IconVideo,
  IconWarning,
} from "@/components/app/icons";

type Pending = { key: string; name: string; size: number; error?: string };

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function kindIcon(kind: MediaAsset["kind"]) {
  if (kind === "video") return IconVideo;
  if (kind === "document") return IconDocument;
  return IconImage;
}

export function MediaUploader({
  workspaceId,
  media,
  limits,
  disabled = false,
  onChange,
}: {
  workspaceId: string;
  media: PostMedia[];
  limits: MediaLimits["limits"] | null;
  disabled?: boolean;
  onChange: (media: PostMedia[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [pending, setPending] = useState<Pending[]>([]);
  const [error, setError] = useState("");

  const accepted = limits
    ? [
        ...limits.image.content_types,
        ...limits.video.content_types,
        ...limits.document.content_types,
      ]
    : [];

  /** Client-side pre-check, so an oversized file never leaves the browser. */
  const preCheck = useCallback(
    (file: File): string => {
      if (!limits) return "";
      const type = file.type.split(";")[0];
      const group = limits.image.content_types.includes(type)
        ? limits.image
        : limits.video.content_types.includes(type)
          ? limits.video
          : limits.document.content_types.includes(type)
            ? limits.document
            : null;

      if (!group) {
        return "LinkedIn does not accept this file type. Use a JPG, PNG or GIF image, an MP4 video, or a PDF/DOC/PPT document.";
      }
      if (file.size > group.max_bytes) {
        return `That file is ${formatSize(file.size)}; the limit is ${formatSize(group.max_bytes)}.`;
      }
      // Mixed attachments are refused server-side; say so before the upload.
      const existing = media[0]?.asset.kind;
      const incoming = limits.image.content_types.includes(type)
        ? "image"
        : limits.video.content_types.includes(type)
          ? "video"
          : "document";
      if (existing && existing !== incoming) {
        return `This post already has ${existing === "image" ? "images" : `a ${existing}`} attached. A post carries images, or one video, or one document.`;
      }
      if (incoming === "image" && media.length >= limits.image.max_per_post) {
        return `A post can carry up to ${limits.image.max_per_post} images.`;
      }
      if (incoming !== "image" && media.length >= 1) {
        return `A post can carry only one ${incoming}.`;
      }
      return "";
    },
    [limits, media],
  );

  const upload = useCallback(
    async (files: FileList | File[]) => {
      setError("");
      const list = Array.from(files);
      let current = media;

      for (const file of list) {
        const key = `${file.name}-${file.size}-${Math.random().toString(36).slice(2, 8)}`;
        const problem = preCheck(file);
        if (problem) {
          setPending((p) => [...p, { key, name: file.name, size: file.size, error: problem }]);
          continue;
        }

        setPending((p) => [...p, { key, name: file.name, size: file.size }]);
        try {
          const asset = await contentApi.uploadMedia(workspaceId, file);
          const attached: PostMedia = {
            id: `local-${asset.id}`,
            position: current.length,
            alt_text: "",
            asset,
          };
          current = [...current, attached];
          onChange(current);
          setPending((p) => p.filter((item) => item.key !== key));
        } catch (err) {
          const message =
            err instanceof ApiError ? err.message : "That file could not be uploaded.";
          setPending((p) =>
            p.map((item) => (item.key === key ? { ...item, error: message } : item)),
          );
        }
      }
    },
    [media, onChange, preCheck, workspaceId],
  );

  const remove = (assetId: string) => {
    onChange(
      media
        .filter((item) => item.asset.id !== assetId)
        .map((item, index) => ({ ...item, position: index })),
    );
    // The stored object is left in place: another post or a template may still
    // reference it, and orphan cleanup is a storage-lifecycle concern.
  };

  const setAlt = (assetId: string, alt: string) => {
    onChange(media.map((item) => (item.asset.id === assetId ? { ...item, alt_text: alt } : item)));
  };

  return (
    <div>
      <div
        onDragOver={(event) => {
          if (disabled) return;
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (disabled) return;
          if (event.dataTransfer.files.length) void upload(event.dataTransfer.files);
        }}
        className={clsx(
          "rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors",
          disabled
            ? "cursor-not-allowed border-slate-200 bg-slate-50 opacity-60"
            : dragging
              ? "border-accent bg-accent/5"
              : "border-slate-300 bg-white hover:border-slate-400",
        )}
      >
        <IconUpload className="mx-auto h-6 w-6 text-slate-400" />
        <p className="mt-2 text-[13.5px] font-medium text-slate-700">
          Drag &amp; drop media here
        </p>
        <p className="mt-0.5 text-[12.5px] text-slate-500">
          {limits
            ? `Images up to ${formatSize(limits.image.max_bytes)} (max ${limits.image.max_per_post}), one MP4 up to ${formatSize(limits.video.max_bytes)}, or one document up to ${formatSize(limits.document.max_bytes)}.`
            : "Loading what LinkedIn accepts…"}
        </p>
        <button
          type="button"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
          className="btn-ghost mt-3 !py-1.5 text-[13px]"
        >
          Upload media
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={accepted.join(",")}
          className="hidden"
          onChange={(event) => {
            if (event.target.files?.length) void upload(event.target.files);
            event.target.value = "";
          }}
        />
      </div>

      {error && <p className="mt-2 text-[12.5px] text-state-bad">{error}</p>}

      {(media.length > 0 || pending.length > 0) && (
        <ul className="mt-3 space-y-2">
          {media.map((item) => {
            const Icon = kindIcon(item.asset.kind);
            return (
              <li
                key={item.asset.id}
                className="flex items-start gap-3 rounded-lg border border-slate-200 bg-white p-2.5"
              >
                <span className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-md bg-slate-100">
                  {item.asset.kind === "image" && item.asset.url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={item.asset.url} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <Icon className="h-5 w-5 text-slate-500" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-slate-800">
                    {item.asset.filename}
                  </p>
                  <p className="text-[12px] text-slate-500">
                    {formatSize(item.asset.size_bytes)}
                    {item.asset.width > 0 && ` · ${item.asset.width}×${item.asset.height}`}
                    <span className="ml-1.5 text-state-ok">Uploaded</span>
                  </p>
                  {item.asset.kind === "image" && (
                    <input
                      value={item.alt_text}
                      disabled={disabled}
                      onChange={(event) => setAlt(item.asset.id, event.target.value)}
                      placeholder="Alt text (describe the image)"
                      className="input mt-1.5 !py-1 text-[12.5px]"
                    />
                  )}
                </div>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => remove(item.asset.id)}
                  aria-label={`Remove ${item.asset.filename}`}
                  className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-state-bad"
                >
                  <IconClose className="h-4 w-4" />
                </button>
              </li>
            );
          })}

          {pending.map((item) => (
            <li
              key={item.key}
              className={clsx(
                "flex items-start gap-3 rounded-lg border p-2.5",
                item.error ? "border-state-bad/40 bg-state-bad/5" : "border-slate-200 bg-slate-50",
              )}
            >
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md bg-white">
                {item.error ? (
                  <IconWarning className="h-5 w-5 text-state-bad" />
                ) : (
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-accent" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium text-slate-800">{item.name}</p>
                <p className="text-[12px] text-slate-500">{formatSize(item.size)}</p>
                {item.error ? (
                  <p className="mt-1 text-[12.5px] text-state-bad">{item.error}</p>
                ) : (
                  <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-slate-200">
                    <div className="h-full w-1/2 animate-pulse rounded-full bg-accent" />
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => setPending((p) => p.filter((entry) => entry.key !== item.key))}
                aria-label={`Dismiss ${item.name}`}
                className="rounded p-1 text-slate-400 hover:bg-white hover:text-slate-700"
              >
                <IconClose className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
