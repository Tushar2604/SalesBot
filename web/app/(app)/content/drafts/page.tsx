"use client";

/** Drafts, including anything waiting on approval or sent back for changes. */

import { PostList } from "@/components/content/PostList";

const STATUSES = ["draft", "pending_approval", "approved"] as const;

export default function DraftsPage() {
  return (
    <PostList
      statuses={[...STATUSES]}
      emptyTitle="No drafts"
      emptyBody="Drafts you save while writing appear here, along with anything waiting for approval."
    />
  );
}
