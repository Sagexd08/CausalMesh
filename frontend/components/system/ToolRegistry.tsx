'use client';

import { useState } from 'react';
import { track } from '@/lib/analytics';
import { TOOLS } from '@/lib/site/content';

const GROUP_NOTE = {
  read: 'Recorded. Every path resolves through realpath and must stay inside the workspace.',
  write: 'Gated. Ownership from the contract and an exclusive claim on the path, or a recorded refusal.',
  run: 'Argument list, never a shell string. Allowlist: python, pytest, git. Environment scrubbed.',
} as const;

/** The eleven operations an agent gets, as the tree it actually sees. */
export function ToolRegistry() {
  const [selected, setSelected] = useState('write_file');
  const tool = TOOLS.find((t) => t.name === selected) ?? TOOLS[0];

  return (
    <div className="panel overflow-hidden">
      <div className="panel-head">
        <span>Tool registry</span>
        <span className="text-dim">TOOL_NAMES &middot; pinned by test</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr]">
        <div className="border-b border-line p-5 font-code text-[12.5px] leading-[1.9] sm:border-b-0 sm:border-r">
          <div className="text-fg">agent</div>
          <ul>
            {TOOLS.map((t, i) => {
              const last = i === TOOLS.length - 1;
              const on = t.name === selected;
              return (
                <li key={t.name}>
                  <button
                    type="button"
                    onClick={() => {
                      setSelected(t.name);
                      track('demo_interaction', { demo: 'tool_registry', tool: t.name });
                    }}
                    aria-pressed={on}
                    className="group flex w-full items-center text-left"
                  >
                    <span className="select-none whitespace-pre text-faint">{last ? '└── ' : '├── '}</span>
                    <span className={`transition-colors duration-300 ${on ? 'text-fg' : 'text-muted group-hover:text-fg-2'}`}>
                      {t.name}
                    </span>
                    <span className={`ml-auto text-[10.5px] uppercase tracking-[0.1em] ${on ? 'text-fg-2' : 'text-faint'}`}>
                      {t.group}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
        <div className="flex flex-col p-5" aria-live="polite">
          <div className="label">Selected</div>
          <div className="mt-2 font-code text-[15px] text-fg">{tool.name}</div>
          <p className="mt-3 text-[13.5px] leading-relaxed text-muted">{GROUP_NOTE[tool.group]}</p>
          <div className="mt-auto grid grid-cols-3 gap-4 border-t border-line pt-5">
            {(['read', 'write', 'run'] as const).map((g) => (
              <div key={g}>
                <div className="label">{g}</div>
                <div className="tabular mt-1 text-[22px] font-light text-fg">
                  {TOOLS.filter((t) => t.group === g).length}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
