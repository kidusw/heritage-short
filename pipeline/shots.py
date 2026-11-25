"""Stage: moving shots. One clip per shot, made from that shot's keyframe.

    python -m pipeline.shots                  # use Wan clips where they exist, Ken Burns for the rest
    python -m pipeline.shots --shots s03
    python -m pipeline.shots --method kenburns  # ignore Wan clips

Two methods:
  * wan       Wan 2.2 image-to-video, generated on a free Kaggle GPU by `python -m pipeline.wan_kaggle`
              (slow, so it runs as a separate submit/collect step and lands in outputs/shots/wan/).
  * kenburns  slow pan/zoom on the keyframe with ffmpeg, on this machine, in seconds. Always available,
              so a GPU queue, quota or model failure degrades the film instead of blocking it.

This stage never waits on a GPU: it picks the best clip available right now and records which
method each shot used (and why) in outputs/shots/manifest.json.

Output: square 1080x1080, 24 fps, exactly the shot's duration. The assemble stage crops to 16:9 / 9:16.
"""
from __future__ import annotations

import argparse
import json
import re
import time

from .common import (
    OUTPUTS, ROOT, cache_key, load_env, load_storyboard, log_call, media_duration, read_manifest,
    run_ffmpeg, select_shots, shots_blocked_by_consent, stage_dir, write_manifest,
)

STAGE = "shots"
SIZE = 1080
FPS = 24


def kenburns_move(shot: dict) -> str:
    """Pick a camera move from the motion prompt's words, so Ken Burns follows the storyboard's intent."""
    m = (shot.get("motion_prompt") or "").lower()
    if re.search(r"pull[- ]?back|pull[- ]?out|zoom out|reveal", m):
        return "out"
    if re.search(r"pan right|left to right|tracking|track", m):
        return "right"
    if re.search(r"pan left|right to left|slides past", m):
        return "left"
    if "static" in m:
        return "drift"
    return "in"


def kenburns(src, out, duration: float, move: str) -> None:
    frames = int(round(duration * FPS))
    # Upscale first so sub-pixel zoom steps don't jitter.
    z_in = f"1+0.15*on/{frames}"
    z_out = f"1.15-0.15*on/{frames}"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    expr = {
        "in": (z_in, cx, cy),
        "out": (z_out, cx, cy),
        "right": ("1.12", f"(iw-iw/zoom)*on/{frames}", cy),
        "left": ("1.12", f"(iw-iw/zoom)*(1-on/{frames})", cy),
        "drift": (f"1.04+0.02*on/{frames}", cx, cy),
    }[move]
    run_ffmpeg([
        "-loop", "1", "-i", str(src),
        "-vf", f"scale={SIZE*4}:{SIZE*4}:force_original_aspect_ratio=increase,crop={SIZE*4}:{SIZE*4},"
               f"zoompan=z='{expr[0]}':x='{expr[1]}':y='{expr[2]}':d={frames}:s={SIZE}x{SIZE}:fps={FPS},format=yuv420p",
        "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out),
    ])


def fit_wan_clip(src, out, duration: float) -> None:
    """Wan clips are ~4-5 s; shots are 6-9 s. Slow the clip down (never below 0.55x) and hold the last frame
    for any remainder, then scale to the master size."""
    src_dur = media_duration(src)
    factor = min(max(duration / src_dur, 1.0), 1 / 0.55)
    hold = max(0.0, duration - src_dur * factor)
    run_ffmpeg([
        "-i", str(src),
        "-vf", f"setpts={factor:.4f}*PTS,fps={FPS},scale={SIZE}:{SIZE}:force_original_aspect_ratio=increase,"
               f"crop={SIZE}:{SIZE},tpad=stop_mode=clone:stop_duration={hold:.3f},format=yuv420p",
        "-t", f"{duration:.3f}", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out),
    ])


def placeholder(out, duration: float) -> None:
    """A shot we're not allowed to show yet (consent pending) or have no keyframe for: dark card."""
    run_ffmpeg(["-f", "lavfi", "-i", f"color=c=0x1a1410:s={SIZE}x{SIZE}:r={FPS}:d={duration:.3f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shots", nargs="*")
    ap.add_argument("--method", choices=["auto", "kenburns"], default="auto")
    ap.add_argument("--offline", action="store_true", help="accepted for run.py symmetry; this stage is local")
    args = ap.parse_args(argv)
    load_env()
    sb = load_storyboard()
    out_dir = stage_dir(STAGE)
    kf_path = OUTPUTS / "keyframes" / "manifest.json"
    keyframes = read_manifest("keyframes") if kf_path.exists() else {}
    wan = json.loads((OUTPUTS / STAGE / "wan" / "manifest.json").read_text(encoding="utf-8")) \
        if (OUTPUTS / STAGE / "wan" / "manifest.json").exists() else {}
    mpath = OUTPUTS / STAGE / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}

    shots = select_shots(sb, args.shots)
    blocked = shots_blocked_by_consent(sb, shots)
    for shot in shots:
        sid, dur = shot["id"], shot["duration_s"]
        kf = keyframes.get(sid)
        wclip = wan.get(sid) if args.method == "auto" and shot.get("video", "wan") == "wan" else None
        if wclip and kf and wclip.get("keyframe") != kf["file"]:
            wclip = None  # Wan clip was made from an older keyframe: stale

        if sid in blocked or not kf:
            method, reason, src = "placeholder", ("consent pending" if sid in blocked else "no keyframe yet"), None
        elif wclip and (ROOT / wclip["file"]).exists():
            method, reason, src = "wan", None, ROOT / wclip["file"]
        else:
            method, src = "kenburns", ROOT / kf["file"]
            reason = "preferred in storyboard" if shot.get("video") == "kenburns" else \
                (wan.get(sid, {}).get("error") or "no Wan clip yet")

        move = kenburns_move(shot) if method == "kenburns" else None
        key = cache_key(STAGE, method, str(src.name) if src else None, dur, move, SIZE, FPS)
        out = out_dir / f"{sid}_{method}_{key}.mp4"
        t0 = time.perf_counter()
        if out.exists():
            log_call(stage=STAGE, provider="local", model=method, shot=sid, cache_hit=True, output=out)
            print(f"  = {sid} {method} cached")
        else:
            if method == "kenburns":
                kenburns(src, out, dur, move)
            elif method == "wan":
                fit_wan_clip(src, out, dur)
            else:
                placeholder(out, dur)
            log_call(stage=STAGE, provider="local", model=f"ffmpeg-{method}", shot=sid, latency_s=time.perf_counter() - t0,
                     params={"duration_s": dur, "move": move, "reason": reason}, output=out)
            print(f"  + {sid} {method}{f' ({move})' if move else ''}{f' [{reason}]' if reason else ''}")
        manifest[sid] = {"file": str(out.relative_to(ROOT)), "method": method, "reason": reason, "duration_s": dur}
        write_manifest(STAGE, manifest)

    counts = {}
    for v in manifest.values():
        counts[v["method"]] = counts.get(v["method"], 0) + 1
    print(f"shots: {counts}")


if __name__ == "__main__":
    main()
