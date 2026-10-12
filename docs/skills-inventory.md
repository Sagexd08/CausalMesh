# Skills inventory

Third-party design skills considered for CausalMesh, what was reviewed, and what was
actually used. Written 2026-10-12. Nothing here is installed through an installer; see
"How it was obtained".

## hairline-create (used, vendored)

| Field | Value |
|---|---|
| Source | https://github.com/lucasmarkes/hairline (skill at skills/hairline-create/) |
| License | MIT, Copyright (c) 2026 Lucas Marques (file preserved as LICENSE) |
| Upstream state reviewed | main, last commit 2026-10-08T13:08:09Z (commit SHA not recorded) |
| npm package (not used) | @lucasmarkes/hairline 0.5.0, MIT, no dependencies, no install scripts |
| Vendored at | design/vendor/hairline-create/ |
| Reviewed | 2026-10-12: SKILL.md and build.mjs read in full; validate.mjs, look.mjs and kernel.js swept for process, network, eval and filesystem primitives |

### How it was obtained

The files were downloaded as text and copied in directly. The `npx skills` installer
(npm `skills` 1.7.2, vercel-labs/skills) was NOT run: its metadata was reviewed but its
source was not, so it was not trusted to execute.

### What it does, and what is deliberately not used

- `build.mjs` and `validate.mjs` are used. They read local files, write one HTML file,
  and run `node --check` on a temp copy of the figure that they delete.
- `look.mjs` is **not run**. It executes `npm install playwright-core@1` into a cache
  outside the project (`%LOCALAPPDATA%\hairline-look` on Windows). Figures therefore have
  no browser-sheet check; each is validated structurally only and must be looked at by a
  person before use.
- The validator rejects `fetch`, `XMLHttpRequest`, `WebSocket`, `eval`,
  `new Function`, `import`, `<script>`/`<img>`/`<iframe>`, `localStorage` and
  cookies in a figure, so a figure cannot reach the network.

### Pinned files (SHA-256)

| File | SHA-256 |
|---|---|
| `bench.html` | `0870fd54e137be0f7635cd309b48a4703a791cfca5915bf22d46b941ebc33278` |
| `build.mjs` | `7907c722890a9758ed4b479e819f9f8c12b9df3c4a59fa050577b235eee233e7` |
| `concepts.md` | `af001b0859cb98cfaeb6411dd6a7d815bfde5a9a107954b9aec31b2daeae0d63` |
| `examples/riffle.js` | `f54ee2de62ac4161291dfd0f4c2cb6646e1289adb286cecad23a7356d97cc4d1` |
| `examples/terrain.js` | `7755307a1ddb023ed7e119c5c89e549116f1068f0c0a15b96e692fed5e93014b` |
| `kernel.js` | `2d8be507ceb523581dbfe813f636d1118ca49bf9e62840f66d8ddf55867999ad` |
| `LICENSE` | `948d56f0bc8c383c04c453136dcfb78407f97de65ff8bb4fabff2b79ddd17f59` |
| `look.md` | `d3bc1ae47e4331d39e8c0c589a2439a25bf9e0a09de7dcc653593e0a77e0743e` |
| `look.mjs` | `c7d5c06208ca69982d92df709bf69fd58cbe714b1482d58f5f2ad83ca2612651` |
| `rules.md` | `01c7880d75beac8bb222519c10bda4d44151bdfc17d07563b9b8e2d19fc7de09` |
| `SKILL.md` | `528890cf33862c2b48e5af3b835a0ff5d0d91ce153a70dbc521f743d62542510` |
| `validate.mjs` | `a60ad12271cdf3faf0ee4b84131d2474481ab9196360956ba8383c17928378ff` |

### Update and rollback

Re-download the upstream files, re-read the diff against the hashes above, then replace the
folder and this table together. To roll back, restore the folder from version control.

## emil-design-eng (reviewed, not installed)

- Source: https://github.com/emilkowalski/skills, skill `emil-design-eng`. MIT, Copyright (c) 2026 Emil Kowalski.
- SKILL.md read in full: no shell, no fetches, no writes, no secrets, no installs, no publishing.
- Verdict: looks benign. Not installed; install project-scoped when UI motion work starts.

## frontend-design plugin (reviewed, not installed)

- Source: https://github.com/anthropics/claude-plugins-official, `plugins/frontend-design`. Apache-2.0.
- SKILL.md read in full: instructions only; no scripts, hooks or commands.
- Verdict: looks benign. Not installed.

## Rules that apply to all of these

- A skill guides; it does not override the PRD, tests, privacy rules or approval gates.
- No skill may publish, post, push, change a license or commit generated assets without a human.
- Generated figures are illustrations, never product data.
