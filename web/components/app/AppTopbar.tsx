"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "@/lib/session";
import { AccountMenu } from "@/components/app/AccountMenu";
import { NotificationBell } from "@/components/app/NotificationBell";
import { SafetyGuide } from "@/components/app/SafetyGuide";
import { IconDollar, IconGift, IconHelp, IconPanel } from "@/components/app/icons";

const TITLES: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/campaigns": "All Campaigns",
  "/inbox": "Inbox",
  "/guide": "Guide",
  "/assistant": "AI Assistant",
  "/accounts": "Accounts",
  "/leads": "Sales Console",
  "/team": "Team",
  "/settings": "Settings",
  "/admin/settings": "Admin Settings",
  "/templates": "Templates",
  "/agency-view": "Agency View",
  "/integrations": "Integrations",
};

export function AppTopbar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const pathname = usePathname();
  const { workspace } = useSession();
  const title = TITLES[pathname] ?? "SalesBot";

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 sm:px-6">
      <div className="flex items-center gap-3">
        <button
          onClick={onToggle}
          aria-label="Toggle sidebar"
          className="flex h-8 w-8 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 hover:text-ink-950"
        >
          <IconPanel className={collapsed ? "h-5 w-5 rotate-180" : "h-5 w-5"} />
        </button>
        <h1 className="text-lg font-bold tracking-tight text-ink-950">{title}</h1>
      </div>

      <div className="flex items-center gap-2">
        <SafetyGuide />
        <Link
          href="/settings"
          className="hidden items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-[12.5px] font-semibold text-amber-700 hover:bg-amber-100 sm:flex"
        >
          <IconDollar className="h-4 w-4" />
          Your Plan
        </Link>
        <a
          href="/#faq"
          className="hidden items-center gap-1.5 rounded-full border border-brand-100 bg-brand-50 px-3 py-1.5 text-[12.5px] font-semibold text-brand-700 hover:bg-brand-100 sm:flex"
        >
          <IconHelp className="h-4 w-4" />
          Get Help
        </a>
        <Link
          href="/team"
          className="hidden items-center gap-1.5 rounded-full border border-rose-200 bg-rose-50 px-3 py-1.5 text-[12.5px] font-semibold text-rose-700 hover:bg-rose-100 sm:flex"
        >
          <IconGift className="h-4 w-4" />
          Refer and Earn
        </Link>
        <NotificationBell workspaceId={workspace?.id ?? null} />
        <AccountMenu />
      </div>
    </header>
  );
}
