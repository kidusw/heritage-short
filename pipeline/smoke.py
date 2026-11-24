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
    from .narration import TTSChain, gemini_client, resolve_tts_models, write_wav

    client = gemini_client()
    t0 = time.perf_counter()
    models = [m.name.removeprefix("models/") for m in client.models.list(config={"page_size": 200})]
    log_call(stage=STAGE, provider="gemini", model="models.list", latency_s=time.perf_counter() - t0,
             params={"count": len(models)})
    chain_models = resolve_tts_models(client)
    print(f"  gemini: {len(models)} models visible; TTS failover order: {chain_models}")

    out = stage_dir(STAGE) / "gemini_tts_am.wav"
    # One call only (free tier is ~10 TTS requests/day/model). Re-running smoke reuses the sample.
    if out.exists() and not os.environ.get("SMOKE_FORCE"):
        return f"OK (sample already at {out.as_posix()}; set SMOKE_FORCE=1 to spend a call)"
    pcm, model = TTSChain(client, chain_models).say("ሰላም። ይህ የሙከራ ድምፅ ነው።", "Charon", None,
                                                    shot="smoke", params={"lang": "am"}, out=out)
    write_wav(out, pcm)
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


def kaggle_env() -> dict | None:
    """Kaggle moved to API tokens (KGAT_...) read from KAGGLE_API_TOKEN; legacy username+key still exist.
    Return the env vars the official `kaggle` CLI needs, or None if nothing is configured."""
    token = os.environ.get("KAGGLE_API_TOKEN")
    key = os.environ.get("KAGGLE_KEY", "")
    if not token and key.startswith("KGAT_"):
        token = key  # a new-style token pasted into the old variable
    if token:
        return {"KAGGLE_API_TOKEN": token}
    if os.environ.get("KAGGLE_USERNAME") and key:
        return {"KAGGLE_USERNAME": os.environ["KAGGLE_USERNAME"], "KAGGLE_KEY": key}
    home = Path.home() / ".kaggle"
    if (home / "access_token").exists() or (home / "kaggle.json").exists():
        return {}
    return None


def check_kaggle() -> str:
    """Use the official CLI rather than raw REST: Kaggle changed its API host and auth in 2025-26
    (the old www.kaggle.com/api/v1 kernels endpoint returned 404, FAILURES.md F5)."""
    import subprocess
    import sys

    extra = kaggle_env()
    if extra is None:
        return "SKIPPED (set KAGGLE_API_TOKEN, or KAGGLE_USERNAME + KAGGLE_KEY)"
    t0 = time.perf_counter()
    res = subprocess.run([sys.executable, "-m", "kaggle.cli", "kernels", "list", "--mine", "--page-size", "5"],
                         capture_output=True, text=True, env={**os.environ, **extra}, timeout=120)
    ok = res.returncode == 0
    err = (res.stderr or res.stdout).strip().splitlines()[-1:] if not ok else None
    log_call(stage=STAGE, provider="kaggle", model="kaggle-cli kernels list", latency_s=time.perf_counter() - t0,
             status="ok" if ok else "error", error=err[0][:300] if err else None,
             params={"auth": "api_token" if "KAGGLE_API_TOKEN" in extra else ("legacy_key" if extra else "file")})
    if not ok:
        raise RuntimeError(err[0] if err else f"kaggle CLI exited {res.returncode}")
    lines = [l for l in res.stdout.splitlines() if l.strip()]
    return f"OK (authenticated; {max(0, len(lines) - 2)} of your notebooks listed)"


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
