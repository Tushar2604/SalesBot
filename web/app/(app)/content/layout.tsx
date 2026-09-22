"use client";

/**
 * Content Studio shell: section header, sub-navigation, and the toast host that
 * every page in this module publishes into.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { ToastProvider } from "@/components/content/ContentUi";
import { IconPlus } from "@/components/app/icons";

const SECTIONS = [
  { href: "/content", label: "All posts", exact: true },
  { href: "/content/drafts", label: "Drafts" },
  { href: "/content/scheduled", label: "Scheduled" },
  { href: "/content/published", label: "Published" },
  { href: "/content/calendar", label: "Calendar" },
  { href: "/content/templates", label: "Templates" },
  { href: "/content/queue", label: "Queue" },
];

export default function ContentLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // The composer takes the full width: its own two-column layout is the point,
  // and a second nav row above it only competes with the preview.
  const isComposer = pathname === "/content/new" || /^\/content\/[0-9a-f-]{36}$/.test(pathname);

  return (
    <ToastProvider>
      <div className="mx-auto max-w-6xl">
        {!isComposer && (
          <>
            <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
              <div>
                <h1 className="font-display text-2xl font-extrabold tracking-tight text-ink-950">
                  Content Studio
                </h1>
                <p className="mt-1 text-[13.5px] text-slate-500">
                  Write, preview, schedule and publish to your connected LinkedIn accounts.
                </p>
              </div>
              <Link href="/content/new" className="btn-primary">
                <IconPlus className="h-4 w-4" />
                Create post
              </Link>
            </div>

            <nav className="mb-6 overflow-x-auto rounded-xl border border-slate-200 bg-slate-100/70 p-1">
              <div className="flex w-max gap-1">
                {SECTIONS.map((section) => {
                  const active = section.exact
                    ? pathname === section.href
                    : pathname.startsWith(section.href);
                  return (
                    <Link
                      key={section.href}
                      href={section.href}
                      className={clsx(
                        "whitespace-nowrap rounded-lg px-4 py-2 text-[13.5px] font-semibold transition-colors",
                        active
                          ? "bg-white text-ink-950 shadow-sm"
                          : "text-slate-500 hover:text-ink-950",
                      )}
                    >
                      {section.label}
                    </Link>
                  );
                })}
              </div>
            </nav>
          </>
        )}

        {children}
      </div>
    </ToastProvider>
  );
}
