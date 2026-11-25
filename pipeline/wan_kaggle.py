"""Wan 2.2 image-to-video on a free Kaggle GPU, driven from this machine with the official kaggle CLI.

    python -m pipeline.wan_kaggle submit [--shots s03 s04]   # upload keyframes + start the GPU notebook
    python -m pipeline.wan_kaggle rerun                      # re-push the notebook for the last submission
    python -m pipeline.wan_kaggle status                     # queued / running / complete / error
    python -m pipeline.wan_kaggle collect                    # download clips into outputs/shots/wan/
    python -m pipeline.wan_kaggle run [--shots ...]          # submit, wait, collect

Flow: keyframes + jobs.json -> private Kaggle dataset -> private GPU notebook (pipeline/kaggle/wan_i2v.py)
-> clips + results.json -> outputs/shots/wan/ and runs.jsonl (one line per shot, with GPU seconds).
Then `python -m pipeline.shots` uses these clips; any shot without one falls back to Ken Burns.

Clips are cached by a hash of (model, settings, keyframe file, motion prompt, seed): only shots whose
inputs changed are sent to the GPU. Settings can be overridden with WAN_* env vars (see CONFIG).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

from .common import (
    rel, from_manifest,
    KAGGLE_CLI, OUTPUTS, ROOT, cache_key, load_env, load_storyboard, log_call, read_manifest, select_shots,
    shots_blocked_by_consent, stage_dir,
)
from .smoke import kaggle_env

STAGE = "wan"
DATASET_SLUG = "heritage-short-keyframes"
KERNEL_SLUG = "heritage-short-wan"
KERNEL_SRC = ROOT / "pipeline" / "kaggle" / "wan_i2v.py"


def config() -> dict:
    e = os.environ.get
    return {
        "model": e("WAN_MODEL", "Wan-AI/Wan2.2-TI2V-5B-Diffusers"),
        "width": int(e("WAN_SIZE", "640")), "height": int(e("WAN_SIZE", "640")),
        "num_frames": int(e("WAN_FRAMES", "81")),  # must be 4k+1; 81 frames = 3.4 s at 24 fps
        "fps": 24,
        "steps": int(e("WAN_STEPS", "30")),
        "guidance": float(e("WAN_GUIDANCE", "5.0")),
        "dtype": e("WAN_DTYPE", "float16"),
        "negative": "blurry, distorted, warped faces, extra limbs, text, watermark, flicker",
    }


def kaggle(*args: str, check: bool = True) -> str:
    extra = kaggle_env()
    if extra is None:
        raise SystemExit("Kaggle credentials missing: set KAGGLE_API_TOKEN (or KAGGLE_USERNAME + KAGGLE_KEY) in .env")
    res = subprocess.run([*KAGGLE_CLI, *args], capture_output=True, text=True,
                         env={**os.environ, **extra, "PYTHONIOENCODING": "utf-8"})
    if check and res.returncode != 0:
        raise RuntimeError(f"kaggle {' '.join(args)} failed:\n{res.stderr or res.stdout}")
    return (res.stdout or "") + (res.stderr or "")


def username() -> str:
    if os.environ.get("KAGGLE_USERNAME"):
        return os.environ["KAGGLE_USERNAME"]
    out = kaggle("config", "view", check=False)
    for line in out.splitlines():
        if "username" in line.lower() and ":" in line:
            return line.split(":", 1)[1].strip()
    raise SystemExit("Can't tell your Kaggle username: set KAGGLE_USERNAME in .env")


def work_dir() -> "os.PathLike":
    return stage_dir("shots") / "wan" / "_kaggle"


def wan_manifest() -> dict:
    p = stage_dir("shots") / "wan" / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_wan_manifest(m: dict) -> None:
    p = stage_dir("shots") / "wan" / "manifest.json"
    p.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")


def push_kernel(user: str, cfg: dict, shot_ids: list[str]) -> str:
    """Push the GPU notebook against whatever version of the keyframes dataset is on Kaggle now."""
    wd = work_dir()
    kdir = wd / "kernel"
    shutil.rmtree(kdir, ignore_errors=True)
    kdir.mkdir(parents=True)
    shutil.copy(KERNEL_SRC, kdir / "wan_i2v.py")
    (kdir / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{user}/{KERNEL_SLUG}", "title": KERNEL_SLUG, "code_file": "wan_i2v.py", "language": "python",
        "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [f"{user}/{DATASET_SLUG}"], "competition_sources": [], "kernel_sources": [],
    }, indent=2), encoding="utf-8")
    t0 = time.perf_counter()
    out = kaggle("kernels", "push", "-p", str(kdir), "--accelerator", os.environ.get("WAN_ACCELERATOR", "NvidiaTeslaT4"))
    log_call(stage=STAGE, provider="kaggle", model="kernels push", latency_s=time.perf_counter() - t0,
             params={"jobs": shot_ids, **{k: v for k, v in cfg.items() if k != "negative"}})
    return out


def submit(shot_ids: list[str] | None) -> bool:
    sb = load_storyboard()
    cfg = config()
    keyframes = read_manifest("keyframes")
    existing = wan_manifest()
    shots = select_shots(sb, shot_ids)
    blocked = shots_blocked_by_consent(sb, shots)

    wd = work_dir()
    shutil.rmtree(wd / "dataset", ignore_errors=True)
    (wd / "dataset").mkdir(parents=True)
    jobs = []
    for shot in shots:
        sid = shot["id"]
        kf = keyframes.get(sid)
        if sid in blocked:
            print(f"  x {sid}: consent pending, not sent"); continue
        if not kf:
            print(f"  x {sid}: no keyframe yet, not sent"); continue
        if shot.get("video") == "kenburns":
            print(f"  - {sid}: storyboard prefers Ken Burns"); continue
        prompt = f"{shot.get('motion_prompt', '')}. {shot['keyframe_prompt']}. {sb['style']['visual_prefix']}"
        key = cache_key(STAGE, cfg, kf["file"].replace("\\", "/"), prompt, shot.get("seed", 0))
        if existing.get(sid, {}).get("key") == key and from_manifest(existing[sid].get("file", "")).exists():
            print(f"  = {sid}: clip already made for these inputs"); continue
        img_name = from_manifest(kf["file"]).name
        shutil.copy(from_manifest(kf["file"]), wd / "dataset" / img_name)
        jobs.append({"shot": sid, "image": img_name, "prompt": prompt, "seed": shot.get("seed", 0),
                     "out_name": f"{sid}_{key}", "key": key, "keyframe": kf["file"].replace("\\", "/")})
    if not jobs:
        print("wan: nothing to send")
        return False

    user = username()
    (wd / "dataset" / "jobs.json").write_text(json.dumps({"config": cfg, "jobs": jobs}, indent=2, ensure_ascii=False), encoding="utf-8")
    (wd / "dataset" / "dataset-metadata.json").write_text(json.dumps({
        "title": "heritage-short keyframes", "id": f"{user}/{DATASET_SLUG}", "licenses": [{"name": "CC0-1.0"}]}), encoding="utf-8")

    t0 = time.perf_counter()
    status = kaggle("datasets", "status", f"{user}/{DATASET_SLUG}", check=False).strip().lower()
    if "ready" in status or "pending" in status:
        kaggle("datasets", "version", "-p", str(wd / "dataset"), "-m", f"{len(jobs)} jobs", "-q")
    else:
        kaggle("datasets", "create", "-p", str(wd / "dataset"), "-q")
    # A new dataset version takes a moment to process; the notebook must see this version's jobs.json.
    for _ in range(60):
        if "ready" in kaggle("datasets", "status", f"{user}/{DATASET_SLUG}", check=False).lower():
            break
        time.sleep(5)
    log_call(stage=STAGE, provider="kaggle", model="datasets upload", latency_s=time.perf_counter() - t0,
             params={"jobs": len(jobs), "images": len(jobs)})

    out = push_kernel(user, cfg, [j["shot"] for j in jobs])
    (wd / "submission.json").write_text(json.dumps({"user": user, "submitted": time.time(), "jobs": jobs}, indent=2), encoding="utf-8")
    print(out.strip())
    print(f"wan: submitted {len(jobs)} shots to https://www.kaggle.com/code/{user}/{KERNEL_SLUG}")
    return True


def rerun() -> None:
    """Re-push the notebook for the last submission without re-uploading keyframes (e.g. after a kernel fix).
    Useful on a machine that doesn't have the keyframe images: the dataset on Kaggle still does."""
    sub = json.loads((work_dir() / "submission.json").read_text(encoding="utf-8"))
    print(push_kernel(sub["user"], config(), [j["shot"] for j in sub["jobs"]]).strip())
    sub["submitted"] = time.time()
    (work_dir() / "submission.json").write_text(json.dumps(sub, indent=2), encoding="utf-8")
    print(f"wan: re-ran {len(sub['jobs'])} shots at https://www.kaggle.com/code/{sub['user']}/{KERNEL_SLUG}")


def status() -> str:
    sub = json.loads((work_dir() / "submission.json").read_text(encoding="utf-8"))
    out = kaggle("kernels", "status", f"{sub['user']}/{KERNEL_SLUG}", check=False)
    for word in ("complete", "error", "cancel", "running", "queued"):
        if word in out.lower():
            return word
    return out.strip()


def collect() -> None:
    wd = work_dir()
    sub = json.loads((wd / "submission.json").read_text(encoding="utf-8"))
    dl = wd / "output"
    shutil.rmtree(dl, ignore_errors=True)
    dl.mkdir(parents=True)
    kaggle("kernels", "output", f"{sub['user']}/{KERNEL_SLUG}", "-p", str(dl), "-o", "-q")
    res_path = next(dl.rglob("results.json"), None)
    if not res_path:
        raise SystemExit(f"No results.json in the notebook output. Check the log at "
                         f"https://www.kaggle.com/code/{sub['user']}/{KERNEL_SLUG}")
    res = json.loads(res_path.read_text(encoding="utf-8"))
    cfg = res.get("config", {})
    manifest = wan_manifest()
    clip_dir = stage_dir("shots") / "wan"
    for job in sub["jobs"]:
        sid, r = job["shot"], res["jobs"].get(job["shot"])
        if r and r.get("ok"):
            src = next(dl.rglob(r["file"]), None)
            dst = clip_dir / r["file"]
            shutil.copy(src, dst)
            manifest[sid] = {"file": rel(dst), "key": job["key"], "keyframe": job["keyframe"],
                             "gpu_s": r["gpu_s"], "gpu": res.get("gpu")}
            status_, err = "ok", None
        else:
            err = (r or {}).get("error", "not reached (notebook stopped early?)")
            manifest[sid] = {"key": job["key"], "keyframe": job["keyframe"], "error": err}
            status_ = "error"
        log_call(stage=STAGE, provider="kaggle", model=cfg.get("model", "wan2.2"), shot=sid, seed=job["seed"],
                 params={k: v for k, v in cfg.items() if k != "negative"}, latency_s=(r or {}).get("gpu_s", 0),
                 gpu_s=(r or {}).get("gpu_s", 0), status=status_, error=err,
                 output=manifest[sid].get("file"))
        gpu = f" ({r.get('gpu_s', 0):.0f}s GPU)" if r else ""
        print(f"  {'+' if status_ == 'ok' else 'x'} {sid}: {status_}{' - ' + err[:120] if err else ''}{gpu}")
    save_wan_manifest(manifest)
    print(f"wan: model setup {res.get('setup_s')}s on {res.get('gpu')}, total {res.get('total_s')}s")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["submit", "rerun", "status", "collect", "run"])
    ap.add_argument("--shots", nargs="*")
    ap.add_argument("--timeout-min", type=int, default=240)
    args = ap.parse_args(argv)
    load_env()
    if args.action == "submit":
        submit(args.shots)
    elif args.action == "rerun":
        rerun()
    elif args.action == "status":
        print(status())
    elif args.action == "collect":
        collect()
    else:
        if not submit(args.shots):
            return
        t0 = time.time()
        while time.time() - t0 < args.timeout_min * 60:
            time.sleep(60)
            st = status()
            print(f"  [{(time.time() - t0) / 60:.0f} min] {st}", flush=True)
            if st in ("complete", "error", "cancel"):
                break
        collect()


if __name__ == "__main__":
    main()
