"use client";

import Link from "next/link";
import { useState } from "react";
import { useSession } from "@/lib/session";

const LINKS = [
  { label: "Product", href: "#offer" },
  { label: "Integrations", href: "#integrations" },
  { label: "Pricing", href: "#pricing" },
  { label: "Reviews", href: "#ratings" },
  { label: "Resources", href: "#insights" },
];

export function LandingHeader() {
  const [open, setOpen] = useState(false);
  const { status } = useSession();
  const authenticated = status === "authenticated";

  return (
    <header className="sticky top-0 z-50">
      <div className="bg-ink-950 px-4 py-2 text-center text-[13px] font-medium text-white">
        Turn your GTM into an unstoppable revenue engine{" "}
        <a href="#cta" className="ml-1 underline decoration-white/40 underline-offset-2 hover:decoration-white">
          Book a demo &rarr;
        </a>
      </div>
      <div className="border-b border-slate-200/80 bg-white/90 backdrop-blur-md">
        <nav className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 sm:px-8">
          <a href="#top" className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-sm font-black text-white">
              S
            </span>
            <span className="font-display text-lg font-extrabold tracking-tight text-ink-950">
              SalesBot
            </span>
          </a>

          <ul className="hidden items-center gap-8 lg:flex">
            {LINKS.map((l) => (
              <li key={l.label}>
                <a
                  href={l.href}
                  className="text-[14.5px] font-medium text-slate-600 transition-colors hover:text-ink-950"
                >
                  {l.label}
                </a>
              </li>
            ))}
          </ul>

          <div className="hidden items-center gap-3 lg:flex">
            {authenticated ? (
              <Link
                href="/dashboard"
                className="rounded-full bg-ink-950 px-5 py-2.5 text-[14.5px] font-semibold text-white shadow-sm transition-transform hover:-translate-y-0.5 hover:bg-ink-900"
              >
                Go to Dashboard
              </Link>
            ) : (
              <>
                <Link href="/login" className="text-[14.5px] font-semibold text-slate-700 hover:text-ink-950">
                  Log in
                </Link>
                <Link
                  href="/signup"
                  className="rounded-full bg-ink-950 px-5 py-2.5 text-[14.5px] font-semibold text-white shadow-sm transition-transform hover:-translate-y-0.5 hover:bg-ink-900"
                >
                  Book a demo
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
              <span
                className={`absolute left-0 top-0 h-[1.5px] w-4 bg-ink-950 transition-transform ${open ? "translate-y-[5px] rotate-45" : ""}`}
              />
              <span
                className={`absolute left-0 bottom-0 h-[1.5px] w-4 bg-ink-950 transition-transform ${open ? "-translate-y-[5px] -rotate-45" : ""}`}
              />
            </span>
          </button>
        </nav>

        {open && (
          <div className="border-t border-slate-200 px-5 pb-5 pt-2 lg:hidden">
            <ul className="flex flex-col gap-1">
              {LINKS.map((l) => (
                <li key={l.label}>
                  <a
                    href={l.href}
                    onClick={() => setOpen(false)}
                    className="block rounded-md px-2 py-2.5 text-[15px] font-medium text-slate-700 hover:bg-slate-50"
                  >
                    {l.label}
                  </a>
                </li>
              ))}
            </ul>
            <div className="mt-3 flex flex-col gap-2">
              {authenticated ? (
                <Link href="/dashboard" className="rounded-full bg-ink-950 py-2.5 text-center text-sm font-semibold text-white">
                  Go to Dashboard
                </Link>
              ) : (
                <>
                  <Link href="/login" className="rounded-full border border-slate-200 py-2.5 text-center text-sm font-semibold text-slate-700">
                    Log in
                  </Link>
                  <Link href="/signup" className="rounded-full bg-ink-950 py-2.5 text-center text-sm font-semibold text-white">
                    Book a demo
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
