"use client";

/**
 * Integrations. Each card is a real destination in this app (webhooks land on
 * Admin Settings once that backend exists) except third-party ones (Hyperise)
 * which have no vendor account configured here — those show an explanatory
 * dialog instead of pretending to configure a live integration.
 */

import { useState } from "react";
import Link from "next/link";
import { IconBriefcase, IconClose, IconLink } from "@/components/app/icons";
import { RobotMark } from "@/components/app/icons";

const CARDS = [
  {
    key: "webhooks",
    title: "Webhooks",
    description: "Add webhook integrations like Zapier to export data in real time.",
    icon: IconLink,
  },
  {
    key: "hyperise",
    title: "Hyperise",
    description: "Use custom gifs/images along with your messages to gain more traction.",
    icon: IconBriefcase,
  },
  {
    key: "salesrobo",
    title: "SalesRobo",
    description: "Configure your CRM to control SalesRobo. Like pausing/continuing sequence.",
    icon: RobotMark,
  },
  {
    key: "direct",
    title: "Integrate directly",
    description: "Directly integrate using your API key from Admin Settings.",
    icon: IconLink,
  },
];

export default function IntegrationsPage() {
  const [open, setOpen] = useState<string | null>(null);
  const card = CARDS.find((c) => c.key === open) ?? null;

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-6 text-2xl font-semibold text-ink-950">Integrations</h1>

      <div className="grid gap-4 sm:grid-cols-2">
        {CARDS.map((c) => (
          <div key={c.key} className="card">
            <span className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-brand-50 text-brand-500">
              <c.icon className="h-5 w-5" />
            </span>
            <h2 className="mb-1 font-medium text-ink-950">{c.title}</h2>
            <p className="mb-4 text-sm text-slate-500">{c.description}</p>
            <button className="text-[13px] font-semibold text-brand-600 hover:underline" onClick={() => setOpen(c.key)}>
              Configure →
            </button>
          </div>
        ))}
      </div>

      {card && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6">
            <div className="mb-4 flex items-start justify-between">
              <h2 className="font-medium text-ink-950">{card.title}</h2>
              <button onClick={() => setOpen(null)} aria-label="Close" className="text-slate-400 hover:text-ink-950">
                <IconClose className="h-4 w-4" />
              </button>
            </div>
            {card.key === "webhooks" || card.key === "direct" ? (
              <>
                <p className="mb-4 text-sm text-slate-500">
                  Generate an API key from Admin Settings to authenticate outbound requests.
                </p>
                <Link href="/admin/settings" className="btn-primary inline-flex" onClick={() => setOpen(null)}>
                  Go to API Key
                </Link>
              </>
            ) : card.key === "salesrobo" ? (
              <p className="text-sm text-slate-500">
                A campaign can already be paused or resumed from its detail page, and the whole
                workspace can be paused from Team → Outreach kill switch. A CRM-triggered webhook
                for this needs the outbound webhook backend above.
              </p>
            ) : (
              <p className="text-sm text-slate-500">
                This integration needs a {card.title} vendor account, which isn&apos;t connected in
                this environment.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
