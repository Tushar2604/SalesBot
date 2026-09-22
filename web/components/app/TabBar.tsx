"use client";

import clsx from "clsx";

export type TabDef = { key: string; label: string };

/**
 * Horizontally-scrollable pill tab row, used by Settings, Admin Settings,
 * Campaigns and Agency View.
 */
export function TabBar({
  tabs,
  active,
  onChange,
  className,
}: {
  tabs: TabDef[];
  active: string;
  onChange: (key: string) => void;
  className?: string;
}) {
  return (
    <div className={clsx("overflow-x-auto", className)}>
      <div className="inline-flex w-max gap-1 rounded-full bg-[#f3f4f6] p-1">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => onChange(tab.key)}
            className={clsx(
              "whitespace-nowrap rounded-full px-4 py-2 text-[13.5px] font-medium transition-colors",
              active === tab.key
                ? "bg-white text-ink-950 shadow-sm"
                : "text-slate-500 hover:text-ink-950",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>
    </div>
  );
}
