<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <title>CausalMesh - CLI Demo</title>
    <script src="assets/vendor/gsap.min.js"></script>
    <style>
      @font-face { font-family: "Manrope"; src: url("assets/fonts/Manrope.woff2") format("woff2"); font-weight: 200 800; font-display: block; }
      @font-face { font-family: "JetBrains Mono"; src: url("assets/fonts/JetBrainsMono.woff2") format("woff2"); font-weight: 400 600; font-display: block; }
      /* The site's tokens. Sand is the refusal colour and nothing else. */
      :root {
        --stage: #050505; --panel: #0a0a0a; --fg: #fafafa; --fg2: #d6d5d5; --muted: #a7a6a6; --dim: #8b8a8a;
        --line: rgba(255,255,255,0.10); --line-strong: rgba(255,255,255,0.26);
        --deny: #d2a676; --deny-wash: rgba(210,166,118,0.13);
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
      .muted { color: var(--muted); }

      #bg-grid { background-image: linear-gradient(to right, rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(to bottom, rgba(255,255,255,0.04) 1px, transparent 1px); background-size: 96px 96px; }
      #vignette { background: radial-gradient(ellipse at 50% 45%, transparent 58%, rgba(0,0,0,0.55) 100%); pointer-events: none; }
      #wipe { position: absolute; inset: 0; background: #0c0c0c; z-index: 50; border-right: 2px solid rgba(255,255,255,0.5); }
      #prog { position: absolute; left: 96px; right: 96px; top: 1046px; height: 2px; background: var(--line); }
      #prog-fill { position: absolute; inset: 0; background: var(--fg); transform-origin: 0 50%; transform: scaleX(0); }

      /* pipeline strip: Agent -> SDK -> Gateway -> Policy -> Tool -> Evidence */
      #pipe { position: absolute; left: 96px; top: 40px; width: 1728px; height: 72px; display: flex; align-items: center; opacity: 0; z-index: 40; }
      .pn { position: relative; width: 232px; height: 72px; border: 1px solid var(--line-strong); border-radius: 8px; background: rgba(10,10,10,0.9); padding: 13px 18px; flex: none; }
      .pn .ix { display: block; font-family: "JetBrains Mono", monospace; font-size: 12px; letter-spacing: 0.16em; color: var(--dim); }
      .pn .nm { display: block; margin-top: 6px; font-size: 23px; font-weight: 400; letter-spacing: -0.02em; color: var(--muted); white-space: nowrap; }
      .pn .tg { position: absolute; right: 14px; top: 13px; font-family: "JetBrains Mono", monospace; font-size: 12px; letter-spacing: 0.1em; color: var(--deny); opacity: 0; }
      .pc { position: relative; width: 67px; height: 2px; background: var(--line); flex: none; }
      .pc i { position: absolute; inset: 0; background: var(--fg); transform-origin: 0 50%; transform: scaleX(0); }
      #status { position: absolute; left: 96px; top: 128px; width: 1728px; height: 30px; z-index: 40; }
      .st { position: absolute; left: 0; top: 0; font-family: "JetBrains Mono", monospace; font-size: 17px; color: var(--fg2); opacity: 0; white-space: nowrap; }
      .st b { font-weight: 500; color: var(--fg); }
      .st.deny { color: var(--deny); }
      .st.deny b { color: var(--deny); }
      .cap { position: absolute; left: 96px; top: 1004px; font-family: "JetBrains Mono", monospace; font-size: 16px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--dim); opacity: 0; z-index: 40; white-space: nowrap; }
      .cap b { color: var(--fg); font-weight: 500; }

      /* the stage: everything that zooms lives here, clipped so the strip stays clean */
      .stage { position: absolute; left: 0; top: 166px; width: 1920px; height: 826px; overflow: hidden; z-index: 5; }
      .cam { position: absolute; inset: 0; transform-origin: 50% 50%; }
      .tw { position: absolute; background: var(--panel); border: 1px solid var(--line-strong); border-radius: 10px; overflow: hidden; }
      .tbar { position: absolute; left: 0; right: 0; top: 0; height: 46px; border-bottom: 1px solid var(--line); display: flex; align-items: center; padding: 0 18px; gap: 8px; background: #0e0e0e; }
      .tbar i { width: 11px; height: 11px; border-radius: 50%; border: 1px solid var(--line-strong); }
      .tbar .tt { margin-left: 14px; font-family: "JetBrains Mono", monospace; font-size: 14px; letter-spacing: 0.08em; color: var(--dim); }
      .tbody { position: absolute; left: 0; right: 0; top: 46px; bottom: 0; overflow: hidden; }
      .tvp { position: absolute; left: 0; right: 0; top: 16px; bottom: 16px; overflow: hidden; }
      .tin, .ein { padding: 0 20px; }
      .tin { position: relative; font-family: "JetBrains Mono", monospace; color: var(--fg2); white-space: pre-wrap; word-break: break-all; }
      .tin .ln { opacity: 0; }
      .tin .ps { color: var(--dim); }
      .tin .out { color: var(--muted); }
      .tin .out.hi { color: var(--fg); }
      .tin .out.deny, .tin .deny { color: var(--deny); }
      .tin .out.deny span { color: var(--deny); }
      .tin .cur::after { content: ""; display: inline-block; width: 0.55em; height: 1.05em; margin-left: 1px; vertical-align: text-bottom; background: var(--fg); }
      .tin .k { color: var(--fg2); } .tin .s { color: var(--muted); } .tin .v { color: var(--fg); }
      .hlbar { position: absolute; left: 0; right: 0; background: rgba(255,255,255,0.09); border-left: 3px solid var(--fg); opacity: 0; }
      .hlbar.deny { background: var(--deny-wash); border-left-color: var(--deny); }

      /* editor */
      .ein { position: relative; font-family: "JetBrains Mono", monospace; color: var(--fg2); }
      .el { position: relative; white-space: pre; opacity: 0; }
      .el .no { display: inline-block; width: 44px; margin-right: 18px; text-align: right; color: var(--dim); }
      .el .c1 { color: var(--dim); font-style: italic; } .el .c2 { color: var(--muted); } .el .c3 { color: var(--fg); font-weight: 500; } .el .c4 { color: var(--fg2); }
      .fbar { position: absolute; left: 0; right: 0; background: rgba(255,255,255,0.08); border-left: 3px solid var(--fg); opacity: 0; }
      .notes { position: absolute; left: 1212px; top: 0; width: 612px; }
      .note { position: absolute; left: 0; width: 612px; padding: 22px 26px; border: 1px solid var(--line-strong); border-radius: 10px; background: var(--panel); opacity: 0; }
      .note .a { font-family: "JetBrains Mono", monospace; font-size: 16px; letter-spacing: 0.08em; color: var(--fg); }
      .note .b { margin-top: 10px; font-size: 25px; font-weight: 300; line-height: 1.3; letter-spacing: -0.01em; color: var(--muted); }

      /* title + end card */
      #s0-label { position: absolute; left: 96px; top: 250px; }
      #s0-title { position: absolute; left: 90px; top: 310px; font-size: 150px; }
      #s0-sub { position: absolute; left: 96px; top: 700px; font-family: "JetBrains Mono", monospace; font-size: 22px; color: var(--muted); opacity: 0; letter-spacing: 0.04em; }
      #e-title { position: absolute; left: 0; right: 0; top: 330px; text-align: center; font-size: 170px; }
      #e-tag { position: absolute; left: 0; right: 0; top: 560px; text-align: center; font-size: 44px; font-weight: 300; letter-spacing: -0.02em; color: var(--fg2); }
      #e-note { position: absolute; left: 0; right: 0; top: 760px; text-align: center; font-family: "JetBrains Mono", monospace; font-size: 17px; color: var(--dim); opacity: 0; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080" data-duration="__DUR__" data-fps="30">
      <div id="bg-grid" class="clip" data-start="0" data-duration="__DUR__" data-track-index="0"></div>

      <section id="s0" class="clip" data-start="0" data-duration="__S0DUR__" data-track-index="2" style="z-index:5">
        <div id="s0-label" class="label">product demo / cli walkthrough</div>
        <h1 id="s0-title" class="display"><span class="mask"><span>How developers</span></span><span class="mask"><span>use CausalMesh</span></span></h1>
        <div id="s0-sub">install &gt; declare &gt; serve &gt; execute &gt; verify</div>
      </section>

      <section id="s1" class="clip" data-start="__S1__" data-duration="__S1DUR__" data-track-index="2"><div class="stage"><div class="cam" id="cam1"></div></div></section>

      <section id="s2" class="clip" data-start="__S2__" data-duration="__S2DUR__" data-track-index="2"><div class="stage"><div class="cam" id="cam2"><div class="notes">__NOTES__</div></div></div></section>

      <section id="s3" class="clip" data-start="__S3__" data-duration="__S3DUR__" data-track-index="2"><div class="stage"><div class="cam" id="cam3"></div></div></section>

      <section id="panes" class="clip" data-start="__S4__" data-duration="__PANEDUR__" data-track-index="2"><div class="stage"><div class="cam" id="cam4"></div></div></section>

      <section id="s8" class="clip" data-start="__S8__" data-duration="__S8DUR__" data-track-index="2" style="z-index:5">
        <h2 id="e-title" class="display"><span class="mask"><span>CausalMesh</span></span></h2>
        <div id="e-tag"><span class="mask"><span>The SDK and policy gateway for trustworthy AI agents.</span></span></div>
        <div id="e-note">pre-alpha  |  in-memory evidence  |  no TLS  |  not production-ready</div>
      </section>

      <div id="hud" class="clip" data-start="0" data-duration="__DUR__" data-track-index="72" style="z-index:40">
        <div id="pipe">__PIPE__</div>
        <div id="status">__STATUS__</div>
        __CAPS__
        <div id="prog"><div id="prog-fill"></div></div>
      </div>
      <div id="vignette" class="clip" data-start="0" data-duration="__DUR__" data-track-index="70"></div>
      <div id="wipe" class="clip" data-start="0" data-duration="__DUR__" data-track-index="60"></div>

      <audio id="music" src="assets/music/happy-beats-business-moves-vol-9-by-ende-dot-app.mp3" data-start="0" data-duration="__DUR__" data-track-index="10" data-volume="0.42"
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
            ln._row = self.rows; ln._text = s; els.push(ln);
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
        Term.prototype.hl = function (row, n, t0, t1, deny) {
          var b = mk("hlbar" + (deny ? " deny" : ""), this.inner);
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
          var out = "", re = /(#.*$)|(f?"(?:\\.|[^"\\])*"|f?'(?:\\.|[^'\\])*')|\b(import|from|def|return|if|not|raise|as|True|False|None|class)\b|(@[\w.]+)/g, last = 0, m;
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
          for (var i = from; i <= to; i++) tl.fromTo(this.els[i - 1], { opacity: 0, x: -12 }, { opacity: 1, x: 0, duration: 0.3, ease: EASE, immediateRender: false }, t + (i - from) * gap);
        };
        Editor.prototype.showAll = function (t) { this.els.forEach(function (e) { tl.set(e, { opacity: 1 }, t); }); };
        Editor.prototype.scrollTo = function (t, dur, line) { tl.to(this.inner, { y: -(line - 1) * this.lh, duration: dur, ease: "power2.inOut" }, t); };
        Editor.prototype.focus = function (a, b, t0, t1) {
          var f = mk("fbar", this.inner); f.style.top = ((a - 1) * this.lh) + "px"; f.style.height = ((b - a + 1) * this.lh) + "px";
          tl.fromTo(f, { opacity: 0 }, { opacity: 1, duration: 0.3, immediateRender: false }, t0);
          tl.to(f, { opacity: 0, duration: 0.3 }, t1);
        };

        /* ---------- pipeline ---------- */
        var LIT = { borderColor: "rgba(250,250,250,0.95)", backgroundColor: "rgba(255,255,255,0.10)" };
        var OFF = { borderColor: "rgba(255,255,255,0.26)", backgroundColor: "rgba(10,10,10,0.9)" };
        var DENY = { borderColor: "rgba(210,166,118,0.95)", backgroundColor: "rgba(210,166,118,0.13)" };
        function nodeEl(i) { return q("#pn" + i); }
        function lit(i, t, noConn) {
          tl.to(nodeEl(i), Object.assign({ duration: 0.3 }, LIT), t);
          tl.to("#pn" + i + " .nm", { color: "#fafafa", duration: 0.3 }, t);
          if (i > 0 && !noConn) tl.to("#pc" + (i - 1) + " i", { scaleX: 1, duration: 0.3, ease: "power2.out" }, t - 0.05);
        }
        function deny(i, t) {
          tl.to(nodeEl(i), Object.assign({ duration: 0.3 }, DENY), t);
          tl.to("#pn" + i + " .nm", { color: "#d2a676", duration: 0.3 }, t);
          tl.to("#pn" + i + " .tg", { opacity: 1, duration: 0.3 }, t);
          if (i > 0) tl.to("#pc" + (i - 1) + " i", { scaleX: 1, backgroundColor: "#d2a676", duration: 0.3, ease: "power2.out" }, t - 0.05);
        }
        function dimAll(t) {
          for (var i = 0; i < 6; i++) {
            tl.to(nodeEl(i), Object.assign({ duration: 0.25 }, OFF), t);
            tl.to("#pn" + i + " .nm", { color: "#a7a6a6", duration: 0.25 }, t);
            tl.to("#pn" + i + " .tg", { opacity: 0, duration: 0.2 }, t);
            if (i < 5) tl.to("#pc" + i + " i", { scaleX: 0, backgroundColor: "#fafafa", duration: 0.2 }, t);
          }
        }

        /* ---------- camera ---------- */
        var CX = 960, CY = 413;
        function zoom(cam, t, dur, s, px, py) {
          tl.to(cam, { scale: s, x: (1 - s) * (px - CX), y: (1 - s) * (py - CY), duration: dur, ease: "power2.inOut" }, t);
        }

        /* ---------- captions + status ---------- */
        PL.caps.forEach(function (c) {
          tl.fromTo("#" + c.id, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.4, ease: EASE, immediateRender: false }, c.t0);
          tl.to("#" + c.id, { opacity: 0, duration: 0.3 }, c.t1);
        });
        PL.status.forEach(function (c) {
          tl.fromTo("#" + c.id, { opacity: 0, x: -12 }, { opacity: 1, x: 0, duration: 0.35, ease: EASE, immediateRender: false }, c.t0);
          tl.to("#" + c.id, { opacity: 0, duration: 0.2 }, c.t1 - 0.25);
        });

        /* ---------- scene 0: title ---------- */
        tl.fromTo("#s0-label", { opacity: 0, x: -24 }, { opacity: 1, x: 0, duration: 0.6, ease: EASE }, PL.s0.label);
        tl.fromTo("#s0-title .mask > span", { yPercent: 115 }, { yPercent: 0, duration: 1.0, ease: SOFT, stagger: 0.14 }, PL.s0.title);
        tl.fromTo("#s0-sub", { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.6, ease: EASE }, PL.s0.sub);
        tl.to("#pipe", { opacity: 1, duration: 0.6 }, PL.s0.pipe);
        for (var pi = 0; pi < 6; pi++) { lit(pi, PL.s0.pipe + 0.4 + pi * 0.22); }
        dimAll(PL.s0.pipeDim);

        /* ---------- scenes 1..7: terminals, editors, events from the plan ---------- */
        var cams = { cam1: q("#cam1"), cam2: q("#cam2"), cam3: q("#cam3"), cam4: q("#cam4") };
        var T = {}, E = {};
        PL.terms.forEach(function (o) { T[o.id] = new Term(cams[o.cam], o); if (o.noScroll) T[o.id].noScroll = true; });
        PL.editors.forEach(function (o) { E[o.id] = new Editor(cams[o.cam], Object.assign({}, o, { lines: D[o.data] })); });
        var CLS = {
          none: null,
          deny: function () { return "deny"; },
          check: function (s, i) { return /^(ALLOW)/.test(s) ? "hi" : ""; },
          checkDeny: function () { return "deny"; },
          log: function (s) { return /\[handler\]/.test(s) ? "hi" : (/403 Forbidden|401 Unauthorized/.test(s) ? "deny" : ""); },
          jsonDeny: function (s) { return /"(message|rule)"/.test(s) ? "deny" : ""; },
          evidence: function () { return ""; }
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
          else if (e.type === "focus") E[e.ed].focus(e.a, e.b, e.t0, e.t1);
          else if (e.type === "hlFind") { var row = T[e.term].find(e.find, e.nth || 0); T[e.term].hl(row + (e.off || 0), e.n || 1, e.t0, e.t1, !!e.deny); }
          else if (e.type === "scrollFind") { var r2 = T[e.term].find(e.find, e.nth || 0); T[e.term].scrollRow(e.t, e.dur, r2 + (e.off || 0)); }
          else if (e.type === "lit") lit(e.node, e.t, !!e.noConn);
          else if (e.type === "tag") tl.to("#pn" + e.node + " .tg", { opacity: 1, duration: 0.3 }, e.t);
          else if (e.type === "scrollKey") T[e.term].scrollRow(e.t, e.dur, END[e.key].first._row + (e.off || 0));
          else if (e.type === "deny") deny(e.node, e.t);
          else if (e.type === "dimAll") dimAll(e.t);
          else if (e.type === "zoom") zoom(cams[e.cam], e.t, e.dur, e.s, e.px, e.py);
          else if (e.type === "note") {
            tl.fromTo("#" + e.id, { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.5, ease: EASE, immediateRender: false }, e.t0);
            if (e.t1) tl.to("#" + e.id, { opacity: 0.35, duration: 0.4 }, e.t1);
          }
        });

        /* ---------- scene 8: end card ---------- */
        for (var ei = 0; ei < 6; ei++) lit(ei, PL.s8.pipe + ei * 0.16);
        tl.fromTo("#e-title .mask > span", { yPercent: 115 }, { yPercent: 0, duration: 1.0, ease: SOFT }, PL.s8.title);
        tl.fromTo("#e-tag .mask > span", { yPercent: 115 }, { yPercent: 0, duration: 0.9, ease: EASE }, PL.s8.tag);
        tl.fromTo("#e-note", { opacity: 0 }, { opacity: 1, duration: 0.8 }, PL.s8.note);

        window.__timelines["main"] = tl;
        tl.seek(0);
      })();
    </script>
  </body>
</html>
