"use client";

import { useState } from "react";
import { LABEL_META, LABEL_OPTIONS, type ConversationLabel } from "@/lib/inbox-api";
import { IconChevronDown } from "@/components/app/icons";

export function LabelPicker({
  value,
  onChange,
  disabled,
}: {
  value: ConversationLabel;
  onChange: (label: ConversationLabel) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const meta = LABEL_META[value];

  return (
    <div className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12.5px] font-semibold disabled:opacity-50 ${meta.className}`}
      >
        {meta.text}
        <IconChevronDown className="h-3.5 w-3.5" />
      </button>

      {open && (
        <>
          <button
            aria-label="Close"
            className="fixed inset-0 z-10 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 z-20 mt-1.5 w-44 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg">
            {LABEL_OPTIONS.map((label) => (
              <button
                key={label}
                onClick={() => {
                  onChange(label);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] font-medium text-slate-700 hover:bg-slate-50"
              >
                <span className={`h-2 w-2 rounded-full ${LABEL_META[label].dot}`} />
                {LABEL_META[label].text}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
