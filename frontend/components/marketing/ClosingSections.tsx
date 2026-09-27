import { BenchmarkTable } from '@/components/system/BenchmarkTable';
import { CodeBlock } from '@/components/system/CodeBlock';
import { Panel } from '@/components/system/Panel';
import { Reveal } from '@/components/ui/Reveal';
import { Label, Section, SectionHead, StatusDot } from '@/components/ui/Section';
import { TrackedLink } from '@/components/ui/TrackedLink';
import { CONTRACT, LINKS, RESEARCH, RESULTS, TOOLS } from '@/lib/site/content';
import { FaqList } from './FaqList';

const INSTALL = `$ git clone https://github.com/Sagexd08/CausalMesh
$ cd CausalMesh && pip install -e .
$ causalmesh doctor
$ causalmesh policy show`;

const PROGRAM = `from causalmesh import CausalMesh, Tool

mesh = CausalMesh.from_config("causalmesh.yaml")
mesh.register_tool(
    Tool(name="write_file", handler=write_file, kind="filesystem", mutating=True)
)

result = mesh.execute(
    agent_id="coding-agent",
    tool="write_file",
    arguments={"path": "src/example.py", "content": "print('hello')"},
)

if result.denied:
    print(result.describe())   # rule, holder, reason: and it is recorded`;

export function DeveloperSection() {
  const status: Array<[string, string]> = [
    ['Contract', `v${CONTRACT.version} · ${CONTRACT.roles} roles`],
    ['Arm', `${CONTRACT.arm} · enforcing`],
    ['Tools', `${TOOLS.length} operations`],
    ['Evidence', 'signed · verify on exit'],
  ];

  return (
    <Section id="developer">
      <SectionHead index="06 / Developer" title="From a clone to a gated call." className="max-w-[760px]">
        The runtime core is Python 3.11 with two dependencies: cryptography
        for Ed25519 and PyYAML for the contract. Every CLI command takes
        <code className="mx-1 font-code text-[14px] text-fg-2">--json</code>
        and its exit code means something, so a script can branch on it.
      </SectionHead>

      <div className="mt-14 grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1.35fr]">
        <Reveal className="flex flex-col gap-4">
          <CodeBlock title="shell" code={INSTALL} copyId="install" />
          <Panel title="Session" status="ready">
            <dl className="divide-y divide-line">
              {status.map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-4 px-4 py-3 font-code text-[12px]">
                  <dt className="label">{k}</dt>
                  <dd className="flex items-center gap-2 text-fg-2">
                    <StatusDot />
                    {v}
                  </dd>
                </div>
              ))}
            </dl>
          </Panel>
        </Reveal>
        <Reveal index={1}>
          <CodeBlock title="agent.py" code={PROGRAM} copyId="sdk_program" className="h-full" />
        </Reveal>
      </div>
    </Section>
  );
}

export function MeasuredSection() {
  return (
    <Section id="measured">
      <div className="grid grid-cols-1 gap-x-16 gap-y-8 lg:grid-cols-[1fr_1fr] lg:items-end">
        <SectionHead index="07 / Measured" title="Numbers from runs, not from a pitch." />
        <Reveal index={2}>
          <p className="max-w-[56ch] text-[14.5px] leading-[1.7] text-muted">
            The pilot collection: 2 tasks, 4 arms, 3 repetitions, executed
            2026-09-13. Every run used a deterministic mock agent, so this shows
            that the machinery measures correctly. It estimates nothing about
            how a model behaves.
          </p>
        </Reveal>
      </div>
      <Reveal index={1} className="mt-12">
        <BenchmarkTable />
      </Reveal>
      <Reveal index={2}>
        <p className="mt-4 font-code text-[11.5px] text-dim">
          Source: data/raw/{RESULTS.experiment_id}, exported by scripts/export_results.py.
          C0 failing is the expected result, not a defect.
        </p>
      </Reveal>
    </Section>
  );
}

export function ResearchSection() {
  return (
    <Section id="research">
      <SectionHead index="08 / Research" title="The infrastructure is the research." className="max-w-[760px]">
        CausalMesh started as a question: how much of the benefit of
        coordinating agents comes from what they are told, and how much from
        what they are prevented from doing. The substrate is how that gets
        measured.
      </SectionHead>
      <Reveal index={1} className="mt-14">
        <ul className="border-t border-line">
          {RESEARCH.map((item) => (
            <li key={item.href}>
              <TrackedLink
                event="research_click"
                props={{ title: item.title }}
                href={item.href}
                className="group grid grid-cols-1 gap-x-8 gap-y-2 border-b border-line py-6 transition-colors duration-300 hover:bg-white/[0.02] md:grid-cols-[110px_120px_1fr_auto] md:items-baseline md:px-2"
              >
                <span className="font-code text-[12px] text-dim">{item.date}</span>
                <span className="label">{item.category}</span>
                <span>
                  <span className="block text-[18px] tracking-[-0.02em] text-fg">{item.title}</span>
                  <span className="mt-1 block max-w-[70ch] text-[14px] leading-relaxed text-muted">
                    {item.description}
                  </span>
                </span>
                <span className="font-code text-[12px] text-dim transition-colors group-hover:text-fg">
                  Read <span aria-hidden="true">&rarr;</span>
                </span>
              </TrackedLink>
            </li>
          ))}
        </ul>
      </Reveal>
    </Section>
  );
}

export function FaqSection() {
  return (
    <Section id="faq">
      <div className="grid grid-cols-1 gap-x-16 gap-y-12 lg:grid-cols-[0.8fr_1.2fr]">
        <SectionHead index="09 / FAQ" title="What an operator asks first." />
        <Reveal index={1}>
          <FaqList />
        </Reveal>
      </div>
    </Section>
  );
}

export function CtaSection() {
  return (
    <section id="contact" className="scroll-mt-8 border-t border-line">
      <div className="mx-auto w-full max-w-[1320px] px-6 py-28 sm:px-10 md:py-40 lg:px-16">
        <Reveal>
          <Label>Get started</Label>
        </Reveal>
        <Reveal index={1}>
          <h2 className="mt-6 max-w-[14ch] text-[clamp(2.6rem,1.6rem+4vw,5.6rem)] font-light leading-[0.98] tracking-[-0.045em] text-fg">
            Gate the next action.
          </h2>
        </Reveal>
        <Reveal index={2}>
          <div className="mt-12 flex flex-wrap items-center gap-8">
            <TrackedLink event="hero_cta" props={{ placement: 'cta' }} href={LINKS.quickstart} className="pill">
              Get Started
            </TrackedLink>
            <TrackedLink event="architecture_click" props={{ placement: 'cta' }} href={LINKS.architecture} className="ghost">
              View Architecture <span aria-hidden="true">&rarr;</span>
            </TrackedLink>
          </div>
        </Reveal>
        <Reveal index={3}>
          <p className="mt-16 max-w-[58ch] text-[14px] leading-relaxed text-dim">
            Releasing soon under the MIT licence. Until then the documentation,
            the whitepaper and the list of known gaps are the most direct way in.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
