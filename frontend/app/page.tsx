import { SiteFooter } from '@/components/layout/SiteFooter';
import { Architecture } from '@/components/marketing/Architecture';
import {
  CtaSection,
  DeveloperSection,
  FaqSection,
  MeasuredSection,
  ResearchSection,
} from '@/components/marketing/ClosingSections';
import { Hero } from '@/components/marketing/Hero';
import {
  ClaimsSection,
  EntrySection,
  EvidenceSection,
  GateSection,
  ToolsSection,
} from '@/components/marketing/SystemSections';

export const metadata = {
  title: 'CausalMesh | The Next Layer of Intelligence',
  description:
    'The accountability layer underneath AI agents. Every action gated, signed, and recorded, with every refusal kept alongside its reason.',
};

/**
 * Pacing, top to bottom: emotion, then understanding, then proof. The hero
 * is one cinematic composition; the architecture explains it; 01 to 05 show
 * each part of the machine working on real artifacts; then code, measured
 * numbers, research, and one action.
 */
export default function Page() {
  return (
    <div className="site-root min-h-screen">
      <link rel="preload" as="image" href="/hero-poster.jpg" />
      <Hero />
      <main id="main-content">
        <Architecture />
        <GateSection />
        <ToolsSection />
        <ClaimsSection />
        <EntrySection />
        <EvidenceSection />
        <DeveloperSection />
        <MeasuredSection />
        <ResearchSection />
        <FaqSection />
        <CtaSection />
      </main>
      <SiteFooter />
    </div>
  );
}
