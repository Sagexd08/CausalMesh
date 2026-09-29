/**
 * Everything the site states as fact, in one place, with where it came from.
 *
 * Nothing here is illustrative. Verdicts are the JSON that
 * `causalmesh policy check` returned against this repository's own
 * `causalmesh.yaml`. The trace is the signed chain of one real pilot run,
 * `pilot_landing__concurrent_edit_collision__C3__r0000`. Measured results
 * come from `lib/landing/results.json`, which `scripts/export_results.py`
 * generates. If a value here changes, it is because the thing it was copied
 * from changed.
 */
import results from '@/lib/landing/results.json';

export const RESULTS = results;
export type ArmId = 'C0' | 'C1' | 'C2' | 'C3';

export const LINKS = {
  quickstart: '/docs/quickstart',
  docs: '/docs',
  whitepaper: '/whitepaper',
  architecture: '#architecture',
  backlog: 'https://github.com/Sagexd08/CausalMesh/blob/main/docs/backlog.md',
  security: 'https://github.com/Sagexd08/CausalMesh/blob/main/docs/security.md',
  adoption: 'https://github.com/Sagexd08/CausalMesh/blob/main/docs/adoption.md',
};

export const NAV = [
  { label: 'About', href: '#architecture' },
  { label: 'Features', href: '#system' },
  { label: 'FAQ', href: '#faq' },
  { label: 'Contact', href: '#contact' },
] as const;

/** Clients the endpoint speaks to. The claim is the protocol, not a partnership. */
export const STRIP = ['Claude Code', 'Codex', 'Cursor', 'OpenCode'] as const;

/* --------------------------------------------------------------------- */
/* 01 Gate: real verdicts from `causalmesh policy check --json`.          */
/* --------------------------------------------------------------------- */

export type VerdictExample = {
  agent: string;
  kind: 'path' | 'budget' | 'endpoint' | 'spend';
  name: string;
  amount?: string;
  allowed: boolean;
  rule: string;
  holder: string | null;
  reason: string;
};

export const VERDICTS: VerdictExample[] = [
  {
    agent: 'docs',
    kind: 'path',
    name: 'src/causalmesh/crypto/chain.py',
    allowed: false,
    rule: 'ownership',
    holder: 'substrate',
    reason: "'src/causalmesh/crypto/chain.py' is owned by 'substrate', not 'docs'",
  },
  {
    agent: 'substrate',
    kind: 'path',
    name: 'src/causalmesh/crypto/chain.py',
    allowed: true,
    rule: 'default-allow',
    holder: null,
    reason: 'no rule refuses this',
  },
  {
    agent: 'interface',
    kind: 'budget',
    name: 'tokens',
    amount: '500000',
    allowed: false,
    rule: 'budget',
    holder: null,
    reason: "500000 -> tokens would take 'interface' to 500000 against a limit of 400000",
  },
  {
    agent: 'reviewer',
    kind: 'path',
    name: 'README.md',
    allowed: false,
    rule: 'ownership',
    holder: 'docs',
    reason: "'README.md' is owned by 'docs', not 'reviewer'",
  },
];

/** The repository's own contract, summarised from causalmesh.yaml. */
export const CONTRACT = {
  version: 1,
  roles: 6,
  arm: 'C3',
  contested: 3,
  tokenBudget: '400,000',
  sign: true,
  verifyOnExit: true,
};

/* --------------------------------------------------------------------- */
/* 02 Tool boundary: TOOL_NAMES, eleven operations, pinned by a test.     */
/* --------------------------------------------------------------------- */

export const TOOLS: Array<{ name: string; group: 'read' | 'write' | 'run' }> = [
  { name: 'read_file', group: 'read' },
  { name: 'list_files', group: 'read' },
  { name: 'git_status', group: 'read' },
  { name: 'git_diff', group: 'read' },
  { name: 'write_file', group: 'write' },
  { name: 'create_file', group: 'write' },
  { name: 'modify_file', group: 'write' },
  { name: 'delete_file', group: 'write' },
  { name: 'rename_file', group: 'write' },
  { name: 'run_command', group: 'run' },
  { name: 'run_tests', group: 'run' },
];

export const RESOURCE_KINDS = [
  ['path', 'a file', 'measured'],
  ['spend', 'money leaving the account', 'built'],
  ['endpoint', 'a network destination', 'built'],
  ['budget', 'tokens, seconds, bytes', 'built'],
] as const;

/* --------------------------------------------------------------------- */
/* 05 Evidence: the signed chain of one real C3 pilot run.                */
/* --------------------------------------------------------------------- */

export const TRACE_RUN = 'pilot_landing__concurrent_edit_collision__C3__r0000';

export const TRACE: Array<{
  t: string;
  seq: number;
  type: 'READ' | 'WRITE' | 'FAILURE';
  agent: string;
  path: string;
  detail: string;
  outcome: 'executed' | 'denied';
  hash: string;
}> = [
  {
    t: '+0.000',
    seq: 0,
    type: 'READ',
    agent: 'agent_a',
    path: 'src/config.py',
    detail: 'read_file',
    outcome: 'executed',
    hash: '0c75065597',
  },
  {
    t: '+0.000',
    seq: 1,
    type: 'READ',
    agent: 'agent_b',
    path: 'src/config.py',
    detail: 'read_file',
    outcome: 'executed',
    hash: '1f1c3ea9dd',
  },
  {
    t: '+1.000',
    seq: 2,
    type: 'WRITE',
    agent: 'agent_a',
    path: 'src/config.py',
    detail: 'write_file 301 B',
    outcome: 'executed',
    hash: 'c7a0cfc7c6',
  },
  {
    t: '+2.000',
    seq: 3,
    type: 'FAILURE',
    agent: 'agent_b',
    path: 'src/config.py',
    detail: "write_file held by 'agent_a'",
    outcome: 'denied',
    hash: 'e3c6c935a1',
  },
];

export const TRACE_SUMMARY = {
  events: 4,
  denials: 1,
  coordinationBytes: 196,
  appendP50us: 254,
  appendP99us: 352,
  hookP50us: 4,
  hookP99us: 9,
  headHash: 'e3c6c935a1da9f74cfa0d915e398a4f4a68d06e6c9f04a815412bc9463cafb38',
  keyRing: 'd06c764fc1b9e989',
  outcome: 'integration tests failed (exit code 1)',
  claims: [
    { path: 'src/alpha.py', holder: 'agent_a' },
    { path: 'src/config.py', holder: 'agent_a' },
    { path: 'src/beta.py', holder: 'agent_b' },
  ],
  denial:
    "write to 'src/config.py' denied: held by 'agent_a' until 1700000120000000 (claim ..._agent_a_1)",
};

/* --------------------------------------------------------------------- */
/* Arms                                                                  */
/* --------------------------------------------------------------------- */

export const ARMS: Array<{ id: ArmId; name: string; information: string; enforcement: string }> = [
  { id: 'C0', name: 'Isolated', information: 'none', enforcement: 'none' },
  { id: 'C1', name: 'Transcript', information: 'unbounded', enforcement: 'none' },
  { id: 'C2', name: 'Metadata', information: 'bounded', enforcement: 'none' },
  { id: 'C3', name: 'Metadata + claims', information: 'bounded', enforcement: 'write claims' },
];

/* --------------------------------------------------------------------- */
/* Research index. Dates are each document's last commit.                */
/* --------------------------------------------------------------------- */

export const RESEARCH = [
  {
    date: '2026-09-15',
    category: 'PAPER',
    title: 'Separating information from enforcement',
    description:
      'The whitepaper: four arms, two factors, what the substrate guarantees, and the measured pilot.',
    href: '/whitepaper',
  },
  {
    date: '2026-09-15',
    category: 'EXPERIMENT',
    title: 'The four contrasts',
    description:
      'Which comparison isolates which factor, and the one that deliberately does not.',
    href: '/docs/concepts/contrasts',
  },
  {
    date: '2026-09-15',
    category: 'EVIDENCE',
    title: 'The evidence model',
    description: 'What is recorded, what is immutable, and what "verifiable" means precisely.',
    href: '/docs/concepts/evidence-model',
  },
  {
    date: '2026-09-15',
    category: 'CHAIN',
    title: 'Signed chain',
    description: 'Canonicalization, Ed25519 attribution, and the adversarial battery.',
    href: '/docs/subsystems/signed-chain',
  },
  {
    date: '2026-09-15',
    category: 'CLAIMS',
    title: 'Claim registry',
    description:
      'Transactional write leases, and the measurement defect that made enforcement invisible.',
    href: '/docs/subsystems/claim-registry',
  },
  {
    date: '2026-09-15',
    category: 'BOUNDARY',
    title: 'Tool boundary',
    description: 'Eleven controlled operations, no shell, every call gated and recorded.',
    href: '/docs/subsystems/tool-boundary',
  },
  {
    date: '2026-09-15',
    category: 'LIMITS',
    title: 'Limitations',
    description: 'What is not built, what is not proven, and what this project refuses to claim.',
    href: '/docs/limitations',
  },
];

/* --------------------------------------------------------------------- */
/* FAQ                                                                   */
/* --------------------------------------------------------------------- */

export const FAQ = [
  {
    q: 'Does CausalMesh make agents better at their task?',
    a: 'It makes no claim about that. Every run so far used a deterministic mock agent, which proves the machinery measures correctly and says nothing about how a model behaves. The pilot shows the substrate works; it estimates no effect.',
  },
  {
    q: 'What does the gate actually refuse?',
    a: 'Four kinds of resource, closed deliberately: a file path, money leaving the account, a network endpoint, and a consumable budget. A refusal is returned as data with the rule that fired and the holder or limit involved, and it is recorded, not thrown.',
  },
  {
    q: 'Can I check the evidence without trusting you?',
    a: 'Yes. `causalmesh verify` checks a chain offline, on a machine that never ran it, with the system shut down. The chain is bit-reproducible: hostnames, wall-clock time and random ids live outside the signature.',
  },
  {
    q: 'How do I put it in front of an agent I already run?',
    a: 'Three ways. Call `mesh.execute()` from Python, point an OpenAI-compatible client at `causalmesh serve`, or wire `causalmesh policy check --stdin` into a harness hook. The repository ships a Claude Code PreToolUse adapter as an example.',
  },
  {
    q: 'What does it cost to install?',
    a: 'Python 3.11 or newer. The runtime core depends on `cryptography` for Ed25519, `PyYAML` for the contract, and `typer` and `rich` for the CLI. The analysis stack and the FastAPI server are separate extras.',
  },
  {
    q: 'What is not built yet?',
    a: 'It is written down. `docs/backlog.md` takes an entry for every gap with its reason, including the ones that make a result look better than it is. On Windows, process isolation is separation rather than a filesystem jail, and the docs say so.',
  },
];
