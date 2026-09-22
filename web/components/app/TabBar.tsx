"use client";

import clsx from "clsx";

export type TabDef = { key: string; label: string };

/**
 * Horizontally-scrollable pill tab row, used by Settings, Admin Settings,
 * Campaigns and Agency View. A plain `<button>` row rather than a `<Tabs>`
 * abstraction — every screen's tab list is static and short, so there is
 * nothing generic to gain from a heavier component.
 */
export function TabBar({
  tabs,
  active,
  onChange,
}: {
  tabs: TabDef[];
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="mb-6 overflow-x-auto rounded-xl border border-slate-200 bg-slate-100/70 p-1">
      <div className="flex w-max gap-1">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => onChange(tab.key)}
            className={clsx(
              "whitespace-nowrap rounded-lg px-4 py-2 text-[13.5px] font-semibold transition-colors",
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
