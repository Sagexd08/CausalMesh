import Agents from "./components/Agents.jsx";
import Architecture from "./components/Architecture.jsx";
import Console from "./components/Console.jsx";
import Contrasts from "./components/Contrasts.jsx";
import Cost from "./components/Cost.jsx";
import Hero from "./components/Hero.jsx";
import Integrity from "./components/Integrity.jsx";
import Nav from "./components/Nav.jsx";
import Problem from "./components/Problem.jsx";
import Routing from "./components/Routing.jsx";
import Footer from "./components/Footer.jsx";

function ConsoleBand() {
  return (
    <div className="border-y border-rule-soft bg-paper-sunk/50 py-16 md:py-20">
      <div className="mx-auto w-full max-w-[1180px] px-6 sm:px-10 lg:px-16">
        <Console />
      </div>
    </div>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-paper">
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
