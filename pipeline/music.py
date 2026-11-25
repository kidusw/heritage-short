"""Stage: music. An original score from ACE-Step 1.5 (open weights) on a free Kaggle GPU.

    python -m pipeline.music run                 # 3 candidates (3 seeds), wait, download
    python -m pipeline.music submit | status | collect
    python -m pipeline.music choose b "warmer, the krar line sits under the voice"   # pick one, log why
    python -m pipeline.music                     # (from run.py) no-op if a score is already chosen

The score is generated once for the whole film (length = Amharic timeline + end card), from
storyboard.music (prompt, lyrics, bpm). Candidates are cached by a hash of those inputs and the model
settings; changing the music prompt makes new candidates, changing a shot doesn't.
Output: outputs/music/<name>_<hash>.wav and manifest.json {candidates, chosen, why}.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time

from .common import OUTPUTS, cache_key, from_manifest, load_env, load_storyboard, log_call, rel, stage_dir, total_duration
from .wan_kaggle import kaggle, username

STAGE = "music"
KERNEL_SLUG = "heritage-short-music"
KERNEL_SRC = OUTPUTS.parent / "pipeline" / "kaggle" / "acestep_music.py"
NAMES = ["a", "b", "c"]


def config() -> dict:
    e = os.environ.get
    return {"model": e("ACESTEP_MODEL", "ACE-Step/acestep-v15-xl-turbo-diffusers"),
            "steps": int(e("ACESTEP_STEPS", "8")), "guidance": float(e("ACESTEP_GUIDANCE", "1.0")),
            "dtype": e("ACESTEP_DTYPE", "float16")}  # T4 has no fast bf16


def manifest() -> dict:
    p = stage_dir(STAGE) / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"candidates": {}, "chosen": None}


def save(m: dict) -> None:
    (stage_dir(STAGE) / "manifest.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")


def spec(sb: dict) -> dict:
    # Score covers the longest language timeline if a radio cut exists, else the planned length.
    lengths = [json.loads(p.read_text(encoding="utf-8"))["total_s"] for p in (OUTPUTS / "radio").glob("timeline_*.json")]
    duration = round(max(lengths) if lengths else total_duration(sb)) + 2
    m = sb["music"]
    cfg = config()
    key = cache_key(STAGE, cfg, m["prompt"], m.get("lyrics", "[instrumental]"), m.get("bpm"), duration)
    seed = m.get("seed", 42)
    return {"config": cfg, "prompt": m["prompt"], "lyrics": m.get("lyrics", "[instrumental]"), "bpm": m.get("bpm"),
            "duration_s": duration, "key": key,
            "candidates": [{"name": f"{n}_{key}", "label": n, "seed": seed + i} for i, n in enumerate(NAMES)]}


def submit() -> bool:
    sb = load_storyboard()
    sp = spec(sb)
    m = manifest()
    if all(c["label"] in m["candidates"] and m["candidates"][c["label"]].get("key") == sp["key"]
           and from_manifest(m["candidates"][c["label"]]["file"]).exists() for c in sp["candidates"]):
        print("music: candidates for this prompt already exist")
        return False
    user = username()
    kdir = stage_dir(STAGE) / "_kaggle" / "kernel"
    shutil.rmtree(kdir, ignore_errors=True)
    kdir.mkdir(parents=True)
    # A kernel push uploads only the code file, so the job spec is embedded at the top of the script.
    (kdir / "acestep_music.py").write_text(f"SPEC = {json.dumps(sp, ensure_ascii=False)}\n" + KERNEL_SRC.read_text(encoding="utf-8"),
                                          encoding="utf-8")
    (kdir / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{user}/{KERNEL_SLUG}", "title": KERNEL_SLUG, "code_file": "acestep_music.py", "language": "python",
        "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": []}, indent=2), encoding="utf-8")
    t0 = time.perf_counter()
    kaggle("kernels", "push", "-p", str(kdir), "--accelerator", os.environ.get("ACESTEP_ACCELERATOR", "NvidiaTeslaT4"))
    log_call(stage=STAGE, provider="kaggle", model="kernels push", latency_s=time.perf_counter() - t0,
             params={**sp["config"], "duration_s": sp["duration_s"], "seeds": [c["seed"] for c in sp["candidates"]]})
    (stage_dir(STAGE) / "_kaggle" / "submission.json").write_text(json.dumps({"user": user, **sp}, indent=2, ensure_ascii=False),
                                                                    encoding="utf-8")
    print(f"music: submitted 3 candidates, {sp['duration_s']}s each: https://www.kaggle.com/code/{user}/{KERNEL_SLUG}")
    return True


def status() -> str:
    sub = json.loads((stage_dir(STAGE) / "_kaggle" / "submission.json").read_text(encoding="utf-8"))
    out = kaggle("kernels", "status", f"{sub['user']}/{KERNEL_SLUG}", check=False).lower()
    return next((w for w in ("complete", "error", "cancel", "running", "queued") if w in out), out.strip())


def collect() -> None:
    wd = stage_dir(STAGE) / "_kaggle"
    sub = json.loads((wd / "submission.json").read_text(encoding="utf-8"))
    dl = wd / "output"
    shutil.rmtree(dl, ignore_errors=True)
    dl.mkdir()
    kaggle("kernels", "output", f"{sub['user']}/{KERNEL_SLUG}", "-p", str(dl), "-o", "-q")
    res_path = next(dl.rglob("results.json"), None)
    if not res_path:
        raise SystemExit(f"No results.json; see the log at https://www.kaggle.com/code/{sub['user']}/{KERNEL_SLUG}")
    res = json.loads(res_path.read_text(encoding="utf-8"))
    m = manifest()
    for c in sub["candidates"]:
        r = res["candidates"].get(c["name"]) or {"ok": False, "error": "not reached"}
        if r["ok"]:
            dst = stage_dir(STAGE) / r["file"]
            shutil.copy(next(dl.rglob(r["file"])), dst)
            m["candidates"][c["label"]] = {"file": rel(dst), "seed": c["seed"], "key": sub["key"], "gpu_s": r["gpu_s"]}
        print(f"  {'+' if r['ok'] else 'x'} {c['label']} (seed {c['seed']}): {'ok' if r['ok'] else r['error'][:150]}"
              f" ({r.get('gpu_s', 0):.0f}s GPU)")
        log_call(stage=STAGE, provider="kaggle", model=sub["config"]["model"], shot=f"candidate_{c['label']}", seed=c["seed"],
                 params={**sub["config"], "duration_s": sub["duration_s"]}, latency_s=r.get("gpu_s", 0), gpu_s=r.get("gpu_s", 0),
                 status="ok" if r["ok"] else "error", error=r.get("error"), output=m["candidates"].get(c["label"], {}).get("file"))
    if not m.get("chosen") and any(c["label"] in m["candidates"] for c in sub["candidates"]):
        first = next(c["label"] for c in sub["candidates"] if c["label"] in m["candidates"])
        m["chosen"], m["why"] = first, "auto: first successful candidate (run `music choose` after listening)"
    save(m)
    print(f"music: setup {res.get('setup_s')}s on {res.get('gpu')}; chosen = {m.get('chosen')}")


def choose(label: str, why: str) -> None:
    m = manifest()
    if label not in m["candidates"]:
        raise SystemExit(f"No candidate '{label}'. Have: {list(m['candidates'])}")
    m["chosen"], m["why"] = label, why
    save(m)
    log_call(stage=STAGE, provider="human", model="choice", shot=f"candidate_{label}", params={"why": why})
    print(f"music: chose {label}: {why}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", default="ensure", choices=["ensure", "submit", "status", "collect", "run", "choose"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--timeout-min", type=int, default=90)
    a = ap.parse_args(argv)
    load_env()
    if a.action == "ensure":
        m = manifest()
        print(f"music: chosen = {m.get('chosen')}" if m.get("chosen") else
              "music: no score yet (run `python -m pipeline.music run`); the film will be exported without one")
    elif a.action == "submit":
        submit()
    elif a.action == "status":
        print(status())
    elif a.action == "collect":
        collect()
    elif a.action == "choose":
        if len(a.args) < 2:
            raise SystemExit('usage: python -m pipeline.music choose <a|b|c> "why"')
        choose(a.args[0], " ".join(a.args[1:]))
    else:
        if not submit():
            return
        t0 = time.time()
        while time.time() - t0 < a.timeout_min * 60:
            time.sleep(45)
            st = status()
            print(f"  [{(time.time() - t0) / 60:.0f} min] {st}", flush=True)
            if st in ("complete", "error", "cancel"):
                break
        collect()


if __name__ == "__main__":
    main()
