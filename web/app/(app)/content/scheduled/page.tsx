"use client";

/** Scheduled posts, plus anything mid-publish or cancelled. */

import { PostList } from "@/components/content/PostList";

const STATUSES = ["scheduled", "publishing", "cancelled", "failed"] as const;

export default function ScheduledPage() {
  return (
    <PostList
      statuses={[...STATUSES]}
      emptyTitle="Nothing scheduled"
      emptyBody="Schedule a post and it appears here in chronological order, ready to edit, reschedule or cancel before it goes out."
    />
  );
}
