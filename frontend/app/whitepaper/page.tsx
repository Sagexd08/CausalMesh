import { SiteFooter } from '@/components/layout/SiteFooter';
import { SiteNav } from '@/components/layout/SiteNav';
import Paper from '@/components/landing/Paper.jsx';

export const metadata = {
  title: 'Whitepaper | CausalMesh',
  description:
    'Separating information from enforcement in fleets of coding agents: the experimental design, what the substrate guarantees, the governance gap it answers, and the measured results.',
  openGraph: {
    title: 'CausalMesh Whitepaper',
    description:
      'Four arms, two factors, and a signed chain that verifies offline. What coordination buys, measured.',
    type: 'article',
  },
};

export default function WhitepaperPage() {
  return (
    <div className="site-root min-h-screen">
      <div className="site-page-nav">
        <SiteNav base="/" />
      </div>
      <main id="main-content" className="paper-dark">
        <Paper />
      </main>
      <SiteFooter />
    </div>
  );
}
