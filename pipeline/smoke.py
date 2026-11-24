"""Provider smoke test: call each provider once with the smallest possible request
and log it to runs.jsonl. Run this first on any new machine.

    python -m pipeline.smoke

Providers whose keys are missing are reported as SKIPPED, not failures.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .common import load_env, log_call, stage_dir

STAGE = "smoke"


def check_gemini() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return "SKIPPED (no GEMINI_API_KEY)"
    from google import genai

    from .narration import gemini_tts, resolve_tts_model, write_wav

    client = genai.Client(api_key=key)
    t0 = time.perf_counter()
    models = [m.name.removeprefix("models/") for m in client.models.list()]
    log_call(stage=STAGE, provider="gemini", model="models.list", latency_s=time.perf_counter() - t0,
             params={"count": len(models)})
    tts = [m for m in models if "tts" in m]
    print(f"  gemini: {len(models)} models visible; TTS models: {tts or 'none'}")

    model = resolve_tts_model(client)
    out = stage_dir(STAGE) / "gemini_tts_am.wav"
    t0 = time.perf_counter()
    try:
        pcm = gemini_tts(client, model, "ሰላም። ይህ የሙከራ ድምፅ ነው።", "Charon", None)
    except Exception as e:
        log_call(stage=STAGE, provider="gemini", model=model, latency_s=time.perf_counter() - t0, status="error", error=str(e)[:500])
        raise
    write_wav(out, pcm)
    log_call(stage=STAGE, provider="gemini", model=model, latency_s=time.perf_counter() - t0, params={"voice": "Charon", "lang": "am"}, output=out)
    return f"OK ({model}, Amharic sample at {out.as_posix()})"


def check_cloudflare() -> str:
    acct, token = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if not (acct and token):
        return "SKIPPED (no CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN)"
    from .keyframes import cf_generate, CF_MODEL

    out = stage_dir(STAGE) / "cloudflare_flux.jpg"
    t0 = time.perf_counter()
    img = cf_generate("a single red apple on a wooden table, soft light", seed=1, steps=4)
    out.write_bytes(img)
    log_call(stage=STAGE, provider="cloudflare", model=CF_MODEL, latency_s=time.perf_counter() - t0, seed=1, params={"steps": 4}, output=out)
    return f"OK ({CF_MODEL}, {len(img)//1024} KB image)"


def kaggle_creds() -> tuple[str, str] | None:
    u, k = os.environ.get("KAGGLE_USERNAME"), os.environ.get("KAGGLE_KEY")
    if u and k:
        return u, k
    p = Path.home() / ".kaggle" / "kaggle.json"
    if p.exists():
        d = json.loads(p.read_text())
        return d["username"], d["key"]
    return None


def check_kaggle() -> str:
    creds = kaggle_creds()
    if not creds:
        return "SKIPPED (no KAGGLE_USERNAME/KAGGLE_KEY or ~/.kaggle/kaggle.json)"
    import requests

    t0 = time.perf_counter()
    r = requests.get("https://www.kaggle.com/api/v1/kernels/list", params={"user": creds[0], "pageSize": 5}, auth=creds, timeout=30)
    log_call(stage=STAGE, provider="kaggle", model="kernels.list", latency_s=time.perf_counter() - t0,
             status="ok" if r.ok else "error", error=None if r.ok else r.text[:300])
    r.raise_for_status()
    return f"OK (authenticated as {creds[0]}; {len(r.json())} recent notebooks)"


def main() -> None:
    load_env()
    results = {}
    for name, fn in [("gemini", check_gemini), ("cloudflare", check_cloudflare), ("kaggle", check_kaggle)]:
        print(f"- {name} ...")
        try:
            results[name] = fn()
        except Exception as e:  # noqa: BLE001
            results[name] = f"FAILED: {str(e)[:300]}"
    print("\nSmoke test results")
    for k, v in results.items():
        print(f"  {k:<11} {v}")
    if any(v.startswith("FAILED") for v in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
