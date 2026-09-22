const TOOLS = [
  "HubSpot", "Salesforce", "Pipedrive", "Zapier", "Slack", "Google Sheets",
  "Calendly", "Notion", "Close", "Make", "Webhooks", "Clay",
];

export function Integrations() {
  return (
    <section id="integrations" className="bg-slate-50/70 py-20 sm:py-28">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <div className="grid items-center gap-12 lg:grid-cols-2 lg:gap-20">
          <div>
            <p className="text-[13px] font-bold uppercase tracking-wider text-brand-600">Integrations</p>
            <h2 className="mt-3 font-display text-3xl font-extrabold tracking-tight text-ink-950 sm:text-4xl">
              Integrate with the tools you already use
            </h2>
            <p className="mt-4 max-w-md text-[15.5px] leading-relaxed text-slate-600">
              Sync leads, replies, and bookings automatically with your CRM and stack &mdash; no manual exports, ever.
            </p>
            <a
              href="#integrations"
              className="mt-7 inline-flex items-center gap-2 text-[14.5px] font-bold text-brand-600 hover:text-brand-700"
            >
              See all integrations
              <span aria-hidden>&rarr;</span>
            </a>
          </div>

          <div className="grid grid-cols-3 gap-4 sm:grid-cols-4">
            {TOOLS.map((tool, i) => (
              <div
                key={tool}
                className={`flex aspect-square flex-col items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white p-3 text-center shadow-sm transition-transform hover:-translate-y-1 hover:shadow-md ${
                  i % 5 === 0 ? "rotate-[-2deg]" : i % 3 === 0 ? "rotate-[2deg]" : ""
                }`}
              >
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 font-display text-sm font-extrabold text-brand-600">
                  {tool[0]}
                </span>
                <span className="text-[11px] font-semibold leading-tight text-slate-600">{tool}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
