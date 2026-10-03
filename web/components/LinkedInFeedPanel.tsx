"use client";

/**
 * View-and-like: the account's own feed, rendered in our UI, with a Like
 * button that queues a real LinkedIn like.
 *
 * A like is never fired on click. It is queued as an `ActionTask` and runs on
 * the account's own pacing (the same log-normal delay, daily cap and circuit
 * breaker that govern invites and messages), so the button shows "Queued"
 * rather than an instant "Liked" — the delay is real, not a UI trick.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, linkedinApi, type FeedPost, type LinkedInAccount } from "@/lib/api";
import { IconRefresh } from "@/components/app/icons";
import { ToggleRow } from "@/components/ui/Toggle";
import { AutoLikeRules } from "@/components/AutoLikeRules";

// Polls the cache while a refresh (or a like) is known to be in flight, and
// stops once there is nothing left to wait for.
const POLL_MS = 4000;
const POLL_MAX_TICKS = 30; // ~2 minutes

function ThumbIcon({ filled }: { filled: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth={1.8}>
      <path d="M7 10v11H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h3Zm0 0 4.5-7.5a1.5 1.5 0 0 1 2.7.9V8h4.2a2 2 0 0 1 1.97 2.32l-1.3 8A2 2 0 0 1 17.1 20H10a3 3 0 0 1-3-3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function relative(iso: string | null): string {
  if (!iso) return "never";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function PostCard({
  post,
  onLike,
  liking,
}: {
  post: FeedPost;
  onLike: () => void;
  liking: boolean;
}) {
  const queued = post.like_pending || liking;
  return (
    <article className="card">
      <div className="flex items-start gap-3">
        {post.author_avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={post.author_avatar_url}
            alt=""
            className="h-10 w-10 shrink-0 rounded-full object-cover"
          />
        ) : (
          <div className="h-10 w-10 shrink-0 rounded-full bg-slate-200" />
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-ink-950">
            {post.author_name || "LinkedIn member"}
          </p>
          {post.author_headline && (
            <p className="truncate text-xs text-slate-500">{post.author_headline}</p>
          )}
        </div>
      </div>

      {post.text && (
        <p className="mt-3 whitespace-pre-wrap text-sm text-ink-800">{post.text}</p>
      )}

      {post.image_urls.length > 0 && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={post.image_urls[0]}
          alt=""
          className="mt-3 max-h-80 w-full rounded-lg object-cover"
        />
      )}

      <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
        <span className="text-xs text-slate-500">
          {post.like_count > 0 ? `${post.like_count} likes` : ""}
        </span>
        <button
          type="button"
          disabled={post.liked || queued}
          onClick={onLike}
          className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition ${
            post.liked
              ? "bg-brand-50 text-brand-600"
              : queued
                ? "bg-slate-100 text-slate-500"
                : "text-slate-600 hover:bg-slate-100"
          }`}
        >
          <ThumbIcon filled={post.liked} />
          {post.liked ? "Liked" : queued ? "Queued" : "Like"}
        </button>
      </div>
    </article>
  );
}

export function LinkedInFeedPanel({
  workspaceId,
  account,
  onAutoLikeChange,
}: {
  workspaceId: string;
  account: LinkedInAccount;
  /** Persists the toggle; the parent owns the risk-acknowledgement flow. */
  onAutoLikeChange: (enabled: boolean) => void;
}) {
  const accountId = account.id;
  const [posts, setPosts] = useState<FeedPost[] | null>(null);
  const [fetchedAt, setFetchedAt] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [likingUrn, setLikingUrn] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollTicks = useRef(0);

  const load = useCallback(async () => {
    try {
      const feed = await linkedinApi.feed(workspaceId, accountId);
      setPosts(feed.posts);
      setFetchedAt(feed.fetched_at);
      return feed;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the feed");
      return null;
    }
  }, [workspaceId, accountId]);

  useEffect(() => {
    setPosts(null);
    setFetchedAt(null);
    void load();
  }, [load]);

  // While a refresh or a like is in flight, poll the cache until it settles —
  // both run in a worker on the account's own pacing, not on this request.
  useEffect(() => {
    if (!refreshing && !likingUrn) return;
    pollTicks.current = 0;
    const id = setInterval(async () => {
      pollTicks.current += 1;
      const feed = await load();
      if (feed && (feed.fetched_at !== fetchedAt || !feed.refreshing)) {
        setRefreshing(false);
      }
      if (likingUrn && feed?.posts.some((p) => p.urn === likingUrn && (p.liked || !p.like_pending))) {
        setLikingUrn(null);
      }
      if (pollTicks.current >= POLL_MAX_TICKS) {
        setRefreshing(false);
        setLikingUrn(null);
      }
    }, POLL_MS);
    return () => clearInterval(id);
    // fetchedAt intentionally excluded: it is the value being watched for change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshing, likingUrn, load]);

  async function refresh() {
    setError(null);
    try {
      const feed = await linkedinApi.refreshFeed(workspaceId, accountId);
      setPosts(feed.posts);
      setFetchedAt(feed.fetched_at);
      setRefreshing(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not refresh the feed");
    }
  }

  async function like(urn: string) {
    setError(null);
    setLikingUrn(urn);
    setPosts((prev) => prev?.map((p) => (p.urn === urn ? { ...p, like_pending: true } : p)) ?? prev);
    try {
      await linkedinApi.likePost(workspaceId, accountId, urn);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not queue that like");
      setLikingUrn(null);
      setPosts((prev) => prev?.map((p) => (p.urn === urn ? { ...p, like_pending: false } : p)) ?? prev);
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-medium text-ink-950">This account&apos;s feed</h2>
          <p className="text-xs text-slate-500">
            Last refreshed {relative(fetchedAt)}. Likes are queued and paced like every other
            action — they will not appear instantly.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={refreshing}
          className="flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-sm font-medium text-ink-800 hover:bg-slate-50 disabled:opacity-50"
        >
          <IconRefresh className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div className="card mb-4">
        <ToggleRow
          title="Auto-like a few posts a day"
          description={
            account.auto_like_enabled
              ? `On — a background sweep picks 2-5 posts a day from this cache (only ones your rules below allow) and queues ` +
                `a like, on the same pacing and daily cap (${account.caps.daily_likes}/day) as clicking ` +
                `Like yourself. It never reads more of LinkedIn than the cache already has.`
              : "Off — likes only happen when you click Like below. Turning this on lets the " +
                "system pick a small random handful on its own instead; it's a heuristic standing " +
                "in for your judgement, not a replacement for it."
          }
          checked={account.auto_like_enabled}
          onChange={onAutoLikeChange}
        />
        <AutoLikeRules workspaceId={workspaceId} accountId={account.id} />
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-state-bad/40 bg-state-bad/10 px-4 py-3 text-sm text-state-bad">
          {error}
        </p>
      )}

      {posts === null ? (
        <div className="card">
          <p className="text-sm text-slate-500">Loading…</p>
        </div>
      ) : posts.length === 0 ? (
        <div className="card">
          <p className="text-sm text-slate-500">
            No posts cached yet. Click Refresh to read the feed — this loads a real page on the
            account, so it takes a few seconds.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {posts.map((post) => (
            <PostCard
              key={post.urn}
              post={post}
              liking={likingUrn === post.urn}
              onLike={() => void like(post.urn)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
