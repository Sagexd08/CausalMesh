/**
 * Dependency path: a small branching network of rounded modules on a plinth,
 * joined by low bars. A module that something hangs off carries a boss on its
 * lid; a leaf has none. The pointer over a module is a change there: it grows,
 * and the change reaches the modules downstream, staggered by hops, their
 * strokes going from `sil` to `hi` as it arrives. What it depends on, upstream,
 * stays at rest. At rest the root is the one bright mark. The slider is how
 * many hops the change has travelled.
 *
 * The pattern: discrete items on a tree. Tweens, a stagger by hop distance,
 * and a hit test against each module's rest pose, front-most first.
 */
const {
  Cam, facing, fit, prism, proj, rings, unproj, tdone, tset, tval, tween,
  disposer, mk, pointer, put, register, solid,
} = HL;

const LINE = "A change reaches what depends on it.";
const G = 44, N = 20, BW = 5, BH = 3, PB = 5, LIFT = 12, STEP = 60, X1 = 168, Y1 = 124;
// id, column, row, parent (index), rest height: root tall, leaves low
const M = [[0, 1, -1, 34], [1, 1, 0, 26], [0, 2, 0, 22], [2, 1, 1, 16], [1, 0, 1, 18], [1, 2, 2, 12], [3, 1, 3, 9]];

function mount({ stage, svg, read }, value) {
  const bag = disposer();
  let hops = value, act = -1, src = -1;

  const C = Cam(45, 0.5, 1.55);
  fit(C, [[-16, -16, -PB], [X1, Y1, -PB], [X1, -16, -PB], [-16, Y1, -PB], [10, 54, 50], [142, 54, 20]], 200, 166);
  const P = proj(C), front = facing(C);

  const nodes = M.map(([c, r, p, h0], i) => ({ i, p, h0, cx: c * G + N / 2, cy: r * G + N / 2, z: tween(0), drawn: NaN }));
  nodes.forEach((n) => { n.depth = n.p < 0 ? 0 : nodes[n.p].depth + 1; n.leaf = !nodes.some((k) => k.p === n.i); });

  // Everything that stands on the plinth, with the key it is painted by: far to near.
  const parts = nodes.map((n) => ({ key: n.cx + n.cy, n }));
  nodes.filter((n) => n.p >= 0).forEach((n) => {
    const q = nodes[n.p], flat = q.cy === n.cy, h = N / 2, w = BW / 2;
    const box = flat
      ? [Math.min(q.cx, n.cx) + h, n.cy - w, Math.max(q.cx, n.cx) - h, n.cy + w]
      : [n.cx - w, Math.min(q.cy, n.cy) + h, n.cx + w, Math.max(q.cy, n.cy) - h];
    parts.push({ key: (box[0] + box[2] + box[1] + box[3]) / 2, n, box });
  });
  parts.sort((a, b) => a.key - b.key);

  const g = mk("g", {}, svg);
  const [pr, pi] = rings(-16, -16, X1, Y1, 10, 2.2);
  put(solid(g), prism(P, front, pr, pi, -PB, 0));
  for (const { n, box } of parts) {
    if (box) {
      const [r, i] = rings(box[0], box[1], box[2], box[3], 1.2, 0.6);
      n.bar = solid(g);
      put(n.bar, prism(P, front, r, i, 0, BH));
      continue;
    }
    [n.ring, n.inner] = rings(n.cx - N / 2, n.cy - N / 2, n.cx + N / 2, n.cy + N / 2, 4, 1.4);
    n.el = solid(g);
    if (!n.leaf) {
      [n.bring, n.binner] = rings(n.cx - 4, n.cy - 4, n.cx + 4, n.cy + 4, 2, 0.8);
      n.boss = solid(g);
    }
  }

  /** Hops from module a down to n, or -1 when n is not downstream of a (or is upstream). */
  function hopsTo(a, n) {
    if (a < 0) return -1;
    let d = n.depth - nodes[a].depth, q = n;
    if (d < 0) return -1;
    for (let k = 0; k < d; k++) q = nodes[q.p];
    return q.i === a ? d : -1;
  }

  function draw(n, v) {
    if (v === n.drawn) return;
    n.drawn = v;
    const h = n.h0 + v;
    put(n.el, prism(P, front, n.ring, n.inner, 0, h));
    if (n.boss) put(n.boss, prism(P, front, n.bring, n.binner, h, h + 2.6));
  }

  const B = register(stage, (_dt, now) => {
    let moving = false;
    for (const n of nodes) {
      const v = tval(n.z, now);
      if (!tdone(n.z, now)) moving = true;
      draw(n, v);
      // the bright stroke arrives with the change; at rest the root alone is lit
      const on = v > LIFT / 2 || (act < 0 && n.p < 0);
      n.el.sil.classList.toggle("hi", on);
      if (n.boss) n.boss.sil.classList.toggle("hi", on);
      if (n.bar) n.bar.sil.classList.toggle("hi", v > LIFT / 2 && n.i !== src);
    }
    return moving;
  });
  bag.add(B.unregister);

  /** Retargets every module from the change at `src`, staggered by hops; letting go spreads from the same place. */
  function apply() {
    const now = performance.now();
    for (const n of nodes) {
      const h = hopsTo(src, n);
      tset(n.z, act >= 0 && h >= 0 && h <= hops + 1e-6 ? LIFT : 0, now, Math.max(h, 0) * STEP);
    }
    read.textContent = LINE;
    B.wake();
  }

  // Hit test: each module's rest pose, on its lid, mid-height and foot, nearest the viewer first.
  const order = nodes.slice().sort((a, b) => b.cx + b.cy - (a.cx + a.cy));
  function hit(p) {
    for (const n of order) for (const z of [n.h0, n.h0 / 2, 0]) {
      const w = unproj(C, p[0], p[1], z);
      if (Math.abs(w[0] - n.cx) <= N / 2 + 1.5 && Math.abs(w[1] - n.cy) <= N / 2 + 1.5) return n.i;
    }
    return -1;
  }
  function choose(a) {
    if (a === act) return;
    act = a;
    if (a >= 0) src = a;
    apply();
  }

  bag.add(pointer(stage, { move: (p) => choose(hit(p)), down: (p) => choose(hit(p)), leave: () => choose(-1) }));
  bag.add(() => svg.replaceChildren());
  // rest is drawn at once: the root alone is bright
  for (const n of nodes) draw(n, 0);
  nodes[0].el.sil.classList.add("hi");
  nodes[0].boss.sil.classList.add("hi");
  apply();

  return {
    set: (v) => { hops = v; apply(); },
    destroy: bag.dispose,
  };
}

hairline({
  name: "dependency-path",
  means: "A change reaches what depends on it.",
  rules: [1, 2, 4, 5],
  range: [0, 2, 3],
  tour: [[128, 88], [176, 123], [128, 166], null],
  mount,
});
