"""Builds index.html from template.tpl and the real transcripts in transcripts/.

Nothing shown in a terminal is typed by hand here: every output is read from
transcripts/, captured by running demo-project/ (see transcripts/README.md).
Timings live in this file so the animation and the audio cues share one source.

    python build_index.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TR = HERE / "transcripts"
B = 0.5264  # one beat of the music bed
SC = [0, 8, 22, 34, 48, 60, 76, 90, 106, 116]  # scene starts, in beats


def S(i: int) -> float:
    return round(SC[i] * B, 3)


DUR = round(SC[9] * B, 3)


def lines(name: str) -> list[str]:
    return [ln.rstrip() for ln in (TR / name).read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------- data
gw_log = lines("gateway.log")
ev = json.loads((TR / "evidence.txt").read_text(encoding="utf-8"))
assert ev[1]["previous_hash"] == ev[0]["chain_hash"], "evidence chain does not link"
LINK = ev[0]["chain_hash"][:12]

DATA = {
    "pip": lines("pip_install.excerpt.txt"),
    "init": lines("init.txt"),
    "ls": ["causalmesh.yaml"],
    "validate": lines("validate.txt"),
    "show": lines("show.txt"),
    "tools": lines("tools.txt"),
    "log_start": gw_log[0:4],
    "log_tools": [gw_log[4]],
    "log_handler": [gw_log[5]],
    "log_200": [gw_log[6]],
    "log_403": [gw_log[7]],
    "log_ev200": [gw_log[8]],
    "log_ev401": [gw_log[9]],
    "check_allow": lines("check_allow.txt"),
    "exec_allow": lines("exec_allow.txt"),
    "check_deny": lines("check_deny.txt"),
    "exec_deny": lines("exec_deny.txt"),
    "evidence": lines("evidence.txt"),
    "noauth": lines("evidence_noauth.txt"),
    "gateway_py": (HERE / "demo-project" / "gateway.py").read_text(encoding="utf-8").splitlines(),
    "yaml": (HERE / "demo-project" / "causalmesh.yaml").read_text(encoding="utf-8").splitlines(),
}
assert "[handler]" in DATA["log_handler"][0] and "200" in DATA["log_200"][0]
assert "403" in DATA["log_403"][0] and "/v1/evidence" in DATA["log_ev200"][0]
assert "401" in DATA["log_ev401"][0] and DATA["check_deny"][0].startswith("REFUSE")

TOKEN = "cm-dev-7f3a9c2e41b8d605"
EXPORT = f"export CODING_AGENT_TOKEN={TOKEN}"
AUTH = '-H "Authorization: Bearer $CODING_AGENT_TOKEN"'


def post_cmd(path: str, content: str) -> list[str]:
    return [
        "curl -s -X POST localhost:8420/v1/tools/write_file/execute \\",
        f"  {AUTH} \\",
        '  -H "Content-Type: application/json" \\',
        "  -d '{\"agent_id\": \"coding-agent\",",
        f'       "arguments": {{"path": "{path}",',
        f'                     "content": "{content}"}}}}\' \\',
        "  | python -m json.tool",
    ]


# --------------------------------------------------------------------------- plan
terms = [
    dict(id="t1", cam="cam1", x=96, y=40, w=1728, h=746, fs=20, lh=31, title="bash"),
    dict(id="t3", cam="cam3", x=948, y=40, w=876, h=746, fs=17, lh=27, title="bash"),
    dict(id="tc", cam="cam4", x=96, y=40, w=808, h=746, fs=16, lh=25, title="terminal 1 - client"),
    dict(id="tg", cam="cam4", x=940, y=40, w=884, h=746, fs=16, lh=25, title="terminal 2 - gateway"),
]
editors = [
    dict(id="e2", cam="cam2", x=96, y=40, w=1080, h=746, fs=19, lh=30, title="gateway.py", lang="py", data="gateway_py"),
    dict(id="e3", cam="cam3", x=96, y=40, w=820, h=746, fs=20, lh=31, title="causalmesh.yaml", lang="yaml", data="yaml"),
]

actions: list[dict] = []
events: list[dict] = []
audio: list[tuple] = []  # (src, start, dur, vol)
status: list[dict] = []
caps: list[dict] = []


def cmd(term, t, text_lines, cps, key=None):
    total = sum(len(s) for s in text_lines)
    end = t + total / cps
    actions.append(dict(kind="cmd", term=term, t=round(t, 3), lines=text_lines, cps=cps, key=key))
    audio.append(("keypress-003.wav", t, 0.25, 0.4))
    audio.append(("keypress-011.wav", end, 0.25, 0.4))
    return end


def out(term, t, data, per, cls=None, json_=False, noscroll=False, key=None):
    actions.append(dict(kind="out", term=term, t=round(t, 3), data=data, per=per, cls=cls, json=json_, noscroll=noscroll, key=key))
    return t + len(DATA[data]) * per


def say(cid, t0, t1, text, deny=False):
    status.append(dict(id=cid, t0=round(t0, 3), t1=round(t1, 3), html=text, deny=deny))


def cap(cid, t0, t1, n, text):
    caps.append(dict(id=cid, t0=round(t0, 3), t1=round(t1, 3), html=f"<b>step {n} / 7</b>&nbsp;&nbsp;{text}"))


def ev_(**kw):
    events.append(kw)


def zoom(cam, t, dur, s, px, py):
    ev_(type="zoom", cam=cam, t=round(t, 3), dur=dur, s=s, px=px, py=py)


# ---- scene 1: install and initialize
t0 = S(1)
e = cmd("t1", t0 + 0.55, ['pip install -e ".[server]"'], 70)
e = out("t1", e + 0.22, "pip", 0.12)
e = cmd("t1", t0 + 2.0, ["mkdir agent-demo && cd agent-demo"], 70)
e = cmd("t1", t0 + 2.9, ["causalmesh init"], 70)
e = out("t1", e + 0.2, "init", 0.15)
e = cmd("t1", t0 + 4.1, ["ls"], 70)
e = out("t1", e + 0.2, "ls", 0.1)
actions.append(dict(kind="idle", term="t1", t=round(t0 + 4.6, 3)))
zoom("cam1", t0 + 0.3, 6.6, 1.05, 900, 300)
cap("cap1", t0 + 0.3, t0 + 7.1, 1, "install and initialize")
say("st1", t0 + 3.5, t0 + 7.0, "<b>causalmesh init</b> writes the contract: causalmesh.yaml")

# ---- scene 2: register a tool
t0 = S(2)
ev_(type="scrollEd", ed="e2", line=7, t=round(t0, 3))
ev_(type="reveal", ed="e2", from_=7, to=28, gap=0.035, t=round(t0 + 0.3, 3))
ev_(type="dimAll", t=round(t0 + 0.05, 3))
ev_(type="focus", ed="e2", a=13, b=15, t0=round(t0 + 1.3, 3), t1=round(t0 + 2.6, 3))
ev_(type="note", id="nt1", t0=round(t0 + 1.3, 3), t1=round(t0 + 2.8, 3))
ev_(type="focus", ed="e2", a=19, b=28, t0=round(t0 + 2.7, 3), t1=round(t0 + 3.5, 3))
ev_(type="focus", ed="e2", a=24, b=24, t0=round(t0 + 3.5, 3), t1=round(t0 + 4.7, 3))
ev_(type="note", id="nt2", t0=round(t0 + 3.5, 3), t1=round(t0 + 4.8, 3))
ev_(type="focus", ed="e2", a=25, b=25, t0=round(t0 + 4.7, 3), t1=round(t0 + 6.0, 3))
ev_(type="note", id="nt3", t0=round(t0 + 4.8, 3))
ev_(type="lit", node=1, t=round(t0 + 2.8, 3), noConn=True)
ev_(type="lit", node=4, t=round(t0 + 3.0, 3), noConn=True)
zoom("cam2", t0 + 0.3, 5.6, 1.04, 700, 300)
cap("cap2", t0 + 0.3, t0 + 6.1, 2, "register a tool")
audio.append(("rollover2.ogg", t0 + 1.3, 0.06, 0.5))
audio.append(("rollover2.ogg", t0 + 3.5, 0.06, 0.5))

# ---- scene 3: declare who may do what
t0 = S(3)
ev_(type="dimAll", t=round(t0 + 0.05, 3))
ev_(type="reveal", ed="e3", from_=1, to=17, gap=0.05, t=round(t0 + 0.3, 3))
ev_(type="focus", ed="e3", a=7, b=7, t0=round(t0 + 1.4, 3), t1=round(t0 + 2.6, 3))
ev_(type="focus", ed="e3", a=11, b=11, t0=round(t0 + 2.6, 3), t1=round(t0 + 3.8, 3))
ev_(type="lit", node=3, t=round(t0 + 1.4, 3), noConn=True)
say("st3a", t0 + 1.4, t0 + 2.6, "<b>coding-agent</b> owns src/ and tests/")
say("st3b", t0 + 2.6, t0 + 3.8, "<b>dba-agent</b> owns production/")
e = cmd("t3", t0 + 3.0, ["causalmesh policy validate"], 70)
e = out("t3", e + 0.2, "validate", 0.12)
e = cmd("t3", t0 + 4.2, ["causalmesh policy show"], 70)
e = out("t3", e + 0.2, "show", 0.1)
say("st3c", t0 + 5.6, t0 + 7.2, "arm C3: the gate refuses. Other arms only record.")
zoom("cam3", t0 + 0.3, 2.6, 1.05, 480, 300)
zoom("cam3", t0 + 3.0, 3.8, 1.05, 1150, 300)
cap("cap3", t0 + 0.3, t0 + 7.2, 3, "declare who may do what")

# ---- scene 4..7: the two terminals
t0 = S(4)
ev_(type="dimAll", t=round(t0 + 0.05, 3))
e = cmd("tg", t0 + 0.3, [EXPORT], 90)
e = cmd("tg", t0 + 1.05, ["python gateway.py"], 70)
gend = out("tg", e + 0.2, "log_start", 0.12, cls="log")
e = cmd("tc", t0 + 2.3, [EXPORT], 90)
e = cmd("tc", t0 + 3.1, [f'curl -s localhost:8420/v1/tools {AUTH} | python -m json.tool'], 110)
out("tc", e + 0.2, "tools", 0.06)
out("tg", e + 0.2, "log_tools", 0.1, cls="log")
ev_(type="lit", node=2, t=round(t0 + 1.9, 3), noConn=True)
say("st4a", t0 + 2.0, t0 + 4.0, "the gateway serves the registered tool over HTTP")
say("st4b", t0 + 4.3, t0 + 6.2, "<b>GET /v1/tools</b> lists write_file")
zoom("cam4", t0 + 0.05, 0.6, 1.12, 1380, 250)
zoom("cam4", t0 + 2.1, 0.8, 1.12, 500, 250)
cap("cap4", t0 + 0.3, t0 + 6.1, 4, "start the gateway")
audio.append(("card-slide-4.ogg", t0 + 1.4, 0.46, 0.5))

# scene 5: authorized execution
t0 = S(5)
ev_(type="dimAll", t=round(t0 + 0.1, 3))
e = cmd("tc", t0 + 0.25, ["causalmesh policy check --agent coding-agent --kind path --name src/app.py"], 100)
e = out("tc", e + 0.2, "check_allow", 0.15, cls="check")
audio.append(("impactGlass_light_002.ogg", e - 0.2, 0.21, 0.6))
say("st5a", t0 + 1.2, t0 + 2.2, "policy check: would this be allowed? <b>records nothing</b>")
e = cmd("tc", t0 + 1.9, post_cmd("src/app.py", "print(1)"), 150, key="post_a")
T = t0 + 4.05
for i, dt in enumerate([0.0, 0.2, 0.4, 0.65]):
    ev_(type="lit", node=i, t=round(T + dt, 3))
say("st5b", t0 + 4.65, t0 + 5.25, "<b>1</b>  the gateway asks the policy first")
out("tg", t0 + 5.15, "log_handler", 0.1, cls="log")
audio.append(("drop_002.ogg", t0 + 5.15, 0.19, 0.6))
ev_(type="lit", node=4, t=round(t0 + 5.15, 3))
say("st5c", t0 + 5.3, t0 + 6.35, "<b>2</b>  only then does the handler run")
out("tc", t0 + 5.45, "exec_allow", 0.04, json_=True, key="exec_a")
ev_(type="lit", node=5, t=round(t0 + 5.5, 3))
out("tg", t0 + 5.7, "log_200", 0.1, cls="log")
ev_(type="hlFind", term="tc", find='"recorded": true', n=1, t0=round(t0 + 6.5, 3), t1=round(t0 + 8.2, 3), nth=0)
ev_(type="hlFind", term="tc", find='"event_id"', n=1, t0=round(t0 + 6.5, 3), t1=round(t0 + 8.2, 3), nth=0)
say("st5d", t0 + 6.45, t0 + 8.3, "<b>3</b>  recorded: true, with an event_id")
zoom("cam4", t0 + 0.05, 0.5, 1.12, 500, 250)
zoom("cam4", t0 + 3.9, 0.6, 1.0, 960, 413)
zoom("cam4", t0 + 5.0, 0.7, 1.15, 1380, 250)
zoom("cam4", t0 + 5.9, 0.8, 1.15, 500, 300)
cap("cap5", t0 + 0.2, t0 + 8.3, 5, "authorized execution")

# scene 6: denied execution
t0 = S(6)
ev_(type="dimAll", t=round(t0 + 0.1, 3))
e = cmd("tc", t0 + 0.2, ["causalmesh policy check --agent coding-agent --kind path --name production/schema.sql"], 110)
e = out("tc", e + 0.2, "check_deny", 0.15, cls="checkDeny")
audio.append(("impactSoft_heavy_002.ogg", e - 0.3, 0.58, 0.55))
say("st6a", t0 + 1.15, t0 + 2.2, "the same check, another path: <b>REFUSE</b>", deny=True)
e = cmd("tc", t0 + 1.9, post_cmd("production/schema.sql", "DROP TABLE users;"), 150, key="post_d")
T = t0 + 4.2
for i, dt in enumerate([0.0, 0.2, 0.4]):
    ev_(type="lit", node=i, t=round(T + dt, 3))
ev_(type="deny", node=3, t=round(t0 + 4.85, 3))
say("st6b", t0 + 4.85, t0 + 5.5, "the policy refuses before the handler is reached", deny=True)
out("tc", t0 + 5.0, "exec_deny", 0.05, json_=True, cls="jsonDeny", key="exec_d")
out("tg", t0 + 5.15, "log_403", 0.1, cls="log")
audio.append(("impactSoft_medium_001.ogg", t0 + 5.15, 0.19, 0.6))
ev_(type="tag", node=4, t=round(t0 + 5.4, 3))
say("st6c", t0 + 5.5, t0 + 6.7, "no [handler] line: <b>the tool never ran</b>", deny=True)
ev_(type="lit", node=5, t=round(t0 + 5.6, 3), noConn=True)
say("st6d", t0 + 6.7, t0 + 7.3, "and the denial is <b>recorded</b> as evidence")
zoom("cam4", t0 + 0.05, 0.5, 1.12, 500, 250)
zoom("cam4", t0 + 4.7, 0.6, 1.0, 960, 413)
zoom("cam4", t0 + 5.15, 0.7, 1.15, 1380, 250)
zoom("cam4", t0 + 6.0, 0.8, 1.15, 500, 300)
cap("cap6", t0 + 0.2, t0 + 7.3, 6, "denied execution")

# scene 7: evidence
t0 = S(7)
ev_(type="dimAll", t=round(t0 + 0.1, 3))
e = cmd("tc", t0 + 0.25, [f'curl -s localhost:8420/v1/evidence {AUTH} | python -m json.tool'], 120, key="ev_cmd")
ev_(type="scrollKey", term="tc", key="ev_cmd", t=round(t0 + 0.2, 3), dur=0.35)
eo = out("tc", e + 0.2, "evidence", 0.012, json_=True, noscroll=True)
out("tg", e + 0.2, "log_ev200", 0.1, cls="log")
audio.append(("drop_002.ogg", e + 0.2, 0.19, 0.55))
ev_(type="lit", node=5, t=round(t0 + 1.3, 3), noConn=True)
ev_(type="hlFind", term="tc", find='"outcome": "executed"', n=1, t0=round(t0 + 2.1, 3), t1=round(t0 + 3.4, 3), nth=0)
say("st7a", t0 + 2.1, t0 + 3.4, "<b>event 1</b>  WRITE, executed, signed")
ev_(type="scrollFind", term="tc", find='"event_id": "sdk_coding-agent_000002"', nth=1, off=-3, t=round(t0 + 3.5, 3), dur=0.5)
ev_(type="hlFind", term="tc", find='"outcome": "denied"', n=1, t0=round(t0 + 4.2, 3), t1=round(t0 + 5.4, 3), nth=0, deny=True)
ev_(type="hlFind", term="tc", find='"rule": "ownership"', n=1, t0=round(t0 + 4.2, 3), t1=round(t0 + 5.4, 3), nth=1, deny=True)
say("st7b", t0 + 4.15, t0 + 5.4, "<b>event 2</b>  the denial is recorded too", deny=True)
ev_(type="scrollFind", term="tc", find='"previous_hash"', nth=1, off=-22, t=round(t0 + 5.5, 3), dur=0.5)
ev_(type="hlFind", term="tc", find='"previous_hash"', n=1, t0=round(t0 + 6.0, 3), t1=round(t0 + 7.0, 3), nth=1)
say("st7c", t0 + 5.55, t0 + 7.0, f"previous_hash <b>{LINK}</b> = chain_hash of event 1")
e = cmd("tc", t0 + 6.9, ["curl -s -o /dev/null -w '%{http_code}\\n' localhost:8420/v1/evidence"], 130)
e = out("tc", e + 0.15, "noauth", 0.1)
out("tg", e - 0.1, "log_ev401", 0.1, cls="log")
say("st7d", t0 + 7.15, t0 + 8.0, "no token: <b>401</b>. No evidence without auth.")
zoom("cam4", t0 + 0.05, 0.5, 1.12, 500, 250)
cap("cap7", t0 + 0.2, t0 + 8.3, 7, "evidence recorded")

# scene 0 / 8 timings
S0 = dict(label=0.3, title=0.55, sub=2.0, pipe=1.2, pipeDim=3.5)
S8 = dict(pipe=0.2, title=1.0, tag=2.0, note=3.2)
audio.append(("card-slide-1.ogg", 0.55, 0.6, 0.6))
audio.append(("impactBell_heavy_004.ogg", S(8) + 1.05, 0.3, 0.8))
ev_(type="dimAll", t=round(S(8) + 0.05, 3))

PLAN = dict(
    dur=DUR,
    wipes=[S(1), S(2), S(3), S(4), S(8)],
    s0=S0, s8={k: round(S(8) + v, 3) for k, v in S8.items()},
    caps=[dict(id=c["id"], t0=c["t0"], t1=c["t1"]) for c in caps],
    status=[dict(id=s["id"], t0=s["t0"], t1=s["t1"]) for s in status],
    terms=terms, editors=editors, actions=actions,
    events=[{("from" if k == "from_" else k): v for k, v in e.items()} for e in events],
)
# the template reads e.type; scrollKey/tag are handled below via the shared interpreter

# ------------------------------------------------------------------ html fragments
names = ["Agent", "CausalMesh SDK", "Gateway", "Policy", "Tool", "Evidence"]
tags = {3: "REFUSED", 4: "NOT RUN"}
pipe = ""
for i, n in enumerate(names):
    pipe += f'<div class="pn" id="pn{i}"><span class="ix">0{i + 1}</span><span class="nm">{n}</span><span class="tg">{tags.get(i, "")}</span></div>'
    if i < 5:
        pipe += f'<div class="pc" id="pc{i}"><i></i></div>'
status_html = "".join(f'<div class="st{" deny" if s["deny"] else ""}" id="{s["id"]}">{s["html"]}</div>' for s in status)
caps_html = "".join(f'<div class="cap" id="{c["id"]}">{c["html"]}</div>' for c in caps)
notes = [
    ("nt1", 40, "1  THE HANDLER", "A plain Python function. Nothing CausalMesh-specific."),
    ("nt2", 222, "2  mutating=True", "The gate is consulted before the handler runs."),
    ("nt3", 404, "3  resource_args", "Names the argument the gate checks against the contract."),
]
notes_html = "".join(f'<div class="note" id="{i}" style="top:{y}px"><div class="a">{a}</div><div class="b">{b}</div></div>' for i, y, a, b in notes)
audio_html = ""
for n, (src, t, d, v) in enumerate(sorted(audio, key=lambda a: a[1])):
    audio_html += f'<audio id="sfx{n}" src="assets/sfx/{src}" data-start="{round(t, 3)}" data-duration="{d}" data-track-index="{20 + n}" data-volume="{v}"></audio>\n      '

html = (HERE / "template.tpl").read_text(encoding="utf-8")
rep = {
    "__DUR__": str(DUR), "__FADE0__": str(round(DUR - 2.4, 2)),
    "__S0DUR__": str(round(S(1), 3)),
    "__S1__": str(S(1)), "__S1DUR__": str(round(S(2) - S(1), 3)),
    "__S2__": str(S(2)), "__S2DUR__": str(round(S(3) - S(2), 3)),
    "__S3__": str(S(3)), "__S3DUR__": str(round(S(4) - S(3), 3)),
    "__S4__": str(S(4)), "__PANEDUR__": str(round(S(8) - S(4), 3)),
    "__S8__": str(S(8)), "__S8DUR__": str(round(DUR - S(8), 3)),
    "__PIPE__": pipe, "__STATUS__": status_html, "__CAPS__": caps_html,
    "__NOTES__": notes_html, "__AUDIO__": audio_html,
    "__DATA__": json.dumps(DATA), "__PLAN__": json.dumps(PLAN),
}
for k, v in rep.items():
    assert k in html, k
    html = html.replace(k, v)
(HERE / "index.html").write_text(html, encoding="utf-8", newline="\n")
print(f"index.html written: {len(html):,} bytes, {DUR}s, {len(audio)} audio cues, {len(actions)} terminal actions")
