import { ClaimReplay } from '@/components/system/ClaimReplay';
import { EntrySurfaces } from '@/components/system/EntrySurfaces';
import { ExecutionTrace } from '@/components/system/ExecutionTrace';
import { Metric, MetricCell, MetricGrid } from '@/components/system/Panel';
import { ToolRegistry } from '@/components/system/ToolRegistry';
import { VerdictConsole } from '@/components/system/VerdictConsole';
import { Reveal } from '@/components/ui/Reveal';
import { Section, SectionHead } from '@/components/ui/Section';
import { CONTRACT, RESOURCE_KINDS, RESULTS } from '@/lib/site/content';

/**
 * 01 to 05: one machine, shown a part at a time. Each section is a claim
 * and the surface that proves it, and every surface is built from a real
 * artifact rather than a mock-up of one.
 */

export function GateSection() {
  return (
    <Section id="system">
      <div className="grid grid-cols-1 gap-x-16 gap-y-12 lg:grid-cols-[0.8fr_1.2fr] lg:items-end">
        <SectionHead index="01 / Gate" title="Every action passes one gate.">
          A contract declares who may write what, spend what, and call where.
          The gate answers with a Verdict, returned rather than raised, naming
          the rule that fired and the holder or limit involved. These four are
          this repository&rsquo;s own contract, checked by the real CLI.
        </SectionHead>
        <Reveal index={2}>
          <MetricGrid className="sm:grid-cols-4">
            <MetricCell><Metric label="Roles" value={CONTRACT.roles} unit="declared" /></MetricCell>
            <MetricCell><Metric label="Arm" value={CONTRACT.arm} unit="enforcing" /></MetricCell>
            <MetricCell><Metric label="Contested" value={CONTRACT.contested} unit="exclusive" /></MetricCell>
            <MetricCell><Metric label="Token budget" value={CONTRACT.tokenBudget} /></MetricCell>
          </MetricGrid>
        </Reveal>
      </div>
      <Reveal index={1} className="mt-14">
        <VerdictConsole />
      </Reveal>
    </Section>
  );
}

export function ToolsSection() {
  return (
    <Section id="tools">
      <div className="grid grid-cols-1 gap-x-16 gap-y-12 lg:grid-cols-[0.8fr_1.2fr]">
        <div>
          <SectionHead index="02 / Tool boundary" title="Give agents tools, not trust.">
            An agent gets eleven operations and nothing else. There is no shell:
            commands are argument lists checked against an allowlist, the
            environment is scrubbed, and every path must resolve inside the
            workspace. Anything the gate can refuse is one of four resource kinds.
          </SectionHead>
          <Reveal index={3}>
            <table className="mt-12 w-full border-t border-line font-code text-[12.5px]">
              <caption className="sr-only">Resource kinds the gate can refuse</caption>
              <tbody>
                {RESOURCE_KINDS.map(([kind, what, status]) => (
                  <tr key={kind} className="border-b border-line">
                    <th scope="row" className="py-3.5 pr-4 text-left font-normal text-fg">{kind}</th>
                    <td className="py-3.5 pr-4 font-site text-[14px] text-muted">{what}</td>
                    <td className="py-3.5 text-right text-[11px] uppercase tracking-[0.1em] text-dim">{status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Reveal>
        </div>
        <Reveal index={2}>
          <ToolRegistry />
        </Reveal>
      </div>
    </Section>
  );
}

export function ClaimsSection() {
  const c1 = RESULTS.arms.find((a) => a.arm === 'C1')!.mean_coordination_bytes;
  const c2 = RESULTS.arms.find((a) => a.arm === 'C2')!.mean_coordination_bytes;
  const saving = Math.round(((c1 - c2) / c1) * 100);

  return (
    <Section id="claims">
      <div className="grid grid-cols-1 gap-x-16 gap-y-12 lg:grid-cols-[0.8fr_1.2fr]">
        <div>
          <SectionHead index="03 / Claims" title="Agents share a repository. Not a file.">
            One exclusive write lease per path, issued and renewed
            transactionally. A second writer is refused with the holder&rsquo;s
            name and the lease&rsquo;s expiry, and the refusal enters the chain
            like any other event. Peers learn what changed through bounded,
            typed metadata instead of a transcript.
          </SectionHead>
          <Reveal index={3}>
            <MetricGrid className="mt-12">
              <MetricCell><Metric label="Transcript (C1)" value={Math.round(c1)} unit="B / run" /></MetricCell>
              <MetricCell>
                <Metric label="Metadata (C2, C3)" value={Math.round(c2)} unit="B / run" note={`${saving}% less than the transcript`} />
              </MetricCell>
            </MetricGrid>
          </Reveal>
        </div>
        <Reveal index={2}>
          <ClaimReplay />
        </Reveal>
      </div>
    </Section>
  );
}

export function EntrySection() {
  return (
    <Section id="entry">
      <SectionHead
        index="04 / Entry surfaces"
        title="Put the gate in front of the agent you already run."
        className="max-w-[760px]"
      >
        Call it from Python, point an OpenAI-compatible client at it, or wire it
        into a harness hook. The surface changes; the gate, the contract and
        the chain do not. Nothing about the agent has to be rewritten.
      </SectionHead>
      <Reveal index={1} className="mt-14">
        <EntrySurfaces />
      </Reveal>
    </Section>
  );
}

export function EvidenceSection() {
  return (
    <Section id="evidence">
      <SectionHead index="05 / Evidence" title="Observe every execution. Verify it anywhere." className="max-w-[820px]">
        Every event is signed with the acting agent&rsquo;s Ed25519 key and
        linked to the one before it. The chain is bit-reproducible, so a
        second machine that never ran the collection can check it offline.
        Below is one real run, including the fact that its task failed.
      </SectionHead>
      <Reveal index={1} className="mt-14">
        <ExecutionTrace />
      </Reveal>
    </Section>
  );
}
