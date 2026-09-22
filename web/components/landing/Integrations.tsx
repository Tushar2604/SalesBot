const TOOLS = [
  "HubSpot", "Salesforce", "Pipedrive", "Zapier", "Slack", "Google Sheets",
  "Calendly", "Notion", "Close", "Make", "Webhooks", "Clay",
];

export function Integrations() {
  return (
    <section id="integrations" className="bg-[#f7f9fc] py-16 sm:py-24">
      <div className="landing-wrap grid items-center gap-12 lg:grid-cols-2 lg:gap-20">
        <div>
          <h2 className="text-[28px] font-semibold leading-tight tracking-tight text-ink-950 sm:text-[36px]">
            Integrate with the tools you already use
          </h2>
          <p className="mt-4 max-w-md text-[15px] leading-relaxed text-slate-600">
            Native integrations and modern webhooks let you easily connect SalesBot with all the software your team already uses
          </p>
          <a href="#integrations" className="mt-7 inline-flex items-center gap-2 text-[14.5px] font-semibold text-sky-600 hover:text-sky-700">
            See all integrations
            <span aria-hidden>→</span>
          </a>
        </div>

        <div className="grid grid-cols-3 gap-4 sm:grid-cols-4">
          {TOOLS.map((tool) => (
            <div
              key={tool}
              className="flex aspect-square flex-col items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white p-3 text-center shadow-sm"
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-50 text-[13px] font-semibold text-ink-950">
                {tool.slice(0, 2)}
              </span>
              <span className="text-[11px] font-medium leading-tight text-slate-600">{tool}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
