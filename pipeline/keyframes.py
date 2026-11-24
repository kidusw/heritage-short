"""Stage: keyframes. One still image per shot from Cloudflare Workers AI (FLUX).

    python -m pipeline.keyframes
    python -m pipeline.keyframes --shots s04 s05
    python -m pipeline.keyframes --offline     # flat colour placeholders, no API

The prompt for each shot is built the same way every time, which is what keeps the look consistent:
    style.visual_prefix + character descriptions (verbatim) + shot.keyframe_prompt + camera
Output: outputs/keyframes/<shot>_<hash>.jpg and manifest.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os

from .common import OUTPUTS, cache_key, load_env, load_storyboard, log_call, run_ffmpeg, select_shots, stage_dir, with_retries, write_manifest

STAGE = "keyframes"
CF_MODEL = os.environ.get("CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")


def build_prompt(sb: dict, shot: dict) -> str:
    chars = {c["id"]: c["description"] for c in sb.get("characters", [])}
    parts = [sb["style"]["visual_prefix"]]
    # Character descriptions are repeated verbatim in every shot: the cheapest consistency trick there is.
    parts += [f"The {c} is {chars[c]}." for c in shot.get("characters", [])]
    parts.append(shot["keyframe_prompt"])
    if shot.get("camera"):
        parts.append(f"Shot: {shot['camera']}.")
    if sb["style"].get("negative"):
        parts.append(f"No {sb['style']['negative']}.")
    return " ".join(parts)


def cf_generate(prompt: str, seed: int, steps: int = 8) -> bytes:
    import requests

    acct, token = os.environ["CLOUDFLARE_ACCOUNT_ID"], os.environ["CLOUDFLARE_API_TOKEN"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{CF_MODEL}"
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"},
                      json={"prompt": prompt[:2048], "seed": seed, "steps": steps}, timeout=120)
    if r.status_code == 429:
        from .common import QuotaError
        raise QuotaError(r.text[:300])
    r.raise_for_status()
    body = r.json()
    img = (body.get("result") or {}).get("image")
    if not img:
        raise RuntimeError(f"No image in response: {str(body)[:300]}")
    return base64.b64decode(img)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shots", nargs="*")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--steps", type=int, default=8)
    args = ap.parse_args(argv)

    load_env()
    sb = load_storyboard()
    if not args.offline and not (os.environ.get("CLOUDFLARE_ACCOUNT_ID") and os.environ.get("CLOUDFLARE_API_TOKEN")):
        raise SystemExit("CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN not set (see README), or pass --offline.")
    provider, model = ("offline", "placeholder") if args.offline else ("cloudflare", CF_MODEL)
    out_dir = stage_dir(STAGE)
    mpath = OUTPUTS / STAGE / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}

    for i, shot in enumerate(select_shots(sb, args.shots)):
        sid, seed = shot["id"], shot.get("seed", 0)
        prompt = build_prompt(sb, shot)
        params = {"steps": args.steps, "prompt": prompt}
        key = cache_key(STAGE, provider, model, prompt, seed, args.steps)
        out = out_dir / f"{sid}_{key}.jpg"
        if out.exists() and not args.force:
            log_call(stage=STAGE, provider=provider, model=model, shot=sid, seed=seed, params=params, cache_hit=True, output=out)
            print(f"  = {sid} cached")
        elif args.offline:
            hue = (i * 37) % 360
            run_ffmpeg(["-f", "lavfi", "-i", f"color=c=0x{(hue*7)%256:02x}{(hue*3)%256:02x}{(hue*5)%256:02x}:s=1024x1024", "-frames:v", "1", str(out)])
            log_call(stage=STAGE, provider=provider, model=model, shot=sid, seed=seed, params=params, output=out)
            print(f"  + {sid} placeholder")
        else:
            img = with_retries(lambda att: cf_generate(prompt, seed, args.steps), stage=STAGE, provider=provider,
                               model=model, shot=sid, seed=seed, params=params, output=out)
            out.write_bytes(img)
            print(f"  + {sid}")
        manifest[sid] = {"file": str(out.relative_to(OUTPUTS.parent)), "prompt": prompt, "seed": seed}
    write_manifest(STAGE, manifest)


if __name__ == "__main__":
    main()
