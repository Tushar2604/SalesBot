"use client";

import { Manrope } from "next/font/google";
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
import { FinalCta } from "@/components/landing/FinalCta";
import { LandingFooter } from "@/components/landing/LandingFooter";

const display = Manrope({ subsets: ["latin"], variable: "--font-display", weight: ["500", "700", "800"] });

export default function Home() {
  return (
    <div className={`${display.variable} bg-white font-sans text-slate-900`}>
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
        <Faq />
        <Insights />
        <FinalCta />
      </main>
      <LandingFooter />
    </div>
  );
}
