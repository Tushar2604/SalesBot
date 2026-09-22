"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSession } from "@/lib/session";
import { BrandWordmark } from "@/components/app/icons";

type MenuItem = { label: string; href: string; desc?: string };
type Menu = { label: string; href?: string; items?: MenuItem[] };

const MENUS: Menu[] = [
  {
    label: "Features",
    items: [
      { label: "Automate LinkedIn", href: "#offer", desc: "Connection requests, messages and InMails in bulk" },
      { label: "Send videos & voice notes", href: "#offer", desc: "Personalized media at scale" },
      { label: "Automate email sending", href: "#offer", desc: "Gmail, Outlook or custom SMTP" },
      { label: "Create drip campaigns", href: "#offer", desc: "Multi-step sequences with conditions" },
      { label: "Smart Reply Detection", href: "#offer", desc: "Messaging stops when a lead replies" },
      { label: "Unified inbox", href: "#offer", desc: "LinkedIn + email in one place" },
      { label: "Import from LinkedIn Search", href: "#how", desc: "Search, Sales Nav, Recruiter or CSV" },
      { label: "Detailed analytics", href: "#ratings", desc: "Campaign, account and team reports" },
    ],
  },
  {
    label: "For You?",
    items: [
      { label: "B2B sales teams", href: "#why", desc: "Fill pipeline without extra headcount" },
      { label: "Lead gen agencies", href: "#why", desc: "Manage client accounts from one workspace" },
      { label: "Founders & SDRs", href: "#why", desc: "Launch a campaign in minutes" },
      { label: "Whitelabel partners", href: "#offer", desc: "Resell under your own brand" },
    ],
  },
  { label: "Pricing", href: "#pricing" },
  {
    label: "Resources",
    items: [
      { label: "Blogs", href: "#insights" },
      { label: "Playbooks", href: "#insights" },
      { label: "FAQ", href: "#faq" },
      { label: "Watch demo", href: "#how" },
    ],
  },
  { label: "Watch Demo", href: "#how" },
  {
    label: "Partners",
    items: [
      { label: "Affiliate program", href: "#cta" },
      { label: "Whitelabel", href: "#offer" },
      { label: "Community", href: "#cta" },
    ],
  },
];

export function LandingHeader() {
  const [open, setOpen] = useState(false);
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  const { status } = useSession();
  const authenticated = status === "authenticated";

  useEffect(() => {
    if (!open) setActiveMenu(null);
  }, [open]);

  return (
    <header className="sticky top-0 z-50">
      <div className="bg-gradient-to-r from-[#e8fff4] via-[#e8f4ff] to-[#efe8ff]">
        <div className="landing-wrap flex items-center justify-between gap-4 py-2.5">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/80 bg-white px-2.5 py-1 text-[11px] font-semibold text-ink-950 shadow-sm">
              <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
              Launching soon
            </span>
            <p className="hidden min-w-0 truncate text-[13px] text-ink-950 sm:block">
              <span className="font-semibold">Meet Kuron Your AI GTM Team</span>
              <span className="mx-2 text-slate-300">|</span>
              <span className="text-slate-600">Autonomous outbound, powered by expert AI agents.</span>
            </p>
          </div>
          <a
            href="#cta"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-[#12324d] px-4 py-2 text-[13px] font-medium text-white hover:bg-[#0d263b]"
          >
            Explore Kuron
            <span aria-hidden>→</span>
          </a>
        </div>
      </div>

      <div className="border-b border-white/40 bg-white/75 backdrop-blur-md">
        <nav className="landing-wrap flex h-[72px] items-center justify-between gap-4">
          <a href="#top" className="shrink-0">
            <BrandWordmark markClassName="h-8 w-8" />
          </a>

          <ul className="hidden items-center gap-1 xl:flex">
            {MENUS.map((menu) => (
              <li
                key={menu.label}
                className="relative"
                onMouseEnter={() => setActiveMenu(menu.items ? menu.label : null)}
                onMouseLeave={() => setActiveMenu(null)}
              >
                {menu.href && !menu.items ? (
                  <a href={menu.href} className="rounded-md px-2.5 py-2 text-[14px] font-medium text-ink-950 hover:bg-slate-50">
                    {menu.label}
                  </a>
                ) : (
                  <button
                    className="inline-flex items-center gap-1 rounded-md px-2.5 py-2 text-[14px] font-medium text-ink-950 hover:bg-slate-50"
                    onClick={() => setActiveMenu((v) => (v === menu.label ? null : menu.label))}
                    aria-expanded={activeMenu === menu.label}
                  >
                    {menu.label}
                    {menu.items && (
                      <svg viewBox="0 0 12 12" className="h-3 w-3 text-slate-500" fill="none">
                        <path d="M2.5 4.5 6 8l3.5-3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                      </svg>
                    )}
                  </button>
                )}
                {menu.items && activeMenu === menu.label && (
                  <div className="absolute left-0 top-full z-40 w-[320px] pt-2">
                    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white py-2 shadow-card">
                      {menu.items.map((item) => (
                        <a
                          key={item.label}
                          href={item.href}
                          className="block px-4 py-2.5 hover:bg-slate-50"
                          onClick={() => setActiveMenu(null)}
                        >
                          <span className="block text-[13.5px] font-medium text-ink-950">{item.label}</span>
                          {item.desc && <span className="mt-0.5 block text-[12px] text-slate-500">{item.desc}</span>}
                        </a>
                      ))}
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>

          <div className="hidden items-center gap-2 lg:flex">
            {authenticated ? (
              <Link href="/dashboard" className="btn-navy px-5 py-2 text-[14px]">
                Go to Dashboard
              </Link>
            ) : (
              <>
                <Link
                  href="/login"
                  className="rounded-full border border-black bg-white px-[25px] py-2 text-[14px] font-medium text-black hover:bg-slate-50"
                >
                  Sign in
                </Link>
                <Link href="/signup" className="btn-navy px-5 py-2.5 text-[14px]">
                  Free Trial (14 days)
                  <span aria-hidden>→</span>
                </Link>
              </>
            )}
          </div>

          <button
            aria-label="Toggle menu"
            className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 lg:hidden"
            onClick={() => setOpen((v) => !v)}
          >
            <span className="relative block h-3 w-4">
              <span className={`absolute left-0 top-0 h-[1.5px] w-4 bg-ink-950 transition-transform ${open ? "translate-y-[5px] rotate-45" : ""}`} />
              <span className={`absolute bottom-0 left-0 h-[1.5px] w-4 bg-ink-950 transition-transform ${open ? "-translate-y-[5px] -rotate-45" : ""}`} />
            </span>
          </button>
        </nav>

        {open && (
          <div className="border-t border-slate-200 px-5 pb-5 pt-2 lg:hidden">
            <ul className="flex flex-col">
              {MENUS.map((menu) => (
                <li key={menu.label}>
                  <a
                    href={menu.href ?? menu.items?.[0]?.href ?? "#top"}
                    onClick={() => setOpen(false)}
                    className="block rounded-md px-2 py-2.5 text-[15px] font-medium text-slate-700 hover:bg-slate-50"
                  >
                    {menu.label}
                  </a>
                </li>
              ))}
            </ul>
            <div className="mt-3 flex flex-col gap-2">
              {authenticated ? (
                <Link href="/dashboard" className="btn-navy py-2.5 text-center">
                  Go to Dashboard
                </Link>
              ) : (
                <>
                  <Link href="/login" className="rounded-full border border-black py-2.5 text-center text-sm font-medium">
                    Sign in
                  </Link>
                  <Link href="/signup" className="btn-navy py-2.5 text-center">
                    Free Trial (14 days)
                  </Link>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </header>
  );
}
