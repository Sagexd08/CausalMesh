"use client";

import { useEffect, useState } from "react";
import { ChainIcon, FleetIcon, GateIcon, SignIcon } from "./MotionIcons.jsx";
import { RESULTS, armResult } from "@/lib/landing/data.js";

/**
 * The whitepaper, as a designed reading surface rather than a PDF link.
 *
 * Mode is Read: the visitor is here to understand something, so structure
 * serves comprehension first and expression second. That means a measure
 * held near 70ch, a sticky contents column that tracks position, real
 * section numbering (this is the one place the craft floor's ban on section
 * numbers does not apply — a paper's numbered sections are how its own
 * cross-references work), and figures that are drawn rather than described.
 *
 * **Every claim is one of three kinds, and the page marks which.** Measured
 * facts come from the pilot artifacts and carry their run count. Cited facts
 * name their source and link it. Designed-but-unbuilt work is labelled
 * planned. A paper that blurs those three is marketing with footnotes.
 */

const SECTIONS = [
  ["abstract", "Abstract"],
  ["question", "1. The question"],
  ["design", "2. Experimental design"],
  ["guarantees", "3. What the substrate guarantees"],
  ["governance", "4. The governance gap"],
  ["results", "5. Measured results"],
  ["framework", "6. From experiment to framework"],
  ["limitations", "7. Limitations"],
  ["references", "References"],
];

/** Tracks which section is in view, so the contents column stays honest. */
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
      { rootMargin: "-80px 0px -65% 0px", threshold: 0 }
    );
    for (const [id] of SECTIONS) {
      const node = document.getElementById(id);
      if (node) observer.observe(node);
    }
    return () => observer.disconnect();
  }, []);

  return active;
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

function H({ id, children, tag }) {
  return (
    <h2
      id={id}
      className="scroll-mt-24 font-display text-[1.6rem] font-bold leading-tight tracking-tightest text-ink-900 sm:text-[1.9rem]"
    >
      {children}
      {tag && <Tag kind={tag} />}
    </h2>
  );
}

function P({ children }) {
  return (
    <p className="mt-4 text-[15.5px] leading-[1.75] text-ink-700">{children}</p>
  );
}

export default function Paper() {
  const active = useActiveSection();
  const c1 = armResult("C1");
  const c2 = armResult("C2");
  const c3 = armResult("C3");
  const saving = Math.round(
    ((c1.mean_coordination_bytes - c2.mean_coordination_bytes) /
      c1.mean_coordination_bytes) *
      100
  );

  return (
    <div className="mx-auto w-full max-w-[1180px] px-6 py-16 sm:px-10 lg:px-16 lg:py-24">
      <div className="grid grid-cols-1 gap-x-16 lg:grid-cols-[210px_1fr]">
        {/* Contents. Sticky on desktop, a plain list on mobile — a sticky
            rail on a phone eats the screen the text needs. */}
        <nav aria-label="Contents" className="mb-12 lg:mb-0">
          <div className="lg:sticky lg:top-24">
            <div className="font-mono text-[10.5px] uppercase tracking-wider text-ink-500">
              Contents
            </div>
            <ul className="mt-4 space-y-2.5 border-l border-rule-soft">
              {SECTIONS.map(([id, label]) => (
                <li key={id}>
                  <a
                    href={`#${id}`}
                    className={`-ml-px block border-l-2 pl-3 text-[13px] leading-snug transition-colors ${
                      active === id
                        ? "border-ink-900 font-medium text-ink-900"
                        : "border-transparent text-ink-500 hover:text-ink-800"
                    }`}
                  >
                    {label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </nav>

        <article className="max-w-[70ch]">
          <div className="font-mono text-[11px] uppercase tracking-wider text-ink-500">
            Whitepaper &middot; v0.1 &middot; September 2026
          </div>
          <h1 className="mt-4 font-display text-[2.4rem] font-extrabold leading-[1.05] tracking-tightest text-ink-900 sm:text-[3.1rem]">
            Separating information from enforcement in fleets of coding agents
          </h1>
          <p className="mt-6 text-[16.5px] leading-relaxed text-ink-600">
            An experimental substrate that measures what coordination buys, and
            produces cryptographic evidence of everything every agent did.
          </p>

          <div className="mt-8 flex flex-wrap gap-x-8 gap-y-3 border-y border-rule-soft py-4 text-[13px] text-ink-600">
            <span>
              <span className="cm-nums font-medium text-ink-900">
                {RESULTS.total_runs}
              </span>{" "}
              runs
            </span>
            <span>
              <span className="cm-nums font-medium text-ink-900">4</span> arms
            </span>
            <span>
              <span className="cm-nums font-medium text-ink-900">
                {RESULTS.total_runs}
              </span>
              /{RESULTS.total_runs} chains verified offline
            </span>
            <span>
              <span className="cm-nums font-medium text-ink-900">775</span> tests
            </span>
          </div>

          {/* -- Abstract ------------------------------------------------ */}
          <section className="mt-14">
            <H id="abstract">Abstract</H>
            <P>
              When several language-model coding agents work on one repository
              they interfere: they read stale state, duplicate each other&rsquo;s
              work, and overwrite each other&rsquo;s changes. Systems that
              address this do two things at once — they <em>tell</em> agents what
              their peers are doing, and they <em>prevent</em> agents from
              conflicting. Because the two arrive together, their individual
              contributions are unknown.
            </P>
            <P>
              CausalMesh separates them experimentally. Four arms manipulate
              exactly two factors, information and enforcement, holding
              everything else constant. The contribution is measurement, not the
              invention of a new coordination mechanism. A second contribution
              follows from how the measurement is built: because every agent
              action is signed into a hash-linked chain that verifies offline,
              the substrate produces an audit trail that standards bodies have
              begun to require and that no interoperability protocol currently
              expresses.
            </P>
          </section>

          {/* -- 1 ------------------------------------------------------- */}
          <section className="mt-14">
            <H id="question">1. The question</H>
            <P>
              How much of the coordination benefit in distributed LLM coding
              agents comes from information, and how much from enforcement?
            </P>
            <P>
              The problem is not hypothetical. An analysis of 142,000+
              agent-authored pull requests across 59,000+ repositories found a{" "}
              <strong className="font-medium text-ink-900">27.67%</strong>{" "}
              conflict rate, with cross-agent pairs conflicting at roughly twice
              the rate of intra-agent pairs.
              <Tag kind="cited" />
            </P>
            <figure className="mt-8 rounded-xl border border-rule-soft bg-paper-raised p-6">
              <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
                {[
                  [FleetFigure, "Agents share one repo"],
                  [GateFigure, "A write is refused"],
                  [ChainFigure, "The refusal is linked"],
                  [SignFigure, "And signed"],
                ].map(([Figure, caption]) => (
                  <div key={caption} className="flex flex-col items-center gap-3 text-center">
                    <Figure />
                    <span className="text-[12px] leading-snug text-ink-600">
                      {caption}
                    </span>
                  </div>
                ))}
              </div>
              <figcaption className="mt-5 border-t border-rule-soft pt-4 text-[12.5px] leading-relaxed text-ink-500">
                Figure 1. The path of one refused action. Every stage is
                recorded; the refusal is evidence rather than an error.
              </figcaption>
            </figure>
          </section>

          {/* -- 2 ------------------------------------------------------- */}
          <section className="mt-14">
            <H id="design">2. Experimental design</H>
            <P>
              Four arms manipulate two factors. C0 gives agents no peer
              information and no enforcement. C1 gives an unbounded conversational
              transcript. C2 gives bounded structured metadata — typed events
              chosen by a deterministic relevance scorer inside a fixed window.
              C3 gives the metadata of C2 <em>plus</em> enforced exclusive write
              claims.
            </P>
            <P>
              The contrasts that answer the question follow directly: C0→C2
              isolates the information benefit, C1→C2 isolates representation
              cost, C2→C3 isolates enforcement, and C1→C3 measures the complete
              coordinated system.
            </P>
            <P>
              Everything else is held constant — task, model, decoding
              parameters, agent roles, repository fixture, tool semantics,
              success criteria and randomization protocol. Anything that cannot
              be held constant is recorded and treated as a potential confound.
              Critically, C2 and C3 run the same code path through the same
              channel object; only the gate&rsquo;s verdict differs. That is what
              makes the C2→C3 contrast measure enforcement rather than a
              difference in how two arms happened to be implemented.
            </P>
          </section>

          {/* -- 3 ------------------------------------------------------- */}
          <section className="mt-14">
            <H id="guarantees">3. What the substrate guarantees</H>
            <P>
              Three properties are enforced in code and covered by tests, rather
              than asserted in prose.
            </P>

            <Claim
              n="3.1"
              title="Chain integrity"
              statement="Every agent action is an event signed with Ed25519 and hash-linked to its predecessor. Altering, reordering or removing any event invalidates every chain hash after it."
              why="Verification runs with the relay stopped and no repository present, so the evidence does not depend on the system that produced it still being trustworthy — or still running."
              tag="measured"
            />
            <Claim
              n="3.2"
              title="Claim exclusivity"
              statement="At most one valid writer claim may exist for a resource at any instant."
              why="Held in SQLite under BEGIN IMMEDIATE rather than an in-process lock, because agents run as separate OS processes — the exact boundary an in-process lock does not cross."
              tag="measured"
            />
            <Claim
              n="3.3"
              title="Refusal is data"
              statement="A denied action is recorded with its actor, its resource, the holder that blocked it, and the reason — never raised as an exception for each call site to log as it sees fit."
              why="The denial record is the primary measurement of enforcement. An earlier build raised instead, and reported a confident zero while enforcement was working correctly."
              tag="measured"
            />
            <Claim
              n="3.4"
              title="One primitive, every resource"
              statement="A refused write and a refused payment are the same event: a gate consults declared authority, denies, and records the denial."
              why="The claim registry was written for file paths and treats a path as an opaque normalized string, so it holds an exclusive lease on a payment destination without modification. This is why one substrate covers agents that write code, spend money, or run unattended."
              tag="measured"
            />
          </section>

          {/* -- 4 ------------------------------------------------------- */}
          <section className="mt-14">
            <H id="governance">4. The governance gap</H>
            <P>
              The properties above are not only useful — they are increasingly
              required, and they are precisely what current agent protocols
              cannot express.
            </P>
            <P>
              A 2026 analysis of MCP, A2A and ACP found that none can express
              accountability and attribution, verifiable audit trails,
              provenance, resource-ownership enforcement, multi-agent conflict
              resolution, fine-grained access control, or enforcement mechanisms.
              <Tag kind="cited" /> Separately, OpenTelemetry&rsquo;s GenAI
              semantic conventions standardize how agents are <em>traced</em> and
              explicitly stop before evaluation, safety scoring and enforcement.
              <Tag kind="cited" />
            </P>
            <P>
              Meanwhile NIST&rsquo;s AI Agent Standards Initiative names
              authentication, authorization, auditing and non-repudiation as the
              controls agents lack, observing that agents running under generic
              service-account credentials &ldquo;cannot be audited back to
              specific user intent&rdquo;.
              <Tag kind="cited" /> Singapore&rsquo;s IMDA framework for agentic
              AI requires each agent to carry a verifiable identity and an audit
              trail of which agent acted under whose authorisation.
              <Tag kind="cited" />
            </P>
            <P>
              AGENTS.md illustrates the gap by what it omits. Read by every major
              coding agent and present in 60,000+ repositories, it expresses
              guidelines and enforces nothing. A convention every agent reads and
              no agent is held to is a convention without a substrate.
            </P>
          </section>

          {/* -- 5 ------------------------------------------------------- */}
          <section className="mt-14">
            <H id="results" tag="measured">
              5. Measured results
            </H>
            <P>
              A pilot of {RESULTS.total_runs} runs — 2 tasks × 4 arms × 3
              repetitions — executed on deterministic mock agents. Every figure
              below is read from the run artifacts; none is illustrative.
            </P>

            <div className="mt-6 overflow-x-auto">
              <table className="w-full min-w-[420px] border-collapse text-[13.5px]">
                <thead>
                  <tr className="border-b border-rule text-left text-ink-600">
                    <th className="py-2 pr-4 font-medium">Arm</th>
                    <th className="py-2 pr-4 text-right font-medium">Success</th>
                    <th className="py-2 pr-4 text-right font-medium">Bytes / run</th>
                    <th className="py-2 text-right font-medium">Refused</th>
                  </tr>
                </thead>
                <tbody>
                  {["C0", "C1", "C2", "C3"].map((id) => {
                    const r = armResult(id);
                    return (
                      <tr key={id} className="border-b border-rule-soft">
                        <td className="py-2.5 pr-4 font-mono text-ink-900">{id}</td>
                        <td className="cm-nums py-2.5 pr-4 text-right text-ink-800">
                          {Math.round(r.success_rate * 100)}%
                        </td>
                        <td className="cm-nums py-2.5 pr-4 text-right text-ink-800">
                          {r.mean_coordination_bytes}
                        </td>
                        <td className="cm-nums py-2.5 text-right text-ink-800">
                          {r.denials || "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <P>
              Three findings. Information alone closes the gap: C0 fails every
              run, C2 succeeds on every one. Representation is nearly free: C2
              reaches C1&rsquo;s success rate on {saving}% fewer coordination
              bytes, so the unbounded transcript buys nothing the bounded window
              does not. And enforcement is task-dependent — C3 carries the same
              cost as C2 and refuses {c3.denials} writes, which lowers its
              aggregate success rate to {Math.round(c3.success_rate * 100)}%
              while preventing every clobber on the contested task.
            </P>
            <P>
              That last result is the one worth stating carefully. A refused
              write is recorded as a run that did not meet its success criterion.
              Whether that is a cost or a benefit depends on what the alternative
              was — and on the contested task, the alternative was a silent
              overwrite. The per-task breakdown is where this is visible; the
              pooled average describes neither task.
            </P>
          </section>

          {/* -- 6 ------------------------------------------------------- */}
          <section className="mt-14">
            <H id="framework" tag="planned">
              6. From experiment to framework
            </H>
            <P>
              Web development has frameworks that encode conventions in the
              substrate. Agentic development has libraries and harnesses but no
              equivalent: every project re-derives which model, how tools are
              structured, what the context strategy is, and who may write or
              spend what.
            </P>
            <P>
              The policy plane generalises the measured gate from file paths to
              resources of four kinds — paths, spend, endpoints and budgets —
              declared in a <code className="font-mono text-[13px]">causalmesh.yaml</code>{" "}
              that sits beside AGENTS.md. AGENTS.md says what agents should do;
              the contract says what they may do, and the gate holds them to it.
            </P>
            <P>
              This is built and interrogable today and is <em>not</em> yet wired
              into the run loop, which is why this section is labelled planned
              rather than measured. The measured results in §5 come from the
              original path-only gate, which is unchanged.
            </P>
          </section>

          {/* -- 7 ------------------------------------------------------- */}
          <section className="mt-14">
            <H id="limitations">7. Limitations</H>
            <P>
              This build measures a platform, not language models. Every run
              reported here used a deterministic mock agent, so nothing in it
              supports a claim about how real coding agents coordinate. The
              adapters are written against the chat-completions wire protocol and
              tested over real HTTP, but no hosted model has been run through
              them — that needs an API key and a budget, and spending money is
              the operator&rsquo;s decision.
            </P>
            <P>
              The pilot is {RESULTS.total_runs} runs across 2 tasks. It is
              descriptive: no interval is reported and no significance test is
              performed, because the statistics layer that would support such a
              claim is not built. The confirmatory design calls for 1,920 runs
              and has not been executed.
            </P>
            <P>
              Isolation for the C0 arm is layered rather than absolute on
              Windows, where no chroot exists. The documentation states this as a
              limitation rather than asserting an isolation guarantee the
              platform cannot provide.
            </P>
          </section>

          {/* -- refs ---------------------------------------------------- */}
          <section className="mt-14">
            <H id="references">References</H>
            <ol className="mt-5 space-y-3 text-[13.5px] leading-relaxed text-ink-600">
              {[
                ["Governance Gaps in Agent Interoperability Protocols: What MCP, A2A, and ACP Cannot Express", "https://arxiv.org/pdf/2606.31498"],
                ["Trust Without Trusting: A Recomputable Trust Protocol for Autonomous Agents", "https://arxiv.org/pdf/2605.06738"],
                ["An Empirical Study of Agent Developer Practices in AI Agent Frameworks", "https://arxiv.org/pdf/2512.01939"],
                ["NIST: Announcing the AI Agent Standards Initiative", "https://www.nist.gov/news-events/news/2026/02/announcing-ai-agent-standards-initiative-interoperable-and-secure"],
                ["When Agents Collide: What 33,596 Pull Requests Reveal About Merge Conflicts", "https://codex.danielvaughan.com/2026/07/28/agent-pr-merge-conflicts-concurrent-coding-agents-codex-cli-worktree-isolation-coordination-defence/"],
                ["Inside the LLM Call: GenAI Observability with OpenTelemetry", "https://opentelemetry.io/blog/2026/genai-observability/"],
                ["AGENTS.md Specification", "https://asdlc.io/practices/agents-md-spec/"],
              ].map(([title, href], index) => (
                <li key={href} className="flex gap-3">
                  <span className="cm-nums shrink-0 font-mono text-[12px] text-ink-400">
                    [{index + 1}]
                  </span>
                  <a
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                    className="underline decoration-rule-soft underline-offset-2 transition-colors hover:text-ink-900 hover:decoration-marker-deep"
                  >
                    {title}
                  </a>
                </li>
              ))}
            </ol>
          </section>
        </article>
      </div>
    </div>
  );
}

function Claim({ n, title, statement, why, tag }) {
  return (
    <div className="mt-7 border-l-2 border-ink-900 pl-5">
      <h3 className="font-display text-[1.05rem] font-semibold text-ink-900">
        <span className="cm-nums mr-2 font-mono text-[12.5px] text-ink-500">{n}</span>
        {title}
        {tag && <Tag kind={tag} />}
      </h3>
      <p className="mt-2 text-[14.5px] leading-relaxed text-ink-800">{statement}</p>
      <p className="mt-2 text-[13px] leading-relaxed text-ink-500">{why}</p>
    </div>
  );
}

// Figure marks, sized once so the row reads as one set.
const FIG = "h-8 w-8 text-ink-800";
const FleetFigure = () => <FleetIcon className={FIG} />;
const GateFigure = () => <GateIcon className={FIG} />;
const ChainFigure = () => <ChainIcon className={FIG} />;
const SignFigure = () => <SignIcon className={FIG} />;
