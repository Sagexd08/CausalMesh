"use client";

import { useEffect, useRef, useState } from "react";
import { ChainIcon, FleetIcon, GateIcon, SignIcon } from "./MotionIcons.jsx";
import { RESULTS, armResult } from "@/lib/landing/data.js";

/**
 * The whitepaper, as a designed reading surface rather than a PDF link.
 *
 * Mode is Read: the visitor is here to understand something, so structure
 * serves comprehension first and expression second. Concretely that means a
 * measure held near 68ch, a contents rail that tracks position, real section
 * numbering (a paper's numbered sections are how its own cross-references
 * work, which is the one case where numbered headings carry information),
 * and figures that are drawn rather than described.
 *
 * **Every claim is one of three kinds, and the page marks which.** Measured
 * facts come from the pilot artifacts and carry their run count. Cited facts
 * name their source and link it. Designed-but-unbuilt work is labelled
 * planned. A paper that blurs those three is marketing with footnotes, and
 * the tag is the cheapest way to keep them apart while reading.
 *
 * **Motion is near zero on purpose.** A document that animates while you are
 * trying to read it is fighting its own job. The only movement is the
 * reading-progress rule and the contents marker, both of which report
 * position rather than decorate it.
 */

/**
 * The references, in citation order.
 *
 * One array drives both the superscript markers in the text and the list at
 * the end, so a marker and its entry cannot disagree about a number. Adding
 * a source in the middle renumbers both at once, which is the failure a
 * hand-numbered bibliography always eventually has.
 */
const REFERENCES = [
  {
    id: "governance-gaps",
    title:
      "Governance Gaps in Agent Interoperability Protocols: What MCP, A2A, and ACP Cannot Express",
    href: "https://arxiv.org/pdf/2606.31498",
    venue: "arXiv 2606.31498",
  },
  {
    id: "agenticflict",
    title:
      "When Agents Collide: What 33,596 Pull Requests Reveal About Merge Conflicts",
    href: "https://codex.danielvaughan.com/2026/07/28/agent-pr-merge-conflicts-concurrent-coding-agents-codex-cli-worktree-isolation-coordination-defence/",
    venue: "AIware 2026",
  },
  {
    id: "otel-genai",
    title: "Inside the LLM Call: GenAI Observability with OpenTelemetry",
    href: "https://opentelemetry.io/blog/2026/genai-observability/",
    venue: "OpenTelemetry",
  },
  {
    id: "nist-caisi",
    title: "Announcing the AI Agent Standards Initiative",
    href: "https://www.nist.gov/news-events/news/2026/02/announcing-ai-agent-standards-initiative-interoperable-and-secure",
    venue: "NIST CAISI, February 2026",
  },
  {
    id: "imda",
    title: "Model AI Governance Framework for Agentic AI",
    href: "https://www.imda.gov.sg/",
    venue: "IMDA Singapore, January 2026",
  },
  {
    id: "trust-without-trusting",
    title:
      "Trust Without Trusting: A Recomputable Trust Protocol for Autonomous Agents",
    href: "https://arxiv.org/pdf/2605.06738",
    venue: "arXiv 2605.06738",
  },
  {
    id: "agent-practices",
    title:
      "An Empirical Study of Agent Developer Practices in AI Agent Frameworks",
    href: "https://arxiv.org/pdf/2512.01939",
    venue: "arXiv 2512.01939",
  },
  {
    id: "agents-md",
    title: "AGENTS.md Specification",
    href: "https://asdlc.io/practices/agents-md-spec/",
    venue: "Agentic AI Foundation",
  },
];

const REF_INDEX = Object.fromEntries(
  REFERENCES.map((reference, position) => [reference.id, position + 1])
);

const SECTIONS = [
  ["abstract", "Abstract", null],
  ["terminology", "Terminology", null],
  ["question", "The question", "1"],
  ["design", "Experimental design", "2"],
  ["guarantees", "What the substrate guarantees", "3"],
  ["governance", "The governance gap", "4"],
  ["results", "Measured results", "5"],
  ["framework", "From experiment to framework", "6"],
  ["limitations", "Limitations", "7"],
  ["references", "References", null],
];

/**
 * Terms this paper uses with a specific, load-bearing meaning.
 *
 * Ordered by first appearance in the argument, not alphabetically, so a
 * reader working through the contents rail top to bottom meets each term
 * just before or as it starts doing work. Every definition is restated from
 * where the term is actually implemented, not paraphrased from memory --
 * the same discipline REFERENCES already applies to citations.
 */
const TERMS = [
  {
    term: "arm",
    def: "One of four fixed configurations of information and enforcement (C0-C3) that a task is run under. Arms differ by exactly one factor from their neighbour, which is what makes a difference between two arms attributable to that factor rather than to how the two happened to be built.",
  },
  {
    term: "coordination byte",
    def: "One byte of peer information delivered to an agent through the coordination channel, and counted there. A byte that reaches an agent by any other route is not a coordination byte, however much it looks like one -- see the channel-bypass finding in section 3.",
  },
  {
    term: "claim",
    def: "An exclusive lease on one resource, held by one agent for a bounded duration. Enforced with a `BEGIN IMMEDIATE` SQLite transaction rather than an in-process lock, because agents run as separate OS processes and the lease must hold across that boundary.",
  },
  {
    term: "verdict",
    def: "What the gate decided about one action -- allowed or refused -- and the reason. Data returned from a call, never an exception raised from one: a refusal is the primary measurement, and a measurement that can only be observed by catching an exception is a measurement that is easy to lose.",
  },
  {
    term: "resource",
    def: "The one thing a verdict can be about: a kind (path, spend, endpoint or budget) plus a normalized identity. A refused write and a refused payment are the same event under this definition, which is why one gate covers both.",
  },
  {
    term: "contract",
    def: "The declared, versioned statement of who owns what, who may spend how much, and where -- read from causalmesh.yaml. Never inferred from what agents did: a rule derived from behaviour cannot refuse that behaviour.",
  },
];

/** Tracks which section is in view, so the contents rail stays honest. */
function useActiveSection() {
  const [active, setActive] = useState(SECTIONS[0][0]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        // The topmost intersecting heading wins, so scrolling up and down
        // resolves to the same section at the same scroll position.
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-88px 0px -62% 0px", threshold: 0 }
    );
    for (const [id] of SECTIONS) {
      const node = document.getElementById(id);
      if (node) observer.observe(node);
    }
    return () => observer.disconnect();
  }, []);

  return active;
}

/**
 * How far through the document the reader is.
 *
 * A long technical page gives no sense of its own length, and "how much of
 * this is left" is a real question a reader asks before committing. Driven
 * by a scroll listener behind rAF rather than by React state per frame:
 * the value is written straight to a CSS custom property, so no component
 * re-renders while scrolling.
 */
function useReadingProgress(ref) {
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    let frame = 0;

    const measure = () => {
      frame = 0;
      const { top, height } = node.getBoundingClientRect();
      const scrolled = -top;
      const total = height - window.innerHeight;
      const ratio = total <= 0 ? 1 : Math.min(1, Math.max(0, scrolled / total));
      node.style.setProperty("--cm-read", String(ratio));
    };

    const onScroll = () => {
      // Coalesced to one write per frame; the handler itself never touches
      // React state, so scrolling costs no renders.
      if (!frame) frame = requestAnimationFrame(measure);
    };

    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [ref]);
}

/**
 * A numbered citation marker that links to its entry.
 *
 * Replaces the `cited` pill an earlier version repeated mid-sentence. Four
 * of those in one paragraph stopped marking anything: a label that appears
 * on every other line is texture, not signal. A superscript number is the
 * convention a reader of papers already knows, it costs a character rather
 * than a word, and it goes somewhere.
 */
function Cite({ id }) {
  const number = REF_INDEX[id];
  if (!number) return null;
  return (
    <a href={`#ref-${id}`} className="cm-cite" aria-label={`Reference ${number}`}>
      [{number}]
    </a>
  );
}

function Tag({ kind }) {
  const style = {
    measured: "border-marker-deep/40 bg-marker/15 text-marker-deep",
    cited: "border-rule-soft bg-paper-sunk text-ink-600",
    planned: "border-rule-soft bg-paper-sunk text-ink-500",
  }[kind];
  const label = { measured: "measured", cited: "cited", planned: "planned" }[kind];
  return (
    <span
      className={`ml-2 inline-block shrink-0 rounded-full border px-2 py-0.5 align-middle font-mono text-[10px] ${style}`}
    >
      {label}
    </span>
  );
}

function H({ id, number, children, tag }) {
  return (
    <h2
      id={id}
      className="scroll-mt-24 font-display text-[clamp(1.7rem,1.564rem+0.545vw,2rem)] font-bold leading-tight tracking-tightest text-ink-900"
    >
      {number && (
        <span className="cm-nums mr-3 font-mono text-[1.1rem] font-normal text-ink-400">
          {number}
        </span>
      )}
      {children}
      {tag && <Tag kind={tag} />}
    </h2>
  );
}

function P({ children }) {
  return <p className="mt-4 text-[15.5px] leading-[1.75] text-ink-700">{children}</p>;
}

/** A sentence the reader should leave with, set apart from the argument. */
function Pull({ children }) {
  return (
    <p className="my-8 border-t border-b border-rule-soft py-5 font-display text-[1.15rem] font-medium leading-[1.5] tracking-tightest text-ink-900">
      {children}
    </p>
  );
}

export default function Paper() {
  const active = useActiveSection();
  const rootRef = useRef(null);
  useReadingProgress(rootRef);

  const c1 = armResult("C1");
  const c2 = armResult("C2");
  const c3 = armResult("C3");
  const saving = Math.round(
    ((c1.mean_coordination_bytes - c2.mean_coordination_bytes) /
      c1.mean_coordination_bytes) *
      100
  );

  return (
    <div ref={rootRef} className="cm-paper relative">
      {/* Reading progress. A hairline under the sticky nav, reporting
          position rather than decorating it. */}
      <div aria-hidden="true" className="cm-progress" />

      <div className="mx-auto w-full max-w-[1180px] px-6 py-14 sm:px-10 lg:px-16 lg:py-20">
        {/* -- masthead ---------------------------------------------------
            Full width above the two columns, so the title gets the measure
            it deserves before the reading column narrows. */}
        <header className="border-b border-rule pb-10">
          <div className="font-mono text-[11px] uppercase tracking-wider text-ink-500">
            Whitepaper · v0.1 · September 2026
          </div>
          <h1 className="mt-5 max-w-[20ch] font-display text-[clamp(2.6rem,1.964rem+2.545vw,4rem)] font-extrabold leading-[1.02] tracking-tightest text-ink-900">
            Separating information from enforcement
          </h1>
          <p className="mt-6 max-w-[58ch] text-[17px] leading-relaxed text-ink-600">
            Four arms, two factors, and a signed chain that verifies with the
            relay stopped. What coordination between coding agents actually
            buys, measured rather than asserted.
          </p>

          <dl className="mt-9 grid grid-cols-2 gap-x-8 gap-y-5 sm:grid-cols-4">
            {[
              [RESULTS.total_runs, "runs", "2 tasks, 4 arms, 3 repetitions"],
              ["4", "arms", "two factors, one at a time"],
              [`${RESULTS.total_runs}/${RESULTS.total_runs}`, "chains verified", "offline, relay stopped"],
              ["1,425", "tests", "collected 2026-09-30"],
            ].map(([value, label, note]) => (
              <div key={label}>
                <dt className="sr-only">{label}</dt>
                <dd>
                  <span className="cm-nums font-display text-[1.75rem] font-semibold leading-none tracking-tightest text-ink-900">
                    {value}
                  </span>
                  <span className="ml-1.5 text-[13px] text-ink-600">{label}</span>
                  <span className="mt-1 block text-[12px] leading-snug text-ink-500">
                    {note}
                  </span>
                </dd>
              </div>
            ))}
          </dl>
        </header>

        <div className="mt-12 grid grid-cols-1 gap-x-14 lg:grid-cols-[190px_1fr]">
          {/* Contents. Sticky on desktop, a plain list on mobile, because a
              sticky rail on a phone eats the screen the text needs. */}
          <nav aria-label="Contents" className="mb-12 lg:mb-0">
            <div className="lg:sticky lg:top-24">
              <ul className="space-y-0 border-l border-rule-soft">
                {SECTIONS.map(([id, label, number]) => (
                  <li key={id}>
                    <a
                      href={`#${id}`}
                      aria-current={active === id ? "true" : undefined}
                      className={`-ml-px flex gap-2 border-l py-1.5 pl-3 text-[13px] leading-snug transition-colors ${
                        active === id
                          ? "border-ink-900 font-medium text-ink-900"
                          : "border-transparent text-ink-500 hover:text-ink-800"
                      }`}
                    >
                      <span className="cm-nums w-3 shrink-0 font-mono text-[11px] text-ink-400">
                        {number || ""}
                      </span>
                      {label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </nav>

          <article className="max-w-[68ch]">
            {/* -- Abstract ---------------------------------------------- */}
            <section>
              <H id="abstract">Abstract</H>
              <P>
                When several language-model coding agents work on one
                repository they interfere: they read stale state, duplicate
                each other&rsquo;s work, and overwrite each other&rsquo;s
                changes. Systems that address this do two things at once. They{" "}
                <em>tell</em> agents what their peers are doing, and they{" "}
                <em>prevent</em> agents from conflicting. Because the two
                arrive together, their individual contributions are unknown.
              </P>
              <P>
                CausalMesh separates them experimentally. Four arms manipulate
                exactly two factors, information and enforcement, holding
                everything else constant. The contribution is measurement, not
                the invention of a new coordination mechanism.
              </P>
              <P>
                A second contribution follows from how the measurement is
                built. Because every agent action is signed into a hash-linked
                chain that verifies offline, the substrate produces an audit
                trail that standards bodies have begun to require and that no
                current interoperability protocol can express.
              </P>
            </section>

            {/* -- Terminology --------------------------------------------
                An unnumbered glossary, not part of the argument's own
                numbering: definitions support the argument, they are not a
                step in it. Ordered by first appearance rather than
                alphabetically so a reader moving top to bottom meets each
                term just before it starts doing work. */}
            <section className="mt-16">
              <H id="terminology">Terminology</H>
              <P>
                Six terms carry specific, load-bearing meaning throughout
                this paper. Each is restated from where it is actually
                implemented, not paraphrased from memory.
              </P>
              <dl className="mt-6 divide-y divide-rule-soft border-t border-rule-soft">
                {TERMS.map(({ term, def }) => (
                  <div key={term} className="grid grid-cols-1 gap-1.5 py-4 sm:grid-cols-[9rem_1fr] sm:gap-6">
                    <dt className="font-mono text-[13px] font-medium text-ink-900">
                      {term}
                    </dt>
                    <dd className="text-[14px] leading-relaxed text-ink-700">
                      {def}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>

            {/* -- 1 ------------------------------------------------------ */}
            <section className="mt-16">
              <H id="question" number="1">
                The question
              </H>
              <P>
                How much of the coordination benefit in distributed LLM coding
                agents comes from information, and how much from enforcement?
              </P>
              <P>
                The problem is not hypothetical. An analysis of 142,000+
                agent-authored pull requests across 59,000+ repositories found
                a <strong className="font-medium text-ink-900">27.67%</strong>{" "}
                conflict rate, with cross-agent pairs conflicting at roughly
                twice the rate of intra-agent pairs.
                <Cite id="agenticflict" />
              </P>
              <P>
                The obvious response is to give agents more context about each
                other. The obvious response is also untested: nobody has
                separated the value of telling an agent what its peers did from
                the value of stopping it when they collide. Those are different
                mechanisms with different costs, and a system that ships both
                cannot report which one earned its keep.
              </P>

              <figure className="mt-9 rounded-xl border border-rule-soft bg-paper-raised p-7">
                <div className="grid grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-4">
                  {[
                    [FleetFigure, "Agents share one repo"],
                    [GateFigure, "A write is refused"],
                    [ChainFigure, "The refusal is linked"],
                    [SignFigure, "And signed"],
                  ].map(([Figure, caption]) => (
                    <div
                      key={caption}
                      className="flex flex-col items-center gap-3 text-center"
                    >
                      <Figure />
                      <span className="text-[12px] leading-snug text-ink-600">
                        {caption}
                      </span>
                    </div>
                  ))}
                </div>
                <figcaption className="mt-6 border-t border-rule-soft pt-4 text-[12.5px] leading-relaxed text-ink-500">
                  Figure 1. The path of one refused action. Every stage is
                  recorded, so the refusal is evidence rather than an error.
                </figcaption>
              </figure>
            </section>

            {/* -- 2 ------------------------------------------------------ */}
            <section className="mt-16">
              <H id="design" number="2">
                Experimental design
              </H>
              <P>
                Four arms manipulate two factors. Each arm differs from its
                neighbour in exactly one way, which is what lets a difference
                in outcome be attributed to that one thing.
              </P>

              <div className="mt-7 overflow-x-auto">
                <table className="w-full min-w-[460px] border-collapse text-left text-[13.5px]">
                  <caption className="sr-only">
                    The four experimental arms and the two factors each
                    manipulates
                  </caption>
                  <thead>
                    <tr className="border-b border-rule text-ink-600">
                      <th scope="col" className="py-2.5 pr-4 font-medium">
                        Arm
                      </th>
                      <th scope="col" className="py-2.5 pr-4 font-medium">
                        Information
                      </th>
                      <th scope="col" className="py-2.5 font-medium">
                        Enforcement
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ["C0", "none", "none", "Fully isolated. No peer visibility at all."],
                      ["C1", "unbounded transcript", "none", "Every peer event in full. Cost grows with turns."],
                      ["C2", "bounded metadata", "none", "Typed events inside a fixed window."],
                      ["C3", "bounded metadata", "write claims", "Identical information to C2, plus enforced leases."],
                    ].map(([arm, info, enf, note]) => (
                      <tr key={arm} className="border-b border-rule-soft align-top">
                        <td className="py-3 pr-4">
                          <span className="font-mono font-medium text-ink-900">
                            {arm}
                          </span>
                          <span className="mt-1 block max-w-[24ch] text-[12px] leading-snug text-ink-500">
                            {note}
                          </span>
                        </td>
                        <td className="py-3 pr-4 text-ink-700">{info}</td>
                        <td className="py-3 text-ink-700">{enf}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <P>
                The contrasts follow directly. C0 to C2 isolates the
                information benefit. C1 to C2 isolates representation cost. C2
                to C3 isolates enforcement. C1 to C3 measures the complete
                coordinated system.
              </P>
              <P>
                Everything else is held constant: task, model, decoding
                parameters, agent roles, repository fixture, tool semantics,
                success criteria, and randomization protocol. Anything that
                cannot be held constant is recorded and treated as a potential
                confound.
              </P>
              <Pull>
                C2 and C3 run the same code path through the same channel
                object. Only the gate&rsquo;s verdict differs, which is what
                makes that contrast measure enforcement rather than a
                difference in how two arms happened to be built.
              </Pull>
            </section>

            {/* -- 3 ------------------------------------------------------ */}
            <section className="mt-16">
              <H id="guarantees" number="3">
                What the substrate guarantees
              </H>
              <P>
                Four properties, each enforced in code and covered by tests
                rather than asserted in prose. The reasoning matters as much as
                the statement, so each carries the failure it was written
                against.
              </P>

              <Claim
                n="3.1"
                title="Chain integrity"
                statement="Every agent action is an event signed with Ed25519 and hash-linked to its predecessor. Altering, reordering or removing any event invalidates every chain hash after it."
                why="Verification runs with the relay stopped and no repository present, so the evidence does not depend on the system that produced it still being trustworthy, or still running."
                tag="measured"
              />
              <Claim
                n="3.2"
                title="Claim exclusivity"
                statement="At most one valid writer claim may exist for a resource at any instant."
                why="Held in SQLite under BEGIN IMMEDIATE rather than an in-process lock, because agents run as separate OS processes. An in-process lock does not cross that boundary, which is the exact boundary the experiment puts them on."
                tag="measured"
              />
              <Claim
                n="3.3"
                title="Refusal is data"
                statement="A denied action is recorded with its actor, its resource, the holder that blocked it, and the reason. It is never raised as an exception for each call site to log as it sees fit."
                why="The denial record is the primary measurement of enforcement. An earlier build raised instead, and reported a confident zero while enforcement was working correctly. A measurement that cannot observe its own subject is worse than a missing one."
                tag="measured"
              />
              <Claim
                n="3.4"
                title="One primitive, every resource"
                statement="A refused write and a refused payment are the same event. A gate consults declared authority, denies, and records the denial."
                why="The claim registry was written for file paths and treats a path as an opaque normalized string, so it holds an exclusive lease on a payment destination without modification. That is why one substrate covers agents that write code, spend money, or run unattended."
                tag="measured"
              />

              <h3 className="mt-9 font-display text-[1.05rem] font-semibold text-ink-900">
                <span className="cm-nums mr-2.5 font-mono text-[12.5px] font-normal text-ink-400">
                  3.5
                </span>
                Key derivation, stated formally
                <Tag kind="measured" />
              </h3>
              <P>
                Every signing identity in a run, one per agent plus the policy
                plane&rsquo;s own, is derived rather than generated, which is
                what lets a run be reproduced byte for byte from its seed.
                The derivation is HKDF-SHA256 (RFC 5869), instantiated as
              </P>

              <Algorithm
                formula={
                  <>
                    K<sub>actor</sub> = HKDF&#8209;SHA256(IKM = seed, salt =
                    actor_id, info = D, L = 32)
                  </>
                }
                terms={[
                  ["seed", "the run’s master seed, ≥ 16 bytes of entropy"],
                  ["actor_id", "the agent or plane identity being keyed, as UTF-8 bytes"],
                  ["D", "the fixed domain-separation string causalmesh/ed25519/v1"],
                  ["L", "output length in bytes; 32, matching an Ed25519 seed"],
                ]}
                properties={[
                  [
                    "Determinism",
                    "the same (seed, actor_id) pair always yields the same K_actor, so a run reproduces its own signatures exactly.",
                  ],
                  [
                    "Independence",
                    "HKDF’s output is indistinguishable from random without seed, so learning one actor’s derived key reveals nothing about another’s, even though every key shares an origin.",
                  ],
                ]}
                source="crypto/keys.py :: derive_signing_key"
              />

              <P>
                D is mixed into every derivation specifically so a seed
                reused by some other component of the system, now or later,
                can never collide with a key this protocol derived. K
                <sub>actor</sub> is then used directly as the 32-byte seed
                for an Ed25519 keypair, which is what signs every event the
                actor produces (3.1).
              </P>
              <P>
                This is the reproducible path. An operator whose agents must
                not share a derivation origin, because they are mutually
                distrusting participants rather than roles inside one run,
                supplies external keys instead; that run is no longer
                reproducible from the seed alone, which is the correct
                tradeoff for that deployment shape and is stated as such
                rather than left implicit.
              </P>
            </section>

            {/* -- 4 ------------------------------------------------------ */}
            <section className="mt-16">
              <H id="governance" number="4">
                The governance gap
              </H>
              <P>
                The properties above are not only useful. They are increasingly
                required, and they are precisely what current agent protocols
                cannot express.
              </P>
              <P>
                A 2026 analysis of MCP, A2A and ACP enumerated what the
                interoperability layer leaves out.
                <Cite id="governance-gaps" /> Set against what this substrate
                implements, the overlap is most of the list.
              </P>

              {/* The seven gaps are the section's entire argument, and they
                  were a sentence. A checklist is the right shape: the reader
                  is comparing two sets, and the honest answer includes the
                  rows we do not cover. */}
              <ul className="mt-7 divide-y divide-rule-soft border-t border-rule">
                {[
                  ["Accountability and attribution", true, "Every event carries its agent, run and task identity."],
                  ["Verifiable audit trails", true, "Ed25519 signatures over a hash-linked chain."],
                  ["Provenance", true, "Recorded in the run envelope, outside the signed payload."],
                  ["Resource-ownership enforcement", true, "Declared ownership drives the claim registry."],
                  ["Multi-agent conflict resolution", true, "Exclusive leases, and a recorded refusal when one is refused."],
                  ["Fine-grained access control", true, "Allowlists, ceilings and budgets, per role."],
                  ["Enforcement mechanisms", true, "The gate. This is the factor the experiment isolates."],
                ].map(([gap, covered, how]) => (
                  <li key={gap} className="flex gap-4 py-3.5">
                    <span
                      aria-hidden="true"
                      className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                        covered ? "bg-marker-deep" : "bg-ink-300"
                      }`}
                    />
                    <div>
                      <div className="text-[14.5px] font-medium text-ink-900">
                        {gap}
                      </div>
                      <div className="mt-0.5 text-[13px] leading-relaxed text-ink-500">
                        {how}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="mt-4 text-[13px] leading-relaxed text-ink-500">
                Seven of seven, which is less impressive than it sounds: the
                paper enumerated the properties a coordination substrate needs,
                and this was built to be one. The useful reading is that the
                list exists and that no interoperability protocol satisfies it.
              </p>

              <P>
                The observability layer stops at the same line.
                OpenTelemetry&rsquo;s GenAI semantic conventions standardize
                how agents are <em>traced</em>, and explicitly stop before
                evaluation, safety scoring and enforcement.
                <Cite id="otel-genai" /> That boundary is not an oversight.
                Tracing describes what happened; enforcement decides what may
                happen, and the two need different machinery. We emit spans
                rather than competing with them.
              </P>
              <P>
                Meanwhile the requirement is arriving from regulators.
                NIST&rsquo;s AI Agent Standards Initiative names
                authentication, authorization, auditing and non-repudiation as
                the controls agents lack, observing that agents running under
                generic service-account credentials &ldquo;cannot be audited
                back to specific user intent&rdquo;.
                <Cite id="nist-caisi" /> Singapore&rsquo;s IMDA framework for
                agentic AI requires each agent to carry a verifiable identity
                and an audit trail of which agent acted under whose
                authorisation.
                <Cite id="imda" />
              </P>
              <P>
                An independent proposal arrives at the same construction from
                first principles: a <em>recomputable</em> trust protocol, where
                a third party re-verifies signed execution traces offline
                without trusting the infrastructure that produced them.
                <Cite id="trust-without-trusting" /> That is what{" "}
                <code className="rounded bg-paper-sunk px-1.5 py-0.5 font-mono text-[13px] text-ink-800">
                  causalmesh verify
                </code>{" "}
                does with the relay stopped, and it is the property section 3.1
                describes.
              </P>
              <Pull>
                AGENTS.md is read by every major coding agent and sits in
                60,000+ repositories.
                <Cite id="agents-md" /> It expresses guidelines and enforces
                nothing. A convention every agent reads and no agent is held to
                is a convention without a substrate.
              </Pull>
            </section>

            {/* -- 5 ------------------------------------------------------ */}
            <section className="mt-16">
              <H id="results" number="5" tag="measured">
                Measured results
              </H>
              <P>
                A pilot of {RESULTS.total_runs} runs, 2 tasks by 4 arms by 3
                repetitions, executed on deterministic mock agents. Every
                figure below is read from the run artifacts. None is
                illustrative.
              </P>

              <div className="mt-7 overflow-x-auto">
                <table className="w-full min-w-[440px] border-collapse text-[13.5px]">
                  <caption className="sr-only">
                    Success rate, coordination cost and refusals by arm
                  </caption>
                  <thead>
                    <tr className="border-b border-rule text-left text-ink-600">
                      <th scope="col" className="py-2.5 pr-4 font-medium">
                        Arm
                      </th>
                      <th scope="col" className="py-2.5 pr-4 text-right font-medium">
                        Success
                      </th>
                      <th scope="col" className="py-2.5 pr-4 text-right font-medium">
                        Bytes / run
                      </th>
                      <th scope="col" className="py-2.5 text-right font-medium">
                        Refused
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {["C0", "C1", "C2", "C3"].map((id) => {
                      const r = armResult(id);
                      return (
                        <tr key={id} className="border-b border-rule-soft">
                          <td className="py-3 pr-4 font-mono text-ink-900">{id}</td>
                          <td className="cm-nums py-3 pr-4 text-right text-ink-800">
                            {Math.round(r.success_rate * 100)}%
                          </td>
                          <td className="cm-nums py-3 pr-4 text-right text-ink-800">
                            {r.mean_coordination_bytes}
                          </td>
                          <td className="cm-nums py-3 text-right text-ink-800">
                            {r.denials || "0"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <h3 className="mt-9 font-display text-[1.05rem] font-semibold text-ink-900">
                Information alone closes the gap
              </h3>
              <P>
                C0 fails every run. C2 succeeds on every one. Whatever else is
                true, agents that cannot see each other cannot complete these
                tasks, and bounded metadata is enough to fix that.
              </P>

              <h3 className="mt-7 font-display text-[1.05rem] font-semibold text-ink-900">
                Representation is nearly free
              </h3>
              <P>
                C2 reaches C1&rsquo;s success rate on {saving}% fewer
                coordination bytes. The unbounded transcript buys nothing here
                that the bounded window does not, while costing{" "}
                {c1.mean_coordination_bytes} bytes per run against{" "}
                {c2.mean_coordination_bytes}. On this task, full history is a
                cost without a matching benefit.
              </P>

              <h3 className="mt-7 font-display text-[1.05rem] font-semibold text-ink-900">
                Enforcement is task-dependent, and the average hides it
              </h3>
              <P>
                C3 carries the same cost as C2 and refuses {c3.denials} writes,
                which lowers its aggregate success rate to{" "}
                {Math.round(c3.success_rate * 100)}%. Read as a single number
                that looks like a regression. Read per task it is not: C3
                prevents every clobber on the contested task and behaves
                identically to C2 on the other.
              </P>
              <Pull>
                A refused write is recorded as a run that did not meet its
                success criterion. Whether that is a cost or a benefit depends
                entirely on what the alternative was, and on the contested task
                the alternative was a silent overwrite.
              </Pull>
              <P>
                This is why the analysis reports per-task contrasts by default.
                The pooled average describes neither task: enforcement costs
                nothing where ownership is disjoint, and prevents every
                collision where it is contested. Averaging those two produces a
                number that is true of no task the system actually ran.
              </P>
            </section>

            {/* -- 6 ------------------------------------------------------ */}
            <section className="mt-16">
              <H id="framework" number="6" tag="planned">
                From experiment to framework
              </H>
              <P>
                Web development has frameworks that encode conventions in the
                substrate. Agentic development has libraries and harnesses but
                no equivalent, so every project re-derives which model, how
                tools are structured, what the context strategy is, and who may
                write or spend what.
              </P>
              <P>
                The policy plane generalises the measured gate from file paths
                to resources of four kinds: paths, spend, endpoints and
                budgets. They are declared in a{" "}
                <code className="rounded bg-paper-sunk px-1.5 py-0.5 font-mono text-[13px] text-ink-800">
                  causalmesh.yaml
                </code>{" "}
                that sits beside AGENTS.md. AGENTS.md says what agents should
                do. The contract says what they may do, and the gate holds them
                to it.
              </P>
              <P>
                The same four planes carry all of it. A contract declares
                authority, a gate decides, a chain records, and the arms
                measure whether the convention paid for itself. That last plane
                is the unusual one: a framework that ships a guideline
                alongside a number proving the guideline earned its cost is a
                different kind of claim from one that ships the guideline
                alone.
              </P>
              <P>
                This is built and interrogable today. It is{" "}
                <em>not</em> yet wired into the run loop, which is why this
                section is labelled planned rather than measured. The results
                in section 5 come from the original path-only gate, which is
                unchanged.
              </P>
            </section>

            {/* -- 7 ------------------------------------------------------ */}
            <section className="mt-16">
              <H id="limitations" number="7">
                Limitations
              </H>
              <P>
                This build measures a platform, not language models. Every run
                reported here used a deterministic mock agent, so nothing in it
                supports a claim about how real coding agents coordinate. The
                adapters are written against the chat-completions wire protocol
                and tested over real HTTP, but no hosted model has been run
                through them. That needs an API key and a budget, and spending
                money is the operator&rsquo;s decision.
              </P>
              <P>
                The pilot is {RESULTS.total_runs} runs across 2 tasks. It is
                descriptive: no interval is reported and no significance test
                is performed, because the statistics layer that would support
                such a claim is not built. The confirmatory design calls for
                1,920 runs and has not been executed.
              </P>
              <P>
                Isolation for the C0 arm is layered rather than absolute on
                Windows, where no chroot exists. The documentation states this
                as a limitation rather than asserting an isolation guarantee
                the platform cannot provide.
              </P>
              <P>
                Two tasks is a narrow base for the claim that enforcement is
                task-dependent. The finding is that enforcement behaved
                differently on a contested task than on a disjoint one, which
                is a demonstration that the difference exists, not a
                quantification of how often it does.
              </P>
            </section>

            {/* -- refs --------------------------------------------------- */}
            <section className="mt-16">
              <H id="references">References</H>
              <ol className="mt-6 divide-y divide-rule-soft border-t border-rule-soft">
                {REFERENCES.map((reference, index) => (
                  <li
                    key={reference.id}
                    id={`ref-${reference.id}`}
                    className="flex scroll-mt-28 gap-4 py-3.5 target:bg-marker-wash"
                  >
                    <span className="cm-nums w-5 shrink-0 font-mono text-[12px] text-ink-400">
                      {index + 1}
                    </span>
                    <div>
                      <a
                        href={reference.href}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[13.5px] leading-relaxed text-ink-700 underline decoration-rule-soft underline-offset-2 transition-colors hover:text-ink-900 hover:decoration-marker-deep"
                      >
                        {reference.title}
                      </a>
                      <div className="mt-0.5 font-mono text-[11.5px] text-ink-500">
                        {reference.venue}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            </section>

            {/* One way out of the document, to the thing it describes. */}
            <div className="mt-16 flex flex-wrap items-center gap-x-5 gap-y-3 border-t border-rule pt-7">
              <span className="inline-flex items-center gap-2 bg-marker px-5 py-2.5 text-[14px] font-medium text-ink-900">
                Source releasing soon
              </span>
              <a
                href="/docs"
                className="text-[14px] text-ink-700 underline decoration-rule-soft underline-offset-4 transition-colors hover:text-ink-900 hover:decoration-marker-deep"
              >
                Run it yourself
              </a>
            </div>
          </article>
        </div>
      </div>
    </div>
  );
}

/**
 * One guarantee: what it says, and the failure it was written against.
 *
 * Set on a hairline rather than the heavy left bar an earlier version used.
 * A 2px accent rule down the side of a card is a habit rather than a
 * decision, and at four in a row it turned the section into a stack of
 * alert boxes.
 */
function Claim({ n, title, statement, why, tag }) {
  return (
    <div className="mt-7 border-t border-rule-soft pt-5">
      <h3 className="font-display text-[1.05rem] font-semibold text-ink-900">
        <span className="cm-nums mr-2.5 font-mono text-[12.5px] font-normal text-ink-400">
          {n}
        </span>
        {title}
        {tag && <Tag kind={tag} />}
      </h3>
      <p className="mt-2.5 text-[14.5px] leading-relaxed text-ink-800">{statement}</p>
      <p className="mt-2 text-[13px] leading-relaxed text-ink-500">{why}</p>
    </div>
  );
}

/**
 * A mechanism stated with real notation, on the same
 * `border-rule-soft bg-paper-raised` panel Figure 1 already uses so a
 * formal box reads as a sibling of the paper's other set-apart content
 * rather than a new visual language dropped in for one section.
 *
 * No LaTeX renderer: the paper has one formula in it, and a KaTeX
 * dependency for one equation is a much larger cost than setting it in
 * the mono face the page already uses everywhere for data.
 */
function Algorithm({ formula, terms, properties, source }) {
  return (
    <figure className="mt-6 rounded-xl border border-rule-soft bg-paper-raised p-6 sm:p-7">
      <div className="overflow-x-auto rounded-lg border border-rule-soft bg-paper px-5 py-4">
        <p className="cm-nums whitespace-nowrap font-mono text-[14.5px] text-ink-900">
          {formula}
        </p>
      </div>

      <dl className="mt-5 space-y-1.5">
        {terms.map(([symbol, meaning]) => (
          <div key={symbol} className="flex gap-3 text-[13px] leading-relaxed">
            <dt className="w-20 shrink-0 font-mono text-ink-600">{symbol}</dt>
            <dd className="text-ink-700">{meaning}</dd>
          </div>
        ))}
      </dl>

      <ul className="mt-5 space-y-2.5 border-t border-rule-soft pt-5">
        {properties.map(([name, detail]) => (
          <li key={name} className="text-[13px] leading-relaxed text-ink-700">
            <span className="font-medium text-ink-900">{name}.</span> {detail}
          </li>
        ))}
      </ul>

      <figcaption className="mt-5 border-t border-rule-soft pt-3 font-mono text-[11.5px] text-ink-500">
        {source}
      </figcaption>
    </figure>
  );
}

// Figure marks, sized once so the row reads as one set.
const FIG = "h-8 w-8 text-ink-800";
const FleetFigure = () => <FleetIcon className={FIG} />;
const GateFigure = () => <GateIcon className={FIG} />;
const ChainFigure = () => <ChainIcon className={FIG} />;
const SignFigure = () => <SignIcon className={FIG} />;
