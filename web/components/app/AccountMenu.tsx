"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSession } from "@/lib/session";

export function AccountMenu() {
  const { me, signOut } = useSession();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickOutside(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  const initial = (me?.user.full_name || me?.user.email || "U")[0]?.toUpperCase();

  return (
    <div ref={rootRef} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Account menu"
        className="flex h-8 w-8 items-center justify-center rounded-full bg-ink-950 text-[11px] font-bold text-white"
      >
        {initial}
      </button>

      {open && (
        <div className="absolute right-0 top-11 z-30 w-64 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
          <div className="border-b border-slate-100 px-4 py-3">
            <p className="truncate text-[13.5px] font-bold text-ink-950">
              {me?.user.full_name || "Account"}
            </p>
            <p className="truncate text-[12px] text-slate-500">{me?.user.email}</p>
          </div>
          <div className="flex flex-col py-1.5">
            <Link
              href="/settings"
              onClick={() => setOpen(false)}
              className="px-4 py-2 text-left text-[13.5px] font-medium text-slate-700 hover:bg-slate-50"
            >
              Settings
            </Link>
            <Link
              href="/team"
              onClick={() => setOpen(false)}
              className="px-4 py-2 text-left text-[13.5px] font-medium text-slate-700 hover:bg-slate-50"
            >
              Team
            </Link>
          </div>
          <div className="border-t border-slate-100 py-1.5">
            <button
              onClick={() => void signOut()}
              className="w-full px-4 py-2 text-left text-[13.5px] font-semibold text-rose-600 hover:bg-rose-50"
            >
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
