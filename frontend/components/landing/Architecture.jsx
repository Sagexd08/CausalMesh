import { Mark, Reveal, Section } from "./Primitives.jsx";
import { ChevronRight } from "./Icons.jsx";
import FlowDiagram from "./FlowDiagram.jsx";

/**
 * The four layers, as a specification list rather than a card grid.
 *
 * Equal-size icon-heading-text cards are the lazy container, and numbering
 * them 01-04 implies a sequence the reader needs when these are layers a
 * call passes through, not steps anyone follows. A stacked list with the
 * guarantee on the left and the mechanism on the right says the same thing
 * and reads in one pass.
 */

const LAYERS = [
  {
    name: "Tool boundary",
    claim: "Eleven operations. No shell.",
    detail:
      "run_command takes an argument list, never a shell string. A shell would let an agent reach any path its OS token permits through && or a subshell, voiding every containment claim below it.",
    proof: "leakage-tested",
  },
  {
    name: "Claim registry",
    claim: "One writer per path, transactionally.",
    detail:
      "SQLite with BEGIN IMMEDIATE, so check-and-acquire is atomic across processes. Leases expire, so a crashed agent cannot wedge the fleet, and every refusal records who was blocked, by whom, and why.",
    proof: "concurrency-tested across threads",
  },
  {
    name: "Coordination channels",
    claim: "One typed injection point, fully accounted.",
    detail:
      "Events available, selected, injected and dropped are counted separately, with a stored reason for every selection. Nothing is silently truncated, and under C0 the channel raises rather than quietly dropping.",
    proof: "bypass-tested",
  },
  {
    name: "Signed chain",
    claim: "Ed25519 per actor, verifiable offline.",
    detail:
      "Each event is canonicalized, signed, and hash-linked to its predecessor. The verifier imports nothing from the relay, enforced by a test, so a chain verifies on another machine months later with the system shut down.",
    proof: "8 attack classes detected",
  },
];

function LayerDiagram() {
  return (
    <div className="mt-14 border-y border-rule-soft bg-paper-sunk/40 px-5 py-8 sm:px-8 sm:py-10">
      <FlowDiagram />

      <div className="relative mt-7">
        <div
          aria-hidden="true"
          className="absolute left-0 right-0 top-1/2 hidden border-t border-dashed border-rule-soft lg:block"
        />
        <div className="relative grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {LAYERS.map((layer, i) => (
            <div
              key={layer.name}
              className="group relative border border-rule-soft bg-paper p-4 transition-colors duration-300 hover:border-ink-900"
            >
              <div className="flex items-start justify-between gap-3">
                <span className="flex h-8 w-8 items-center justify-center border border-ink-900 bg-ink-900 font-mono text-xs text-paper">
                  {i + 1}
                </span>
                <span className="mt-1 h-2 w-2 rounded-full bg-marker-deep shadow-[0_0_0_3px_rgba(215,239,90,0.3)]" />
              </div>
              <h3 className="mt-8 text-[15px] font-medium leading-snug text-ink-900">
                {layer.name}
              </h3>
              <p className="mt-2 text-[12.5px] leading-relaxed text-ink-600">
                {layer.claim}
              </p>
              <p className="mt-5 font-mono text-[10px] uppercase tracking-[0.12em] text-marker-deep">
                {layer.proof}
              </p>
              {i < LAYERS.length - 1 && (
                <span
                  aria-hidden="true"
                  className="absolute -right-3 top-1/2 z-10 hidden h-5 w-5 -translate-y-1/2 items-center justify-center border border-rule-soft bg-paper text-ink-500 lg:flex"
                >
                  <ChevronRight className="h-3 w-3" />
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="mt-8 flex items-center justify-center gap-3 text-center font-mono text-[10px] uppercase tracking-[0.16em] text-ink-500">
        <span className="h-px w-10 bg-rule-soft" />
        <span>structural, not a runtime flag</span>
        <span className="h-px w-10 bg-rule-soft" />
      </div>
    </div>
  );
}

export default function Architecture() {
  return (
    <Section id="architecture" className="py-24 md:py-32">
      <div className="max-w-[24ch]">
        <h2 className="font-display text-[2.3rem] font-bold leading-[1.08] tracking-tightest text-ink-900 sm:text-[3rem]">
          Four <Mark>layers</Mark> between the fleet and the repo
        </h2>
      </div>

      <LayerDiagram />

      <div className="mt-16">
        {LAYERS.map((layer, i) => (
          <Reveal key={layer.name} delay={i * 70}>
            <article className="grid grid-cols-1 gap-x-12 gap-y-3 border-t border-rule-soft py-8 transition-colors duration-300 hover:border-ink-900 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
              <div>
                <h3 className="text-[19px] font-medium text-ink-900">
                  {layer.name}
                </h3>
                <p className="mt-1.5 text-[15px] text-ink-700">{layer.claim}</p>
                <p className="mt-3 font-mono text-[11.5px] uppercase tracking-[0.12em] text-marker-deep">
                  {layer.proof}
                </p>
              </div>
              <p className="max-w-prose text-[14.5px] leading-relaxed text-ink-600">
                {layer.detail}
              </p>
            </article>
          </Reveal>
        ))}
        <div className="border-t border-rule-soft" />
      </div>

      <div className="mt-12 grid grid-cols-1 gap-10 lg:grid-cols-[1.3fr_1fr]">
        <p className="max-w-prose text-[15px] leading-relaxed text-ink-600">
          The arms are <span className="text-ink-900">installed objects</span>,
          not configuration branches. C0 gets a channel that raises if anything
          is offered; C3 gets a gate that consults the registry. Nothing reads
          an arm name and decides what to do, which makes each condition a
          structural property of the assembled runtime rather than a flag
          somebody could set wrong.
        </p>
        <div className="bg-paper-sunk p-6">
          <p className="text-[14px] font-medium text-ink-900">
            What this does not claim
          </p>
          <p className="mt-2 text-[13.5px] leading-relaxed text-ink-600">
            Windows has no <span className="font-mono text-[12.5px]">chroot</span>{" "}
            and no mount namespaces, so process isolation is process separation,
            not a filesystem jail. The docs say so rather than claiming a
            boundary that does not exist.
          </p>
        </div>
      </div>
    </Section>
  );
}
