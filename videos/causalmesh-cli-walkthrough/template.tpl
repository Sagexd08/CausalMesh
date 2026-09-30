<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <title>CausalMesh - CLI Walkthrough</title>
    <script src="assets/vendor/gsap.min.js"></script>
    <style>
      @font-face { font-family: "Manrope"; src: url("assets/fonts/Manrope.woff2") format("woff2"); font-weight: 200 800; font-display: block; }
      @font-face { font-family: "JetBrains Mono"; src: url("assets/fonts/JetBrainsMono.woff2") format("woff2"); font-weight: 400 600; font-display: block; }
      /* Sand is the refusal colour. Blue is the allowed path. Violet is the flow between stages. */
      :root {
        --stage: #050507; --panel: #0a0a0d; --fg: #fafafa; --fg2: #d6d5d8; --muted: #a7a6ab; --dim: #8b8a90;
        --line: rgba(255,255,255,0.10); --line-strong: rgba(255,255,255,0.26);
        --deny: #d2a676; --deny-wash: rgba(210,166,118,0.13);
        --allow: #7db4ff; --allow-wash: rgba(125,180,255,0.13);
        --violet: #9a8cff; --violet-wash: rgba(154,140,255,0.14);
      }
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1920px; height: 1080px; overflow: hidden; background: var(--stage); }
      #root { position: relative; width: 100%; height: 100%; overflow: hidden; background: var(--stage); color: var(--fg);
        font-family: "Manrope", system-ui, sans-serif; -webkit-font-smoothing: antialiased; }
      .clip { position: absolute; inset: 0; }
      .label { font-family: "JetBrains Mono", monospace; font-size: 18px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--dim); }
      .mask { display: block; overflow: hidden; padding-bottom: 0.16em; margin-bottom: -0.16em; }
      .mask > span { display: block; white-space: nowrap; }
      .display { font-weight: 300; letter-spacing: -0.045em; line-height: 1.04; }

      #bg-grid { background-image: linear-gradient(to right, rgba(154,140,255,0.05) 1px, transparent 1px), linear-gradient(to bottom, rgba(154,140,255,0.05) 1px, transparent 1px); background-size: 96px 96px; }
      #bg-glow { background: radial-gradient(ellipse 60% 50% at 78% 20%, rgba(120,110,255,0.10), transparent 70%), radial-gradient(ellipse 50% 45% at 12% 90%, rgba(90,150,255,0.07), transparent 70%); }
      #vignette { background: radial-gradient(ellipse at 50% 45%, transparent 58%, rgba(0,0,0,0.55) 100%); pointer-events: none; }
      #wipe { position: absolute; inset: 0; background: #0c0c10; z-index: 50; border-right: 2px solid rgba(154,140,255,0.7); }
      #prog { position: absolute; left: 96px; right: 96px; top: 1064px; height: 2px; background: var(--line); }
      #prog-fill { position: absolute; inset: 0; background: linear-gradient(90deg, var(--violet), var(--allow)); transform-origin: 0 50%; transform: scaleX(0); }

      /* pipeline strip: Developer -> SDK -> Gateway -> Policy -> ALLOW / DENY -> Tool -> Evidence */
      #pipe { position: absolute; left: 96px; top: 40px; width: 1728px; height: 72px; display: flex; align-items: center; opacity: 0; z-index: 40; }
      .pn { position: relative; width: 212px; height: 72px; border: 1px solid var(--line-strong); border-radius: 8px; background: rgba(10,10,13,0.9); padding: 13px 16px; flex: none; }
      .pn .ix { display: block; font-family: "JetBrains Mono", monospace; font-size: 12px; letter-spacing: 0.16em; color: var(--dim); }
      .pn .nm { display: block; margin-top: 6px; font-size: 22px; font-weight: 400; letter-spacing: -0.02em; color: var(--muted); white-space: nowrap; }
      .pn .tg { position: absolute; right: 12px; top: 13px; font-family: "JetBrains Mono", monospace; font-size: 12px; letter-spacing: 0.1em; color: var(--deny); opacity: 0; }
      .pc { position: relative; width: 40px; height: 2px; background: var(--line); flex: none; }
      .pc i { position: absolute; inset: 0; background: linear-gradient(90deg, var(--violet), var(--allow)); transform-origin: 0 50%; transform: scaleX(0); }
      .pc b { position: absolute; left: 0; top: -3px; width: 8px; height: 8px; border-radius: 50%; background: #fff; box-shadow: 0 0 10px 2px var(--violet); opacity: 0; }
      #status { position: absolute; left: 96px; top: 128px; width: 1728px; height: 30px; z-index: 40; }
      .st { position: absolute; left: 0; top: 0; font-family: "JetBrains Mono", monospace; font-size: 18px; color: var(--fg2); opacity: 0; white-space: nowrap; }
      .st b { font-weight: 500; color: var(--fg); }
      .st.deny, .st.deny b { color: var(--deny); }
      .st.allow b { color: var(--allow); }
      .cap { position: absolute; left: 96px; top: 1002px; display: flex; align-items: baseline; gap: 22px; opacity: 0; z-index: 40; white-space: nowrap; }
      .cap .n { font-family: "JetBrains Mono", monospace; font-size: 15px; letter-spacing: 0.16em; color: var(--violet); }
      .cap .t { font-size: 32px; font-weight: 400; letter-spacing: -0.02em; color: var(--fg); }
      .cap.deny .n, .cap.deny .t { color: var(--deny); }
      .cap.allow .t { color: var(--fg); }

      .stage { position: absolute; left: 0; top: 166px; width: 1920px; height: 826px; overflow: hidden; z-index: 5; }
      .cam { position: absolute; inset: 0; transform-origin: 50% 50%; }
      .tw { position: absolute; background: var(--panel); border: 1px solid var(--line-strong); border-radius: 10px; overflow: hidden; box-shadow: 0 0 60px rgba(120,110,255,0.06); }
      .tbar { position: absolute; left: 0; right: 0; top: 0; height: 46px; border-bottom: 1px solid var(--line); display: flex; align-items: center; padding: 0 18px; gap: 8px; background: #0e0e12; }
      .tbar i { width: 11px; height: 11px; border-radius: 50%; border: 1px solid var(--line-strong); }
      .tbar .tt { margin-left: 14px; font-family: "JetBrains Mono", monospace; font-size: 14px; letter-spacing: 0.08em; color: var(--dim); }
      .chip { position: absolute; right: 16px; top: 9px; padding: 5px 12px; border-radius: 6px; border: 1px solid; font-family: "JetBrains Mono", monospace; font-size: 14px; letter-spacing: 0.12em; opacity: 0; z-index: 3; }
      .chip.allow { color: var(--allow); border-color: var(--allow); background: var(--allow-wash); }
      .chip.deny { color: var(--deny); border-color: var(--deny); background: var(--deny-wash); }
      .tbody { position: absolute; left: 0; right: 0; top: 46px; bottom: 0; overflow: hidden; }
      .tvp { position: absolute; left: 0; right: 0; top: 16px; bottom: 16px; overflow: hidden; }
      .tin, .ein { padding: 0 20px; }
      .tin { position: relative; font-family: "JetBrains Mono", monospace; color: var(--fg2); white-space: pre-wrap; word-break: break-all; }
      .tin .ln { opacity: 0; }
      .tin .ps { color: var(--violet); }
      .tin .out { color: var(--muted); }
      .tin .out.hi { color: var(--fg); }
      .tin .out.allow { color: var(--allow); }
      .tin .out.deny, .tin .deny { color: var(--deny); }
      .tin .out.deny span { color: var(--deny); }
      .tin .cur::after { content: ""; display: inline-block; width: 0.55em; height: 1.05em; margin-left: 1px; vertical-align: text-bottom; background: var(--fg); }
      .tin .k { color: var(--fg2); } .tin .s { color: var(--muted); } .tin .v { color: var(--fg); }
      .hlbar { position: absolute; left: 0; right: 0; background: var(--allow-wash); border-left: 3px solid var(--allow); opacity: 0; }
      .hlbar.deny { background: var(--deny-wash); border-left-color: var(--deny); }
      .hlbar.white { background: rgba(255,255,255,0.09); border-left-color: var(--fg); }
      .marker { position: absolute; left: 20px; right: 20px; border-left: 3px solid var(--deny); background: var(--deny-wash); color: var(--deny); padding: 0 14px; white-space: nowrap; opacity: 0; }

      .ein { position: relative; font-family: "JetBrains Mono", monospace; color: var(--fg2); }
      .el { position: relative; white-space: pre; opacity: 0; }
      .el .no { display: inline-block; width: 44px; margin-right: 18px; text-align: right; color: var(--dim); }
      .el .c1 { color: var(--dim); font-style: italic; } .el .c2 { color: #b9b3ff; } .el .c3 { color: var(--fg); font-weight: 500; } .el .c4 { color: var(--allow); }
      .fbar { position: absolute; left: 0; right: 0; background: var(--violet-wash); border-left: 3px solid var(--violet); opacity: 0; }
      .fbar.deny { background: var(--deny-wash); border-left-color: var(--deny); }
      .notes { position: absolute; left: 1212px; top: 0; width: 612px; }
      .note { position: absolute; left: 0; top: 200px; width: 612px; padding: 22px 26px; border: 1px solid var(--line-strong); border-left: 3px solid var(--violet); border-radius: 10px; background: var(--panel); opacity: 0; }
      .note .a { font-family: "JetBrains Mono", monospace; font-size: 18px; letter-spacing: 0.04em; color: var(--fg); }
      .note .b { margin-top: 10px; font-size: 25px; font-weight: 300; line-height: 1.3; letter-spacing: -0.01em; color: var(--muted); }

      /* verdict badges (scene 4) */
      .badge { position: absolute; left: 1240px; width: 584px; height: 340px; border: 1px solid var(--line-strong); border-radius: 12px; background: var(--panel); padding: 30px 36px; opacity: 0; }
      .badge .lb { font-family: "JetBrains Mono", monospace; font-size: 15px; letter-spacing: 0.16em; color: var(--dim); }
      .badge .w { margin-top: 14px; font-size: 104px; font-weight: 300; letter-spacing: -0.04em; line-height: 1; }
      .badge .tg { margin-top: 24px; font-family: "JetBrains Mono", monospace; font-size: 19px; color: var(--fg); }
      .badge .rl { margin-top: 12px; font-family: "JetBrains Mono", monospace; font-size: 17px; color: var(--muted); line-height: 1.4; }
      .badge.allow { border-color: rgba(125,180,255,0.6); box-shadow: 0 0 60px rgba(125,180,255,0.10); }
      .badge.allow .w { color: var(--allow); }
      .badge.deny { border-color: rgba(210,166,118,0.7); box-shadow: 0 0 60px rgba(210,166,118,0.10); }
      .badge.deny .w, .badge.deny .rl b { color: var(--deny); }
      .badge .rl b { font-weight: 500; color: var(--fg); }

      /* evidence cards (scene 7) */
      .ecard { position: absolute; top: 536px; height: 240px; border: 1px solid var(--line-strong); border-radius: 10px; background: var(--panel); padding: 18px 22px; font-family: "JetBrains Mono", monospace; font-size: 15px; line-height: 25px; color: var(--muted); opacity: 0; }
      .ecard .h { font-size: 14px; letter-spacing: 0.14em; color: var(--fg); margin-bottom: 8px; }
      .ecard .k { display: inline-block; width: 128px; color: var(--dim); }
      .ecard .v { color: var(--fg2); }
      .ecard .hv { color: var(--violet); }
      .ecard .stamp { position: absolute; right: 16px; top: 14px; padding: 3px 10px; border-radius: 5px; border: 1px solid var(--allow); color: var(--allow); background: var(--allow-wash); font-size: 12px; letter-spacing: 0.14em; opacity: 0; }
      .ecard.bad { border-color: rgba(210,166,118,0.7); }
      .ecard.bad .h, .ecard.bad .v.d { color: var(--deny); }
      .ecard.bad .stamp { border-color: var(--deny); color: var(--deny); background: var(--deny-wash); }
      .clink { position: absolute; top: 640px; width: 124px; height: 2px; background: var(--line); opacity: 0; }
      .clink i { position: absolute; inset: 0; background: linear-gradient(90deg, var(--violet), var(--allow)); transform-origin: 0 50%; transform: scaleX(0); }
      .clink span { position: absolute; left: 0; right: 0; top: -26px; text-align: center; font-family: "JetBrains Mono", monospace; font-size: 12px; letter-spacing: 0.06em; color: var(--violet); }
      .csep { position: absolute; top: 640px; width: 124px; text-align: center; font-family: "JetBrains Mono", monospace; font-size: 12px; line-height: 1.5; color: var(--deny); opacity: 0; }

      /* vertical pipeline (scene 8) */
      .vn { position: absolute; left: 96px; width: 520px; height: 72px; border: 1px solid var(--line-strong); border-radius: 10px; background: rgba(10,10,13,0.92); padding: 14px 22px; opacity: 0; }
      .vn .ix { display: block; font-family: "JetBrains Mono", monospace; font-size: 12px; letter-spacing: 0.16em; color: var(--dim); }
      .vn .nm { display: block; margin-top: 5px; font-size: 26px; font-weight: 400; letter-spacing: -0.02em; color: var(--fg); white-space: nowrap; }
      .vn.lit { border-color: rgba(154,140,255,0.9); background: var(--violet-wash); }
      .vsub { position: absolute; left: 648px; width: 520px; height: 72px; display: flex; align-items: center; font-family: "JetBrains Mono", monospace; font-size: 18px; color: var(--muted); opacity: 0; }
      .vsub b { font-weight: 500; color: var(--fg); }
      .vc { position: absolute; left: 355px; width: 2px; height: 34px; background: var(--line); opacity: 0; }
      .vc i { position: absolute; inset: 0; background: linear-gradient(180deg, var(--violet), var(--allow)); transform-origin: 50% 0; transform: scaleY(0); }
      .vc b { position: absolute; left: -3px; top: 0; width: 8px; height: 8px; border-radius: 50%; background: #fff; box-shadow: 0 0 10px 2px var(--violet); opacity: 0; }
      .vtag { position: absolute; left: 470px; height: 26px; padding: 0 10px; border-radius: 5px; border: 1px solid; font-family: "JetBrains Mono", monospace; font-size: 13px; letter-spacing: 0.12em; display: flex; align-items: center; opacity: 0; }
      .vtag.allow { color: var(--allow); border-color: var(--allow); background: var(--allow-wash); }
      .vtag.deny { color: var(--deny); border-color: var(--deny); background: var(--deny-wash); }
      #v-say { position: absolute; left: 1240px; top: 250px; width: 584px; font-size: 42px; font-weight: 300; line-height: 1.28; letter-spacing: -0.025em; color: var(--muted); }
      #v-say .ln2 { display: block; opacity: 0; }
      #v-say b { font-weight: 400; color: var(--fg); }
      #v-say u { text-decoration: none; color: var(--allow); }
      #v-foot { position: absolute; left: 1240px; top: 760px; width: 584px; font-family: "JetBrains Mono", monospace; font-size: 16px; line-height: 1.5; color: var(--dim); opacity: 0; }

      #e-title { position: absolute; left: 0; right: 0; top: 270px; text-align: center; font-size: 150px; letter-spacing: 0.12em; padding-left: 0.12em; }
      #e-tag { position: absolute; left: 0; right: 0; top: 500px; text-align: center; font-size: 50px; font-weight: 300; letter-spacing: -0.025em; line-height: 1.3; color: var(--fg2); }
      #e-tag span.l2 { color: var(--allow); }
      #e-note { position: absolute; left: 0; right: 0; top: 742px; text-align: center; font-family: "JetBrains Mono", monospace; font-size: 20px; letter-spacing: 0.06em; color: var(--muted); opacity: 0; }
      #e-note2 { position: absolute; left: 0; right: 0; top: 790px; text-align: center; font-family: "JetBrains Mono", monospace; font-size: 16px; letter-spacing: 0.04em; color: var(--dim); opacity: 0; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080" data-duration="__DUR__" data-fps="30">
      <div id="bg-grid" class="clip" data-start="0" data-duration="__DUR__" data-track-index="0"></div>
      <div id="bg-glow" class="clip" data-start="0" data-duration="__DUR__" data-track-index="1"></div>

      <section id="s1" class="clip" data-start="__S1__" data-duration="__S1DUR__" data-track-index="2"><div class="stage"><div class="cam" id="cam1"></div></div></section>
      <section id="s2" class="clip" data-start="__S2__" data-duration="__S2DUR__" data-track-index="2"><div class="stage"><div class="cam" id="cam2"></div></div></section>
      <section id="s3" class="clip" data-start="__S3__" data-duration="__S3DUR__" data-track-index="2"><div class="stage"><div class="cam" id="cam3"><div class="notes">__NOTES__</div></div></div></section>
      <section id="s4" class="clip" data-start="__S4__" data-duration="__S4DUR__" data-track-index="2"><div class="stage"><div class="cam" id="cam4">__BADGES__</div></div></section>
      <section id="s5" class="clip" data-start="__S5__" data-duration="__S5DUR__" data-track-index="2"><div class="stage"><div class="cam" id="cam5"></div></div></section>
      <section id="s7" class="clip" data-start="__S7__" data-duration="__S7DUR__" data-track-index="2"><div class="stage"><div class="cam" id="cam6">__CARDS__</div></div></section>

      <section id="s8" class="clip" data-start="__S8__" data-duration="__S8DUR__" data-track-index="2" style="z-index:5">
        <div id="vwrap">__VPIPE__</div>
        <div id="v-say"><span class="ln2">CausalMesh sits between your <b>AI agent</b> and its <b>tools</b>,</span><span class="ln2">enforcing <u>policy before execution</u></span><span class="ln2">and recording <b>evidence</b> of what happened.</span></div>
        <div id="v-foot">the local demo: examples/cli_demo/<br>a contract, one tool, an allowed call, a denied call</div>
      </section>

      <section id="s9" class="clip" data-start="__S9__" data-duration="__S9DUR__" data-track-index="2" style="z-index:5">
        <h2 id="e-title" class="display"><span class="mask"><span>CAUSALMESH</span></span></h2>
        <div id="e-tag"><span class="mask"><span>Policy before execution.</span></span><span class="mask"><span class="l2">Evidence after execution.</span></span></div>
        <div id="e-note">Pre-alpha &bull; local SDK and gateway demo</div>
        <div id="e-note2">in-memory evidence &nbsp;|&nbsp; no TLS &nbsp;|&nbsp; not production-ready</div>
      </section>

      <div id="hud" class="clip" data-start="0" data-duration="__DUR__" data-track-index="72" style="z-index:40">
        <div id="pipe">__PIPE__</div>
        <div id="status">__STATUS__</div>
        __CAPS__
        <div id="prog"><div id="prog-fill"></div></div>
      </div>
      <div id="vignette" class="clip" data-start="0" data-duration="__DUR__" data-track-index="70"></div>
      <div id="wipe" class="clip" data-start="0" data-duration="__DUR__" data-track-index="60"></div>

      <audio id="music" src="assets/music/happy-beats-business-moves-vol-9-by-ende-dot-app.mp3" data-start="0" data-duration="__DUR__" data-track-index="10" data-volume="0.34"
        data-automation='{"version":1,"lanes":[{"target":"volume","points":[{"t":0,"v":0},{"t":0.5,"v":1},{"t":__FADE0__,"v":1},{"t":__DUR__,"v":0}]}]}'></audio>
      __AUDIO__
    </div>

    <script>
      (function () {
        var D = __DATA__;
        var PL = __PLAN__;
        var EASE = "power4.out", SOFT = "expo.out";
        var tl = gsap.timeline({ paused: true });
        window.__timelines = window.__timelines || {};
        function q(s) { return document.querySelector(s); }
        function mk(cls, parent) { var d = document.createElement("div"); d.className = cls; if (parent) parent.appendChild(d); return d; }
        function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

        /* ---------- persistent: grid drift, progress, wipe ---------- */
        tl.fromTo("#bg-grid", { backgroundPosition: "0px 0px" }, { backgroundPosition: "-192px -96px", duration: PL.dur, ease: "none" }, 0);
        tl.fromTo("#prog-fill", { scaleX: 0 }, { scaleX: 1, duration: PL.dur, ease: "none" }, 0);
        tl.set("#wipe", { xPercent: -102 }, 0);
        PL.wipes.forEach(function (t) {
          tl.fromTo("#wipe", { xPercent: -102 }, { xPercent: 0, duration: 0.24, ease: "power2.in", immediateRender: false }, t - 0.24);
          tl.fromTo("#wipe", { xPercent: 0 }, { xPercent: 102, duration: 0.3, ease: "power2.out", immediateRender: false }, t);
        });

        /* ---------- terminal ---------- */
        function Term(cam, o) {
          this.o = o; this.lh = o.lh; this.rows = 0;
          var el = mk("tw", cam); el.style.cssText = "left:" + o.x + "px;top:" + o.y + "px;width:" + o.w + "px;height:" + o.h + "px";
          var bar = mk("tbar", el); bar.innerHTML = "<i></i><i></i><i></i><span class='tt'>" + o.title + "</span>";
          var body = mk("tbody", el); this.inner = mk("tin", mk("tvp", body));
          this.inner.style.fontSize = o.fs + "px"; this.inner.style.lineHeight = o.lh + "px";
          this.cap = Math.floor((o.h - 46 - 32) / o.lh);
          this.cols = Math.floor((o.w - 40) / (o.fs * 0.6));
          this.lines = [];
          this.el = el;
        }
        Term.prototype.rowsFor = function (n) { return Math.max(1, Math.ceil(n / this.cols)); };
        Term.prototype.grow = function (t, r) {
          this.rows += r;
          if (this.rows > this.cap && !this.noScroll) tl.to(this.inner, { y: -(this.rows - this.cap) * this.lh, duration: 0.18, ease: "power2.out" }, t);
        };
        Term.prototype.mkline = function (html, cls) {
          var ln = mk("ln" + (cls ? " " + cls : ""), this.inner); ln.innerHTML = html; ln._row = -1; return ln;
        };
        Term.prototype.cmd = function (t, lines, cps) {
          var self = this, tx = [], lns = [], lens = [], tot = 0, acc = 0;
          lines.forEach(function (s, i) {
            var ln = self.mkline("<span class='ps'>" + (i === 0 ? "$ " : "&gt; ") + "</span><span class='tx'></span>");
            tx.push(ln.querySelector(".tx")); lns.push(ln); lens.push(s.length); tot += s.length;
          });
          lines.forEach(function (s, i) {
            var ti = i === 0 ? t - 0.22 : t + acc / cps;
            lns[i]._row = self.rows;
            tl.set(lns[i], { opacity: 1 }, ti);
            self.grow(ti, self.rowsFor(s.length + 2));
            acc += s.length;
          });
          var o = { n: 0 };
          tl.to(o, {
            n: tot, duration: tot / cps, ease: "none",
            onUpdate: function () {
              var n = Math.floor(o.n + 1e-6), used = 0;
              for (var i = 0; i < lines.length; i++) {
                var take = Math.max(0, Math.min(lens[i], n - used));
                tx[i].textContent = lines[i].slice(0, take);
                var active = (n < tot) && (n >= used) && (n < used + lens[i] || (i === lines.length - 1));
                tx[i].className = "tx" + (active ? " cur" : "");
                used += lens[i];
              }
            }
          }, t);
          this.lines.push({ els: lns, text: lines.join("\n") });
          return { end: t + tot / cps, first: lns[0] };
        };
        Term.prototype.out = function (t, lines, per, opt) {
          var self = this, els = [];
          opt = opt || {};
          var prevNS = this.noScroll; if (opt.noscroll) this.noScroll = true;
          lines.forEach(function (s, i) {
            var cls = opt.cls ? opt.cls(s, i) : "";
            var html = opt.json ? jsonHtml(s) : esc(s === "" ? " " : s);
            var ln = self.mkline(html, "out " + cls);
            ln._row = self.rows; ln._nrows = self.rowsFor(s.length); ln._text = s; els.push(ln);
            var ti = t + i * per;
            tl.set(ln, { opacity: 1 }, ti);
            self.grow(ti, self.rowsFor(s.length));
          });
          this.noScroll = prevNS;
          this.lines.push({ els: els, text: lines.join("\n"), out: true });
          return { end: t + lines.length * per, els: els };
        };
        Term.prototype.idle = function (t) {
          var ln = this.mkline("<span class='ps'>$ </span><span class='tx cur'></span>");
          ln._row = this.rows; tl.set(ln, { opacity: 1 }, t); this.grow(t, 1);
        };
        Term.prototype.find = function (text, nth) {
          var c = 0;
          for (var b = 0; b < this.lines.length; b++) {
            var blk = this.lines[b]; if (!blk.out) continue;
            for (var i = 0; i < blk.els.length; i++) if (blk.els[i]._text.indexOf(text) >= 0) { if (c === (nth || 0)) return blk.els[i]._row; c++; }
          }
          throw new Error("term.find: not found: " + text);
        };
        Term.prototype.findEl = function (text, nth) {
          var c = 0;
          for (var b = 0; b < this.lines.length; b++) {
            var blk = this.lines[b]; if (!blk.out) continue;
            for (var i = 0; i < blk.els.length; i++) if (blk.els[i]._text.indexOf(text) >= 0) { if (c === (nth || 0)) return blk.els[i]; c++; }
          }
          throw new Error("term.findEl: not found: " + text);
        };
        Term.prototype.hl = function (row, n, t0, t1, kind) {
          var b = mk("hlbar" + (kind ? " " + kind : ""), this.inner);
          b.style.top = (row * this.lh) + "px"; b.style.height = (n * this.lh) + "px";
          tl.fromTo(b, { opacity: 0 }, { opacity: 1, duration: 0.25, immediateRender: false }, t0);
          tl.to(b, { opacity: 0, duration: 0.3 }, t1);
        };
        Term.prototype.scrollRow = function (t, dur, row) {
          tl.to(this.inner, { y: -Math.max(0, row) * this.lh, duration: dur, ease: "power2.inOut" }, t);
        };
        function jsonHtml(s) {
          var e = esc(s);
          e = e.replace(/^(\s*)(&quot;|")([^"]+)("):/, function (m, sp, a, k) { return sp + "<span class='k'>\"" + k + "\":</span>"; });
          e = e.replace(/("(?:[^"\\]|\\.)*")(,?)$/, function (m, str, c) { return "<span class='s'>" + str + "</span>" + c; });
          e = e.replace(/(:\s)(true|false|null|-?\d+)(,?)$/, function (m, a, v, c) { return a + "<span class='v'>" + v + "</span>" + c; });
          return e;
        }

        /* ---------- editor ---------- */
        function hlCode(s, lang) {
          var e = esc(s);
          if (lang === "yaml") {
            if (/^\s*#/.test(s)) return "<span class='c1'>" + e + "</span>";
            return e.replace(/^(\s*-?\s*)([A-Za-z_][\w-]*)(:)/, "$1<span class='c3'>$2</span>$3").replace(/(\[.*\])/, "<span class='c4'>$1</span>");
          }
          var out = "", re = /(#.*$)|(f?"(?:\\.|[^"\\])*"|f?'(?:\\.|[^'\\])*')|\b(import|from|def|return|if|not|raise|as|True|False|None|class|with)\b|(@[\w.]+)/g, last = 0, m;
          while ((m = re.exec(e)) !== null) {
            out += e.slice(last, m.index);
            if (m[1]) out += "<span class='c1'>" + m[1] + "</span>";
            else if (m[2]) out += "<span class='c2'>" + m[2] + "</span>";
            else if (m[3]) out += "<span class='c3'>" + m[3] + "</span>";
            else out += "<span class='c4'>" + m[4] + "</span>";
            last = m.index + m[0].length;
          }
          return out + e.slice(last);
        }
        function Editor(cam, o) {
          this.o = o; this.lh = o.lh;
          var el = mk("tw", cam); el.style.cssText = "left:" + o.x + "px;top:" + o.y + "px;width:" + o.w + "px;height:" + o.h + "px";
          var bar = mk("tbar", el); bar.innerHTML = "<i></i><i></i><i></i><span class='tt'>" + o.title + "</span>";
          var body = mk("tbody", el); this.inner = mk("ein", mk("tvp", body));
          this.inner.style.fontSize = o.fs + "px"; this.inner.style.lineHeight = o.lh + "px";
          this.els = [];
          var self = this;
          o.lines.forEach(function (s, i) {
            var l = mk("el", self.inner);
            l.innerHTML = "<span class='no'>" + (i + 1) + "</span>" + hlCode(s, o.lang);
            self.els.push(l);
          });
        }
        Editor.prototype.reveal = function (t, from, to, gap) {
          for (var i = from; i <= to; i++) {
            if (gap === 0) tl.set(this.els[i - 1], { opacity: 1 }, t);
            else tl.fromTo(this.els[i - 1], { opacity: 0, x: -12 }, { opacity: 1, x: 0, duration: 0.3, ease: EASE, immediateRender: false }, t + (i - from) * gap);
          }
        };
        Editor.prototype.scrollTo = function (t, dur, line) { tl.to(this.inner, { y: -(line - 1) * this.lh, duration: dur, ease: "power2.inOut" }, t); };
        Editor.prototype.focus = function (a, b, t0, t1, kind) {
          var f = mk("fbar" + (kind ? " " + kind : ""), this.inner); f.style.top = ((a - 1) * this.lh) + "px"; f.style.height = ((b - a + 1) * this.lh) + "px";
          tl.fromTo(f, { opacity: 0 }, { opacity: 1, duration: 0.3, immediateRender: false }, t0);
          tl.to(f, { opacity: 0, duration: 0.3 }, t1);
        };

        /* ---------- pipeline strip ---------- */
        var N = 7;
        var LIT = { borderColor: "rgba(154,140,255,0.95)", backgroundColor: "rgba(154,140,255,0.14)" };
        var OFF = { borderColor: "rgba(255,255,255,0.26)", backgroundColor: "rgba(10,10,13,0.9)" };
        var DENY = { borderColor: "rgba(210,166,118,0.95)", backgroundColor: "rgba(210,166,118,0.13)" };
        var ALLOW = { borderColor: "rgba(125,180,255,0.95)", backgroundColor: "rgba(125,180,255,0.14)" };
        function nodeEl(i) { return q("#pn" + i); }
        function pulse(i, t) {
          tl.fromTo("#pc" + i + " b", { x: 0, opacity: 1 }, { x: 40, opacity: 0, duration: 0.32, ease: "power1.in", immediateRender: false }, t);
        }
        function lit(i, t, noConn, kind) {
          tl.to(nodeEl(i), Object.assign({ duration: 0.3 }, kind === "allow" ? ALLOW : LIT), t);
          tl.to("#pn" + i + " .nm", { color: "#fafafa", duration: 0.3 }, t);
          if (i > 0 && !noConn) { tl.to("#pc" + (i - 1) + " i", { scaleX: 1, duration: 0.3, ease: "power2.out" }, t - 0.05); pulse(i - 1, t - 0.1); }
        }
        function deny(i, t) {
          tl.to(nodeEl(i), Object.assign({ duration: 0.3 }, DENY), t);
          tl.to("#pn" + i + " .nm", { color: "#d2a676", duration: 0.3 }, t);
          tl.to("#pn" + i + " .tg", { opacity: 1, duration: 0.3 }, t);
          if (i > 0) { tl.to("#pc" + (i - 1) + " i", { scaleX: 1, backgroundImage: "none", backgroundColor: "#d2a676", duration: 0.3, ease: "power2.out" }, t - 0.05); pulse(i - 1, t - 0.1); }
        }
        function dimAll(t) {
          for (var i = 0; i < N; i++) {
            tl.to(nodeEl(i), Object.assign({ duration: 0.25 }, OFF), t);
            tl.to("#pn" + i + " .nm", { color: "#a7a6ab", duration: 0.25 }, t);
            tl.to("#pn" + i + " .tg", { opacity: 0, duration: 0.2 }, t);
            if (i < N - 1) tl.to("#pc" + i + " i", { scaleX: 0, duration: 0.2 }, t);
          }
        }

        /* ---------- camera ---------- */
        var CX = 960, CY = 413;
        function zoom(cam, t, dur, s, px, py) {
          tl.to(cam, { scale: s, x: (1 - s) * (px - CX), y: (1 - s) * (py - CY), duration: dur, ease: "power2.inOut" }, t);
        }

        /* ---------- captions + status ---------- */
        PL.caps.forEach(function (c) {
          tl.fromTo("#" + c.id, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.45, ease: EASE, immediateRender: false }, c.t0);
          tl.to("#" + c.id, { opacity: 0, duration: 0.3 }, c.t1);
        });
        PL.status.forEach(function (c) {
          tl.fromTo("#" + c.id, { opacity: 0, x: -12 }, { opacity: 1, x: 0, duration: 0.35, ease: EASE, immediateRender: false }, c.t0);
          tl.to("#" + c.id, { opacity: 0, duration: 0.2 }, c.t1 - 0.25);
        });

        /* the strip is there from the first frame, dim, and lights as the story reaches each stage */
        tl.to("#pipe", { opacity: 1, duration: 0.6 }, 0.2);

        /* ---------- scenes 1..7 ---------- */
        var cams = { cam1: q("#cam1"), cam2: q("#cam2"), cam3: q("#cam3"), cam4: q("#cam4"), cam5: q("#cam5"), cam6: q("#cam6") };
        var T = {}, E = {};
        PL.terms.forEach(function (o) { T[o.id] = new Term(cams[o.cam], o); });
        PL.editors.forEach(function (o) { E[o.id] = new Editor(cams[o.cam], Object.assign({}, o, { lines: D[o.data] })); });
        var CLS = {
          allow: function (s) { return /^ALLOW/.test(s) ? "allow" : ""; },
          refuse: function (s) { return "deny"; },
          log: function (s) { return /\[handler\]/.test(s) ? "hi" : (/403 Forbidden/.test(s) ? "deny" : ""); },
          jsonDeny: function (s) { return /"(message|rule)"/.test(s) ? "deny" : ""; },
          verify: function (s) {
            if (/valid=True/.test(s)) return "allow";
            if (/denied|valid=False|chain_break|tampering detected|forged/.test(s)) return "deny";
            return "hi";
          }
        };
        var END = {};
        PL.actions.forEach(function (a) {
          var r;
          if (a.kind === "cmd") r = T[a.term].cmd(a.t, a.lines, a.cps);
          else if (a.kind === "out") r = T[a.term].out(a.t, D[a.data], a.per, { cls: a.cls ? CLS[a.cls] : null, json: !!a.json, noscroll: !!a.noscroll });
          else if (a.kind === "idle") T[a.term].idle(a.t);
          if (a.key) END[a.key] = r;
        });
        PL.events.forEach(function (e) {
          if (e.type === "reveal") E[e.ed].reveal(e.t, e.from, e.to, e.gap);
          else if (e.type === "scrollEd") { if (e.dur) E[e.ed].scrollTo(e.t, e.dur, e.line); else tl.set(E[e.ed].inner, { y: -(e.line - 1) * E[e.ed].lh }, e.t); }
          else if (e.type === "focus") E[e.ed].focus(e.a, e.b, e.t0, e.t1, e.kind);
          else if (e.type === "hlFind") { var row = T[e.term].find(e.find, e.nth || 0); T[e.term].hl(row + (e.off || 0), e.n || 1, e.t0, e.t1, e.kind); }
          else if (e.type === "scrollFind") { var r2 = T[e.term].find(e.find, e.nth || 0); T[e.term].scrollRow(e.t, e.dur, r2 + (e.off || 0)); }
          else if (e.type === "lit") lit(e.node, e.t, !!e.noConn, e.kind);
          else if (e.type === "tag") tl.to("#pn" + e.node + " .tg", { opacity: 1, duration: 0.3 }, e.t);
          else if (e.type === "deny") deny(e.node, e.t);
          else if (e.type === "dimAll") dimAll(e.t);
          else if (e.type === "zoom") zoom(cams[e.cam], e.t, e.dur, e.s, e.px, e.py);
          else if (e.type === "chip") {
            var c = mk("chip " + (e.deny ? "deny" : "allow"), T[e.term].el); c.textContent = e.text;
            tl.fromTo(c, { opacity: 0, scale: 0.9 }, { opacity: 1, scale: 1, duration: 0.35, ease: EASE, immediateRender: false }, e.t);
            if (e.t1) tl.to(c, { opacity: 0, duration: 0.25 }, e.t1);
          }
          else if (e.type === "marker") {
            var tm = T[e.term], me = tm.findEl(e.find, e.nth || 0), m = mk("marker", tm.inner);
            m.textContent = e.text; m.style.top = ((me._row + me._nrows) * tm.lh + 4) + "px"; m.style.height = (tm.lh - 2) + "px"; m.style.lineHeight = (tm.lh - 2) + "px";
            tl.fromTo(m, { opacity: 0, x: -14 }, { opacity: 1, x: 0, duration: 0.4, ease: EASE, immediateRender: false }, e.t);
          }
          else if (e.type === "note") {
            tl.fromTo("#" + e.id, { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.45, ease: EASE, immediateRender: false }, e.t0);
            tl.to("#" + e.id, { opacity: 0, duration: 0.3 }, e.t1);
          }
          else if (e.type === "badge") {
            tl.fromTo("#" + e.id, { opacity: 0, y: 24, scale: 0.96 }, { opacity: 1, y: 0, scale: 1, duration: 0.55, ease: EASE, immediateRender: false }, e.t);
          }
        });

        /* ---------- scene 7: evidence cards ---------- */
        var P7 = PL.s7;
        function cardIn(id, t) { tl.fromTo("#" + id, { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.5, ease: EASE, immediateRender: false }, t); }
        cardIn("ec1", P7.c1); cardIn("ec2", P7.c2);
        tl.set("#cl1", { opacity: 1 }, P7.c2 - 0.3);
        tl.to("#cl1 i", { scaleX: 1, duration: 0.5, ease: "power2.out" }, P7.c2 - 0.3);
        tl.to("#ec1 .stamp, #ec2 .stamp", { opacity: 1, duration: 0.4 }, P7.ok);
        tl.to("#ec1, #ec2", { borderColor: "rgba(125,180,255,0.7)", duration: 0.4 }, P7.ok);
        tl.to("#cs1", { opacity: 1, duration: 0.4 }, P7.c3 - 0.4);
        cardIn("ec3", P7.c3);
        tl.to("#ec3 .stamp", { opacity: 1, duration: 0.4 }, P7.bad);

        /* ---------- scene 8: the whole path, vertical ---------- */
        var P8 = PL.s8;
        for (var vi = 0; vi < N; vi++) {
          var vt = P8.t0 + vi * P8.gap;
          tl.fromTo("#vn" + vi, { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.4, ease: EASE, immediateRender: false }, vt);
          tl.to("#vn" + vi, { borderColor: "rgba(154,140,255,0.9)", backgroundColor: "rgba(154,140,255,0.14)", duration: 0.3 }, vt + 0.1);
          tl.fromTo("#vs" + vi, { opacity: 0, x: -12 }, { opacity: 1, x: 0, duration: 0.4, ease: EASE, immediateRender: false }, vt + 0.15);
          if (vi > 0) {
            tl.set("#vc" + (vi - 1), { opacity: 1 }, vt - 0.2);
            tl.to("#vc" + (vi - 1) + " i", { scaleY: 1, duration: 0.3, ease: "power2.out" }, vt - 0.2);
            tl.fromTo("#vc" + (vi - 1) + " b", { y: 0, opacity: 1 }, { y: 30, opacity: 0, duration: 0.3, ease: "power1.in", immediateRender: false }, vt - 0.22);
          }
        }
        var vt4 = P8.t0 + 4 * P8.gap;
        tl.fromTo("#vt-allow", { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.35, ease: EASE, immediateRender: false }, vt4 + 0.35);
        tl.fromTo("#vt-deny", { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.35, ease: EASE, immediateRender: false }, vt4 + 0.55);
        tl.to("#vn4", { borderColor: "rgba(210,166,118,0.9)", backgroundColor: "rgba(210,166,118,0.13)", duration: 0.3 }, vt4 + 0.6);
        tl.to("#vn4", { borderColor: "rgba(154,140,255,0.9)", backgroundColor: "rgba(154,140,255,0.14)", duration: 0.3 }, vt4 + 1.3);
        document.querySelectorAll("#v-say .ln2").forEach(function (el, i) {
          tl.fromTo(el, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.7, ease: EASE, immediateRender: false }, P8.say + i * 0.9);
        });
        tl.fromTo("#v-foot", { opacity: 0 }, { opacity: 1, duration: 0.6 }, P8.say + 3.0);
        tl.to("#pipe", { opacity: 0, duration: 0.3 }, P8.strip); /* the big version replaces the strip and stays off through the end card */

        /* ---------- scene 9: end card ---------- */
        tl.fromTo("#e-title .mask > span", { yPercent: 115 }, { yPercent: 0, duration: 1.0, ease: SOFT }, PL.s9.title);
        tl.fromTo("#e-tag .mask > span", { yPercent: 115 }, { yPercent: 0, duration: 0.9, ease: EASE, stagger: 0.35 }, PL.s9.tag);
        tl.fromTo("#e-note", { opacity: 0 }, { opacity: 1, duration: 0.8 }, PL.s9.note);
        tl.fromTo("#e-note2", { opacity: 0 }, { opacity: 1, duration: 0.8 }, PL.s9.note + 0.4);

        window.__timelines["main"] = tl;
        tl.seek(0);
      })();
    </script>
  </body>
</html>
