# Brag Plan: CausalMesh

Replaces `videos/causalmesh-motion` (the 45s showreel, deleted in the same
change). Made with `/brag`, run with `--tone cinematic --duration 30`, from a
30-second product-film brief.

## What is this app?

The accountability layer underneath AI coding agents: every tool call an agent
makes crosses one gate that checks it against `causalmesh.yaml`, and every
decision, refusals included, is signed and appended to a hash chain you can
verify offline.

## The angle

A technical motion study of one refusal. Two agents reach for the same file;
the gate says no, and says why; that verdict becomes a signed link in a chain.
The film treats the product's own artifacts (a real `policy check` verdict,
the real signed trace of a C3 pilot run, the site's portal) as the design
material. The site already uses one warm colour, `#d2a676`, and only for
refusals. The film keeps that rule: **amber means REFUSE**, and nothing else
on screen is warm.

## Hook (first 2-3 seconds)

Darkness, a fine grid, production metadata. Two hairlines of light travel in
from opposite edges toward one point. Huge type lands in two hits:
**"Two agents."** then **"One file."**, with the real path `src/config.py`
from the pilot run under it. The two lines meet at a node: the gate.

## Key moments (the middle)

- **The gate, typed live.** The site's gate console, rebuilt at video scale.
  The command types out, and **REFUSE** lands in amber with its rule, holder,
  reason and `exit 1`. Then the owner asks the same question and gets
  **ALLOW, exit 0**. Both verdicts are what `causalmesh policy check` returned
  against this repository on 2026-09-30.
- **The verdict becomes evidence.** The console collapses into one event
  block. Three more drop in beside it: the four real events of
  `pilot_landing__concurrent_edit_collision__C3__r0000` (READ, READ, WRITE,
  FAILURE) with their real hash prefixes. The chain tilts into depth while the
  formula `h_i = SHA256(h_(i-1) || canonical(event_i))` writes itself across
  the links.
- **Four properties, four grounds.** Full-bleed colour cards, one per beat
  pair: OWNED (black), LEASED (cream), REFUSED (amber), VERIFIED (black).
  Each carries one real mono detail from the repo.

## Outro / punchline

The portal from the site's hero, slow push-in, with the hero line verbatim:
"The Next Layer of Intelligence". Cut to near-black: the two-bar mark
assembles on the strongest late cue, the name settles, then
**"Gate the next action."** (the site's closing CTA) and
`causalmesh.vercel.app`. Hold.

## User flow worth showing

1. **Entry:** an agent issues a tool call (`write_file` on a path it does not
   own).
2. **Key action:** the gate checks it against `causalmesh.yaml` and refuses,
   with rule, holder, reason and exit code.
3. **Result:** the refusal is recorded as a signed event in the chain,
   alongside the executed writes.

## Tone

- Preset: `cinematic`
- Creative direction: editorial technical motion study. Swiss grid, huge
  cropped type, production-metadata HUD, one warm accent that carries meaning.
- Interpretation: fewer, larger moments. Type is physical: it slams, crops
  past the frame, overshoots and settles, and never simply fades in. The pace
  comes from the cuts and the beat locks, not from rushing the reading. The
  quiet moments (the portal, the end card) are deliberately slow.

## Format: landscape, 1920x1080, 30fps

## Duration: 30s (900 frames)

## Visual identity (from the project)

- Background: `#050505` (`--color-stage`)
- Raised panels: `#0c0c0c` (`--color-stage-panel`)
- Text: `#fafafa` (`--color-fg`), `#d6d5d5` (`--color-fg-2`), `#a7a6a6` (`--color-muted`)
- Lines: `rgb(255 255 255 / .09)` and `/ .16`
- Accent: `#d2a676` (`--color-deny`), used only for refusals
- Display and body font: Manrope (the site's `--font-site`)
- Mono: JetBrains Mono (the site's `--font-code`)
- Strongest visual elements: the portal hero (`hero-poster.jpg`, whose clip is
  the site's hero video), the gate console (`VerdictConsole.tsx`), the
  evidence trace (`TRACE` in `lib/site/content.ts`), the two-bar mark
  (`BrandMark.tsx`)

## Share copy (draft)

CausalMesh. Every agent action gated, signed, and recorded, with every refusal
kept alongside its reason.

## Audio direction

- Role: cinematic support. The music is a steady bed; the SFX are dry and
  sparse, placed on the moments the product acts.
- Music: `happy-beats-business-moves-vol-12-by-ende-dot-app.mp3` (steady,
  clean; 109.96 BPM, beat period ~0.546s)
- Music treatment: fade in over the first ~1.2s under the hook, sit at ~0.34,
  and fade out over the end-card hold so the final frame is almost silent.
- Music cue guidance: bundled preset read
  (`assets/music/cues/...vol-12....music-cues.json`). Strong cues locked:
  **8.74s** (REFUSE lands), **13.11s** (the verdict becomes a chain event),
  **22.93s** (the portal opens), **27.30s** (the mark lands). Beat grid:
  kinetic words at 4.39 / 5.48 / 6.56; capability cards at 18.02 / 19.10 /
  20.19 / 21.28.
- Audio-reactive treatment: subtle. Music RMS drives the gate node's glow and
  the grid's brightness in the intro, and the portal's light bloom in the hero
  shot. No waveform or equalizer graphics.
- SFX posture: sparse and motion-matched, 21 short cues in 30s, most of them quiet (four thinned keypresses, soft drops, one card slide per property card).
- Audio-coupled moments: typed command (key ticks, thinned), the REFUSE stamp
  (soft heavy impact), ALLOW (light click), chain blocks landing (soft drops),
  colour cards (card slides), mark landing (one bell).
- Restraint rule: no stacked hits, no sound on every card or every letter,
  and nothing after the mark's bell except the fading bed.

## Storyboard

### Scene 1: Signal (0.00-4.39s)
Near-black `#050505`, fine 60px grid at low contrast, HUD in the corners
(title, timecode, `ARM C3 · causalmesh.yaml`, `1920x1080 · 30 FPS`),
registration marks. Two hairlines travel from left and right toward a node at
centre-right, labelled `agent_a` and `agent_b`. "Two agents." slams in at
~0.6s. "One file." follows at ~1.64s, with `src/config.py` in mono beneath it.
The lines meet at the node at ~3.27s and the node reads GATE.
Sequential/interaction: yes. Two lines race to one point; two text hits.
Audio intent: tension, low and quiet.
Audio-coupled idea: soft tick on each text hit; the node's glow breathes with RMS.
Transition mood: hard. The node flashes and the frame snaps into huge type.

### Scene 2: Gated. Signed. Recorded. (4.39-7.64s)
Three words from the hero subline, each full-bleed and cropped past the frame
edges, one per two beats: GATED (enters from the right, overshoots, locks),
SIGNED (drops from above through a mask), RECORDED (stretches in from the
left, compresses and settles). Each holds about 0.8s settled. A tiny mono
index `01 / 02 / 03` counts along.
Sequential/interaction: yes. Three words, beat-grid 4.39 / 5.48 / 6.56 (every
other beat, held for reading).
Audio intent: momentum.
Audio-coupled idea: one dry hit per word, the third slightly heavier.
Transition mood: hard. RECORDED's last letter becomes the console's edge.

### Scene 3: The gate (7.64-13.11s)
The gate console from the site at video scale. Left: Requests
(`docs  path:src/causalmesh/policy/gate.py`, and
`causalmesh  path:src/causalmesh/policy/gate.py`). Right: Gate panel, header
`causalmesh.yaml · arm C3`. The command types:
`$ causalmesh policy check --agent docs --kind path --name src/causalmesh/policy/gate.py`.
**REFUSE** stamps in amber at the 8.74s strong cue. Rows land: `rule
ownership`, `holder causalmesh`, `reason 'src/causalmesh/policy/gate.py' is
owned by 'causalmesh', not 'docs'`, `exit 1`. They hold until ~10.9s. At
10.93s the selection moves to the second request and the verdict flips to
**ALLOW**, `default-allow`, `no rule refuses this`, `exit 0`. Hold.
Sequential/interaction: yes. Typing, stamp, rows, selection change.
Audio intent: precise, tactile.
Audio-coupled idea: key ticks (thinned), an impact on REFUSE, a click on the
selection change.
Transition mood: dramatic. At 13.11s the console collapses into one block.

### Scene 4: Chain (13.11-18.02s)
The collapsed verdict becomes an event block. The four real TRACE events lay
out as a row of blocks: `#0 READ agent_a src/config.py 0c75065597`,
`#1 READ agent_b 1f1c3ea9dd`, `#2 WRITE agent_a 301 B c7a0cfc7c6`,
`#3 FAILURE agent_b "held by 'agent_a'" e3c6c935a1` (amber, denied). Links
draw between them. The row tilts into 3D depth with a camera drift, and the
formula `h_i = SHA256( h_(i-1) || canonical(event_i) )` writes across. The
label `Ed25519 · per actor` sits beside it.
Sequential/interaction: yes. Four blocks land on consecutive beats, then the
links draw.
Audio intent: assembling, mechanical.
Audio-coupled idea: a soft drop on each block (first and last emphasised).
Transition mood: hard, on the beat, into the first colour card.

### Scene 5: Properties (18.02-22.93s)
Four full-bleed cards, one per two beats, each a different ground:
- 18.02: **OWNED.** on black, `src/causalmesh/ → causalmesh`
- 19.10: **LEASED.** on cream `#fafafa`, `held by 'agent_a'`
- 20.19: **REFUSED.** on amber `#d2a676`, `kept with the reason`
- 21.28: **VERIFIED.** on black, `offline · from the log alone`, held to 22.93

Each word enters with its own treatment (horizontal snap, vertical mask,
scale-down, tracking collapse).
Sequential/interaction: yes. Four cards on beat-grid pairs, each held.
Audio intent: rhythm.
Audio-coupled idea: a card slide on each card.
Transition mood: dramatic. The black card irises open onto the portal.

### Scene 6: Portal (22.93-27.00s)
The site's hero portal clip, full frame, slow push-in, dark vignette. The hero
title "The Next Layer of Intelligence" rises line by line through masks and
holds. Under it, small mono: `head e3c6c935a1da9f74…` and
`4 events · 1 refusal`, from the same pilot run.
Audio intent: open, breathing.
Audio-coupled idea: the portal's light blooms with RMS.
Transition mood: soft. It fades to near-black.

### Scene 7: Mark (27.00-30.00s)
Near-black. The two slanted bars of the mark slide in from opposite sides and
lock on the 27.30s strong cue. "CausalMesh" settles below it, then
"Gate the next action." and `Get Started · causalmesh.vercel.app`, with the
site's own line: `Releasing soon under the MIT licence.` The final ~1.3s hold
is almost still.
Audio intent: resolve.
Audio-coupled idea: one bell on the mark landing, then the bed fades.

**Music mood for this video:** cinematic, steady
**Audio summary:** a quiet bed that locks the film's four big moments to the
track's strongest beats, with dry tactile accents where the product acts, and
a single bell on the mark.

## Claims deliberately left out

- No success rates, no arm comparisons. The pilot numbers come from a
  deterministic mock agent, and AGENTS.md forbids claims about agent
  behaviour.
- No latency figures (the append/hook p50/p99 values exist, but they come
  from one pilot run on one machine).
- No "available now". The site says "Releasing soon under the MIT licence".
- No "pre-alpha" label. It appears in commit messages, not in the product's
  own docs or site copy.
- No client logos. The site's strip names Claude Code, Codex, Cursor and
  OpenCode as a protocol claim, not a partnership; a 30s film cannot carry
  that nuance, so it is left out.
