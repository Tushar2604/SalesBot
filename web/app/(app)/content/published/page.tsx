"use client";

/** Published posts and whatever performance data the integration can supply. */

import { PostList } from "@/components/content/PostList";

export default function PublishedPage() {
  return (
    <PostList
      statuses={["published"]}
      emptyTitle="Nothing published yet"
      emptyBody="Once a post goes live on LinkedIn it appears here with its permalink and, when the integration can read them, its engagement numbers."
    />
  );
}
