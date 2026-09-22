"use client";

/**
 * The post editor: composer on the left, live LinkedIn preview on the right.
 *
 * Autosave is debounced and always writes to a real draft row, so a browser
 * refresh loses nothing. The first keystroke on a brand-new post creates that
 * row, which is why `onCreate` exists — the page cannot know the id until then.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import clsx from "clsx";
import { ApiError, type LinkedInAccount } from "@/lib/api";
import {
  browserTimezone,
  contentApi,
  publishingApi,
  type MediaLimits,
  type Post,
  type PostMedia,
  type PostVisibility,
  type Template,
} from "@/lib/content-api";
import { LinkedInPreview } from "@/components/content/LinkedInPreview";
import { MediaUploader } from "@/components/content/MediaUploader";
import { AiAssistant } from "@/components/content/AiAssistant";
import { PublishConfirmDialog, ScheduleDialog } from "@/components/content/ScheduleDialog";
import {
  ConfirmDialog,
  Modal,
  PostStatusPill,
  PublishingBanner,
  useToast,
} from "@/components/content/ContentUi";
import {
  IconCheckCircle,
  IconClock,
  IconLayers,
  IconSend,
  IconSmile,
  IconWarning,
} from "@/components/app/icons";

const AUTOSAVE_DELAY = 1200;

/** A small, curated set — enough for a post, without shipping a whole library. */
const EMOJI: { group: string; items: string[] }[] = [
  { group: "Reactions", items: ["🙌", "👏", "🔥", "💡", "🎉", "✅", "⚡", "🚀", "💪", "👀"] },
  { group: "Work", items: ["📈", "📊", "🧠", "🛠️", "🗓️", "📌", "🧵", "🔍", "💼", "🏆"] },
  { group: "People", items: ["🙏", "🤝", "👋", "😄", "🤔", "❤️", "☕", "🌍", "✍️", "📣"] },
];

type SaveState = "idle" | "saving" | "saved" | "error";

export function PostComposer({
  workspaceId,
  accounts,
  initialPost,
  canPublish,
  approvalRequired,
  templates,
}: {
  workspaceId: string;
  accounts: LinkedInAccount[];
  initialPost: Post | null;
  canPublish: boolean;
  approvalRequired: boolean;
  templates: Template[];
}) {
  const router = useRouter();
  const toast = useToast();

  const [post, setPost] = useState<Post | null>(initialPost);
  const [accountId, setAccountId] = useState(
    initialPost?.account.id ?? accounts[0]?.id ?? "",
  );
  const [content, setContent] = useState(initialPost?.content ?? "");
  const [visibility, setVisibility] = useState<PostVisibility>(
    initialPost?.visibility ?? "PUBLIC",
  );
  const [media, setMedia] = useState<PostMedia[]>(initialPost?.media ?? []);
  const [limits, setLimits] = useState<MediaLimits["limits"] | null>(null);

  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState("");
  const [dialog, setDialog] = useState<
    null | "schedule" | "publish" | "emoji" | "template" | "delete"
  >(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [authorizing, setAuthorizing] = useState(false);
  const [templateName, setTemplateName] = useState("");

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // What was last persisted, so autosave never writes an unchanged payload.
  const lastSaved = useRef(
    JSON.stringify({
      accountId: initialPost?.account.id ?? "",
      content: initialPost?.content ?? "",
      visibility: initialPost?.visibility ?? "PUBLIC",
      media: (initialPost?.media ?? []).map((m) => [m.asset.id, m.alt_text]),
    }),
  );
  const creating = useRef(false);

  const account = accounts.find((item) => item.id === accountId) ?? null;
  const capability = post?.account.capability ??
    account?.publishing ?? {
      code: "not_authorized",
      available: false,
      message: "Connect a LinkedIn account to publish.",
      remedy: "",
    };

  const status = post?.status ?? "draft";
  const locked = post !== null && !post.is_editable;

  const characters = content.length;
  const words = content.split(/\s+/).filter(Boolean).length;
  const maxChars = limits ? limits.max_commentary_chars : 3000;
  const overLimit = characters > maxChars;

  useEffect(() => {
    contentApi
      .mediaLimits(workspaceId)
      .then((response) => setLimits(response.limits))
      .catch(() => setLimits(null));
  }, [workspaceId]);

  // ── autosave ───────────────────────────────────────────────────────────────

  const snapshot = useMemo(
    () =>
      JSON.stringify({
        accountId,
        content,
        visibility,
        media: media.map((m) => [m.asset.id, m.alt_text]),
      }),
    [accountId, content, visibility, media],
  );

  const save = useCallback(async () => {
    if (locked || !accountId) return;
    if (snapshot === lastSaved.current) return;
    // Nothing to create a row for yet.
    if (!post && !content.trim() && media.length === 0) return;

    setSaveState("saving");
    setSaveError("");
    const payload = {
      linkedin_account_id: accountId,
      content,
      visibility,
      media: media.map((item) => ({ media_asset_id: item.asset.id, alt_text: item.alt_text })),
    };

    try {
      if (!post) {
        if (creating.current) return;
        creating.current = true;
        const created = await contentApi.createPost(workspaceId, payload);
        creating.current = false;
        setPost(created);
        setMedia(created.media);
        lastSaved.current = snapshot;
        setSaveState("saved");
        // Swap the URL to the real draft so a refresh reopens it.
        router.replace(`/content/${created.id}`);
        return;
      }

      const updated = await contentApi.updatePost(workspaceId, post.id, payload);
      setPost(updated);
      lastSaved.current = snapshot;
      setSaveState("saved");
    } catch (err) {
      creating.current = false;
      setSaveState("error");
      setSaveError(err instanceof ApiError ? err.message : "Could not save. Retrying shortly.");
    }
  }, [accountId, content, locked, media, post, router, snapshot, visibility, workspaceId]);

  useEffect(() => {
    if (locked) return;
    const timer = window.setTimeout(() => void save(), AUTOSAVE_DELAY);
    return () => window.clearTimeout(timer);
  }, [save, locked]);

  // Warn before closing a tab with work that has not landed yet.
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (snapshot !== lastSaved.current && !locked) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [snapshot, locked]);

  // ── actions ────────────────────────────────────────────────────────────────

  /** Every action needs a persisted row; flush any pending edit first. */
  const ensureSaved = async (): Promise<Post | null> => {
    await save();
    return post;
  };

  const runAction = async (label: string, action: (id: string) => Promise<Post>) => {
    setBusy(true);
    setActionError("");
    try {
      await save();
      const current = post;
      if (!current) {
        setActionError("Write something first.");
        return null;
      }
      const updated = await action(current.id);
      setPost(updated);
      setMedia(updated.media);
      setDialog(null);
      return updated;
    } catch (err) {
      const message = err instanceof ApiError ? err.message : `Could not ${label}.`;
      setActionError(message);
      toast.error(message);
      return null;
    } finally {
      setBusy(false);
    }
  };

  const authorize = async (id: string) => {
    setAuthorizing(true);
    try {
      const { authorize_url } = await publishingApi.authorizeUrl(workspaceId, id);
      window.location.href = authorize_url;
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.message : "Could not start the LinkedIn authorization.",
      );
      setAuthorizing(false);
    }
  };

  const insertEmoji = (emoji: string) => {
    const field = textareaRef.current;
    if (!field) {
      setContent((value) => value + emoji);
      return;
    }
    const start = field.selectionStart ?? content.length;
    const end = field.selectionEnd ?? content.length;
    const next = content.slice(0, start) + emoji + content.slice(end);
    setContent(next);
    // Put the caret after the inserted emoji on the next paint.
    window.requestAnimationFrame(() => {
      field.focus();
      field.setSelectionRange(start + emoji.length, start + emoji.length);
    });
  };

  const applyTemplate = (template: Template) => {
    setContent(template.content);
    setDialog(null);
    toast.info(`Template "${template.name}" loaded into the editor.`);
  };

  const saveAsTemplate = async () => {
    setBusy(true);
    try {
      await contentApi.createTemplate(workspaceId, {
        name: templateName.trim() || "Untitled template",
        content,
        media_asset_ids: media.map((item) => item.asset.id),
      });
      setDialog(null);
      setTemplateName("");
      toast.success("Saved as a template.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save the template.");
    } finally {
      setBusy(false);
    }
  };

  // ── render ─────────────────────────────────────────────────────────────────

  if (accounts.length === 0) {
    return (
      <div className="card text-center">
        <h2 className="font-display text-lg font-bold text-ink-950">
          Connect a LinkedIn account first
        </h2>
        <p className="mx-auto mt-1.5 max-w-md text-[13.5px] text-slate-500">
          A post has to go out through a LinkedIn account this workspace owns. Connect one, then
          authorize it for publishing.
        </p>
        <Link href="/accounts" className="btn-primary mt-5 inline-flex">
          Go to accounts
        </Link>
      </div>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
      {/* ── editor ─────────────────────────────────────────────────────────── */}
      <section>
        <PublishingBanner
          capability={capability}
          accountId={accountId}
          onAuthorize={authorize}
          authorizing={authorizing}
        />

        {post?.status === "failed" && post.failure_reason && (
          <div className="mb-4 rounded-xl border border-state-bad/40 bg-state-bad/5 px-4 py-3">
            <div className="flex items-start gap-3">
              <IconWarning className="mt-0.5 h-4 w-4 shrink-0 text-state-bad" />
              <div className="min-w-0 flex-1">
                <p className="text-[13.5px] font-semibold text-slate-800">Publishing failed</p>
                <p className="mt-0.5 text-[13px] text-slate-600">{post.failure_reason}</p>
                {post.request_id && (
                  <p className="mt-1 font-mono text-[11.5px] text-slate-400">
                    LinkedIn reference {post.request_id}
                  </p>
                )}
                <div className="mt-2.5 flex flex-wrap gap-2">
                  {canPublish && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void runAction("retry", (id) => contentApi.retry(workspaceId, id)).then(
                          (updated) => updated && toast.success("Retrying now."),
                        )
                      }
                      className="btn-primary !py-1.5 text-[13px]"
                    >
                      Retry
                    </button>
                  )}
                  {capability.remedy === "authorize" && (
                    <button
                      type="button"
                      onClick={() => void authorize(accountId)}
                      className="btn-ghost !py-1.5 text-[13px]"
                    >
                      Reconnect LinkedIn
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {post?.status === "published" && (
          <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-state-ok/40 bg-state-ok/5 px-4 py-3">
            <IconCheckCircle className="h-4 w-4 shrink-0 text-state-ok" />
            <p className="flex-1 text-[13.5px] font-semibold text-slate-800">
              Published successfully
            </p>
            {post.linkedin_url && (
              <a
                href={post.linkedin_url}
                target="_blank"
                rel="noreferrer"
                className="btn-ghost !py-1.5 text-[13px]"
              >
                View on LinkedIn
              </a>
            )}
          </div>
        )}

        {post?.review_note && post.status === "draft" && (
          <div className="mb-4 rounded-xl border border-state-warn/40 bg-state-warn/5 px-4 py-3 text-[13px] text-slate-700">
            <strong className="font-semibold">Changes requested:</strong> {post.review_note}
          </div>
        )}

        <div className="card">
          {/* Posting as */}
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <span className="text-[12px] font-semibold uppercase tracking-wide text-slate-500">
              Posting as
            </span>
            <select
              value={accountId}
              disabled={locked}
              onChange={(event) => setAccountId(event.target.value)}
              className="input !w-auto min-w-[14rem] !py-1.5 text-[13.5px]"
            >
              {accounts.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.full_name || item.label || item.login_email}
                  {item.publishing.available ? "" : " — needs authorization"}
                </option>
              ))}
            </select>

            <select
              value={visibility}
              disabled={locked}
              onChange={(event) => setVisibility(event.target.value as PostVisibility)}
              className="input !w-auto !py-1.5 text-[13.5px]"
              aria-label="Who can see this post"
            >
              <option value="PUBLIC">Anyone</option>
              <option value="CONNECTIONS">Connections only</option>
            </select>

            <span className="ml-auto flex items-center gap-2">
              <PostStatusPill status={status} />
              <SaveIndicator state={saveState} error={saveError} />
            </span>
          </div>

          <textarea
            ref={textareaRef}
            value={content}
            disabled={locked}
            onChange={(event) => setContent(event.target.value)}
            rows={14}
            placeholder="What do you want to talk about? Start with a line that earns the click."
            className={clsx(
              "w-full resize-y rounded-lg border bg-white px-3.5 py-3 text-[14.5px] leading-relaxed text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-1",
              overLimit
                ? "border-state-bad focus:border-state-bad focus:ring-state-bad"
                : "border-slate-300 focus:border-accent focus:ring-accent",
              locked && "cursor-not-allowed bg-slate-50",
            )}
          />

          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px]">
            <span className={overLimit ? "font-semibold text-state-bad" : "text-slate-500"}>
              Characters: {characters.toLocaleString()} / {maxChars.toLocaleString()}
            </span>
            <span className="text-slate-500">Words: {words.toLocaleString()}</span>
            {characters > 210 && (
              <span className="text-slate-400">
                LinkedIn folds the post after ~210 characters
              </span>
            )}
          </div>
          {overLimit && (
            <p className="mt-1 text-[12.5px] text-state-bad">
              LinkedIn rejects posts over {maxChars.toLocaleString()} characters. Trim{" "}
              {(characters - maxChars).toLocaleString()} more.
            </p>
          )}

          <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-4">
            <button
              type="button"
              disabled={locked}
              onClick={() => setDialog("emoji")}
              className="btn-ghost !py-1.5 text-[13px]"
            >
              <IconSmile className="h-4 w-4" />
              Emoji
            </button>
            <button
              type="button"
              disabled={locked}
              onClick={() =>
                setContent((value) => (value.endsWith("\n") || !value ? value : value + "\n\n"))
              }
              className="btn-ghost !py-1.5 text-[13px]"
              title="Add a paragraph break"
            >
              ¶ Break
            </button>
            <button
              type="button"
              disabled={locked || templates.length === 0}
              onClick={() => setDialog("template")}
              title={templates.length ? undefined : "No templates saved yet"}
              className="btn-ghost !py-1.5 text-[13px]"
            >
              <IconLayers className="h-4 w-4" />
              Templates
            </button>
            <AiAssistant
              workspaceId={workspaceId}
              content={content}
              disabled={locked}
              onApply={(text) => setContent(text)}
            />
          </div>

          <div className="mt-4 border-t border-slate-100 pt-4">
            <p className="label">Media</p>
            <MediaUploader
              workspaceId={workspaceId}
              media={media}
              limits={limits}
              disabled={locked}
              onChange={setMedia}
            />
          </div>
        </div>

        {/* ── action bar ───────────────────────────────────────────────────── */}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={busy || locked || saveState === "saving"}
            onClick={() =>
              void save().then(() => toast.success("Draft saved."))
            }
            className="btn-ghost"
          >
            Save draft
          </button>

          {approvalRequired && !canPublish && (
            <button
              type="button"
              disabled={busy || !content.trim()}
              onClick={() =>
                void runAction("submit", (id) =>
                  contentApi.submitForApproval(workspaceId, id),
                ).then((updated) => updated && toast.success("Sent for approval."))
              }
              className="btn-primary"
            >
              Submit for approval
            </button>
          )}

          {canPublish && (
            <>
              <button
                type="button"
                disabled={busy || !content.trim() || overLimit}
                onClick={() => {
                  void ensureSaved();
                  setActionError("");
                  setDialog("schedule");
                }}
                className="btn-ghost"
              >
                <IconClock className="h-4 w-4" />
                {post?.scheduled_at ? "Reschedule" : "Schedule"}
              </button>
              <button
                type="button"
                disabled={busy || !content.trim() || overLimit}
                onClick={() => {
                  void ensureSaved();
                  setActionError("");
                  setDialog("publish");
                }}
                className="btn-primary"
              >
                <IconSend className="h-4 w-4" />
                Publish now
              </button>
            </>
          )}

          <div className="ml-auto flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!content.trim()}
              onClick={() => setDialog("template")}
              className="btn-ghost !py-1.5 text-[13px]"
            >
              Save as template
            </button>
            {post && (
              <button
                type="button"
                onClick={() => setDialog("delete")}
                className="btn-ghost !py-1.5 text-[13px] text-state-bad"
              >
                Delete
              </button>
            )}
          </div>
        </div>

        {actionError && <p className="mt-2 text-[13px] text-state-bad">{actionError}</p>}

        {post?.status === "scheduled" && post.scheduled_at && (
          <p className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 px-3 py-2.5 text-[13px] text-slate-600">
            <IconClock className="h-4 w-4 text-slate-400" />
            Scheduled for{" "}
            <strong className="font-semibold text-slate-800">
              {new Intl.DateTimeFormat(undefined, {
                dateStyle: "medium",
                timeStyle: "short",
                timeZone: post.scheduled_timezone || "UTC",
              }).format(new Date(post.scheduled_at))}
            </strong>{" "}
            ({post.scheduled_timezone || "UTC"})
            {canPublish && (
              <button
                type="button"
                onClick={() =>
                  void runAction("cancel", (id) => contentApi.cancel(workspaceId, id)).then(
                    (updated) => updated && toast.success("Schedule cancelled."),
                  )
                }
                className="ml-auto font-semibold text-state-bad hover:underline"
              >
                Cancel schedule
              </button>
            )}
          </p>
        )}
      </section>

      {/* ── preview ────────────────────────────────────────────────────────── */}
      <aside className="lg:sticky lg:top-6 lg:self-start">
        <p className="label">LinkedIn preview</p>
        <LinkedInPreview
          content={content}
          media={media}
          authorName={account?.full_name || account?.label || "Your account"}
          authorHeadline={account?.headline ?? ""}
          avatarUrl={account?.avatar_url ?? ""}
          visibility={visibility}
          timeLabel={post?.published_at ? "now" : post?.scheduled_at ? "scheduled" : "now"}
        />
        <p className="mt-2 text-[12px] leading-relaxed text-slate-500">
          An approximation of the LinkedIn feed, drawn with our own components. Exact spacing and
          typography on LinkedIn will differ.
        </p>
      </aside>

      {/* ── dialogs ────────────────────────────────────────────────────────── */}
      {dialog === "emoji" && (
        <Modal title="Insert emoji" onClose={() => setDialog(null)}>
          <div className="space-y-4">
            {EMOJI.map((group) => (
              <div key={group.group}>
                <p className="label">{group.group}</p>
                <div className="flex flex-wrap gap-1">
                  {group.items.map((emoji) => (
                    <button
                      key={emoji}
                      type="button"
                      onClick={() => {
                        insertEmoji(emoji);
                        setDialog(null);
                      }}
                      className="rounded-lg px-2 py-1.5 text-xl hover:bg-slate-100"
                      aria-label={`Insert ${emoji}`}
                    >
                      {emoji}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Modal>
      )}

      {dialog === "template" && (
        <Modal
          title="Templates"
          description="Load saved copy, or keep this post for reuse."
          onClose={() => setDialog(null)}
          wide
        >
          <div className="mb-5 rounded-xl border border-slate-200 p-3">
            <p className="label">Save this post as a template</p>
            <div className="flex flex-wrap gap-2">
              <input
                value={templateName}
                onChange={(event) => setTemplateName(event.target.value)}
                placeholder="Template name"
                className="input flex-1"
              />
              <button
                type="button"
                disabled={busy || !content.trim()}
                onClick={() => void saveAsTemplate()}
                className="btn-primary"
              >
                Save
              </button>
            </div>
          </div>

          {templates.length === 0 ? (
            <p className="text-[13.5px] text-slate-500">No templates saved yet.</p>
          ) : (
            <ul className="space-y-2">
              {templates.map((template) => (
                <li
                  key={template.id}
                  className="flex items-start gap-3 rounded-lg border border-slate-200 p-3"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-[13.5px] font-semibold text-slate-800">{template.name}</p>
                    <p className="mt-0.5 line-clamp-2 text-[12.5px] text-slate-500">
                      {template.content}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => applyTemplate(template)}
                    className="btn-ghost !py-1.5 text-[13px]"
                  >
                    Use
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Modal>
      )}

      {dialog === "schedule" && post && (
        <ScheduleDialog
          post={post}
          defaultTimezone={post.scheduled_timezone || browserTimezone()}
          busy={busy}
          error={actionError}
          onClose={() => setDialog(null)}
          onSchedule={(input) =>
            void runAction("schedule", (id) =>
              contentApi.schedule(workspaceId, id, input),
            ).then((updated) => updated && toast.success("Post scheduled."))
          }
        />
      )}

      {dialog === "publish" && post && (
        <PublishConfirmDialog
          post={post}
          busy={busy}
          error={actionError}
          onClose={() => setDialog(null)}
          onPublish={() =>
            void runAction("publish", (id) => contentApi.publishNow(workspaceId, id)).then(
              (updated) =>
                updated &&
                toast.success(
                  "Publishing now. This page updates when LinkedIn confirms.",
                ),
            )
          }
        />
      )}

      {dialog === "delete" && post && (
        <ConfirmDialog
          title="Delete this post?"
          body="The draft and its schedule are removed. Anything already published to LinkedIn stays on LinkedIn."
          confirmLabel="Delete"
          destructive
          busy={busy}
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            setBusy(true);
            try {
              await contentApi.deletePost(workspaceId, post.id);
              toast.success("Post deleted.");
              router.push("/content");
            } catch (err) {
              toast.error(err instanceof ApiError ? err.message : "Could not delete the post.");
              setBusy(false);
            }
          }}
        />
      )}
    </div>
  );
}

function SaveIndicator({ state, error }: { state: SaveState; error: string }) {
  if (state === "saving") {
    return <span className="text-[12.5px] text-slate-500">Auto-saving…</span>;
  }
  if (state === "saved") {
    return (
      <span className="flex items-center gap-1 text-[12.5px] font-medium text-state-ok">
        <IconCheckCircle className="h-3.5 w-3.5" />
        Saved
      </span>
    );
  }
  if (state === "error") {
    return (
      <span className="text-[12.5px] font-medium text-state-bad" title={error}>
        Not saved
      </span>
    );
  }
  return null;
}
