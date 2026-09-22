"use client";

/** Content Studio — every post, newest activity first. */

import { PostList } from "@/components/content/PostList";

export default function AllPostsPage() {
  return (
    <PostList
      emptyTitle="No posts yet"
      emptyBody="Create your first LinkedIn post, preview it exactly as your audience will see it, then schedule it or publish it straight away."
    />
  );
}
