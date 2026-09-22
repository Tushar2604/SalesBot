"use client";

/**
 * The post list used by All / Drafts / Scheduled / Published.
 *
 * One component for all four because the only differences are the status filter
 * it starts with and which actions make sense per row — both of which are data,
 * not structure.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import { ApiError, linkedinApi, type LinkedInAccount } from "@/lib/api";
import {
  browserTimezone,
  contentApi,
  formatInZone,
  publishingApi,
  relativeTime,
  type Post,
  type PostPage,
  type PostStatus,
} from "@/lib/content-api";
import { useSession } from "@/lib/session";
import {
  CardSkeleton,
  ConfirmDialog,
  EmptyState,
  PostStatusPill,
  useToast,
} from "@/components/content/ContentUi";
import { PublishConfirmDialog, ScheduleDialog } from "@/components/content/ScheduleDialog";
import {
  IconCalendar,
  IconCheckCircle,
  IconCopy,
  IconDocument,
  IconImage,
  IconPencil,
  IconPlus,
  IconSearch,
  IconSend,
  IconTrash,
  IconVideo,
  IconWarning,
} from "@/components/app/icons";

const PAGE_SIZE = 20;

type Dialog =
  | { kind: "schedule"; post: Post }
  | { kind: "publish"; post: Post }
  | { kind: "delete"; post: Post }
  | { kind: "cancel"; post: Post }
  | null;

export function PostList({
  statuses,
  emptyTitle,
  emptyBody,
  showFilters = true,
}: {
  statuses?: PostStatus[];
  emptyTitle: string;
  emptyBody: string;
  showFilters?: boolean;
}) {
  const { workspace, role } = useSession();
  const workspaceId = workspace?.id ?? null;
  const router = useRouter();
  const toast = useToast();

  const canPublish = role === "owner" || role === "admin";

  const [page, setPage] = useState<PostPage | null>(null);
  const [accounts, setAccounts] = useState<LinkedInAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [accountFilter, setAccountFilter] = useState("");
  const [authorFilter, setAuthorFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [offset, setOffset] = useState(0);

  const [dialog, setDialog] = useState<Dialog>(null);
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search);
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    setError("");
    try {
      const result = await contentApi.posts(workspaceId, {
        status: statuses,
        search: debouncedSearch,
        account_id: accountFilter || undefined,
        author_id: authorFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        limit: PAGE_SIZE,
        offset,
      });
      setPage(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load posts.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, statuses, debouncedSearch, accountFilter, authorFilter, dateFrom, dateTo, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!workspaceId) return;
    linkedinApi
      .accounts(workspaceId)
      .then(setAccounts)
      .catch(() => setAccounts([]));
  }, [workspaceId]);

  /** A post in flight is worth re-checking without the user pressing anything. */
  const hasInFlight = useMemo(
    () => (page?.items ?? []).some((post) => post.status === "publishing"),
    [page],
  );
  useEffect(() => {
    if (!hasInFlight) return;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [hasInFlight, load]);

  const authors = useMemo(() => {
    const seen = new Map<string, string>();
    (page?.items ?? []).forEach((post) => {
      if (post.created_by_id) seen.set(post.created_by_id, post.created_by_name || "Unknown");
    });
    return Array.from(seen, ([id, name]) => ({ id, name }));
  }, [page]);

  const act = async (label: string, run: () => Promise<unknown>, success: string) => {
    setBusy(true);
    setDialogError("");
    try {
      await run();
      toast.success(success);
      setDialog(null);
      await load();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : `Could not ${label}.`;
      setDialogError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  const authorize = async (accountId: string) => {
    if (!workspaceId) return;
    try {
      const { authorize_url } = await publishingApi.authorizeUrl(workspaceId, accountId);
      window.location.href = authorize_url;
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not start authorization.");
    }
  };

  if (!workspaceId) {
    return <EmptyState title="No workspace selected" body="Pick a workspace to see its posts." />;
  }

  return (
    <div>
      {showFilters && (
        <div className="mb-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <label className="relative sm:col-span-2">
            <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search posts…"
              className="input !pl-9"
              aria-label="Search posts"
            />
          </label>
          <select
            value={accountFilter}
            onChange={(event) => {
              setAccountFilter(event.target.value);
              setOffset(0);
            }}
            className="input"
            aria-label="Filter by LinkedIn account"
          >
            <option value="">All accounts</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.full_name || account.label || account.login_email}
              </option>
            ))}
          </select>
          <select
            value={authorFilter}
            onChange={(event) => {
              setAuthorFilter(event.target.value);
              setOffset(0);
            }}
            className="input"
            aria-label="Filter by author"
          >
            <option value="">All authors</option>
            {authors.map((author) => (
              <option key={author.id} value={author.id}>
                {author.name}
              </option>
            ))}
          </select>
          <div className="flex gap-2">
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => {
                setDateFrom(event.target.value);
                setOffset(0);
              }}
              className="input"
              aria-label="From date"
            />
            <input
              type="date"
              value={dateTo}
              onChange={(event) => {
                setDateTo(event.target.value);
                setOffset(0);
              }}
              className="input"
              aria-label="To date"
            />
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-xl border border-state-bad/40 bg-state-bad/5 px-4 py-3 text-[13.5px] text-slate-700">
          <IconWarning className="h-4 w-4 shrink-0 text-state-bad" />
          {error}
          <button type="button" onClick={() => void load()} className="ml-auto font-semibold text-accent">
            Retry
          </button>
        </div>
      )}

      {loading && !page ? (
        <CardSkeleton count={3} />
      ) : (page?.items.length ?? 0) === 0 ? (
        <EmptyState
          title={emptyTitle}
          body={emptyBody}
          action={
            <Link href="/content/new" className="btn-primary">
              <IconPlus className="h-4 w-4" />
              Create post
            </Link>
          }
        />
      ) : (
        <>
          <ul className="space-y-3">
            {page!.items.map((post) => (
              <PostCard
                key={post.id}
                post={post}
                canPublish={canPublish}
                onEdit={() => router.push(`/content/${post.id}`)}
                onDuplicate={() =>
                  void act(
                    "duplicate",
                    () => contentApi.duplicate(workspaceId, post.id),
                    "Duplicated as a new draft.",
                  )
                }
                onRepurpose={() =>
                  void act(
                    "repurpose",
                    () => contentApi.repurpose(workspaceId, post.id),
                    "Repurposed into a new draft.",
                  )
                }
                onSchedule={() => {
                  setDialogError("");
                  setDialog({ kind: "schedule", post });
                }}
                onPublish={() => {
                  setDialogError("");
                  setDialog({ kind: "publish", post });
                }}
                onCancel={() => setDialog({ kind: "cancel", post })}
                onDelete={() => setDialog({ kind: "delete", post })}
                onRetry={() =>
                  void act("retry", () => contentApi.retry(workspaceId, post.id), "Retrying now.")
                }
                onAuthorize={() => void authorize(post.account.id)}
                onApprove={() =>
                  void act(
                    "approve",
                    () => contentApi.approve(workspaceId, post.id),
                    "Post approved.",
                  )
                }
              />
            ))}
          </ul>

          {page!.total > PAGE_SIZE && (
            <div className="mt-5 flex items-center justify-between text-[13px] text-slate-500">
              <span>
                {offset + 1}–{Math.min(offset + PAGE_SIZE, page!.total)} of {page!.total}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  className="btn-ghost !py-1.5 text-[13px]"
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={offset + PAGE_SIZE >= page!.total}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  className="btn-ghost !py-1.5 text-[13px]"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {dialog?.kind === "schedule" && (
        <ScheduleDialog
          post={dialog.post}
          defaultTimezone={dialog.post.scheduled_timezone || browserTimezone()}
          busy={busy}
          error={dialogError}
          onClose={() => setDialog(null)}
          onSchedule={(input) =>
            void act(
              "schedule",
              () => contentApi.schedule(workspaceId, dialog.post.id, input),
              "Post scheduled.",
            )
          }
        />
      )}

      {dialog?.kind === "publish" && (
        <PublishConfirmDialog
          post={dialog.post}
          busy={busy}
          error={dialogError}
          onClose={() => setDialog(null)}
          onPublish={() =>
            void act(
              "publish",
              () => contentApi.publishNow(workspaceId, dialog.post.id),
              "Publishing now.",
            )
          }
        />
      )}

      {dialog?.kind === "cancel" && (
        <ConfirmDialog
          title="Cancel this schedule?"
          body="The post goes back to your drafts and will not be published at its scheduled time."
          confirmLabel="Cancel schedule"
          busy={busy}
          onClose={() => setDialog(null)}
          onConfirm={() =>
            void act(
              "cancel",
              () => contentApi.cancel(workspaceId, dialog.post.id),
              "Schedule cancelled.",
            )
          }
        />
      )}

      {dialog?.kind === "delete" && (
        <ConfirmDialog
          title="Delete this post?"
          body="This removes the post from the studio. Anything already published to LinkedIn stays on LinkedIn."
          confirmLabel="Delete"
          destructive
          busy={busy}
          onClose={() => setDialog(null)}
          onConfirm={() =>
            void act(
              "delete",
              () => contentApi.deletePost(workspaceId, dialog.post.id),
              "Post deleted.",
            )
          }
        />
      )}
    </div>
  );
}

function MediaThumb({ post }: { post: Post }) {
  const first = post.media[0];
  if (!first) return null;

  const Icon =
    first.asset.kind === "video"
      ? IconVideo
      : first.asset.kind === "document"
        ? IconDocument
        : IconImage;

  return (
    <div className="relative h-16 w-16 shrink-0 overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
      {first.asset.kind === "image" && first.asset.url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={first.asset.url} alt="" className="h-full w-full object-cover" />
      ) : (
        <span className="flex h-full w-full items-center justify-center text-slate-500">
          <Icon className="h-5 w-5" />
        </span>
      )}
      {post.media.length > 1 && (
        <span className="absolute bottom-0 right-0 rounded-tl-md bg-black/60 px-1.5 py-0.5 text-[10.5px] font-semibold text-white">
          +{post.media.length - 1}
        </span>
      )}
    </div>
  );
}

function PostCard({
  post,
  canPublish,
  onEdit,
  onDuplicate,
  onRepurpose,
  onSchedule,
  onPublish,
  onCancel,
  onDelete,
  onRetry,
  onAuthorize,
  onApprove,
}: {
  post: Post;
  canPublish: boolean;
  onEdit: () => void;
  onDuplicate: () => void;
  onRepurpose: () => void;
  onSchedule: () => void;
  onPublish: () => void;
  onCancel: () => void;
  onDelete: () => void;
  onRetry: () => void;
  onAuthorize: () => void;
  onApprove: () => void;
}) {
  const zone = post.scheduled_timezone || browserTimezone();

  return (
    <li className="card transition-shadow hover:shadow-md">
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-violet-500 text-[11px] font-bold text-white">
          {(post.account.full_name || post.account.label || "?")[0]?.toUpperCase()}
        </span>
        <span className="min-w-0 text-[13.5px] font-semibold text-slate-800">
          {post.account.full_name || post.account.label}
        </span>
        <PostStatusPill status={post.status} />
        {post.created_by_name && (
          <span className="text-[12.5px] text-slate-400">by {post.created_by_name}</span>
        )}
        <span className="ml-auto text-[12.5px] text-slate-400">
          Created {relativeTime(post.created_at)}
        </span>
      </div>

      <div className="mt-3 flex gap-3">
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={onEdit}
            className="block w-full text-left"
            aria-label="Open this post"
          >
            <p className="line-clamp-3 whitespace-pre-wrap text-[13.5px] leading-relaxed text-slate-700">
              {post.content.trim() || <span className="italic text-slate-400">Empty draft</span>}
            </p>
          </button>
          <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-slate-500">
            <span>{post.character_count.toLocaleString()} characters</span>
            <span>{post.word_count.toLocaleString()} words</span>
            {post.hashtags.length > 0 && (
              <span className="text-accent">
                {post.hashtags.slice(0, 3).map((tag) => `#${tag}`).join(" ")}
              </span>
            )}
          </p>
        </div>
        <MediaThumb post={post} />
      </div>

      {(post.scheduled_at || post.published_at) && (
        <p className="mt-3 flex items-center gap-1.5 text-[12.5px] text-slate-500">
          <IconCalendar className="h-3.5 w-3.5 text-slate-400" />
          {post.published_at ? (
            <>Published {formatInZone(post.published_at, zone)}</>
          ) : (
            <>
              Scheduled for {formatInZone(post.scheduled_at, zone)} ({zone})
            </>
          )}
        </p>
      )}

      {post.status === "failed" && post.failure_reason && (
        <div className="mt-3 rounded-lg border border-state-bad/30 bg-state-bad/5 px-3 py-2">
          <p className="text-[12.5px] text-slate-700">
            <strong className="font-semibold">Publishing failed:</strong> {post.failure_reason}
          </p>
        </div>
      )}

      {post.status === "published" && (
        <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          {post.analytics.available ? (
            <dl className="flex flex-wrap gap-x-5 gap-y-1 text-[12.5px]">
              {(
                [
                  ["Impressions", post.analytics.impressions],
                  ["Likes", post.analytics.likes],
                  ["Comments", post.analytics.comments],
                  ["Reposts", post.analytics.reposts],
                  ["Clicks", post.analytics.clicks],
                ] as const
              ).map(([label, value]) => (
                <div key={label}>
                  <dt className="inline text-slate-500">{label} </dt>
                  <dd className="inline font-semibold text-slate-800">{value ?? "—"}</dd>
                </div>
              ))}
              {post.analytics.engagement_rate !== null && (
                <div>
                  <dt className="inline text-slate-500">Engagement </dt>
                  <dd className="inline font-semibold text-slate-800">
                    {(post.analytics.engagement_rate * 100).toFixed(1)}%
                  </dd>
                </div>
              )}
            </dl>
          ) : (
            <p className="text-[12.5px] text-slate-500">
              <strong className="font-semibold text-slate-600">Analytics unavailable.</strong>{" "}
              {post.analytics.message}
            </p>
          )}
        </div>
      )}

      {!post.account.can_publish && post.status !== "published" && (
        <p className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-state-warn/30 bg-state-warn/5 px-3 py-2 text-[12.5px] text-slate-700">
          <IconWarning className="h-3.5 w-3.5 shrink-0 text-state-warn" />
          {post.account.capability.message}
          {post.account.capability.remedy === "authorize" && canPublish && (
            <button
              type="button"
              onClick={onAuthorize}
              className="font-semibold text-accent hover:underline"
            >
              Connect for publishing
            </button>
          )}
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
        {post.is_editable && (
          <ActionButton onClick={onEdit} icon={IconPencil}>
            Edit
          </ActionButton>
        )}
        <ActionButton onClick={onDuplicate} icon={IconCopy}>
          Duplicate
        </ActionButton>
        {post.content.trim() && (
          <ActionButton onClick={onRepurpose}>Repurpose</ActionButton>
        )}

        {canPublish && post.status === "pending_approval" && (
          <ActionButton onClick={onApprove} icon={IconCheckCircle} tone="primary">
            Approve
          </ActionButton>
        )}

        {canPublish && post.is_editable && post.status !== "published" && (
          <>
            <ActionButton onClick={onSchedule} icon={IconCalendar}>
              {post.scheduled_at ? "Reschedule" : "Schedule"}
            </ActionButton>
            {post.status === "failed" ? (
              <ActionButton onClick={onRetry} icon={IconSend} tone="primary">
                Retry
              </ActionButton>
            ) : (
              <ActionButton onClick={onPublish} icon={IconSend} tone="primary">
                Publish now
              </ActionButton>
            )}
          </>
        )}

        {canPublish && post.status === "scheduled" && (
          <ActionButton onClick={onCancel}>Cancel</ActionButton>
        )}

        {post.status === "published" && post.linkedin_url && (
          <a
            href={post.linkedin_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-[12.5px] font-semibold text-slate-700 hover:border-slate-400"
          >
            View on LinkedIn
          </a>
        )}

        {post.status !== "publishing" && (
          <ActionButton onClick={onDelete} icon={IconTrash} tone="danger" className="ml-auto">
            Delete
          </ActionButton>
        )}
      </div>
    </li>
  );
}

function ActionButton({
  onClick,
  icon: Icon,
  children,
  tone = "default",
  className,
}: {
  onClick: () => void;
  icon?: ({ className }: { className?: string }) => JSX.Element;
  children: React.ReactNode;
  tone?: "default" | "primary" | "danger";
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12.5px] font-semibold transition-colors",
        tone === "primary" && "border-accent bg-accent text-white hover:bg-accent-hover",
        tone === "danger" && "border-slate-200 text-state-bad hover:border-state-bad/40 hover:bg-state-bad/5",
        tone === "default" && "border-slate-300 text-slate-700 hover:border-slate-400",
        className,
      )}
    >
      {Icon && <Icon className="h-3.5 w-3.5" />}
      {children}
    </button>
  );
}
