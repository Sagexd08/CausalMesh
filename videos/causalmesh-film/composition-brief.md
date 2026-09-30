# Hyperframes Composition Brief: CausalMesh

## Objective
A 30-second cinematic launch film for CausalMesh: a technical motion study of
one refusal. It replaces `videos/causalmesh-motion`.

## Output
- Composition directory: `videos/causalmesh-film/composition/`
- Rendered video: `videos/causalmesh-film/brag.mp4`
- Format: landscape, 1920x1080, 30 fps
- Duration: 30s (900 frames). The user's brief asked for 30s, which overrides
  /brag's 15-25s default.

## Source Material
- Project root: repository root
- Primary files read: `README.md`, `causalmesh.yaml`,
  `frontend/app/page.tsx`, `frontend/app/site.css`,
  `frontend/lib/site/content.ts`, `frontend/components/marketing/Hero.tsx`,
  `frontend/components/marketing/SystemSections.tsx`,
  `frontend/components/marketing/ClosingSections.tsx`,
  `frontend/components/system/VerdictConsole.tsx`,
  `frontend/components/layout/BrandMark.tsx`, `frontend/app/layout.tsx`
- Product name: CausalMesh
- Tagline: "The Next Layer of Intelligence" (hero), "Gate the next action." (CTA)
- Key UI to recreate: the gate console (`VerdictConsole.tsx`) and the evidence
  trace (`TRACE` in `content.ts`)
- Copy that must appear verbatim:
  - "Every action gated, signed, and recorded" (split into kinetic words)
  - "Every action passes one gate." (section 01 title)
  - "Observe every execution. Verify it anywhere." (section 05 title)
  - "The Next Layer of Intelligence"
  - "Gate the next action."
  - "Releasing soon under the MIT licence."
- Live CLI output captured for this film, 2026-09-30, against this
  repository's `causalmesh.yaml`:
  - `causalmesh policy check --agent docs --kind path --name src/causalmesh/policy/gate.py`
    returned REFUSE, rule `ownership`, holder `causalmesh`, reason
    `'src/causalmesh/policy/gate.py' is owned by 'causalmesh', not 'docs'`, exit 1
  - the same check with `--agent causalmesh` returned ALLOW, rule
    `default-allow`, reason `no rule refuses this`, exit 0
- Real trace: the four events of
  `pilot_landing__concurrent_edit_collision__C3__r0000`, from `TRACE` in
  `frontend/lib/site/content.ts`
- Portal clip: the site's hero video (`assets/video/portal.mp4`, 1664x1248, 10s)

## Creative Direction
- Tone preset: cinematic
- Creative direction: editorial technical motion study. Swiss grid, huge
  cropped light-weight type, production-metadata HUD, one warm accent that
  means REFUSE.
- Angle: see `brag-plan.md`
- Hook: "Two agents." / "One file." while two signal lines race to one gate node
- Outro: the two-bar mark lands on the 27.30s strong cue, then "CausalMesh",
  "Gate the next action.", `causalmesh.vercel.app`
- Avoid: generic SaaS language, neon, purple AI gradients, glassmorphism,
  floating orbs, particle clouds, waveform graphics, any metric about agent
  behaviour

## Visual Identity
- Background `#050505`, panel `#0c0c0c`, text `#fafafa` / `#d6d5d5` /
  `#a7a6a6`, HUD `#8b8a8a`, lines `rgba(255,255,255,.09/.16)`
- Accent `#d2a676` (the site's `--color-deny`), used only for refusals
- Manrope (light, tight tracking, as on the site) and JetBrains Mono, both
  shipped locally

## Storyboard (see brag-plan.md)
1. Signal, 0.00-4.39: two lines race to the gate; "Two agents." / "One file."
2. Kinetic type, 4.39-7.64: GATED. SIGNED. RECORDED., one every two beats
3. Gate console, 7.64-13.11: typed check, REFUSE at 8.74, ALLOW at 11.46
4. Chain, 13.11-18.02: the console collapses into event #3; the real trace
   assembles; the formula writes; the chain tilts into depth
5. Properties, 18.02-22.93: OWNED / LEASED / REFUSED / VERIFIED, each on its
   own ground, ending in a slit of light
6. Portal, 22.93-27.00: match cut to the site's portal, slow push-in, hero title
7. Mark, 27.00-30.00: mark lands at 27.30, then name, CTA and domain; hold

## Audio
- Role: cinematic support. Music `happy-beats-business-moves-vol-12-by-ende-dot-app.mp3`
  at ~0.34, fading in over 1.2s and out over the end hold.
- Cue source: the bundled preset `.claude/skills/brag/assets/music/cues/happy-beats-business-moves-vol-12-by-ende-dot-app.music-cues.json`.
  Strong-cue locks: 8.74, 13.11, 22.93, 27.30. Beat grid for sequential words
  and cards.
- Audio-reactive: per-frame level from `assets/audio-data.js` drives the gate
  node glow, the grid brightness and the portal bloom. Subtle.
- SFX: soft medium/heavy impacts for type hits and REFUSE, thinned keypresses
  for typing, a click on the selection change, soft drops for chain blocks, a
  card slide per property card, and one bell for the mark. All are CC0
  (Kenney), copied from the /brag library.
