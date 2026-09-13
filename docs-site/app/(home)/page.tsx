import Link from 'next/link';

const ENTRY = [
  ['Quickstart', 'Install, run a smoke collection, verify the chains.', '/docs/quickstart'],
  ['The question', 'Information versus enforcement, and why they are hard to separate.', '/docs/concepts/the-question'],
  ['Measured results', 'A real 24-run pilot, and what each row shows.', '/docs/results'],
  ['Limitations', 'What is not built, not proven, and not claimed.', '/docs/limitations'],
];

export default function HomePage() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-6 py-20">
      <p className="font-mono text-xs uppercase tracking-[0.18em] text-fd-muted-foreground">
        Documentation
      </p>

      <h1 className="mt-5 text-4xl font-semibold tracking-tight sm:text-5xl">
        CausalMesh
      </h1>

      <p className="mt-5 max-w-[54ch] text-fd-muted-foreground">
        A coordination substrate for fleets of autonomous coding agents, with
        cryptographically verifiable evidence of everything every agent did —
        and an experiment that separates what information buys from what
        enforcement buys.
      </p>

      <div className="mt-8 flex flex-wrap gap-3">
        <Link
          href="/docs"
          className="rounded-md bg-fd-primary px-5 py-2.5 text-sm font-medium text-fd-primary-foreground transition-opacity hover:opacity-90"
        >
          Read the docs
        </Link>
        <Link
          href="https://github.com/Sagexd08/CausalMesh"
          className="rounded-md border border-fd-border px-5 py-2.5 text-sm font-medium transition-colors hover:bg-fd-accent"
        >
          Source on GitHub
        </Link>
      </div>

      <div className="mt-14 grid gap-px overflow-hidden rounded-lg border border-fd-border bg-fd-border sm:grid-cols-2">
        {ENTRY.map(([title, blurb, href]) => (
          <Link
            key={href}
            href={href}
            className="group bg-fd-background p-5 transition-colors hover:bg-fd-accent"
          >
            <div className="text-sm font-medium">{title}</div>
            <p className="mt-1.5 text-sm text-fd-muted-foreground">{blurb}</p>
          </Link>
        ))}
      </div>

      <dl className="mt-12 grid grid-cols-2 gap-6 border-t border-fd-border pt-8 sm:grid-cols-4">
        {[
          ['797', 'tests passing'],
          ['24', 'runs executed'],
          ['24/24', 'chains verified'],
          ['0', 'fabricated figures'],
        ].map(([value, label]) => (
          <div key={label}>
            <dt className="sr-only">{label}</dt>
            <dd className="text-2xl font-medium tabular-nums">{value}</dd>
            <dd className="mt-1 text-xs text-fd-muted-foreground">{label}</dd>
          </div>
        ))}
      </dl>
    </main>
  );
}
