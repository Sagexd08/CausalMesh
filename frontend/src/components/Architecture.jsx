import { Eyebrow, Reveal, Section } from "./Primitives.jsx";

const LAYERS = [
  {
    n: "01",
    name: "Tool boundary",
    line: "11 controlled operations. No shell.",
    detail:
      "run_command takes an argument list, never a shell string. A shell would let an agent reach any path its OS token permits through && or a subshell, voiding every containment claim below it.",
  },
  {
    n: "02",
    name: "Claim registry",
    line: "Exclusive write leases, transactional.",
    detail:
      "SQLite with BEGIN IMMEDIATE. At most one valid writer per path at any instant. Leases expire, so a crashed agent cannot wedge the fleet, and every refusal records who was blocked, by whom, and why.",
  },
  {
    n: "03",
    name: "Coordination channels",
    line: "One typed injection point, fully accounted.",
    detail:
      "Null, transcript, or bounded metadata. Events available, selected, injected and dropped are counted separately, with a reason stored for every selection decision. Nothing is silently truncated.",
  },
  {
    n: "04",
    name: "Signed chain",
    line: "Ed25519 per actor, hash-linked, offline-verifiable.",
    detail:
      "h_i = SHA256(h_{i-1} || canonical(event_i)). The verifier imports nothing from the relay — enforced by a test — so a chain verifies on another machine, months later, with the system shut down.",
  },
];

export default function Architecture() {
  return (
    <Section id="architecture" className="py-24 md:py-32">
      <div className="max-w-[52rem]">
        <Eyebrow tone="muted">How it works</Eyebrow>
        <h2 className="mt-6 text-3xl md:text-[2.6rem] leading-[1.1] font-semibold tracking-tightest text-chalk-100">
          Four layers between the fleet
          <br />
          and the repository.
        </h2>
      </div>

      <div className="mt-16 grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-white/[0.07] bg-white/[0.06] md:grid-cols-2">
        {LAYERS.map((layer, i) => (
          <Reveal key={layer.n} delay={i * 70}>
            <article className="h-full bg-ink-900/80 p-7 transition-colors duration-300 hover:bg-ink-850/80 md:p-9">
              <div className="flex items-baseline gap-3">
                <span className="font-mono text-[11px] tabular-nums text-signal-dim">
                  {layer.n}
                </span>
                <h3 className="text-[17px] font-medium text-chalk-100">
                  {layer.name}
                </h3>
              </div>
              <p className="mt-3 text-[15px] text-chalk-300">{layer.line}</p>
              <p className="mt-3 max-w-prose text-[14px] leading-relaxed text-chalk-500">
                {layer.detail}
              </p>
            </article>
          </Reveal>
        ))}
      </div>

      <div className="mt-10 grid grid-cols-1 gap-8 lg:grid-cols-12">
        <div className="lg:col-span-7">
          <p className="max-w-prose text-[15px] leading-relaxed text-chalk-500">
            The arms are <span className="text-chalk-200">installed objects</span>
            , not configuration branches. C0 gets a channel that raises if
            anything is offered; C3 gets a gate that consults the registry.
            Nothing reads an arm name and decides what to do, which is what
            makes each condition a structural property of the assembled runtime
            rather than a flag somebody could get wrong.
          </p>
        </div>
        <div className="lg:col-span-5">
          <div className="rule rounded-md border bg-ink-900/60 p-5">
            <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-chalk-600">
              Honest limit
            </div>
            <p className="mt-3 text-[14px] leading-relaxed text-chalk-500">
              On Windows there is no{" "}
              <span className="font-mono text-[13px] text-chalk-300">
                chroot
              </span>{" "}
              and no mount namespaces, so process isolation is process
              separation — not a filesystem jail. The docs say so rather than
              claiming a boundary that does not exist.
            </p>
          </div>
        </div>
      </div>
    </Section>
  );
}
