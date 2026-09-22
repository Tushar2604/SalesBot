"use client";

/**
 * Workspace-wide onboarding progress, driving the "Getting Started guide"
 * banner that appears on nearly every screen. Computed from real data
 * (connected accounts, imported leads, created/launched campaigns) rather
 * than a stored flag, so it never drifts from what's actually true.
 */

import { useCallback, useEffect, useState } from "react";
import { linkedinApi } from "@/lib/api";
import { campaignsApi, leadsApi } from "@/lib/outreach-api";

export const ONBOARDING_STEPS = ["Connect Account", "Import Leads", "Create Campaign", "Start Campaign"] as const;

export type OnboardingProgress = {
  loading: boolean;
  doneCount: number;
  nextHref: string;
};

export function useOnboardingProgress(workspaceId: string | null): OnboardingProgress {
  const [progress, setProgress] = useState<OnboardingProgress>({ loading: true, doneCount: 0, nextHref: "/accounts" });

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const [accounts, lists, campaigns] = await Promise.all([
        linkedinApi.accounts(workspaceId),
        leadsApi.lists(workspaceId),
        campaignsApi.list(workspaceId),
      ]);

      const hasAccount = accounts.length > 0;
      const hasLeads = lists.length > 0;
      const hasCampaign = campaigns.length > 0;
      const hasRunning = campaigns.some((c) => c.status === "running" || c.status === "completed");

      const doneCount = [hasAccount, hasLeads, hasCampaign, hasRunning].filter(Boolean).length;
      const nextHref = !hasAccount ? "/accounts" : !hasLeads ? "/leads" : !hasCampaign ? "/campaigns?new=1" : "/campaigns";

      setProgress({ loading: false, doneCount, nextHref });
    } catch {
      setProgress((prev) => ({ ...prev, loading: false }));
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  return progress;
}
