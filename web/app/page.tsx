import { LandingHeader } from "@/components/landing/LandingHeader";
import { Hero } from "@/components/landing/Hero";
import { TrustedBy } from "@/components/landing/TrustedBy";
import { Testimonials } from "@/components/landing/Testimonials";
import { WhyUse } from "@/components/landing/WhyUse";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { WhatWeOffer } from "@/components/landing/WhatWeOffer";
import { Integrations } from "@/components/landing/Integrations";
import { DevTools } from "@/components/landing/DevTools";
import { Comparison } from "@/components/landing/Comparison";
import { Ratings } from "@/components/landing/Ratings";
import { Faq } from "@/components/landing/Faq";
import { Insights } from "@/components/landing/Insights";
import { Pricing } from "@/components/landing/Pricing";
import { FinalCta } from "@/components/landing/FinalCta";
import { LandingFooter } from "@/components/landing/LandingFooter";

export default function Home() {
  return (
    <div className="bg-white text-ink-950">
      <LandingHeader />
      <main>
        <Hero />
        <TrustedBy />
        <Testimonials />
        <WhyUse />
        <HowItWorks />
        <WhatWeOffer />
        <Integrations />
        <DevTools />
        <Comparison />
        <Ratings />
        <Pricing />
        <Faq />
        <Insights />
        <FinalCta />
      </main>
      <LandingFooter />
    </div>
  );
}
