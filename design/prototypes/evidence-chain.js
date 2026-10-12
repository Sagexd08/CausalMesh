/**
 * Evidence chain: five rounded links in a row, each with a peg that seats in
 * the next, so the row reads as one straight bar. The pointer picks a link
 * (tested against the resting poses) and nudges it out of true: it lifts, slides
 * aside and opens its joint, and every link after it drifts a step further, so
 * none of them mate. Links before it stay seated. The failing joints and links
 * take the bright stroke; at rest the first link carries it. The slider is how
 * far the link is altered, 0 to 1.
 *
 * The pattern: discrete items, one tween per link carrying how many steps out
 * of true it is, staggered outwards from the pick.
 */
const { Cam, facing, fit, prism, proj, put, rings, solid, mk, pointer, register, disposer, tween, tset, tval, tdone } = HL;

const N = 5, G0 = 3, ENG = 5, STEP = 55, REACH = 36;
const DX = 2.6, DY = 3, DZ = 3.2; // one step out of true, at full alteration
const SAY = "Change one event and verification fails at that event.";

// Links alternate large and small; each is a rounded slab on the centre line y = 0.
const L = [];
for (let j = 0, x = 0; j < N; j++) {
  const big = j % 2 === 0, lx = big ? 36 : 26;
  L.push({ x0: x, x1: x + lx, hw: big ? 14 : 10, H: big ? 14 : 10, r: big ? 6 : 4.5 });
  x += lx + G0;
}

function mount({ stage, svg, read }, value) {
  const bag = disposer();
  let a = value, act = -1;

  // Centred on the resting row, so the thumbnail sits in the frame; S leaves room for full alteration.
  const C = Cam(45, 0.5, 1.75);
  const end = L[N - 1].x1;
  fit(C, [[0, -14, 0], [end, -14, 0], [0, 14, 14], [end, 14, 14]], 200, 166);
  const P = proj(C), front = facing(C);

  const g = mk("g", {}, svg);
  // Left to right is far to near: a link, then the peg it carries, then the next link over it.
  const parts = L.map((l, j) => ({
    l, n: tween(0), el: solid(g), peg: j < N - 1 ? solid(g) : null, drawn: NaN, seen: NaN,
  }));

  // Hit centres: the resting poses, which never move.
  const cen = L.map((l) => P((l.x0 + l.x1) / 2, 0, l.H / 2));
  function hit([x, y]) {
    let best = -1, d = REACH;
    cen.forEach((c, j) => { const e = Math.hypot(c[0] - x, c[1] - y); if (e < d) { d = e; best = j; } });
    return best;
  }

  function draw(p, n) {
    const { l } = p, o = n * a, ox = o * DX, oy = -o * DY, oz = o * DZ;
    const [ring, inner] = rings(l.x0 + ox, -l.hw + oy, l.x1 + ox, l.hw + oy, l.r, 1.6);
    put(p.el, prism(P, front, ring, inner, oz, l.H + oz));
    if (p.peg) {
      const [pr, pi] = rings(l.x1 + ox, -4 + oy, l.x1 + G0 + ENG + ox, 4 + oy, 1.6, 0.6);
      put(p.peg, prism(P, front, pr, pi, 2 + oz, 6 + oz));
    }
  }

  // Which strokes are bright: the failing run from the pick on, and the joint that opens at it.
  function light() {
    const live = act >= 0 && a > 0;
    parts.forEach((p, j) => {
      p.el.sil.classList.toggle("hi", live ? j >= act : j === 0);
      if (p.peg) p.peg.sil.classList.toggle("hi", live && j >= act - 1);
    });
  }

  const B = register(stage, (_dt, now) => {
    let moving = false;
    for (const p of parts) {
      const n = tval(p.n, now);
      if (n !== p.drawn || a !== p.seen) { p.drawn = n; p.seen = a; draw(p, n); }
      if (!tdone(p.n, now)) moving = true;
    }
    return moving;
  });
  bag.add(B.unregister);

  /** Picks link k (-1 lets go). The drift spreads out from the pick, one step per link after it. */
  function setActive(k) {
    if (k === act) return;
    const now = performance.now(), from = k >= 0 ? k : act;
    act = k;
    parts.forEach((p, j) => tset(p.n, k >= 0 && j >= k ? j - k + 1 : 0, now, Math.abs(j - from) * STEP));
    light();
    read.textContent = SAY;
    B.wake();
  }

  light();
  read.textContent = SAY;
  bag.add(pointer(stage, { move: (p) => setActive(hit(p)), leave: () => setActive(-1) }));
  bag.add(() => svg.replaceChildren());

  return {
    set: (v) => { a = v; light(); B.wake(); },
    destroy: bag.dispose,
  };
}

hairline({
  name: "evidence-chain",
  means: "Five linked solids: alter one and it, with every link after it, stops mating; the links before it stay seated.",
  rules: [1, 2, 4, 5],
  range: [0, 0.5, 1],
  tour: [[116, 124], [200, 166], [284, 208], null],
  mount,
});
