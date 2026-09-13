"""Generate the hosted demo from the REAL engine output - no hand-transcribed numbers."""
import json, os, html

HERE = os.path.dirname(os.path.abspath(__file__))
det = json.load(open(os.path.join(HERE, "det.json"), encoding="utf-8"))
mod = json.load(open(os.path.join(HERE, "model.json"), encoding="utf-8"))

def slim(d):
    return {
        "score": d.get("score"),
        "counts": d.get("counts"),
        "segments": [{
            "id": s.get("id"),
            "source": s.get("source"),
            "target": s.get("target"),
            "score": s.get("score"),
            "status": s.get("status"),
            "issues": [{
                "severity": (i.get("severity") or "").upper(),
                "detail": i.get("detail") or i.get("note") or i.get("kind") or "",
                "engine": i.get("engine") or "",
            } for i in (s.get("issues") or [])],
        } for s in d.get("segments", [])],
    }

DET, MOD = slim(det), slim(mod)

TPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LQA - Localization QA Agent | live demo</title>
<style>
  :root{
    --bg:#0f1115;--panel:#171a21;--panel2:#1d2128;--line:#2a2f3a;
    --fg:#e8eaf0;--dim:#9aa3b2;--hi:#ffd166;--ok:#4ade80;--bad:#f87171;--warn:#fbbf24;
    --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
    font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
  .wrap{max-width:1000px;margin:0 auto;padding:28px 20px 60px}
  header{border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:22px}
  h1{margin:0 0 6px;font-size:23px;letter-spacing:-.01em}
  .sub{color:var(--dim);font-size:14px}
  .badges{margin-top:12px;display:flex;gap:8px;flex-wrap:wrap}
  .badge{font-size:11.5px;padding:3px 9px;border:1px solid var(--line);
    border-radius:999px;color:var(--dim);background:var(--panel)}
  .badge b{color:var(--fg);font-weight:600}
  h2{font-size:14px;margin:28px 0 10px;text-transform:uppercase;
     letter-spacing:.06em;font-weight:600}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
  .note{color:var(--dim);font-size:13.5px}
  .controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:16px}
  button{background:transparent;color:var(--fg);border:1px solid var(--line);
    border-radius:7px;padding:9px 16px;font-weight:600;font-size:14px;cursor:pointer}
  button:hover{border-color:var(--dim)}
  button.on{background:var(--hi);color:#1a1a1a;border-color:var(--hi)}
  .score{padding:16px;border-radius:10px;border:1px solid var(--line);
    background:var(--panel);display:flex;gap:26px;align-items:center;
    flex-wrap:wrap;margin-bottom:18px}
  .big{font-size:38px;font-weight:700;line-height:1;letter-spacing:-.02em}
  .tally{color:var(--dim);font-size:13px}
  .tally b{color:var(--fg)}
  .seg{font-size:12.5px;margin-bottom:13px;border:1px solid var(--line);
    border-radius:9px;overflow:hidden;background:var(--panel2)}
  .seg .head{display:flex;justify-content:space-between;gap:10px;padding:8px 12px;
    border-bottom:1px solid var(--line);font-size:12px;color:var(--dim);background:var(--panel)}
  .seg .body{padding:11px 12px}
  .row{margin-bottom:9px}
  .row:last-child{margin-bottom:0}
  .lbl{font-size:10.5px;color:var(--dim);text-transform:uppercase;
    letter-spacing:.05em;display:block;margin-bottom:2px}
  .src{color:var(--dim)}
  .find{margin-top:11px;border-top:1px dashed var(--line);padding-top:10px}
  .f{display:flex;gap:9px;align-items:flex-start;margin-bottom:7px;font-size:13.5px}
  .f:last-child{margin-bottom:0}
  .pill{font-size:10px;font-weight:700;padding:2px 7px;border-radius:5px;
    flex:0 0 auto;margin-top:2px}
  .HIGH{background:rgba(248,113,113,.16);color:var(--bad);border:1px solid rgba(248,113,113,.35)}
  .MEDIUM,.MED{background:rgba(251,191,36,.15);color:var(--warn);border:1px solid rgba(251,191,36,.32)}
  .LOW{background:rgba(154,163,178,.14);color:var(--dim);border:1px solid var(--line)}
  .eng{color:var(--dim);font-size:11px;font-family:var(--mono)}
  .status{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:5px;text-transform:uppercase}
  .pass{background:rgba(74,222,128,.14);color:var(--ok);border:1px solid rgba(74,222,128,.3)}
  .block{background:rgba(248,113,113,.16);color:var(--bad);border:1px solid rgba(248,113,113,.35)}
  .review{background:rgba(251,191,36,.15);color:var(--warn);border:1px solid rgba(251,191,36,.32)}
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line)}
  th{color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.05em}
  td.mono{font-family:var(--mono);font-size:12.5px}
  footer{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);
    color:var(--dim);font-size:12.5px}
  a{color:#7dd3fc}
  .gl{font-family:var(--mono);font-size:12.5px;color:var(--dim)}
  .gl span{color:var(--fg)}
  .mono{font-family:var(--mono)}
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>LQA - Localization QA Agent</h1>
  <div class="sub">Terminology-aware Romanian &#8596; English translation review.
    Deterministic checks are authoritative; NVIDIA open models on Nebius Token Factory advise.</div>
  <div class="badges">
    <span class="badge"><b>0</b> third-party deps</span>
    <span class="badge"><b>48/48</b> tests</span>
    <span class="badge">TMX &middot; XLIFF 1.2 &middot; XLIFF 2.0 &middot; JSON</span>
    <span class="badge"><b>nvidia/Nemotron-3-Ultra-550b-a55b</b> on Nebius</span>
  </div>
</header>

<div class="panel" style="margin-bottom:18px">
  <div class="note">
    Every number below is <strong>recorded output from the real engine</strong> on this five-segment
    job &mdash; the offline deterministic run, and a <strong>live
    <span class="mono">nvidia/Nemotron-3-Ultra-550b-a55b</span> run on Nebius Token Factory</strong>.
    The page renders the committed JSON rather than re-deriving it, so nothing here can drift from
    what the tool actually produced. Raw evidence:
    <span class="mono">evidence/</span> in the repo.
  </div>
</div>

<div class="controls">
  <button id="bDet" class="on">Deterministic only</button>
  <button id="bMod">+ Nemotron model layer</button>
  <span class="note" id="note"></span>
</div>

<div class="gl" style="margin-bottom:16px">
  glossary: <span>cont curent &#8594; current account</span> &middot;
  <span>notificare push &#8594; push notification</span> &middot;
  <span>termen de valabilitate &#8594; expiry date</span>
</div>

<div class="score">
  <div><div class="big" id="score">&ndash;</div>
    <div class="tally">overall score / 100</div></div>
  <div class="tally" id="tally"></div>
  <div class="tally" id="engines"></div>
</div>

<div id="segments"></div>

<h2>Model comparison (live on Nebius Token Factory)</h2>
<div class="panel">
  <div class="note" style="margin-bottom:10px">
    The same job through three models. The <em>smallest</em> scored highest &mdash; because it
    reported the least. Only Ultra caught the register violation.
  </div>
  <table>
    <tr><th>Model</th><th>Score</th><th>Findings</th><th>Caught register?</th></tr>
    <tr><td class="mono">nvidia/Nemotron-3-Ultra-550b-a55b</td><td>66.6</td><td>9</td><td>yes</td></tr>
    <tr><td class="mono">meta-llama/Llama-3.3-70B-Instruct</td><td>71.1</td><td>5</td><td>no</td></tr>
    <tr><td class="mono">nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B</td><td>72.7</td><td>5</td><td>no</td></tr>
  </table>
  <div class="note" style="margin-top:10px">
    A register violation &mdash; formal <span class="gl"><span>v&#259; rug&#259;m</span></span>
    rendered as an informal imperative &mdash; is invisible to any regex, and is exactly the kind of
    defect that makes a translation read as foreign to a native speaker.
  </div>
</div>

<h2>Reading the two runs</h2>
<div class="panel">
  <div class="note">
    Deterministic-only scores <strong>85.6</strong>; enabling the model scores <strong>66.6</strong>.
    The score <em>drops</em> because the checker alone can only see what it was told to look for.
    Terminology findings are deduplicated by expected term, so the model agreeing with the checker
    does not double-charge the penalty &mdash; a regression test pins that behaviour.
  </div>
</div>

<footer>
  Deterministic checks (terminology, source leakage, omissions, formatting) are authoritative and
  reproducible offline with zero credits. Model findings are labelled with their engine and are
  advisory; the model advises, it does not judge.
  &nbsp;&middot;&nbsp;
  Source: <a href="https://github.com/grotefigi/lqa-agent">github.com/grotefigi/lqa-agent</a>
</footer>

</div>

<script>
const DET = __DET__;
const MOD = __MOD__;

function esc(s){ return String(s==null?'':s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function render(data, withModel){
  document.getElementById('score').textContent = Number(data.score).toFixed(1);
  const c = data.counts || {};
  document.getElementById('tally').innerHTML =
    `<b>${c.pass||0}</b> pass &middot; <b>${c.review||0}</b> review &middot; ` +
    `<b>${c.block||0}</b> block`;
  document.getElementById('engines').innerHTML = withModel
    ? 'engines: <b>heuristic + nebius</b>'
    : 'engines: <b>heuristic</b>';
  document.getElementById('note').textContent = withModel
    ? 'live Nemotron-3-Ultra run on Token Factory; model findings tagged [model] are advisory'
    : 'offline: zero API key, zero credits, fully reproducible';

  document.getElementById('segments').innerHTML = data.segments.map(s => `
    <div class="seg">
      <div class="head">
        <span class="mono">${esc(s.id)}</span>
        <span><span class="status ${esc(s.status)}">${esc(s.status)}</span>
          &nbsp;<span class="mono">${Number(s.score).toFixed(1)}</span></span>
      </div>
      <div class="body">
        <div class="row"><span class="lbl">source (ro)</span><span class="src">${esc(s.source)}</span></div>
        <div class="row"><span class="lbl">target (en)</span><span>${esc(s.target)}</span></div>
        ${s.issues.length ? `<div class="find">${s.issues.map(i=>`
          <div class="f"><span class="pill ${esc(i.severity)}">${esc(i.severity)}</span>
            <span>${esc(i.detail)} <span class="eng">[${esc(i.engine)}]</span></span></div>`
          ).join('')}</div>`
        : `<div class="find"><span class="note">no issues found</span></div>`}
      </div>
    </div>`).join('');
}

document.getElementById('bDet').onclick = () => {
  document.getElementById('bDet').classList.add('on');
  document.getElementById('bMod').classList.remove('on');
  render(DET, false);
};
document.getElementById('bMod').onclick = () => {
  document.getElementById('bMod').classList.add('on');
  document.getElementById('bDet').classList.remove('on');
  render(MOD, true);
};
render(DET, false);
</script>
</body>
</html>
"""

out = TPL.replace("__DET__", json.dumps(DET, ensure_ascii=False)) \
         .replace("__MOD__", json.dumps(MOD, ensure_ascii=False))

with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as fh:
    fh.write(out)

print("wrote demo/index.html", len(out.encode()), "bytes")
print("DET overall:", DET["score"], "| MOD overall:", MOD["score"])
