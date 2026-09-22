import AgentBand from '@/components/landing/AgentBand.jsx';
import Agents from '@/components/landing/Agents.jsx';
import Calculator from '@/components/landing/Calculator.jsx';
import Architecture from '@/components/landing/Architecture.jsx';
import Console from '@/components/landing/Console.jsx';
import Contrasts from '@/components/landing/Contrasts.jsx';
import Cost from '@/components/landing/Cost.jsx';
import Hero from '@/components/landing/Hero.jsx';
import Integrity from '@/components/landing/Integrity.jsx';
import Nav from '@/components/landing/Nav.jsx';
import Problem from '@/components/landing/Problem.jsx';
import Routing from '@/components/landing/Routing.jsx';
import Framework from '@/components/landing/Framework.jsx';
import DecisionLoop from '@/components/landing/DecisionLoop.jsx';
import Footer from '@/components/landing/Footer.jsx';

export const metadata = {
  title: 'CausalMesh — Coordination you can prove',
  description:
    'The accountability substrate for AI agents. Gate every action, sign every action, record every refusal — for agents that write code, spend money, or run unattended.',
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
        <AgentBand />
        <ConsoleBand />
        <Problem />
        <Framework />
        <DecisionLoop />
        <Routing />
        <Cost />
        <Contrasts />
        <Calculator />
        <Agents />
        <Architecture />
        <Integrity />
      </main>
      <Footer />
    </div>
  );
}
