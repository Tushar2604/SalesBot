"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "@/lib/session";
import { AccountMenu } from "@/components/app/AccountMenu";
import { NotificationBell } from "@/components/app/NotificationBell";
import { SafetyGuide } from "@/components/app/SafetyGuide";
import { IconDollar, IconGift, IconHourglass, IconPanel } from "@/components/app/icons";

const TITLES: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/campaigns": "All Campaigns",
  "/inbox": "Inbox",
  "/guide": "Guide",
  "/assistant": "AI Assistant",
  "/accounts": "Accounts",
  "/leads": "Leads",
  "/team": "Team",
  "/settings": "Settings",
  "/admin/settings": "Admin Settings",
  "/templates": "Templates",
  "/agency-view": "Agency View",
  "/integrations": "Integrations",
  "/content": "Content Studio",
};

const TRIAL_DAYS = 14;

export function trialDaysLeft(createdAt: string | undefined): number {
  if (!createdAt) return TRIAL_DAYS;
  const end = new Date(createdAt).getTime() + TRIAL_DAYS * 86_400_000;
  return Math.max(0, Math.ceil((end - Date.now()) / 86_400_000));
}

function titleFor(pathname: string): string {
  if (TITLES[pathname]) return TITLES[pathname];
  const match = Object.keys(TITLES).find((key) => key !== "/dashboard" && pathname.startsWith(`${key}/`));
  return match ? TITLES[match] : "SalesBot";
}

export function AppTopbar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const pathname = usePathname();
  const { workspace, me } = useSession();
  const title = titleFor(pathname);
  const days = trialDaysLeft(me?.user.created_at);

  return (
    <header className="flex h-[64px] shrink-0 items-center justify-between bg-white px-4 sm:px-6">
      <div className="flex items-center gap-3">
        <button
          onClick={onToggle}
          aria-label="Toggle sidebar"
          className="flex h-8 w-8 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 hover:text-ink-950"
        >
          <IconPanel className={collapsed ? "h-5 w-5 rotate-180" : "h-5 w-5"} />
        </button>
        <h1 className="text-[22px] font-semibold tracking-tight text-ink-950">{title}</h1>
      </div>

      <div className="flex items-center gap-2.5">
        <Link
          href="/settings"
          className="hidden items-center gap-2 rounded-full bg-[#fff4e8] px-3.5 py-1.5 text-[13px] font-medium text-[#f97316] sm:flex"
        >
          <IconHourglass className="h-4 w-4" />
          {days} trial days left
        </Link>
        <SafetyGuide />
        <Link
          href="/settings"
          aria-label="Billing"
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-ink-950"
        >
          <IconDollar className="h-4 w-4" />
        </Link>
        <Link
          href="/team"
          aria-label="Refer and earn"
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-ink-950"
        >
          <IconGift className="h-4 w-4" />
        </Link>
        <NotificationBell workspaceId={workspace?.id ?? null} />
        <AccountMenu />
      </div>
    </header>
  );
}
