'use client';

import { useState } from 'react';
import { track } from '@/lib/analytics';
import { CodeBlock } from './CodeBlock';

/**
 * Three ways in, one gate. The state column is the point: whichever surface
 * is selected, the gate, contract and chain rows do not change.
 */
const SURFACES = {
  sdk: {
    label: 'SDK',
    where: 'in-process',
    title: 'python',
    code: `from causalmesh import CausalMesh, Tool

mesh = CausalMesh.from_config("causalmesh.yaml")
mesh.register_tool(Tool(name="write_file", handler=write_file, mutating=True))

result = mesh.execute(agent_id="coding-agent", tool="write_file",
                      arguments={"path": "src/example.py", "content": "..."})`,
  },
  serve: {
    label: 'SERVE',
    where: '127.0.0.1:8420',
    title: 'shell',
    code: `# gate-and-record endpoint; point any OpenAI-compatible client here
$ causalmesh serve --port 8420

# optionally forward allowed calls upstream
$ causalmesh serve --upstream https://api.openai.com`,
  },
  hook: {
    label: 'HOOK',
    where: 'PreToolUse',
    title: 'shell',
    code: `# a harness hook pipes each action to the gate and branches on exit code
$ echo '{"agent_id": "claude-code", "kind": "path", "name": "src/app.py"}' \\
    | causalmesh policy check --stdin --json

# exit 0 allowed, 1 refused. docs/examples/claude-pretooluse.sh wires it in.`,
  },
} as const;

type Key = keyof typeof SURFACES;

export function EntrySurfaces() {
  const [key, setKey] = useState<Key>('sdk');
  const surface = SURFACES[key];

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
      <div className="min-w-0">
        <div role="tablist" aria-label="Entry surface" className="flex border-b border-line">
          {(Object.keys(SURFACES) as Key[]).map((k) => (
            <button
              key={k}
              role="tab"
              type="button"
              id={`surface-${k}`}
              aria-selected={key === k}
              aria-controls="surface-panel"
              onClick={() => {
                setKey(k);
                track('demo_interaction', { demo: 'entry_surface', surface: k });
              }}
              className={`-mb-px min-h-[44px] border-b px-4 font-code text-[12px] uppercase tracking-[0.1em] transition-colors duration-300 ${
                key === k ? 'border-fg text-fg' : 'border-transparent text-dim hover:text-fg-2'
              }`}
            >
              {SURFACES[k].label}
            </button>
          ))}
        </div>
        <div id="surface-panel" role="tabpanel" aria-labelledby={`surface-${key}`} className="mt-4">
          <CodeBlock key={key} title={surface.title} code={surface.code} copyId={`entry_${key}`} />
        </div>
      </div>

      <div className="panel self-start">
        <div className="panel-head">State</div>
        <dl className="divide-y divide-line font-code text-[12px]">
          {[
            ['surface', surface.label.toLowerCase(), true],
            ['listens', surface.where, true],
            ['gate', 'ContractGate', false],
            ['contract', 'causalmesh.yaml', false],
            ['records to', 'signed chain', false],
          ].map(([k, v, changes]) => (
            <div key={k as string} className="flex items-center justify-between gap-4 px-4 py-3">
              <dt className="text-dim">{k}</dt>
              <dd className={`truncate ${changes ? 'text-fg' : 'text-muted'}`}>{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
