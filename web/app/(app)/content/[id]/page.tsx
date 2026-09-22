"use client";

/** Open an existing post in the composer. */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ApiError, linkedinApi, type LinkedInAccount } from "@/lib/api";
import { contentApi, type Post, type Template } from "@/lib/content-api";
import { useSession } from "@/lib/session";
import { PostComposer } from "@/components/content/PostComposer";
import { CardSkeleton, EmptyState, PostStatusPill } from "@/components/content/ContentUi";
import { IconChevronLeft } from "@/components/app/icons";

export default function EditPostPage() {
  const params = useParams<{ id: string }>();
  const postId = params?.id ?? "";
  const { workspace, role } = useSession();
  const workspaceId = workspace?.id ?? null;
  const canPublish = role === "owner" || role === "admin";

  const [post, setPost] = useState<Post | null>(null);
  const [accounts, setAccounts] = useState<LinkedInAccount[] | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [approvalRequired, setApprovalRequired] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!workspaceId || !postId) return;
    let cancelled = false;

    Promise.all([
      contentApi.post(workspaceId, postId),
      linkedinApi.accounts(workspaceId),
      contentApi.templates(workspaceId).catch(() => [] as Template[]),
      contentApi
        .approvalSettings(workspaceId)
        .catch(() => ({ approval_required: false, can_approve: canPublish })),
    ])
      .then(([loaded, accountList, templateList, settings]) => {
        if (cancelled) return;
        setPost(loaded);
        setAccounts(accountList);
        setTemplates(templateList);
        setApprovalRequired(settings.approval_required);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof ApiError && err.status === 404
            ? "That post no longer exists."
            : err instanceof ApiError
              ? err.message
              : "Could not load this post.",
        );
        setAccounts([]);
      });

    return () => {
      cancelled = true;
    };
  }, [workspaceId, postId, canPublish]);

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Link
          href="/content"
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-300 text-slate-500 hover:border-slate-400 hover:text-ink-950"
          aria-label="Back to Content Studio"
        >
          <IconChevronLeft className="h-4 w-4" />
        </Link>
        <h1 className="font-display text-xl font-extrabold tracking-tight text-ink-950">
          {post?.status === "published" ? "Published post" : "Edit LinkedIn post"}
        </h1>
        {post && <PostStatusPill status={post.status} />}
      </div>

      {error ? (
        <EmptyState
          title="Post unavailable"
          body={error}
          action={
            <Link href="/content" className="btn-primary">
              Back to Content Studio
            </Link>
          }
        />
      ) : !post || accounts === null ? (
        <CardSkeleton count={2} />
      ) : (
        <PostComposer
          workspaceId={workspaceId!}
          accounts={accounts}
          initialPost={post}
          canPublish={canPublish}
          approvalRequired={approvalRequired}
          templates={templates}
        />
      )}
    </div>
  );
}
