const CARDS = [
  {
    tag: "MCP",
    title: "MCP",
    body: "Connect an available MCP server so AI assistants can query and act on your SalesBot workspace directly.",
    href: "#cta",
    cta: "Explore MCP",
  },
  {
    tag: "API",
    title: "API",
    body: "A full REST API to push leads, pull replies, and orchestrate sequences from your own systems.",
    href: "#cta",
    cta: "View API Docs",
  },
  {
    tag: "CLI",
    title: "CLI",
    body: "Script campaigns, imports, and reporting with a lightweight CLI built for developers.",
    href: "#cta",
    cta: "View CLI",
  },
];

export function DevTools() {
  return (
    <section className="bg-white py-16 sm:py-24">
      <div className="landing-wrap">
        <h2 className="landing-h2">MCP, API &amp; CLI integrations</h2>
        <div className="mt-12 grid gap-6 md:grid-cols-3">
          {CARDS.map((c) => (
            <a
              key={c.tag}
              href={c.href}
              className="group rounded-[24px] border border-slate-200 bg-[#f7f9fc] p-7 transition-all hover:border-ink-950 hover:bg-ink-950"
            >
              <span className="inline-flex items-center rounded-full bg-ink-950 px-3 py-1 font-mono text-[11px] font-semibold text-white group-hover:bg-white group-hover:text-ink-950">
                {c.tag}
              </span>
              <h3 className="mt-5 text-[20px] font-semibold tracking-tight text-ink-950 group-hover:text-white">{c.title}</h3>
              <p className="mt-2.5 text-[14px] leading-relaxed text-slate-600 group-hover:text-slate-300">{c.body}</p>
              <span className="mt-5 inline-flex items-center gap-1.5 text-[13.5px] font-semibold text-sky-600 group-hover:text-robot">
                {c.cta} <span aria-hidden>→</span>
              </span>
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}
