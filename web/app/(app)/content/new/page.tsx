"use client";

/**
 * New post.
 *
 * No draft row is created until there is something to save — the composer's
 * first autosave creates it and swaps the URL to `/content/{id}`, so a refresh
 * mid-sentence reopens the same draft rather than a blank page.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, linkedinApi, type LinkedInAccount } from "@/lib/api";
import { contentApi, type Template } from "@/lib/content-api";
import { useSession } from "@/lib/session";
import { PostComposer } from "@/components/content/PostComposer";
import { CardSkeleton, EmptyState } from "@/components/content/ContentUi";
import { IconChevronLeft } from "@/components/app/icons";

export default function NewPostPage() {
  const { workspace, role } = useSession();
  const workspaceId = workspace?.id ?? null;
  const canPublish = role === "owner" || role === "admin";

  const [accounts, setAccounts] = useState<LinkedInAccount[] | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [approvalRequired, setApprovalRequired] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!workspaceId) return;
    let cancelled = false;

    Promise.all([
      linkedinApi.accounts(workspaceId),
      contentApi.templates(workspaceId).catch(() => [] as Template[]),
      contentApi
        .approvalSettings(workspaceId)
        .catch(() => ({ approval_required: false, can_approve: canPublish })),
    ])
      .then(([accountList, templateList, settings]) => {
        if (cancelled) return;
        setAccounts(accountList);
        setTemplates(templateList);
        setApprovalRequired(settings.approval_required);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not load the composer.");
        setAccounts([]);
      });

    return () => {
      cancelled = true;
    };
  }, [workspaceId, canPublish]);

  return (
    <div>
      <div className="mb-5 flex items-center gap-3">
        <Link
          href="/content"
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-300 text-slate-500 hover:border-slate-400 hover:text-ink-950"
          aria-label="Back to Content Studio"
        >
          <IconChevronLeft className="h-4 w-4" />
        </Link>
        <h1 className="font-display text-xl font-extrabold tracking-tight text-ink-950">
          Create LinkedIn post
        </h1>
      </div>

      {error ? (
        <EmptyState title="Something went wrong" body={error} />
      ) : accounts === null ? (
        <CardSkeleton count={2} />
      ) : (
        <PostComposer
          workspaceId={workspaceId!}
          accounts={accounts}
          initialPost={null}
          canPublish={canPublish}
          approvalRequired={approvalRequired}
          templates={templates}
        />
      )}
    </div>
  );
}
