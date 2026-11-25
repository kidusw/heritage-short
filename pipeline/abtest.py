"""Blind A/B test of one shot: Wan 2.2 clip vs Ken Burns on the same keyframe.

    python -m pipeline.abtest s03

Writes outputs/abtest/<shot>_A.mp4 and <shot>_B.mp4 (same length, same size, no labels) in a random order,
and the answer key to outputs/abtest/<shot>_key.json. Show A and B to viewers without saying which is which,
ask "which feels more like a real memory, and why?", then record the votes in EXPERIMENTS.md (E5).
"""
from __future__ import annotations

import json
import random
import sys

from .common import OUTPUTS, from_manifest, load_storyboard, log_call, read_manifest, rel, select_shots, stage_dir
from .shots import fit_wan_clip, kenburns, kenburns_move


def main(argv=None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        raise SystemExit("usage: python -m pipeline.abtest <shot id>")
    sb = load_storyboard()
    shot = select_shots(sb, argv[:1])[0]
    sid, dur = shot["id"], shot["duration_s"]
    kf = read_manifest("keyframes").get(sid)
    wan = json.loads((OUTPUTS / "shots" / "wan" / "manifest.json").read_text(encoding="utf-8")).get(sid, {})
    if not kf or not wan.get("file"):
        raise SystemExit(f"{sid} needs both a keyframe and a collected Wan clip.")
    out = stage_dir("abtest")
    variants = {"wan": out / f"_{sid}_wan.mp4", "kenburns": out / f"_{sid}_kb.mp4"}
    fit_wan_clip(from_manifest(wan["file"]), variants["wan"], dur)
    kenburns(from_manifest(kf["file"]), variants["kenburns"], dur, kenburns_move(shot))
    order = random.sample(["wan", "kenburns"], 2)
    key = {}
    for label, method in zip("AB", order):
        dst = out / f"{sid}_{label}.mp4"
        variants[method].replace(dst)
        key[label] = method
    (out / f"{sid}_key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    log_call(stage="abtest", provider="local", model="ffmpeg", shot=sid, params={"key_file": rel(out / f"{sid}_key.json")})
    print(f"abtest: {rel(out / f'{sid}_A.mp4')} and {rel(out / f'{sid}_B.mp4')}; answer key in {sid}_key.json (don't peek)")


if __name__ == "__main__":
    main()
