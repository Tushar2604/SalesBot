import Link from "next/link";

export function FinalCta() {
  return (
    <section id="cta" className="relative overflow-hidden bg-gradient-to-b from-white to-[#e8f3ff] py-16 sm:py-24">
      <div className="landing-wrap max-w-3xl text-center">
        <h2 className="text-[28px] font-semibold leading-tight tracking-tight text-ink-950 sm:text-[36px]">
          What are you waiting for? Start reaching out to your dream customers today
        </h2>
        <Link href="/signup" className="btn-navy mt-8 h-12 px-7 text-[18px] font-medium">
          Free Trial (14 days)
          <span aria-hidden>→</span>
        </Link>
      </div>
    </section>
  );
}
