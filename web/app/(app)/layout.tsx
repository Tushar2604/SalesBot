"use client";

/**
 * Authenticated shell: guard, sidebar, topbar, kill-switch banner.
 *
 * The guard is client-side because the access token lives in memory; server
 * components cannot see it. Every protected route is also enforced server-side
 * by the API, so a bypassed redirect leaks nothing.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { hasRole, useSession } from "@/lib/session";
import { AppSidebar } from "@/components/app/AppSidebar";
import { AppTopbar } from "@/components/app/AppTopbar";
import { GettingStartedCard } from "@/components/app/GettingStartedCard";
import { useOnboardingProgress } from "@/lib/onboarding";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { status, me, workspace, role } = useSession();
  const [collapsed, setCollapsed] = useState(false);
  const onboarding = useOnboardingProgress(workspace?.id ?? null);

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
  }, [status, router]);

  if (status !== "authenticated" || !me) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50">
        <p className="text-sm text-slate-500">Loading…</p>
      </main>
    );
  }

  return (
    <div className="flex min-h-screen bg-slate-50">
      <AppSidebar collapsed={collapsed} />

      <div className="flex min-w-0 flex-1 flex-col">
        <AppTopbar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />

        {workspace?.outreach_paused && (
          <div className="border-b border-amber-200 bg-amber-50 px-6 py-3 text-sm text-amber-700">
            <strong className="font-semibold">Outreach is paused</strong> for this workspace. No
            LinkedIn or email actions will be sent until it is resumed
            {hasRole(role, "admin") ? " in Configuration." : " by an admin."}
          </div>
        )}
        <main className="flex-1 px-4 py-6 sm:px-8 sm:py-8">
          {!onboarding.loading && (
            <div className="mx-auto max-w-6xl">
              <GettingStartedCard
                workspaceId={workspace?.id ?? null}
                doneCount={onboarding.doneCount}
                onContinue={() => router.push(onboarding.nextHref)}
              />
            </div>
          )}
          {children}
        </main>
      </div>
    </div>
  );
}
