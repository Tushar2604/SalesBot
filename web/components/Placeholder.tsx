/**
 * Stand-in for a route whose phase has not landed yet. It states what the page
 * will do, so the nav is honest rather than dead.
 */
export function Placeholder({
  title,
  phase,
  summary,
  bullets,
}: {
  title: string;
  phase: string;
  summary: string;
  bullets: string[];
}) {
  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 flex items-center gap-3">
        <h1 className="text-2xl font-semibold text-ink-950">{title}</h1>
        <span className="badge">{phase}</span>
      </div>
      <div className="card">
        <p className="mb-4 text-sm text-slate-700">{summary}</p>
        <ul className="space-y-2 text-sm text-slate-500">
          {bullets.map((item) => (
            <li key={item} className="flex gap-2">
              <span className="text-accent">&bull;</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
