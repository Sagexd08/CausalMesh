"""Builds index.html from template.tpl.

Nothing shown in a terminal is typed by hand here: every output is read from
transcripts/ (captured by running examples/cli_demo/ for real, see
transcripts/README.md), and the code shown in the editors is read from
examples/cli_demo/ itself. The assertions below stop the build if the two
disagree, so the video cannot drift from the fixture.

    python build_index.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TR = HERE / "transcripts"
FIXTURE = HERE.parent.parent / "examples" / "cli_demo"
B = 0.5264  # one beat of the music bed
SC = [0, 13, 30, 49, 68, 93, 114, 140, 154, 165]  # scene starts, in beats; the last is the end


def S(i: int) -> float:
    return round(SC[i] * B, 3)


S1, S2, S3, S4, S5, S6, S7, S8, S9 = (S(i) for i in range(9))
DUR = S(9)


def lines(name: str) -> list[str]:
    return [ln.rstrip() for ln in (TR / name).read_text(encoding="utf-8").splitlines()]


def fixture_lines(name: str) -> list[str]:
    return (FIXTURE / name).read_text(encoding="utf-8").splitlines()


# --------------------------------------------------------------------------- data
gw = lines("gateway.log")
assert gw[0].startswith("INFO:") and "Uvicorn running on http://127.0.0.1:8420" in gw[3]
assert gw[4] == "[handler] write_file src/app.py", gw[4]
assert '"POST /v1/tools/write_file/execute HTTP/1.1" 200 OK' in gw[5]
assert '"POST /v1/tools/write_file/execute HTTP/1.1" 403 Forbidden' in gw[6]
assert not any("production" in ln for ln in gw if ln.startswith("[handler]")), "denied call reached the handler"
assert sum(ln.startswith("[handler]") for ln in gw) == 1

check_allow, check_deny = lines("check_allow.txt"), lines("check_deny.txt")
assert check_allow[0].startswith("ALLOW") and check_deny[0].startswith("REFUSE")
deny_rule = check_deny[1].split()[0]
deny_reason = " ".join(" ".join(check_deny[1:]).split()[1:])
allow_rule = check_allow[1].split()[0]
allow_reason = " ".join(check_allow[1].split()[1:])
assert deny_rule == "ownership" and allow_rule == "default-allow"

exec_allow, exec_deny = lines("exec_allow.txt"), lines("exec_deny.txt")
assert exec_allow[0] == "HTTP 200" and any('"recorded": true' in ln for ln in exec_allow)
assert exec_deny[0] == "HTTP 403" and any('"rule": "ownership"' in ln for ln in exec_deny)
assert any('"recorded": true' in ln for ln in exec_deny)

ev_text = (TR / "evidence.txt").read_text(encoding="utf-8")
assert ev_text.startswith("HTTP 200\n")
ev = json.loads(ev_text.split("\n", 1)[1])
assert len(ev) == 2 and ev[1]["previous_hash"] == ev[0]["chain_hash"], "evidence chain does not link"
assert ev[0]["event"]["payload"]["outcome"] == "executed" and ev[1]["event"]["payload"]["outcome"] == "denied"
assert ev[1]["event"]["payload"]["rule"] == "ownership"

verify = lines("verify.txt")
assert verify[0] == "2 recorded events:" and "denied (rule: ownership)" in verify[2]
assert verify[3] == "recorded chain: valid=True events=2 failures=0"
assert verify[5].startswith("forged copy:") and "valid=False" in verify[6]
m = re.search(r"recorded digest ([0-9a-f]+)\.\.\. does not match recomputed ([0-9a-f]+)\.\.\.", verify[7])
assert m and verify[8] == "tampering detected"
REC, RECOMP = m.group(1), m.group(2)
assert ev[1]["chain_hash"].startswith(REC), "verify output and evidence come from different runs"
H = lambda h: h[:16] + "..."  # noqa: E731

gateway_py = fixture_lines("gateway.py")
demo_yaml = fixture_lines("causalmesh.yaml")
init_yaml = lines("init_causalmesh.yaml")


def find_line(src: list[str], text: str, nth: int = 0) -> int:
    hits = [i + 1 for i, ln in enumerate(src) if text in ln]
    assert len(hits) > nth, f"not found in source: {text!r}"
    return hits[nth]


L_WRITE = find_line(gateway_py, "def write_file(")
L_BUILD = find_line(gateway_py, "def build_mesh(")
L_FROM = find_line(gateway_py, "CausalMesh.from_config(")
L_REG = find_line(gateway_py, "mesh.register_tool(")
L_MUT = find_line(gateway_py, "mutating=True,")
L_RES = find_line(gateway_py, 'resource_args=["path"],')
L_RET = find_line(gateway_py, "return mesh")
L_APPDEF = find_line(gateway_py, "def build_app(")
L_APP = find_line(gateway_py, "create_app(mesh=mesh")
assert L_RET - L_WRITE + 1 <= 23, "write_file..build_mesh no longer fits the editor"
assert L_APP - L_APPDEF < 20

Y_CODING = find_line(demo_yaml, "agent_id: coding-agent")
Y_CODING_OWNS = find_line(demo_yaml, "owns: [src/, tests/]")
Y_DBA = find_line(demo_yaml, "agent_id: dba-agent")
Y_DBA_OWNS = find_line(demo_yaml, "owns: [production/]")
Y_INIT_OWNS = find_line(init_yaml, "owns: []")

DATA = {
    "init": lines("init.txt"),
    "validate": lines("validate.txt"),
    "show": lines("show.txt"),
    "log_start": gw[0:4],
    "log_handler": [gw[4]],
    "log_200": [gw[5]],
    "log_403": [gw[6]],
    "check_allow": check_allow,
    "check_deny": check_deny,
    "exec_allow": exec_allow,
    "exec_deny": exec_deny,
    "v_hdr": verify[0:1],
    "v_e1": verify[1:2],
    "v_e2": verify[2:3],
    "v_ok": verify[3:4],
    "v_forged": verify[4:6],
    "v_bad": verify[6:7],
    "v_chain": verify[7:8],
    "v_end": verify[8:9],
    "gateway_py": gateway_py,
    "demo_yaml": demo_yaml,
    "init_yaml": init_yaml,
}

TOKEN = "cm-demo-token-0001-abcdef"  # the throwaway token printed in examples/cli_demo/README.md
EXPORT = f"export CODING_AGENT_TOKEN={TOKEN}"
assert TOKEN in (FIXTURE / "README.md").read_text(encoding="utf-8")

# --------------------------------------------------------------------------- plan
terms = [
    dict(id="t1", cam="cam1", x=96, y=40, w=760, h=746, fs=17, lh=27, title="bash"),
    dict(id="t2", cam="cam2", x=1068, y=40, w=756, h=746, fs=16, lh=25, title="bash"),
    dict(id="t4", cam="cam4", x=96, y=40, w=1100, h=746, fs=19, lh=30, title="bash"),
    dict(id="tg", cam="cam5", x=96, y=40, w=848, h=746, fs=15, lh=25, title="terminal 1 - gateway"),
    dict(id="tc", cam="cam5", x=976, y=40, w=848, h=746, fs=15, lh=25, title="terminal 2 - client"),
    dict(id="t7", cam="cam6", x=96, y=40, w=1728, h=470, fs=19, lh=30, title="bash"),
]
editors = [
    dict(id="e1", cam="cam1", x=890, y=40, w=934, h=746, fs=17, lh=27, title="causalmesh.yaml  (written by causalmesh init)", lang="yaml", data="init_yaml"),
    dict(id="e2", cam="cam2", x=96, y=40, w=940, h=746, fs=17, lh=27, title="examples/cli_demo/causalmesh.yaml", lang="yaml", data="demo_yaml"),
    dict(id="e3", cam="cam3", x=96, y=40, w=1080, h=746, fs=18, lh=28, title="examples/cli_demo/gateway.py", lang="py", data="gateway_py"),
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


def say(cid, t0, t1, text, kind=""):
    status.append(dict(id=cid, t0=round(t0, 3), t1=round(t1, 3), html=text, kind=kind))


def cap(cid, t0, t1, n, text, kind=""):
    caps.append(dict(id=cid, t0=round(t0, 3), t1=round(t1, 3), n=n, text=text, kind=kind))


def ev_(**kw):
    kw = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in kw.items()}
    events.append(kw)


def zoom(cam, t, dur, s, px, py):
    ev_(type="zoom", cam=cam, t=t, dur=dur, s=s, px=px, py=py)


def dim(t):
    ev_(type="dimAll", t=t)


DEV, SDK, GATE, POL, VERD, TOOL, EVID = range(7)

# ---- scene 1: causalmesh init
t0 = S1
e = cmd("t1", t0 + 0.6, ["causalmesh init"], 22)
e = out("t1", e + 0.3, "init", 0.42)
actions.append(dict(kind="idle", term="t1", t=round(t0 + 3.0, 3)))
ev_(type="reveal", ed="e1", **{"from": 1}, to=24, gap=0.06, t=t0 + 2.3)
ev_(type="focus", ed="e1", a=Y_INIT_OWNS, b=Y_INIT_OWNS, t0=t0 + 4.3, t1=t0 + 6.5)
ev_(type="lit", node=DEV, t=t0 + 0.7, noConn=True)
say("st1a", t0 + 2.4, t0 + 4.3, "<b>causalmesh init</b> writes a starter contract: causalmesh.yaml")
say("st1b", t0 + 4.4, t0 + 6.6, "next: fill in <b>owns</b>, the paths each agent may touch")
zoom("cam1", t0 + 0.3, 6.2, 1.05, 900, 300)
cap("cap1", t0 + 0.4, t0 + 6.6, 1, "Start with a policy.")

# ---- scene 2: declare ownership; validate; show
t0 = S2
dim(t0 + 0.05)
ev_(type="reveal", ed="e2", **{"from": 1}, to=len(demo_yaml), gap=0.05, t=t0 + 0.3)
say("st2a", t0 + 0.4, t0 + 1.5, "the demo's contract: <b>examples/cli_demo/causalmesh.yaml</b>")
ev_(type="focus", ed="e2", a=Y_CODING, b=Y_CODING_OWNS, t0=t0 + 1.5, t1=t0 + 3.0)
say("st2b", t0 + 1.5, t0 + 3.0, "<b>coding-agent</b> owns src/ and tests/")
ev_(type="focus", ed="e2", a=Y_DBA, b=Y_DBA_OWNS, t0=t0 + 3.0, t1=t0 + 4.4)
say("st2c", t0 + 3.0, t0 + 4.4, "<b>dba-agent</b> owns production/")
ev_(type="lit", node=POL, t=t0 + 1.5, noConn=True)
e = cmd("t2", t0 + 3.6, ["causalmesh policy validate"], 50)
e = out("t2", e + 0.25, "validate", 0.35)
e = cmd("t2", t0 + 5.3, ["causalmesh policy show"], 45)
e = out("t2", e + 0.25, "show", 0.13)
say("st2d", t0 + 6.6, t0 + 8.9, "arm C3: the gate refuses. Other arms only record what it would have refused.")
zoom("cam2", t0 + 0.3, 2.6, 1.12, 520, 380)
zoom("cam2", t0 + 3.3, 1.0, 1.08, 1300, 300)
cap("cap2", t0 + 0.3, t0 + 8.7, 2, "Declare who may touch what.")

# ---- scene 3: gateway.py
t0 = S3
dim(t0 + 0.05)
ev_(type="scrollEd", ed="e3", line=L_WRITE, t=t0)
ev_(type="reveal", ed="e3", **{"from": L_WRITE}, to=L_RET, gap=0.04, t=t0 + 0.3)
ev_(type="reveal", ed="e3", **{"from": L_RET + 1}, to=len(gateway_py), gap=0, t=t0 + 0.1)
say("st3a", t0 + 0.4, t0 + 1.4, "<b>write_file</b>: a plain function that knows nothing about policy")
steps = [
    (L_FROM, L_FROM, "nt1", 1.5, 3.0, SDK),
    (L_REG, L_REG, "nt2", 3.0, 4.5, SDK),
    (L_MUT, L_MUT, "nt3", 4.5, 6.0, None),
    (L_RES, L_RES, "nt4", 6.0, 7.4, None),
]
for a, b, nid, s0_, s1_, node in steps:
    ev_(type="focus", ed="e3", a=a, b=b, t0=t0 + s0_, t1=t0 + s1_)
    ev_(type="note", id=nid, t0=t0 + s0_, t1=t0 + s1_ - 0.05)
ev_(type="lit", node=SDK, t=t0 + 1.6, noConn=True)
ev_(type="scrollEd", ed="e3", line=L_APPDEF, dur=0.7, t=t0 + 7.4)
ev_(type="focus", ed="e3", a=L_APP, b=L_APP, t0=t0 + 8.3, t1=t0 + 9.8)
ev_(type="note", id="nt5", t0=t0 + 8.3, t1=t0 + 9.8)
ev_(type="lit", node=GATE, t=t0 + 8.3, noConn=True)
audio.append(("rollover2.ogg", t0 + 1.5, 0.06, 0.5))
audio.append(("rollover2.ogg", t0 + 4.5, 0.06, 0.5))
audio.append(("rollover2.ogg", t0 + 6.0, 0.06, 0.5))
zoom("cam3", t0 + 0.3, 1.2, 1.06, 800, 330)
cap("cap3", t0 + 0.3, t0 + 9.8, 3, "Put your tool behind the SDK.")

# ---- scene 4: policy checks
t0 = S4
dim(t0 + 0.05)
ev_(type="lit", node=POL, t=t0 + 0.3, noConn=True)
CHECK = "causalmesh policy check --agent coding-agent --kind path --name "
e = cmd("t4", t0 + 0.4, [CHECK + "src/app.py"], 80)
e = out("t4", e + 0.2, "check_allow", 0.25, cls="allow")
ev_(type="badge", id="bd1", t=t0 + 1.75)
ev_(type="lit", node=VERD, t=t0 + 1.75, noConn=True, kind="allow")
audio.append(("impactGlass_light_002.ogg", t0 + 1.7, 0.21, 0.6))
say("st4a", t0 + 1.7, t0 + 4.1, "asks the gate, records nothing: <b>ALLOW</b>, exit code 0", kind="allow")
dim(t0 + 4.15)
ev_(type="lit", node=POL, t=t0 + 4.2, noConn=True)
e = cmd("t4", t0 + 4.4, [CHECK + "production/schema.sql"], 90)
e = out("t4", e + 0.2, "check_deny", 0.3, cls="refuse")
ev_(type="badge", id="bd2", t=t0 + 5.75)
ev_(type="deny", node=VERD, t=t0 + 5.75)
audio.append(("impactSoft_heavy_002.ogg", t0 + 5.7, 0.58, 0.55))
ev_(type="hlFind", term="t4", find="ownership", n=1, t0=t0 + 6.4, t1=t0 + 9.0, nth=0, kind="deny")
say("st4b", t0 + 5.8, t0 + 9.8, f"<b>rule: {deny_rule}</b>  {deny_reason}", kind="deny")
zoom("cam4", t0 + 0.3, 9.0, 1.04, 700, 300)
cap("cap4", t0 + 0.3, t0 + 9.8, 4, "The gate decides before execution.")

# ---- scene 5: the gateway and an authorized call
t0 = S5
dim(t0 + 0.05)
e = cmd("tg", t0 + 0.5, [EXPORT], 130)
e = cmd("tg", t0 + 1.4, ["python gateway.py"], 35)
e = out("tg", t0 + 2.1, "log_start", 0.3, cls="log")
ev_(type="lit", node=GATE, t=t0 + 2.2, noConn=True)
say("st5a", t0 + 2.4, t0 + 4.4, "the gateway listens on <b>127.0.0.1:8420</b>")
e = cmd("tc", t0 + 3.6, [EXPORT], 130)
e = cmd("tc", t0 + 4.4, ['python client.py write src/app.py "print(1)"'], 40, key="post_a")
for i, dt in enumerate([0, 0.25, 0.5, 0.75]):
    ev_(type="lit", node=i, t=t0 + 5.7 + dt)
say("st5b", t0 + 5.7, t0 + 6.9, "<b>1</b>  the gateway asks the policy first")
ev_(type="lit", node=VERD, t=t0 + 6.9, kind="allow")
say("st5c", t0 + 6.9, t0 + 8.3, "<b>2</b>  ALLOW: only now does the handler run", kind="allow")
out("tg", t0 + 7.2, "log_handler", 0.1, cls="log")
ev_(type="lit", node=TOOL, t=t0 + 7.2)
audio.append(("drop_002.ogg", t0 + 7.2, 0.19, 0.6))
out("tg", t0 + 7.55, "log_200", 0.1, cls="log")
out("tc", t0 + 7.7, "exec_allow", 0.05, json_=True, key="exec_a")
ev_(type="chip", term="tc", text="200  ALLOWED", deny=False, t=t0 + 7.7, t1=S6 + 3.4)
ev_(type="lit", node=EVID, t=t0 + 8.5)
ev_(type="hlFind", term="tc", find='"recorded": true', n=1, t0=t0 + 9.2, t1=t0 + 11.7, nth=0)
ev_(type="hlFind", term="tc", find='"event_id"', n=1, t0=t0 + 9.2, t1=t0 + 11.7, nth=0)
say("st5d", t0 + 8.4, t0 + 12.6, "<b>3</b>  recorded: true, with an event_id", kind="allow")
zoom("cam5", t0 + 7.0, 0.7, 1.07, 520, 250)
zoom("cam5", t0 + 8.1, 0.8, 1.07, 1400, 300)
zoom("cam5", t0 + 11.8, 0.9, 1.0, 960, 413)
cap("cap5", t0 + 3.4, t0 + 12.8, 5, "Authorized: the tool runs.", kind="allow")

# ---- scene 6: a denied call, same panes
t0 = S6
dim(t0 + 0.1)
e = cmd("tc", t0 + 0.5, ['python client.py write production/schema.sql "DROP TABLE users;"'], 45, key="post_d")
say("st6a", t0 + 2.0, t0 + 3.3, "the same call, another path")
for i, dt in enumerate([0, 0.2, 0.4, 0.6]):
    ev_(type="lit", node=i, t=t0 + 2.2 + dt)
ev_(type="deny", node=VERD, t=t0 + 3.3)
say("st6b", t0 + 3.3, t0 + 4.9, "the policy refuses before the handler is reached", kind="deny")
out("tc", t0 + 3.6, "exec_deny", 0.08, json_=True, cls="jsonDeny", key="exec_d")
ev_(type="chip", term="tc", text="403  DENIED", deny=True, t=t0 + 3.6)
out("tg", t0 + 3.85, "log_403", 0.1, cls="log")
audio.append(("impactSoft_medium_001.ogg", t0 + 3.85, 0.19, 0.6))
ev_(type="tag", node=TOOL, t=t0 + 4.2)
ev_(type="marker", term="tg", find="403 Forbidden", nth=0, text="no [handler] line for this request: the tool never ran", t=t0 + 4.5)
say("st6c", t0 + 4.9, t0 + 7.5, "no [handler] line: <b>the tool never ran</b>", kind="deny")
ev_(type="hlFind", term="tc", find='"rule": "ownership"', n=1, t0=t0 + 5.6, t1=t0 + 7.6, nth=0, kind="deny")
ev_(type="lit", node=EVID, t=t0 + 7.7)
ev_(type="hlFind", term="tc", find='"recorded": true', n=1, t0=t0 + 7.8, t1=t0 + 10.2, nth=1)
say("st6d", t0 + 7.6, t0 + 10.7, "and the denial is <b>recorded</b> as evidence")
zoom("cam5", t0 + 3.7, 0.8, 1.07, 520, 340)
zoom("cam5", t0 + 5.3, 0.8, 1.07, 1400, 300)
zoom("cam5", t0 + 9.6, 0.9, 1.0, 960, 413)
cap("cap6", t0 + 0.3, t0 + 10.7, 6, "Denied: the handler never runs.", kind="deny")

# ---- scene 7: evidence and tamper detection
t0 = S7
dim(t0 + 0.1)
ev_(type="lit", node=EVID, t=t0 + 0.4, noConn=True)
e = cmd("t7", t0 + 0.4, ["python verify_evidence.py --tamper"], 40)
out("t7", t0 + 1.5, "v_hdr", 0.3, cls="verify")
out("t7", t0 + 2.0, "v_e1", 0.3, cls="verify")
out("t7", t0 + 3.0, "v_e2", 0.3, cls="verify")
out("t7", t0 + 4.6, "v_ok", 0.3, cls="verify")
out("t7", t0 + 6.2, "v_forged", 0.3, cls="verify")
out("t7", t0 + 7.9, "v_bad", 0.3, cls="verify")
out("t7", t0 + 8.9, "v_chain", 0.3, cls="verify")
out("t7", t0 + 10.3, "v_end", 0.3, cls="verify")
ev_(type="hlFind", term="t7", find="valid=True", n=1, t0=t0 + 4.7, t1=t0 + 6.1, nth=0)
ev_(type="hlFind", term="t7", find="valid=False", n=1, t0=t0 + 8.0, t1=t0 + 9.5, nth=0, kind="deny")
ev_(type="hlFind", term="t7", find="tampering detected", n=1, t0=t0 + 10.4, t1=t0 + 13.0, nth=0, kind="deny")
say("st7a", t0 + 1.6, t0 + 4.4, "the gateway's recorded events: <b>signed</b> and hash-linked")
say("st7b", t0 + 4.6, t0 + 6.5, "<b>valid=True</b>  verified against the operator's key ring", kind="allow")
say("st7c", t0 + 6.5, t0 + 8.7, "the demo rewrites the denial to say it <b>executed</b>", kind="deny")
say("st7d", t0 + 8.7, t0 + 13.4, "<b>valid=False</b>  the rewritten event no longer matches its hash", kind="deny")
audio.append(("drop_002.ogg", t0 + 2.0, 0.19, 0.5))
audio.append(("impactGlass_light_002.ogg", t0 + 4.7, 0.21, 0.6))
audio.append(("impactSoft_heavy_002.ogg", t0 + 8.0, 0.58, 0.55))
zoom("cam6", t0 + 0.3, 1.2, 1.04, 700, 300)
zoom("cam6", t0 + 6.2, 1.0, 1.06, 960, 600)
cap("cap7", t0 + 0.3, t0 + 13.3, 7, "Every call leaves evidence.")
P7 = dict(c1=t0 + 2.0, c2=t0 + 3.0, ok=t0 + 4.8, c3=t0 + 6.5, bad=t0 + 8.0)

# ---- scenes 8 and 9
P8 = dict(t0=S8 + 0.4, gap=0.55, say=S8 + 3.4, strip=S8)
P9 = dict(t=S9, title=S9 + 0.3, tag=S9 + 1.4, note=S9 + 3.3)
audio.append(("card-slide-1.ogg", S8 + 0.4, 0.6, 0.5))
audio.append(("impactBell_heavy_004.ogg", S9 + 0.35, 0.3, 0.7))

PLAN = dict(
    dur=DUR,
    wipes=[S2, S3, S4, S5, S7, S8, S9],
    caps=[dict(id=c["id"], t0=c["t0"], t1=c["t1"]) for c in caps],
    status=[dict(id=s["id"], t0=s["t0"], t1=s["t1"]) for s in status],
    terms=terms,
    editors=editors,
    actions=actions,
    events=events,
    s7={k: round(v, 3) for k, v in P7.items()},
    s8={k: round(v, 3) for k, v in P8.items()},
    s9={k: round(v, 3) for k, v in P9.items()},
)

# ------------------------------------------------------------------ html fragments
names = ["Developer", "SDK", "Gateway", "Policy", "ALLOW / DENY", "Tool", "Evidence"]
tags = {VERD: "REFUSED", TOOL: "NOT RUN"}
pipe = ""
for i, n in enumerate(names):
    pipe += f'<div class="pn" id="pn{i}"><span class="ix">0{i + 1}</span><span class="nm">{n}</span><span class="tg">{tags.get(i, "")}</span></div>'
    if i < len(names) - 1:
        pipe += f'<div class="pc" id="pc{i}"><i></i><b></b></div>'

status_html = "".join(f'<div class="st {s["kind"]}" id="{s["id"]}">{s["html"]}</div>' for s in status)
caps_html = "".join(
    f'<div class="cap {c["kind"]}" id="{c["id"]}"><span class="n">{c["n"]:02d} / 07</span><span class="t">{c["text"]}</span></div>' for c in caps
)

notes = [
    ("nt1", "1  CausalMesh.from_config", "Loads the contract the CLI just validated."),
    ("nt2", "2  mesh.register_tool", "The tool goes behind the SDK. Its handler stays a plain function."),
    ("nt3", "3  mutating=True", "The gate is consulted before the handler runs."),
    ("nt4", '4  resource_args=["path"]', "The argument the gate checks against the contract's owns."),
    ("nt5", "5  create_app(mesh=mesh)", "Serves the same mesh over HTTP. Calls arrive at /v1/tools/{name}/execute."),
]
notes_html = "".join(f'<div class="note" id="{i}"><div class="a">{a}</div><div class="b">{b}</div></div>' for i, a, b in notes)

badges_html = (
    '<div class="badge allow" id="bd1" style="top:40px"><div class="lb">POLICY CHECK  /  EXIT CODE 0</div>'
    f'<div class="w">ALLOW</div><div class="tg">{check_allow[0].split()[1]}</div>'
    f'<div class="rl"><b>{allow_rule}</b><br>{allow_reason}</div></div>'
    '<div class="badge deny" id="bd2" style="top:426px"><div class="lb">POLICY CHECK  /  EXIT CODE 1</div>'
    f'<div class="w">REFUSE</div><div class="tg">{check_deny[0].split()[1]}</div>'
    f'<div class="rl">rule: <b>{deny_rule}</b><br>{deny_reason}</div></div>'
)

e0, e1_ = ev[0], ev[1]
cards_html = (
    '<div class="ecard" id="ec1" style="left:96px;width:480px"><span class="stamp">VERIFIED</span>'
    '<div class="h">EVENT 1 - WRITE</div>'
    f'<div><span class="k">path</span><span class="v">{e0["event"]["paths"][0]}</span></div>'
    f'<div><span class="k">outcome</span><span class="v">{e0["event"]["payload"]["outcome"]}</span></div>'
    f'<div><span class="k">agent</span><span class="v">{e0["event"]["identity"]["agent_id"]}</span></div>'
    '<div><span class="k">signature</span><span class="v">ed25519</span></div>'
    f'<div><span class="k">chain_hash</span><span class="hv">{H(e0["chain_hash"])}</span></div></div>'
    '<div class="clink" id="cl1" style="left:576px"><span>previous_hash</span><i></i></div>'
    '<div class="ecard" id="ec2" style="left:700px;width:480px"><span class="stamp">VERIFIED</span>'
    '<div class="h">EVENT 2 - FAILURE</div>'
    f'<div><span class="k">path</span><span class="v">{e1_["event"]["paths"][0]}</span></div>'
    f'<div><span class="k">outcome</span><span class="v">{e1_["event"]["payload"]["outcome"]} (rule: {e1_["event"]["payload"]["rule"]})</span></div>'
    f'<div><span class="k">previous_hash</span><span class="hv">{H(e1_["previous_hash"])}</span></div>'
    f'<div><span class="k">chain_hash</span><span class="hv">{H(e1_["chain_hash"])}</span></div></div>'
    '<div class="csep" id="cs1" style="left:1180px">if one<br>record is<br>rewritten:</div>'
    '<div class="ecard bad" id="ec3" style="left:1304px;width:520px"><span class="stamp">REJECTED</span>'
    '<div class="h">EVENT 2 - REWRITTEN</div>'
    f'<div><span class="k">path</span><span class="v">{e1_["event"]["paths"][0]}</span></div>'
    '<div><span class="k">outcome</span><span class="v d">executed  (edited)</span></div>'
    f'<div><span class="k">recorded</span><span class="hv">{REC}...</span></div>'
    f'<div><span class="k">recomputed</span><span class="v d">{RECOMP}...</span></div>'
    '<div><span class="k">verify_chain</span><span class="v d">chain_break</span></div></div>'
)

vsubs = [
    "your agent and your tools",
    "<b>from_config</b>, <b>register_tool</b>",
    "<b>create_app(mesh=mesh)</b>",
    "the contract: <b>ownership</b>, arm C3",
    "decided <b>before</b> the handler runs",
    "<b>write_file</b> runs only after ALLOW",
    "signed, hash-chained. <b>Denials too.</b>",
]
vp = ""
for i, n in enumerate(names):
    y = 150 + i * 108
    vp += f'<div class="vn" id="vn{i}" style="top:{y}px"><span class="ix">0{i + 1}</span><span class="nm">{n}</span></div>'
    vp += f'<div class="vsub" id="vs{i}" style="top:{y}px"><span>{vsubs[i]}</span></div>'
    if i < len(names) - 1:
        vp += f'<div class="vc" id="vc{i}" style="top:{y + 73}px"><i></i><b></b></div>'
y4 = 150 + VERD * 108
vp += f'<div class="vtag allow" id="vt-allow" style="left:352px;top:{y4 + 23}px">ALLOW</div>'
vp += f'<div class="vtag deny" id="vt-deny" style="left:440px;top:{y4 + 23}px">DENY</div>'

audio_html = ""
for n, (src, t, d, v) in enumerate(sorted(audio, key=lambda a: a[1])):
    audio_html += f'<audio id="sfx{n}" src="assets/sfx/{src}" data-start="{round(t, 3)}" data-duration="{d}" data-track-index="{20 + n}" data-volume="{v}"></audio>\n      '

html = (HERE / "template.tpl").read_text(encoding="utf-8")
rep = {
    "__DUR__": str(DUR), "__FADE0__": str(round(DUR - 2.4, 2)),
    "__S1__": str(S1), "__S1DUR__": str(round(S2 - S1, 3)),
    "__S2__": str(S2), "__S2DUR__": str(round(S3 - S2, 3)),
    "__S3__": str(S3), "__S3DUR__": str(round(S4 - S3, 3)),
    "__S4__": str(S4), "__S4DUR__": str(round(S5 - S4, 3)),
    "__S5__": str(S5), "__S5DUR__": str(round(S7 - S5, 3)),
    "__S7__": str(S7), "__S7DUR__": str(round(S8 - S7, 3)),
    "__S8__": str(S8), "__S8DUR__": str(round(S9 - S8, 3)),
    "__S9__": str(S9), "__S9DUR__": str(round(DUR - S9, 3)),
    "__PIPE__": pipe, "__STATUS__": status_html, "__CAPS__": caps_html,
    "__NOTES__": notes_html, "__BADGES__": badges_html, "__CARDS__": cards_html,
    "__VPIPE__": vp, "__AUDIO__": audio_html,
    "__DATA__": json.dumps(DATA), "__PLAN__": json.dumps(PLAN),
}
for k, v in rep.items():
    assert k in html, k
    html = html.replace(k, v)
leftover = re.findall(r"__[A-Z0-9]+__", html)
assert not leftover, f"unreplaced placeholders: {leftover}"
(HERE / "index.html").write_text(html, encoding="utf-8", newline="\n")
print(f"index.html written: {len(html):,} bytes, {DUR}s, {len(audio)} audio cues, {len(actions)} terminal actions")
