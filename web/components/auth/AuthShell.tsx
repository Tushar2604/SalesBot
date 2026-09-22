import Link from "next/link";
import { RobotMark } from "@/components/app/icons";
import { AuthPreview } from "@/components/auth/AuthPreview";

export function AuthShell({
  eyebrow,
  title,
  switchPrompt,
  switchHref,
  switchLabel,
  children,
}: {
  eyebrow?: string;
  title: string;
  switchPrompt: string;
  switchHref: string;
  switchLabel: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-white">
      <div className="flex w-full flex-col justify-center px-6 py-12 sm:px-12 lg:w-1/2 lg:px-16 xl:px-24">
        <div className="mx-auto w-full max-w-md">
          <Link href="/" className="mb-10 flex items-center gap-2">
            <RobotMark className="h-9 w-9 text-ink-950" />
            <span className="font-display text-2xl font-extrabold tracking-tight text-ink-950">SalesBot</span>
          </Link>

          {eyebrow && <p className="mb-1 text-[13px] font-semibold text-brand-600">{eyebrow}</p>}
          <h1 className="font-display text-[1.8rem] font-extrabold tracking-tight text-ink-950">{title}</h1>
          <p className="mt-2 text-[14.5px] text-slate-500">
            {switchPrompt}{" "}
            <Link href={switchHref} className="font-semibold text-brand-600 hover:text-brand-700">
              {switchLabel}
            </Link>
          </p>

          <div className="mt-8">{children}</div>
        </div>
      </div>

      <div className="relative hidden overflow-hidden bg-gradient-to-br from-violet-600 via-brand-600 to-teal-400 lg:flex lg:w-1/2 lg:flex-col lg:justify-between lg:p-14 xl:p-16">
        <div aria-hidden className="pointer-events-none absolute inset-0 opacity-40 mix-blend-overlay">
          <div className="absolute -left-24 top-1/3 h-72 w-72 rounded-full bg-white blur-3xl" />
        </div>

        <div className="relative z-10">
          <div className="mb-6 flex gap-1 text-amber-300">
            {Array.from({ length: 5 }).map((_, i) => (
              <svg key={i} viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
                <path d="M10 1.5l2.6 5.6 6.1.6-4.6 4.1 1.3 6-5.4-3.1-5.4 3.1 1.3-6-4.6-4.1 6.1-.6z" />
              </svg>
            ))}
          </div>
          <h2 className="font-display text-4xl font-extrabold leading-[1.1] tracking-tight text-white xl:text-[2.75rem]">
            Automate Your LinkedIn and Email Outreach
          </h2>
          <p className="mt-6 max-w-md text-[16px] leading-relaxed text-white/85">
            Try our proven two-in-one LinkedIn and Email automation software and get quality
            leads every day like our 3,200+ users do.
          </p>
        </div>

        <div className="relative z-10 mt-12 translate-y-10">
          <AuthPreview />
        </div>
      </div>
    </div>
  );
}
