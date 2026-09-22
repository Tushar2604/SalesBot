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
  IconChevronDown,
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
  RobotMark,
  IconSparkle,
} from "@/components/app/icons";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: IconDashboard },
  { href: "/guide", label: "Guide", icon: IconBook },
  { href: "/campaigns", label: "Campaigns", icon: IconBolt },
  { href: "/leads", label: "Leads", icon: IconConsole },
  { href: "/inbox", label: "Inbox", icon: IconInbox },
  { href: "/assistant", label: "AI Assistant", icon: IconSparkle },
  { href: "/content", label: "Content Studio", icon: IconPencil },
  { href: "/accounts", label: "Accounts", icon: IconUsers },
];

const ADVANCED_ROUTES = ["/templates", "/agency-view", "/integrations"];
const ADVANCED_LINKS = [
  { href: "/templates", label: "Templates", icon: IconLayers },
  { href: "/agency-view", label: "Agency View", icon: IconBriefcase },
  { href: "/integrations", label: "Integrations", icon: IconLink },
];

const UNREAD_POLL_MS = 20_000;

/** Conversations with something new, refreshed on navigation and on a timer. */
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
  const { workspace } = useSession();
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

  return (
    <div className="px-5 pt-5">
      <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">
        LinkedIn Account
      </p>
      {account === "loading" ? (
        <div className="h-[60px] animate-pulse rounded-xl border border-white/10 bg-white/[0.03]" />
      ) : account === null ? (
        <Link
          href="/accounts"
          className="flex flex-col gap-1 rounded-xl border border-dashed border-white/15 px-3 py-2.5 text-[12.5px] font-medium text-slate-400 hover:border-white/30 hover:text-white"
        >
          No account connected
          <span className="text-brand-400">Connect one &rarr;</span>
        </Link>
      ) : (
        <Link
          href="/accounts"
          className="flex w-full items-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 hover:bg-white/[0.06]"
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-violet-500 text-[11px] font-bold text-white">
            {(account.full_name || account.label || "?")[0]?.toUpperCase()}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13.5px] font-semibold text-white">
              {account.full_name || account.label || "LinkedIn account"}
            </span>
            <span
              className={clsx(
                "block text-[11.5px] font-medium",
                account.is_connected ? "text-emerald-400" : "text-rose-400",
              )}
            >
              {account.is_connected ? "Connected" : "Disconnected"}
            </span>
          </span>
        </Link>
      )}
      {account && account !== "loading" && (
        <Link
          href="/settings"
          title="Change in Settings, then Safe Mode"
          className={clsx(
            "mt-2 flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[11.5px] font-semibold transition-colors",
            account.test_mode
              ? "bg-emerald-400/10 text-emerald-400 hover:bg-emerald-400/20"
              : "bg-amber-400/10 text-amber-300 hover:bg-amber-400/20",
          )}
        >
          <IconShield className="h-3.5 w-3.5" />
          Safe Mode {account.test_mode ? "On" : "Off"}
        </Link>
      )}
    </div>
  );
}

export function AppSidebar({ collapsed }: { collapsed: boolean }) {
  const pathname = usePathname();
  const { me, workspace, role, selectWorkspace, signOut } = useSession();
  const settingsRoutes = ["/settings", "/admin/settings", "/team"];
  const [settingsOpen, setSettingsOpen] = useState(settingsRoutes.includes(pathname));
  const [advancedOpen, setAdvancedOpen] = useState(ADVANCED_ROUTES.includes(pathname));

  const settingsActive = settingsRoutes.includes(pathname);
  const advancedActive = ADVANCED_ROUTES.includes(pathname);
  const unreadInbox = useUnreadInbox(workspace?.id, pathname);

  return (
    <aside
      className={clsx(
        "hidden shrink-0 flex-col bg-ink-950 text-slate-300 md:flex",
        collapsed ? "w-[76px]" : "w-64",
      )}
    >
      <Link
        href="/"
        className={clsx("flex items-center gap-2 px-5 pb-2 pt-6", collapsed && "justify-center px-0")}
      >
        <RobotMark className="h-7 w-7 shrink-0 text-brand-400" />
        {!collapsed && <span className="font-display text-lg font-extrabold tracking-tight text-white">SalesBot</span>}
      </Link>

      <div className={clsx("px-5 pt-5", collapsed && "px-3")}>
        {!collapsed && (
          <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Workspace</p>
        )}
        <div
          className={clsx(
            "relative flex w-full items-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 hover:bg-white/[0.06]",
            collapsed && "justify-center px-2",
          )}
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-violet-500 text-[11px] font-bold text-white">
            {(workspace?.name || me?.user.full_name || "W")[0]?.toUpperCase()}
          </span>
          {!collapsed && (
            <>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13.5px] font-semibold text-white">
                  {workspace?.name || "No workspace"}
                </span>
                <span className={clsx("block text-[11.5px] font-medium", workspace ? "text-emerald-400" : "text-rose-400")}>
                  {workspace ? "Connected" : "Disconnected"}
                </span>
              </span>
              <IconChevronUpDown className="h-4 w-4 shrink-0 text-slate-500" />
            </>
          )}
          {me && me.workspaces.length > 0 && (
            <select
              aria-label="Switch workspace"
              className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
              value={workspace?.id ?? ""}
              onChange={(e) => selectWorkspace(e.target.value)}
            >
              {me.workspaces.map(({ workspace: ws }) => (
                <option key={ws.id} value={ws.id}>
                  {ws.name}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      <LinkedInAccountPanel collapsed={collapsed} />

      <div className="mt-5 flex-1 overflow-y-auto px-3 pb-4">
        {!collapsed && <p className="mb-2 px-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Menu</p>}
        <nav className="flex flex-col gap-1">
          {NAV.map((item) => {
            const active =
              pathname === item.href ||
              (item.href !== "/dashboard" && pathname.startsWith(`${item.href}/`));
            const Icon = item.icon;
            const badge = item.href === "/inbox" ? unreadInbox : 0;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={clsx(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-[14px] font-medium transition-colors",
                  collapsed && "justify-center px-2",
                  active ? "bg-white text-ink-950" : "text-slate-300 hover:bg-white/[0.06] hover:text-white",
                )}
              >
                <span className="relative shrink-0">
                  <Icon className="h-[18px] w-[18px]" />
                  {collapsed && badge > 0 && (
                    <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-rose-500 ring-2 ring-ink-950" />
                  )}
                </span>
                {!collapsed && <span className="flex-1">{item.label}</span>}
                {!collapsed && badge > 0 && (
                  <span
                    aria-label={`${badge} unread conversations`}
                    className="min-w-[20px] rounded-full bg-rose-500 px-1.5 py-0.5 text-center text-[11px] font-bold leading-none text-white"
                  >
                    {badge > 99 ? "99+" : badge}
                  </span>
                )}
              </Link>
            );
          })}

          <button
            onClick={() => setSettingsOpen((v) => !v)}
            className={clsx(
              "mt-1 flex items-center gap-3 rounded-lg px-3 py-2.5 text-left text-[14px] font-medium transition-colors",
              collapsed && "justify-center px-2",
              settingsActive ? "bg-white text-ink-950" : "text-slate-300 hover:bg-white/[0.06] hover:text-white",
            )}
          >
            <IconGear className="h-[18px] w-[18px] shrink-0" />
            {!collapsed && (
              <>
                <span className="flex-1">Settings</span>
                <IconChevronDown className={clsx("h-4 w-4 transition-transform", settingsOpen && "rotate-180")} />
              </>
            )}
          </button>
          {!collapsed && settingsOpen && (
            <div className="ml-[26px] flex flex-col gap-0.5 border-l border-white/10 pl-4">
              <Link
                href="/settings"
                className={clsx(
                  "rounded-md px-2 py-2 text-[13.5px] font-medium",
                  pathname === "/settings" ? "text-brand-400" : "text-slate-400 hover:text-white",
                )}
              >
                Settings
              </Link>
              <Link
                href="/admin/settings"
                className={clsx(
                  "rounded-md px-2 py-2 text-[13.5px] font-medium",
                  pathname === "/admin/settings" ? "text-brand-400" : "text-slate-400 hover:text-white",
                )}
              >
                Admin Settings
              </Link>
              <Link
                href="/team"
                className={clsx(
                  "rounded-md px-2 py-2 text-[13.5px] font-medium",
                  pathname === "/team" ? "text-brand-400" : "text-slate-400 hover:text-white",
                )}
              >
                Team
              </Link>
            </div>
          )}

          <button
            onClick={() => setAdvancedOpen((v) => !v)}
            className={clsx(
              "mt-1 flex items-center gap-3 rounded-lg px-3 py-2.5 text-left text-[14px] font-medium transition-colors",
              collapsed && "justify-center px-2",
              advancedActive ? "bg-white text-ink-950" : "text-slate-300 hover:bg-white/[0.06] hover:text-white",
            )}
          >
            <IconLayers className="h-[18px] w-[18px] shrink-0" />
            {!collapsed && (
              <>
                <span className="flex-1">Advanced</span>
                <IconChevronDown className={clsx("h-4 w-4 transition-transform", advancedOpen && "rotate-180")} />
              </>
            )}
          </button>
          {!collapsed && advancedOpen && (
            <div className="ml-[26px] flex flex-col gap-0.5 border-l border-white/10 pl-4">
              {ADVANCED_LINKS.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={clsx(
                    "rounded-md px-2 py-2 text-[13.5px] font-medium",
                    pathname === item.href ? "text-brand-400" : "text-slate-400 hover:text-white",
                  )}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          )}
        </nav>
      </div>

      {me && !collapsed && (
        <div className="border-t border-white/10 px-5 py-4">
          <p className="truncate text-[12.5px] font-medium text-slate-300">{me.user.full_name || me.user.email}</p>
          <p className="mb-2.5 truncate text-[11px] text-slate-500">{role} &middot; {me.user.email}</p>
          <button
            onClick={() => void signOut()}
            className="text-[12.5px] font-semibold text-slate-400 hover:text-white"
          >
            Sign out
          </button>
        </div>
      )}
    </aside>
  );
}
