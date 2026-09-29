# Brief: 45-second CausalMesh launch film

Two instructions from the project owner, merged. The original showreel
brief, verbatim:

> make a dynamic 45-second motion graphics video that shows what an
> incredible motion designer you are, like it's your showreel for a
> resume. go all out

A second instruction supplied the *technique* for how to shoot it — an
Apple-keynote-style continuous take (one shape morphing into the next,
no cuts, no fades) with liquid-glass UI treatment, iris transitions, and
a hard beat-synced structure. That technique is adopted here in service
of the first brief's subject and constraints: the film is still about
CausalMesh, still built on this project's existing hyperframes/GSAP
toolchain, and still bound by AGENTS.md. The second brief's own subject
matter — a generic one-word brand wordmark, product photos, an
e-commerce order flow, a wall-hung print — does not apply and is not
used; only its shooting technique carries over.

## Reading of the brief

- **Length:** 45 seconds, not approximately. `meta`, `shot-plan.json`,
  the root composition duration and the rendered MP4 must all agree.
- **Format:** 1920x1080, 16:9. (Supersedes the earlier 1080x1920 9:16
  shot-plan and `index.html` viewport — both need updating to match.)
- **Purpose:** a showreel that also reads as a launch film. Each beat
  demonstrates a different motion-design skill, so the piece shows range
  and craft, not one effect repeated. Aim for kinetic typography, shape
  and path morphing, data and chart animation, 3D or parallax depth,
  masked and zoom-through transitions, particle or grid systems, easing
  variety, and a designed end card — shot as one continuous take.
- **Subject:** CausalMesh. The film's material is the product's own
  ideas: information versus enforcement, the signed hash chain, claims
  and leases, the gate, the four arms C0-C3. Use them as motion subject
  matter. There is no brand wordmark to invent, no product photography,
  no order flow, no wall art — CausalMesh already has a name, a mark
  (`frontend/components/layout/BrandMark.tsx`), and real on-screen
  material (the site's copy, a real policy-check verdict, a real signed
  chain). Use those, not placeholders.
- **Quality bar:** deliberate rhythm (fast and slow beats, holds that
  let a shot land, but per the shooting technique below no held frame
  drifts past its beat), consistent type and colour system, motion that
  is synced to the music and sfx in `assets/`, no dead frames, no
  overlapping or clipped text, legible at 1080p.

## Shooting technique (adopted from the second brief)

Apply these as the *how*, not the *what* — CausalMesh content, not a
generic brand:

- **One continuous take.** No hard cuts, no crossfades, no blur-ins, no
  brightness "developing" transitions, no 3D flips, no particle
  dissolves. Every scene is made out of the shape the previous scene
  left behind: text rises out of a mask line, icons pop from zero on a
  spring, bars draw across, panels push, or a shape floods the frame and
  contracts into the next scene. This project's existing
  `zoom-through-transition` and `whip-pan-cut` components already follow
  this discipline (one strip carrying both scenes) — extend that pattern
  to the new scenes rather than introducing an actual cut.
- **Iris transitions** as a recurring punctuation device (open and
  close), built from a small number of blades around a shared aperture,
  matched at open and close so the film can loop cleanly if needed.
- **Liquid-glass panels** for UI surfaces that need to look like real
  interface chrome (the terminal panel, the chain cards, the gate
  readout): a background clone behind the glass element, sampled through
  an SVG displacement map, with a rim light — not a flat blur. Chromium
  misreads `backdrop-filter: url(...)` against SVG filters, so clone the
  background layer instead of relying on native backdrop-filter for this
  effect.
- **Springs, not eased tweens, for anything with weight** — icons
  popping in, the mark assembling, panels landing. GSAP's built-in
  elastic/back eases are acceptable here since the project is GSAP-based
  (the second brief's closed-form spring-step math was written for a
  from-scratch canvas renderer this project doesn't use).
- **A cursor-driven UI moment** somewhere in the film (a click, drag, or
  long-press against a real on-screen control) if it serves a beat — not
  mandatory everywhere, unlike the second brief's every-beat cursor.
- **Bans carried over as-is:** no crossfades, no blur-ins, no brightness
  "developing," no 3D flips (the diagram's 3D tilt-up is a perspective
  transform, not a flip, and stays), no generic template feel, no held
  frame longer than ~1s without a beat-motivated reason.

## Beat map

The music bed (`assets/music/happy-beats-business-moves-vol-9-by-ende-dot-app.mp3`)
is ~120 BPM, giving a 0.5s beat and roughly 90 beats across 45s. The
existing `assets/audio-data.js` only carries measured per-frame band
energy for the first 15s (450 frames @ 30fps) — that's what the current
shot-plan's beat list (`[1.07, 1.59, ... 12.65]`) was extracted from.

**Before the 45s render can be beat-accurate past 0:15, `audio-data.js`
must be regenerated** by extending/looping the music bed to the full 45s
and re-running the `hyperframes-creative extract-audio-data.py`
extraction against it. Until that happens, the beat grid for 0:15–0:45
in `shot-plan.json` is a tempo-computed placeholder (every 0.5s from a
120 BPM assumption), not a measured one, and is marked as such. Treat it
as provisional; re-verify against the regenerated audio data before
finishing the render.

## Non-negotiable project rules (AGENTS.md)

- Do not claim anything about real agent behaviour or results. Every run
  so far used a deterministic mock agent. No benchmark numbers, no
  customers, no quotes, no performance claims. Every on-screen statement
  must be traceable to `README.md` or `docs/`.
- Terminal-style text on screen is ASCII.
- `npm run check` must pass with no errors, and the final render must be
  opened and inspected frame by frame at the shot boundaries.

## Open follow-ups

1. Regenerate `assets/audio-data.js` for the full 45s bed (see Beat map).
2. Rework `index.html` from 1080x1920 to 1920x1080 and extend the GSAP
   timeline from 15s to 45s with the new scenes in `shot-plan.json`.
3. Author the two new hand-built mechanisms the shooting technique
   needs and the current component library doesn't have: an iris-blade
   transition component, and a liquid-glass panel component (SVG
   displacement clone + rim light). Both go in `compositions/components/`
   and register in `hyperframes.json` / `hyperframes.lock.json` like the
   existing eight.
