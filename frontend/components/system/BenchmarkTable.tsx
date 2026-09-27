'use client';

import { useState } from 'react';
import { track } from '@/lib/analytics';
import { ARMS, RESULTS, type ArmId } from '@/lib/site/content';

type TaskFilter = 'all' | keyof typeof RESULTS.tasks;

const TASKS: Array<[TaskFilter, string]> = [
  ['all', 'All tasks'],
  ['concurrent_edit_collision', 'concurrent_edit_collision'],
  ['schema_handler_widen', 'schema_handler_widen'],
];

/**
 * The pilot collection, as measured. Filtering to one task narrows the
 * columns the export records per task (runs, successes); the rest are
 * shown as unknown rather than zero, because the export does not break
 * them down and a confident zero would be a fabrication.
 */
export function BenchmarkTable() {
  const [task, setTask] = useState<TaskFilter>('all');

  const row = (id: ArmId) => {
    const arm = RESULTS.arms.find((a) => a.arm === id)!;
    if (task === 'all') {
      return {
        runs: arm.runs,
        success: arm.successes,
        denials: String(arm.denials),
        bytes: String(Math.round(arm.mean_coordination_bytes)),
        verified: `${arm.chains_verified}/${arm.runs}`,
      };
    }
    const cell = RESULTS.tasks[task][id];
    return { runs: cell.runs, success: cell.success, denials: 'unknown', bytes: 'unknown', verified: 'unknown' };
  };

  return (
    <div className="panel overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <span className="label">
          {RESULTS.experiment_id} &middot; {RESULTS.total_runs} runs
        </span>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by task">
          {TASKS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-pressed={task === id}
              onClick={() => {
                setTask(id);
                track('benchmark_filter', { task: id });
              }}
              className={`min-h-[32px] rounded-full px-3 font-code text-[11px] transition-colors duration-300 ${
                task === id ? 'bg-white/10 text-fg' : 'text-dim hover:text-fg-2'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-left font-code text-[12.5px]">
          <thead>
            <tr className="text-[10.5px] uppercase tracking-[0.1em] text-dim">
              {['Arm', 'Information', 'Enforcement', 'Runs', 'Succeeded', 'Denials', 'Coord bytes / run', 'Chains verified'].map(
                (h, i) => (
                  <th key={h} scope="col" className={`border-b border-line px-4 py-3 font-normal ${i >= 3 ? 'text-right' : ''}`}>
                    {h}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {ARMS.map((arm) => {
              const r = row(arm.id);
              return (
                <tr key={arm.id} className="border-b border-line last:border-0">
                  <th scope="row" className="px-4 py-4 font-normal">
                    <span className="text-fg">{arm.id}</span>
                    <span className="ml-3 font-site text-[13px] text-muted">{arm.name}</span>
                  </th>
                  <td className="px-4 py-4 text-muted">{arm.information}</td>
                  <td className="px-4 py-4 text-muted">{arm.enforcement}</td>
                  <td className="tabular px-4 py-4 text-right text-fg-2">{r.runs}</td>
                  <td className="tabular px-4 py-4 text-right text-fg">{r.success}</td>
                  <Num value={r.denials} deny />
                  <Num value={r.bytes} />
                  <Num value={r.verified} />
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Num({ value, deny = false }: { value: string; deny?: boolean }) {
  const unknown = value === 'unknown';
  return (
    <td
      className={`tabular px-4 py-4 text-right ${
        unknown ? 'text-faint' : deny && value !== '0' ? 'text-deny' : 'text-fg-2'
      }`}
    >
      {value}
    </td>
  );
}
