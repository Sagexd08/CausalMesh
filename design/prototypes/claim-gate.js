/**
 * Claim gate: one block, with an agent already seated against it and a gate
 * standing in front of both. A second agent stands off to the side. The
 * pointer is projected onto the ground and the farther it is dragged toward
 * the block, the harder the second agent is pushed at the gate. Its advance
 * saturates, so it is held short of the gate and never reaches the block, and
 * it springs back when the pointer leaves. The seated agent never moves. The
 * slider is how hard the second agent pushes.
 *
 * The pattern: a continuous field, as Terrain is. A hit test on the ground
 * plane, which never moves, and a spring per moving number.
 */
const {
  Cam, clamp, facing, fit, prism, proj, rings, unproj, spring, stepS,
  flatDot, mk, place, pointer, put, register, disposer, solid,
} = HL;

// World units. The second agent slides along y = 15; the gate stands at x = 50..54.
const X_REST = 92, X_STOP = 62, X_FACE = 30, AY0 = 9, AY1 = 21, LEAN = 2.5;
const SAY = "A claimed path refuses a second writer.";

function mount({ stage, svg, read }, value) {
  const bag = disposer();
  let push = clamp(value, 0, 1), adv = 0;

  const C = Cam(45, 0.5, 2.7);
  fit(C, [[0, -3, 0], [102, -3, 0], [0, 33, 0], [102, 33, 0], [0, 0, 28], [30, 30, 28], [102, 15, 18], [54, 33, 22], [54, -3, 22]], 200, 166);
  const P = proj(C), front = facing(C);
  const g = mk("g", {}, svg);

  // A solid is appended in paint order, back to front: block, seated agent, gate, then the mover.
  const build = (sl, x0, y0, x1, y1, r, b, z0, z1) => {
    const [ring, inner] = rings(x0, y0, x1, y1, r, b);
    put(sl, prism(P, front, ring, inner, z0, z1));
    return sl;
  };
  const part = (...a) => build(solid(g), ...a);

  part(0, 0, 30, 30, 5, 1.6, 0, 26);
  // the block's lid carries a short dot code
  for (const y of [8, 15, 22]) place(flatDot(g, C, 0.9, "dot off"), P(15, y, 26));

  const holder = [part(30, AY0, 42, AY1, 3.5, 1.2, 0, 9), part(32.5, AY0 + 2.5, 39.5, AY1 - 2.5, 2.5, 0.9, 9, 17)];
  const gate = [part(50, -3, 54, 1, 1.5, 0.8, 0, 20), part(50.6, 0, 53.4, 30, 1.4, 0.6, 8, 12), part(50, 29, 54, 33, 1.5, 0.8, 0, 20)];

  const mover = { base: solid(g), head: solid(g) };
  const sp = spring(X_REST, { eps: 0.02 }), lp = spring(0, { eps: 0.01 });
  let dx = NaN, dl = NaN;
  function drawMover() {
    const x = clamp(sp.x, X_STOP - 1, X_REST + 4), l = clamp(lp.x, 0, LEAN);
    if (x === dx && l === dl) return;
    dx = x; dl = l;
    build(mover.base, x - 6, AY0, x + 6, AY1, 3.5, 1.2, 0, 9);
    build(mover.head, x - 3.5 - l, AY0 + 2.5, x + 3.5 - l, AY1 - 2.5, 2.5, 0.9, 9, 17);
  }
  drawMover();

  const B = register(stage, (dt) => {
    const m1 = stepS(sp, dt), m2 = stepS(lp, dt);
    drawMover();
    return m1 || m2;
  });
  bag.add(B.unregister);

  function retarget() {
    const u = adv * (0.5 + 0.5 * push);                         // effort, 0..1
    const d = (1 - Math.exp(-3 * u)) / (1 - Math.exp(-3));      // saturates: the gate gives nothing back
    sp.t = X_REST - (X_REST - X_STOP) * d;
    lp.t = LEAN * clamp((u - 0.3) / 0.6, 0, 1);                 // head leans in once the push is hard
    const held = sp.t - X_STOP < 10;                            // the target pose, so the hit never flickers
    for (const p of gate) p.sil.classList.toggle("hi", held);
    for (const p of holder) p.sil.classList.toggle("hi", !held);
    read.textContent = SAY;
    B.wake();
  }
  holder.forEach((p) => p.sil.classList.add("hi"));
  read.textContent = SAY;

  bag.add(pointer(stage, {
    move: (p) => { adv = clamp((X_REST - unproj(C, p[0], p[1], 0)[0]) / (X_REST - X_FACE), 0, 1); retarget(); },
    leave: () => { adv = 0; retarget(); },
  }));
  bag.add(() => svg.replaceChildren());

  return {
    set: (v) => { push = clamp(v, 0, 1); retarget(); },
    destroy: bag.dispose,
  };
}

hairline({
  name: "claim-gate",
  means: "A block is held by the agent seated against it; a second agent pushes at the gate and is held short.",
  rules: [1, 3, 4, 8],
  range: [0, 0.5, 1],
  tour: [[249, 222], [207, 201], [156, 175], null],
  mount,
});
