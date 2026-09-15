import Footer from '@/components/landing/Footer.jsx';
import Nav from '@/components/landing/Nav.jsx';
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
    <div className="landing-root min-h-screen bg-paper">
      <Nav />
      <main id="main">
        <Paper />
      </main>
      <Footer />
    </div>
  );
}
