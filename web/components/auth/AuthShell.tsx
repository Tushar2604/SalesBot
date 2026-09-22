import Link from "next/link";
import { BrandWordmark } from "@/components/app/icons";
import { AuthPreview } from "@/components/auth/AuthPreview";

export function AuthShell({
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
      <div className="flex w-full flex-col justify-center px-6 py-12 sm:px-12 lg:w-[55%] lg:px-16 xl:px-24">
        <div className="mx-auto w-full max-w-[420px]">
          <Link href="/" className="mb-10 inline-flex">
            <BrandWordmark markClassName="h-9 w-9 text-ink-950" markTone="inherit" />
          </Link>

          <h1 className="text-[28px] font-semibold tracking-tight text-ink-950">{title}</h1>
          <p className="mt-2 text-[14px] text-slate-500">
            {switchPrompt}{" "}
            <Link href={switchHref} className="font-medium text-accent hover:text-accent-hover">
              {switchLabel}
            </Link>
          </p>

          <div className="mt-8">{children}</div>
        </div>
      </div>

      <div className="relative hidden overflow-hidden bg-gradient-to-b from-[#7b3cff] via-[#5b4dff] to-[#4aa3ff] lg:flex lg:w-[45%] lg:flex-col lg:justify-between lg:p-12 xl:p-14">
        <div className="relative z-10 max-w-md">
          <div className="mb-5 flex gap-1 text-white">
            {Array.from({ length: 5 }).map((_, i) => (
              <svg key={i} viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
                <path d="M10 1.5l2.6 5.6 6.1.6-4.6 4.1 1.3 6-5.4-3.1-5.4 3.1 1.3-6-4.6-4.1 6.1-.6z" />
              </svg>
            ))}
          </div>
          <h2 className="text-[32px] font-semibold leading-[1.15] tracking-tight text-white xl:text-[36px]">
            Automate Your LinkedIn and Email Outreach
          </h2>
          <p className="mt-5 max-w-sm text-[15px] leading-relaxed text-white/85">
            Try our proven two-in-one LinkedIn and Email automation software and get quality leads every day like our
            3,200+ users do
          </p>
        </div>

        <div className="relative z-10 mt-10 translate-y-8">
          <AuthPreview />
        </div>
      </div>
    </div>
  );
}
