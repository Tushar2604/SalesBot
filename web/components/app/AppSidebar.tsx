"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import clsx from "clsx";
import { linkedinApi, type LinkedInAccount } from "@/lib/api";
import { inboxApi } from "@/lib/inbox-api";
import { useSession } from "@/lib/session";
import {
  IconBolt,
  IconBook,
  IconBriefcase,
  IconChevronRight,
  IconChevronUpDown,
  IconConsole,
  IconDashboard,
  IconGear,
  IconInbox,
  IconLayers,
  IconLink,
  IconPencil,
  IconShield,
  IconUsers,
  BrandWordmark,
  RobotMark,
  IconSparkle,
} from "@/components/app/icons";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: IconDashboard },
  { href: "/campaigns", label: "Campaigns", icon: IconBolt },
  { href: "/inbox", label: "Inbox", icon: IconInbox },
  { href: "/accounts", label: "Accounts", icon: IconUsers },
];

const SETTINGS_ROUTES = ["/settings", "/admin/settings", "/team"];
const SETTINGS_LINKS = [
  { href: "/settings", label: "Settings" },
  { href: "/admin/settings", label: "Admin Settings" },
  { href: "/team", label: "Team" },
];

const ADVANCED_ROUTES = ["/guide", "/leads", "/assistant", "/content", "/templates", "/agency-view", "/integrations"];
const ADVANCED_LINKS = [
  { href: "/guide", label: "Guide", icon: IconBook },
  { href: "/leads", label: "Leads", icon: IconConsole },
  { href: "/assistant", label: "AI Assistant", icon: IconSparkle },
  { href: "/content", label: "Content Studio", icon: IconPencil },
  { href: "/templates", label: "Templates", icon: IconLayers },
  { href: "/agency-view", label: "Agency View", icon: IconBriefcase },
  { href: "/integrations", label: "Integrations", icon: IconLink },
];

const UNREAD_POLL_MS = 20_000;

function useUnreadInbox(workspaceId: string | undefined, pathname: string): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!workspaceId) {
      setCount(0);
      return;
    }
    let cancelled = false;
    const load = () =>
      inboxApi
        .conversations(workspaceId, { unreadOnly: true, limit: 1 })
        .then((page) => !cancelled && setCount(page.total))
        .catch(() => undefined);
    void load();
    const timer = setInterval(load, UNREAD_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [workspaceId, pathname]);

  return count;
}

function LinkedInAccountPanel({ collapsed }: { collapsed: boolean }) {
  const { workspace, me, selectWorkspace } = useSession();
  const [account, setAccount] = useState<LinkedInAccount | null | "loading">("loading");

  useEffect(() => {
    if (!workspace?.id) {
      setAccount(null);
      return;
    }
    setAccount("loading");
    linkedinApi
      .accounts(workspace.id)
      .then((accounts) => setAccount(accounts[0] ?? null))
      .catch(() => setAccount(null));
  }, [workspace?.id]);

  if (collapsed) return null;

  const name =
    account && account !== "loading"
      ? account.full_name || account.label || "LinkedIn account"
      : me?.user.full_name || workspace?.name || "Account";
  const initials = name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const connected = account && account !== "loading" ? account.is_connected : false;
  const safeOn = account && account !== "loading" ? account.test_mode : true;

  return (
    <div className="px-4 pt-6">
      <p className="mb-3 px-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
        LinkedIn Account
      </p>
      <Link href="/accounts" className="relative flex items-center gap-3 px-1 py-1">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[#2a2d35] text-[12px] font-semibold text-white">
          {account === "loading" ? "…" : initials}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13.5px] font-medium text-white">{name}</span>
          <span className={clsx("block text-[12px] font-medium", connected ? "text-emerald-400" : "text-[#ff4d4f]")}>
            {account === "loading" ? "…" : account ? (connected ? "Connected" : "Disconnected") : "No account"}
          </span>
        </span>
        <IconChevronUpDown className="h-4 w-4 shrink-0 text-slate-500" />
        {me && me.workspaces.length > 1 && (
          <select
            aria-label="Switch workspace"
            className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
            value={workspace?.id ?? ""}
            onChange={(e) => selectWorkspace(e.target.value)}
            onClick={(e) => e.stopPropagation()}
          >
            {me.workspaces.map(({ workspace: ws }) => (
              <option key={ws.id} value={ws.id}>
                {ws.name}
              </option>
            ))}
          </select>
        )}
      </Link>
      <Link
        href="/settings"
        className="mt-3 flex items-center gap-1.5 px-1 text-[12.5px] font-medium text-[#22c55e]"
      >
        <IconShield className="h-3.5 w-3.5" />
        Safe Mode {safeOn ? "On" : "Off"}
      </Link>
      <div className="mt-4 h-px bg-white/10" />
    </div>
  );
}

function navClass(active: boolean, collapsed: boolean) {
  return clsx(
    "flex items-center gap-3 rounded-[10px] px-3 py-3 text-[14px] transition-colors",
    collapsed && "justify-center px-2",
    active ? "bg-[#f3f4f6] font-medium text-ink-950" : "font-normal text-[#a3acba] hover:bg-white/[0.06] hover:text-white",
  );
}

export function AppSidebar({ collapsed }: { collapsed: boolean }) {
  const pathname = usePathname();
  const { workspace } = useSession();
  const [settingsOpen, setSettingsOpen] = useState(SETTINGS_ROUTES.includes(pathname));
  const [advancedOpen, setAdvancedOpen] = useState(ADVANCED_ROUTES.some((r) => pathname === r || pathname.startsWith(`${r}/`)));

  const settingsActive = SETTINGS_ROUTES.includes(pathname);
  const advancedActive = ADVANCED_ROUTES.some((r) => pathname === r || pathname.startsWith(`${r}/`));
  const unreadInbox = useUnreadInbox(workspace?.id, pathname);

  return (
    <aside
      className={clsx(
        "hidden shrink-0 flex-col bg-[#0b0c10] text-[#a3acba] md:flex",
        collapsed ? "w-[76px]" : "w-[240px]",
      )}
    >
      <Link href="/dashboard" className={clsx("flex items-center gap-2 px-5 pb-1 pt-5", collapsed && "justify-center px-0")}>
        {collapsed ? (
          <RobotMark className="h-8 w-8 shrink-0" />
        ) : (
          <BrandWordmark inverted markClassName="h-8 w-8" className="text-white" />
        )}
      </Link>

      <LinkedInAccountPanel collapsed={collapsed} />

      <div className="mt-4 flex-1 overflow-y-auto px-3 pb-4">
        {!collapsed && (
          <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Menu</p>
        )}
        <nav className="flex flex-col gap-0.5">
          {NAV.map((item) => {
            const active =
              pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(`${item.href}/`));
            const Icon = item.icon;
            const badge = item.href === "/inbox" ? unreadInbox : 0;
            return (
              <Link key={item.href} href={item.href} className={navClass(active, collapsed)}>
                <span className="relative shrink-0">
                  <Icon className="h-[18px] w-[18px]" />
                  {collapsed && badge > 0 && (
                    <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-rose-500 ring-2 ring-[#0b0c10]" />
                  )}
                </span>
                {!collapsed && <span className="flex-1">{item.label}</span>}
                {!collapsed && badge > 0 && (
                  <span className="min-w-[20px] rounded-full bg-rose-500 px-1.5 py-0.5 text-center text-[11px] font-bold leading-none text-white">
                    {badge > 99 ? "99+" : badge}
                  </span>
                )}
              </Link>
            );
          })}

          <button
            onClick={() => setSettingsOpen((v) => !v)}
            className={navClass(settingsActive, collapsed)}
          >
            <IconGear className="h-[18px] w-[18px] shrink-0" />
            {!collapsed && (
              <>
                <span className="flex-1 text-left">Settings</span>
                <IconChevronRight className={clsx("h-4 w-4 transition-transform", settingsOpen && "rotate-90")} />
              </>
            )}
          </button>
          {!collapsed && settingsOpen && (
            <div className="mb-1 ml-4 flex flex-col border-l border-white/10 pl-3">
              {SETTINGS_LINKS.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={clsx(
                    "rounded-md px-2 py-2 text-[13px]",
                    pathname === item.href ? "text-white" : "text-[#a3acba] hover:text-white",
                  )}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          )}

          <button onClick={() => setAdvancedOpen((v) => !v)} className={navClass(advancedActive, collapsed)}>
            <IconLayers className="h-[18px] w-[18px] shrink-0" />
            {!collapsed && (
              <>
                <span className="flex-1 text-left">Advanced</span>
                <IconChevronRight className={clsx("h-4 w-4 transition-transform", advancedOpen && "rotate-90")} />
              </>
            )}
          </button>
          {!collapsed && advancedOpen && (
            <div className="ml-4 flex flex-col border-l border-white/10 pl-3">
              {ADVANCED_LINKS.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={clsx(
                    "rounded-md px-2 py-2 text-[13px]",
                    pathname === item.href || pathname.startsWith(`${item.href}/`)
                      ? "text-white"
                      : "text-[#a3acba] hover:text-white",
                  )}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          )}
        </nav>
      </div>
    </aside>
  );
}
