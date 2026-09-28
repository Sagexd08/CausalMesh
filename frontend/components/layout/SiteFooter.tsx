import { BrandMark } from './BrandMark';
import { LINKS, RESULTS } from '@/lib/site/content';

/**
 * Minimal, four columns. There is no status page to report on, so the
 * bottom line carries the one status this project can actually vouch for:
 * how many of its recorded chains verify.
 */
const COLUMNS: Array<[string, Array<[string, string | null]>]> = [
  [
    'Product',
    [
      ['Gate', '/#system'],
      ['Tool boundary', '/#tools'],
      ['Claims', '/#claims'],
      ['Entry surfaces', '/#entry'],
    ],
  ],
  [
    'Developers',
    [
      ['Docs', LINKS.docs],
      ['Quickstart', LINKS.quickstart],
      ['SDK', '/#developer'],
      ['GitHub (soon)', null],
    ],
  ],
  [
    'Research',
    [
      ['Whitepaper', LINKS.whitepaper],
      ['Measured results', '/#measured'],
      ['Evidence model', '/docs/concepts/evidence-model'],
      ['Limitations', '/docs/limitations'],
    ],
  ],
  [
    'Project',
    [
      ['About', '/#architecture'],
      ['Security model', LINKS.security],
      ['Known gaps', LINKS.backlog],
      ['Contact', '/#contact'],
    ],
  ],
];

export function SiteFooter() {
  const verified = RESULTS.arms.reduce((n, a) => n + a.chains_verified, 0);

  return (
    <footer className="border-t border-line">
      <div className="mx-auto w-full max-w-[1320px] px-6 pb-10 pt-20 sm:px-10 lg:px-16">
        <div className="grid grid-cols-1 gap-14 lg:grid-cols-[1fr_2fr]">
          <BrandMark className="h-9 w-9 text-fg" />
          <div className="grid grid-cols-2 gap-x-8 gap-y-10 sm:grid-cols-4">
            {COLUMNS.map(([heading, links]) => (
              <nav key={heading} aria-label={heading}>
                <h2 className="label">{heading}</h2>
                <ul className="mt-5 space-y-3">
                  {links.map(([label, href]) => (
                    <li key={label}>
                      {href ? (
                        <a href={href} className="text-[14px] text-muted transition-colors duration-300 hover:text-fg">
                          {label}
                        </a>
                      ) : (
                        <span className="text-[14px] text-faint">{label}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </nav>
            ))}
          </div>
        </div>

        <div className="mt-20 flex flex-col gap-4 border-t border-line pt-6 font-code text-[11.5px] text-dim sm:flex-row sm:items-center sm:justify-between">
          <span className="flex items-center gap-2.5 uppercase tracking-[0.1em]">
            <span aria-hidden="true" className="inline-block h-[6px] w-[6px] rounded-full bg-fg" />
            {verified} / {RESULTS.total_runs} chains verified
          </span>
          <span>MIT licence &middot; Python 3.11+</span>
        </div>
      </div>
    </footer>
  );
}
