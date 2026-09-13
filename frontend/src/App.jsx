import Architecture from "./components/Architecture.jsx";
import { Footer, Nav } from "./components/Chrome.jsx";
import Contrasts from "./components/Contrasts.jsx";
import Hero from "./components/Hero.jsx";
import Integrity from "./components/Integrity.jsx";
import Problem from "./components/Problem.jsx";
import Results from "./components/Results.jsx";

export default function App() {
  return (
    <div className="grain relative min-h-screen">
      <Nav />
      <main id="main">
        <Hero />
        <Problem />
        <Contrasts />
        <Results />
        <Architecture />
        <Integrity />
      </main>
      <Footer />
    </div>
  );
}
