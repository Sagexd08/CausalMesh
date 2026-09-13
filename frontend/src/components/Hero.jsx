import { Eyebrow, Section } from "./Primitives.jsx";
import { RESULTS } from "../data.js";

/**
 * Asymmetric by construction: a 7/5 split, headline hard-left, live evidence
 * panel offset right and pushed down. Centered hero layouts are banned above
 * variance 4, and this product's whole claim is that it produces evidence —
 * so the evidence is in the first viewport rather than described later.
 */
export default function Hero() {
  const verified = RESULTS.arms.reduce((n, a) => n + a.chains_verified, 0);

  return (
    <Section className="pt-28 pb-24 md:pt-36 md:pb-32">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-x-12 gap-y-16 items-start">
        <div className="lg:col-span-7">
          <Eyebrow>Coordination substrate · v0.1</Eyebrow>

          <h1 className="mt-7 text-[2.7rem] leading-[1.04] sm:text-6xl lg:text-[4.2rem] font-semibold tracking-tightest text-chalk-100">
            Four agents.
            <br />
            One codebase.
            <br />
            <span className="text-chalk-500">Provable</span>{" "}
            <span className="text-signal">order.</span>
          </h1>

          <p className="mt-8 max-w-prose text-[17px] leading-relaxed text-chalk-400">
            CausalMesh sits between a fleet of coding agents and the repository
            they share. Every action passes a gate, every action is signed into
            a hash chain, and conflicting writes are refused with the reason
            recorded.
          </p>

          <p className="mt-5 max-w-prose text-[17px] leading-relaxed text-chalk-500">
            It also answers a question nobody has answered cleanly:{" "}
            <span className="text-chalk-200">
              how much coordination benefit comes from information, and how much
              from enforcement?
            </span>
          </p>

          <div className="mt-11 flex flex-wrap items-center gap-3">
            <a
              href="#results"
              className="group inline-flex items-center gap-2 rounded-md bg-signal px-5 py-3 text-[14px] font-medium text-ink-950 transition-colors hover:bg-signal-dim"
            >
              See the measured results
              <span
                aria-hidden="true"
                className="transition-transform duration-200 group-hover:translate-x-0.5"
              >
                →
              </span>
            </a>
            <a
              href="https://github.com/Sagexd08/CausalMesh"
              className="inline-flex items-center rounded-md border border-white/10 px-5 py-3 text-[14px] text-chalk-300 transition-colors hover:border-white/20 hover:text-chalk-100"
            >
              Read the source
            </a>
          </div>
        </div>

        {/* Offset panel: real chain fragment, real hashes, real denial. */}
        <div className="lg:col-span-5 lg:mt-20">
          <figure className="rule overflow-hidden rounded-lg border bg-ink-900/70">
            <figcaption className="flex items-center justify-between border-b border-white/[0.07] px-4 py-2.5">
              <span className="font-mono text-[11px] text-chalk-600">
                run_C3 · concurrent_edit_collision
              </span>
              <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-signal">
                <span
                  className="h-1.5 w-1.5 rounded-full bg-signal"
                  aria-hidden="true"
                />
                verified
              </span>
            </figcaption>

            <div className="divide-y divide-white/[0.05] font-mono text-[12.5px] leading-relaxed">
              {[
                ["0", "READ", "agent_a", "src/config.py", null],
                ["1", "READ", "agent_b", "src/config.py", null],
                ["2", "WRITE", "agent_a", "src/config.py", "ok"],
                ["3", "FAILURE", "agent_b", "src/config.py", "denied"],
              ].map(([seq, type, actor, path, state]) => (
                <div
                  key={seq}
                  className="grid grid-cols-[1.6rem_4.6rem_1fr] items-baseline gap-x-3 px-4 py-2"
                >
                  <span className="text-chalk-600 tabular-nums">{seq}</span>
                  <span
                    className={
                      state === "denied" ? "text-arm-c0" : "text-chalk-400"
                    }
                  >
                    {type}
                  </span>
                  <span className="truncate">
                    <span className="text-chalk-300">{actor}</span>
                    <span className="text-chalk-600"> · {path}</span>
                  </span>
                </div>
              ))}
            </div>

            <div className="border-t border-white/[0.07] bg-ink-850/60 px-4 py-3">
              <div className="font-mono text-[11px] text-chalk-600">
                agent_b blocked — src/config.py held by agent_a
              </div>
              <div className="mt-1.5 font-mono text-[11px] text-chalk-600">
                head <span className="text-chalk-400">3064aaefc488…</span>
              </div>
            </div>
          </figure>

          <p className="mt-4 font-mono text-[11px] leading-relaxed text-chalk-600">
            {verified} of {RESULTS.total_runs} chains verified offline, rebuilt
            from each run&apos;s derived seed.
          </p>
        </div>
      </div>
    </Section>
  );
}
