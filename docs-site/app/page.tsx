import Agents from '@/components/landing/Agents.jsx';
import Architecture from '@/components/landing/Architecture.jsx';
import Console from '@/components/landing/Console.jsx';
import Contrasts from '@/components/landing/Contrasts.jsx';
import Cost from '@/components/landing/Cost.jsx';
import Hero from '@/components/landing/Hero.jsx';
import Integrity from '@/components/landing/Integrity.jsx';
import Nav from '@/components/landing/Nav.jsx';
import Problem from '@/components/landing/Problem.jsx';
import Routing from '@/components/landing/Routing.jsx';
import Footer from '@/components/landing/Footer.jsx';

export const metadata = {
  title: 'CausalMesh — Information or enforcement?',
  description:
    'A coordination substrate for fleets of autonomous coding agents, with cryptographically verifiable evidence of everything every agent did.',
};

function ConsoleBand() {
  return (
    <div className="border-y border-rule-soft bg-paper-sunk/50 py-16 md:py-20">
      <div className="mx-auto w-full max-w-[1180px] px-6 sm:px-10 lg:px-16">
        <Console />
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <div className="landing-root min-h-screen bg-paper">
      <Nav />
      <main id="main">
        <Hero />
        <ConsoleBand />
        <Problem />
        <Routing />
        <Cost />
        <Contrasts />
        <Agents />
        <Architecture />
        <Integrity />
      </main>
      <Footer />
    </div>
  );
}
