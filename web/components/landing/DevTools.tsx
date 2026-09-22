const CARDS = [
  {
    tag: "MCP",
    title: "Connect an available on server",
    body: "Built-in MCP server lets AI assistants query and act on your SalesBot workspace directly.",
  },
  {
    tag: "API",
    title: "Build custom automation with our API",
    body: "A full REST API to push leads, pull replies, and orchestrate sequences from your own systems.",
  },
  {
    tag: "CLI",
    title: "Automate from your terminal",
    body: "Script campaigns, imports, and reporting with a lightweight CLI built for developers.",
  },
];

export function DevTools() {
  return (
    <section className="bg-white py-20 sm:py-28">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="font-display text-3xl font-extrabold tracking-tight text-ink-950 sm:text-4xl">
            MCP, API &amp; CLI integrations
          </h2>
          <p className="mt-3 text-[15.5px] text-slate-600">
            Connect SalesBot to any workflow, application, or developer workflow.
          </p>
        </div>

        <div className="mt-14 grid gap-6 md:grid-cols-3">
          {CARDS.map((c) => (
            <div
              key={c.tag}
              className="group rounded-2xl border border-slate-200 bg-slate-50/60 p-7 transition-all hover:border-ink-950 hover:bg-ink-950"
            >
              <span className="inline-flex items-center rounded-full bg-ink-950 px-3 py-1 font-mono text-[11px] font-bold text-white group-hover:bg-white group-hover:text-ink-950">
                {c.tag}
              </span>
              <h3 className="mt-5 font-display text-lg font-bold tracking-tight text-ink-950 group-hover:text-white">
                {c.title}
              </h3>
              <p className="mt-2.5 text-[14px] leading-relaxed text-slate-600 group-hover:text-slate-300">
                {c.body}
              </p>
              <span className="mt-5 inline-flex items-center gap-1.5 text-[13.5px] font-bold text-brand-600 group-hover:text-brand-400">
                Learn more <span aria-hidden>&rarr;</span>
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
