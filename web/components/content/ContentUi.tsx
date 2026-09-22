"use client";

/**
 * Small shared pieces for Content Studio: status pill, modal shell, toasts,
 * skeletons, empty states, and the publishing-permission banner.
 *
 * These live in one file because each is a handful of lines and they are always
 * used together; splitting them would add imports without adding clarity.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import {
  STATUS_LABELS,
  STATUS_STYLES,
  type PostStatus,
  type PublishingCapability,
} from "@/lib/content-api";
import { IconCheckCircle, IconClose, IconWarning } from "@/components/app/icons";

// ── status ───────────────────────────────────────────────────────────────────

export function PostStatusPill({ status }: { status: PostStatus }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11.5px] font-semibold",
        STATUS_STYLES[status],
      )}
    >
      {status === "publishing" && (
        <span className="h-2 w-2 animate-pulse rounded-full bg-current" aria-hidden />
      )}
      {STATUS_LABELS[status]}
    </span>
  );
}

// ── modal ────────────────────────────────────────────────────────────────────

export function Modal({
  title,
  description,
  onClose,
  children,
  footer,
  wide = false,
}: {
  title: string;
  description?: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    // Freeze the page behind the dialog so a long list does not scroll under it.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-ink-950/40 p-0 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={clsx(
          "max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-white shadow-xl sm:rounded-2xl",
          wide ? "sm:max-w-3xl" : "sm:max-w-lg",
        )}
      >
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
          <div>
            <h2 className="font-display text-[17px] font-bold text-ink-950">{title}</h2>
            {description && <p className="mt-0.5 text-[13px] text-slate-500">{description}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <IconClose className="h-4 w-4" />
          </button>
        </header>
        <div className="px-5 py-4">{children}</div>
        {footer && (
          <footer className="flex flex-wrap justify-end gap-2 border-t border-slate-200 px-5 py-4">
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}

// ── toasts ───────────────────────────────────────────────────────────────────

type Toast = { id: number; tone: "ok" | "bad" | "info"; message: string; href?: string; hrefLabel?: string };
type ToastApi = {
  success: (message: string, link?: { href: string; label: string }) => void;
  error: (message: string) => void;
  info: (message: string) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback(
    (tone: Toast["tone"], message: string, link?: { href: string; label: string }) => {
      const id = Date.now() + Math.random();
      setToasts((current) => [...current, { id, tone, message, href: link?.href, hrefLabel: link?.label }]);
      // Errors stay longer: they usually need reading twice.
      window.setTimeout(() => {
        setToasts((current) => current.filter((toast) => toast.id !== id));
      }, tone === "bad" ? 8000 : 5000);
    },
    [],
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (message, link) => push("ok", message, link),
      error: (message) => push("bad", message),
      info: (message) => push("info", message),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            className={clsx(
              "pointer-events-auto flex items-start gap-2.5 rounded-xl border px-4 py-3 shadow-lg",
              toast.tone === "ok" && "border-state-ok/30 bg-white text-slate-800",
              toast.tone === "bad" && "border-state-bad/30 bg-white text-slate-800",
              toast.tone === "info" && "border-slate-200 bg-white text-slate-800",
            )}
          >
            {toast.tone === "ok" ? (
              <IconCheckCircle className="mt-0.5 h-4 w-4 shrink-0 text-state-ok" />
            ) : toast.tone === "bad" ? (
              <IconWarning className="mt-0.5 h-4 w-4 shrink-0 text-state-bad" />
            ) : null}
            <div className="min-w-0 flex-1 text-[13.5px]">
              <p>{toast.message}</p>
              {toast.href && (
                <a
                  href={toast.href}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1 inline-block font-semibold text-accent hover:underline"
                >
                  {toast.hrefLabel ?? "Open"}
                </a>
              )}
            </div>
            <button
              type="button"
              aria-label="Dismiss"
              onClick={() => setToasts((current) => current.filter((t) => t.id !== toast.id))}
              className="rounded p-0.5 text-slate-400 hover:text-slate-700"
            >
              <IconClose className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>");
  return context;
}

// ── loading and empty states ─────────────────────────────────────────────────

export function CardSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-3" aria-hidden>
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="card animate-pulse">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-full bg-slate-200" />
            <div className="flex-1 space-y-2">
              <div className="h-3 w-40 rounded bg-slate-200" />
              <div className="h-2.5 w-24 rounded bg-slate-100" />
            </div>
            <div className="h-5 w-20 rounded-full bg-slate-100" />
          </div>
          <div className="mt-4 space-y-2">
            <div className="h-2.5 w-full rounded bg-slate-100" />
            <div className="h-2.5 w-11/12 rounded bg-slate-100" />
            <div className="h-2.5 w-2/3 rounded bg-slate-100" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="card flex flex-col items-center py-14 text-center">
      <h3 className="font-display text-[17px] font-bold text-ink-950">{title}</h3>
      <p className="mt-1.5 max-w-sm text-[13.5px] text-slate-500">{body}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

// ── publishing permission ────────────────────────────────────────────────────

/**
 * The honest answer when an account cannot post.
 *
 * This is the surface required by the product rule that a missing LinkedIn
 * permission is *reported*, with a route to fixing it, and never papered over.
 */
export function PublishingBanner({
  capability,
  accountId,
  onAuthorize,
  authorizing = false,
}: {
  capability: PublishingCapability;
  accountId?: string;
  onAuthorize?: (accountId: string) => void;
  authorizing?: boolean;
}) {
  if (capability.available) return null;

  return (
    <div className="mb-4 rounded-xl border border-state-warn/40 bg-state-warn/5 px-4 py-3">
      <div className="flex items-start gap-3">
        <IconWarning className="mt-0.5 h-4 w-4 shrink-0 text-state-warn" />
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] font-semibold text-slate-800">
            {capability.code === "not_configured"
              ? "Publishing is not set up on this deployment"
              : "This LinkedIn account cannot publish yet"}
          </p>
          <p className="mt-0.5 text-[13px] text-slate-600">{capability.message}</p>

          <div className="mt-2.5 flex flex-wrap gap-2">
            {capability.remedy === "authorize" && accountId && onAuthorize && (
              <button
                type="button"
                disabled={authorizing}
                onClick={() => onAuthorize(accountId)}
                className="btn-primary !py-1.5 text-[13px]"
              >
                {authorizing ? "Opening LinkedIn…" : "Connect for publishing"}
              </button>
            )}
            {capability.remedy === "configure" && (
              <Link href="/accounts" className="btn-ghost !py-1.5 text-[13px]">
                LinkedIn accounts
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── confirmation ─────────────────────────────────────────────────────────────

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  destructive = false,
  busy = false,
  onConfirm,
  onClose,
}: {
  title: string;
  body: React.ReactNode;
  confirmLabel: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-ghost">
            Cancel
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onConfirm}
            className={destructive ? "btn-danger" : "btn-primary"}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </>
      }
    >
      <div className="text-[13.5px] text-slate-600">{body}</div>
    </Modal>
  );
}
