import { ArchitectureDiagram } from '@/components/system/ArchitectureDiagram';
import { Reveal } from '@/components/ui/Reveal';
import { Section, SectionHead } from '@/components/ui/Section';

const FLOW = [
  ['Input', 'a tool call from any agent'],
  ['Process', 'one gate, one contract'],
  ['State', 'a Verdict, a lease, a ledger entry'],
  ['Output', 'a signed event, allowed or refused'],
];

export function Architecture() {
  return (
    <Section id="architecture" className="border-t-0 pt-28 md:pt-40">
      <div className="grid grid-cols-1 gap-x-16 gap-y-14 lg:grid-cols-[0.85fr_1.15fr]">
        <div>
          <SectionHead
            index="00 / Architecture"
            title={
              <>
                One infrastructure layer.
                <br />
                <span className="text-muted">Every execution surface.</span>
              </>
            }
          >
            An agent reaches the world through tools. CausalMesh sits on that
            path, and only there. Whichever way a call arrives, it crosses the
            same boundary, is decided by the same gate, and lands in the same
            signed chain. The only branch is whether the handler runs.
          </SectionHead>

          <Reveal index={3}>
            <ol className="mt-12 border-t border-line">
              {FLOW.map(([k, v], i) => (
                <li key={k} className="grid grid-cols-[28px_92px_1fr] items-baseline gap-3 border-b border-line py-3.5">
                  <span className="font-code text-[11px] text-faint">0{i + 1}</span>
                  <span className="label !text-fg-2">{k}</span>
                  <span className="text-[14px] text-muted">{v}</span>
                </li>
              ))}
            </ol>
          </Reveal>
        </div>

        <Reveal index={2}>
          <ArchitectureDiagram />
        </Reveal>
      </div>
    </Section>
  );
}
