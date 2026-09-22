"use client";

import { BrandWordmark } from "@/components/app/icons";

const COLUMNS = [
  {
    title: "Product",
    links: [
      { label: "Features", href: "#offer" },
      { label: "Pricing", href: "#pricing" },
      { label: "Whitelabel", href: "#offer" },
      { label: "Affiliate Program", href: "#cta" },
      { label: "Community", href: "#cta" },
    ],
  },
  {
    title: "Resources",
    links: [
      { label: "Blogs", href: "#insights" },
      { label: "Playbooks", href: "#insights" },
      { label: "FAQ", href: "#faq" },
    ],
  },
  {
    title: "Compare",
    links: [
      { label: "SalesBot vs HeyReach", href: "#ratings" },
      { label: "SalesBot vs Lemlist", href: "#ratings" },
      { label: "SalesBot vs Expandi", href: "#ratings" },
      { label: "SalesBot vs Dripify", href: "#ratings" },
      { label: "SalesBot vs Waalaxy", href: "#ratings" },
    ],
  },
  {
    title: "Company",
    links: [
      { label: "About", href: "#why" },
      { label: "Contact Us", href: "#cta" },
      { label: "Privacy policy", href: "#faq" },
      { label: "Terms of use", href: "#faq" },
      { label: "Cancellation & Refund", href: "#faq" },
    ],
  },
];

export function LandingFooter() {
  return (
    <footer className="border-t border-slate-200 bg-white pt-14 text-slate-600">
      <div className="landing-wrap">
        <div className="flex flex-col items-start justify-between gap-6 rounded-[24px] bg-[#f7f9fc] p-6 sm:flex-row sm:items-center sm:p-8">
          <div>
            <h3 className="text-[18px] font-semibold text-ink-950">Stay in the loop</h3>
            <p className="mt-1 text-[14px]">LinkedIn &amp; email outreach tips, twice a month.</p>
          </div>
          <form className="flex w-full max-w-md gap-2" onSubmit={(e) => e.preventDefault()}>
            <input type="email" required placeholder="Enter your email" className="input" />
            <button type="submit" className="btn-navy shrink-0 px-5">
              Subscribe
            </button>
          </form>
        </div>

        <div className="mt-14 grid grid-cols-2 gap-10 pb-10 sm:grid-cols-4">
          {COLUMNS.map((col) => (
            <div key={col.title}>
              <h4 className="text-[13px] font-semibold text-ink-950">{col.title}</h4>
              <ul className="mt-4 flex flex-col gap-2.5">
                {col.links.map((l) => (
                  <li key={l.label}>
                    <a href={l.href} className="text-[13.5px] text-slate-500 hover:text-ink-950">
                      {l.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="flex flex-col items-start justify-between gap-4 border-t border-slate-200 py-8 sm:flex-row sm:items-center">
          <BrandWordmark markClassName="h-7 w-7" />
          <p className="max-w-xl text-[11.5px] leading-relaxed text-slate-400">
            SalesBot is not endorsed by, affiliated or an official product of the LinkedIn Corporation, registered in the
            U.S. and other countries. All LinkedIn™ logos and trademarks used and displayed are the property of LinkedIn.
          </p>
        </div>
      </div>
    </footer>
  );
}
