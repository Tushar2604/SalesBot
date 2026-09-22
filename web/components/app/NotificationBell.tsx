"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { notificationsApi, type Notification } from "@/lib/api";
import { IconBell } from "@/components/app/icons";

const POLL_MS = 30_000;

function timeAgo(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function NotificationBell({ workspaceId }: { workspaceId: string | null }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const page = await notificationsApi.list(workspaceId);
      setItems(page.items);
      setUnreadCount(page.unread_count);
    } catch {
      // Silent: the bell just stays at its last known state until the next poll.
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
    const interval = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(interval);
  }, [load]);

  useEffect(() => {
    function onClickOutside(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next) {
      setLoading(true);
      await load();
      setLoading(false);
    }
  }

  async function onSelect(notification: Notification) {
    setOpen(false);
    if (workspaceId && !notification.read) {
      setItems((prev) => prev.map((n) => (n.id === notification.id ? { ...n, read: true } : n)));
      setUnreadCount((c) => Math.max(0, c - 1));
      notificationsApi.markRead(workspaceId, notification.id).catch(() => undefined);
    }
    if (notification.link) router.push(notification.link);
  }

  async function onMarkAllRead() {
    if (!workspaceId) return;
    setItems((prev) => prev.map((n) => ({ ...n, read: true })));
    setUnreadCount(0);
    notificationsApi.markAllRead(workspaceId).catch(() => undefined);
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        onClick={() => void toggle()}
        aria-label="Notifications"
        className="relative flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-ink-950"
      >
        <IconBell className="h-[18px] w-[18px]" />
        {unreadCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-500 px-1 text-[9px] font-bold leading-none text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-11 z-30 w-80 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <span className="text-[13.5px] font-bold text-ink-950">Notifications</span>
            {unreadCount > 0 && (
              <button
                onClick={() => void onMarkAllRead()}
                className="text-[12px] font-semibold text-brand-600 hover:underline"
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {loading && items.length === 0 && (
              <p className="px-4 py-6 text-center text-[13px] text-slate-400">Loading…</p>
            )}
            {!loading && items.length === 0 && (
              <p className="px-4 py-6 text-center text-[13px] text-slate-400">
                You&apos;re all caught up.
              </p>
            )}
            {items.map((notification) => (
              <button
                key={notification.id}
                onClick={() => void onSelect(notification)}
                className="flex w-full items-start gap-2.5 border-b border-slate-50 px-4 py-3 text-left last:border-b-0 hover:bg-slate-50"
              >
                <span
                  className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${notification.read ? "bg-transparent" : "bg-brand-500"}`}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-ink-950">
                    {notification.title}
                  </span>
                  {notification.body && (
                    <span className="mt-0.5 block truncate text-[12px] text-slate-500">
                      {notification.body}
                    </span>
                  )}
                  <span className="mt-1 block text-[11px] text-slate-400">
                    {timeAgo(notification.created_at)}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
