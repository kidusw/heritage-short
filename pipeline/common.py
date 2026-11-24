"""Shared plumbing for every stage: storyboard loading + validation, run logging,
content-hash caching and retries.

Every stage follows the same pattern:

    sb = load_storyboard()                      # validated against schema/
    key = cache_key("narration", model, text, voice)   # hash of everything that affects the output
    out = OUTPUTS / "narration" / f"{shot_id}_{lang}_{key}.wav"
    if out.exists():  log_call(..., cache_hit=True)    # free re-run
    else:             with_retries(call_model)          # logs every attempt to runs.jsonl

Because the file name contains the hash of its inputs, editing one shot's prompt
changes only that shot's hash, so only that shot is regenerated.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
STORYBOARD = ROOT / "storyboard.json"
SCHEMA = ROOT / "schema" / "storyboard.schema.json"
OUTPUTS = ROOT / "outputs"
RUNS_LOG = ROOT / "runs.jsonl"

# One id per process, so all calls from one `make film` can be grouped in runs.jsonl.
RUN_ID = os.environ.get("HS_RUN_ID") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


def load_env() -> None:
    """Load .env if python-dotenv is installed. Secrets never live in the repo."""
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def require_env(*names: str) -> dict[str, str]:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise SystemExit(f"Missing environment variables: {', '.join(missing)}. Copy .env.example to .env and fill them in.")
    return {n: os.environ[n] for n in names}


# ---------------------------------------------------------------- storyboard

class StoryboardError(Exception):
    pass


def load_storyboard(path: Path = STORYBOARD) -> dict:
    """Load and validate the storyboard. Stages must never run on an invalid contract."""
    import jsonschema

    with open(path, encoding="utf-8") as f:
        sb = json.load(f)
    with open(SCHEMA, encoding="utf-8") as f:
        schema = json.load(f)

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(sb), key=lambda e: list(e.path))
    if errors:
        msg = "\n".join(f"  - {'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors)
        raise StoryboardError(f"storyboard.json failed schema validation:\n{msg}")

    # Cross-field checks JSON Schema can't express.
    problems = []
    ids = [s["id"] for s in sb["shots"]]
    if len(ids) != len(set(ids)):
        problems.append("shot ids must be unique")
    char_ids = {c["id"] for c in sb.get("characters", [])}
    for s in sb["shots"]:
        for c in s.get("characters", []):
            if c not in char_ids:
                problems.append(f"shot {s['id']} references unknown character '{c}'")
        for lang in sb["languages"]:
            if lang not in s["narration"]:
                problems.append(f"shot {s['id']} has no narration for language '{lang}' (use \"\" for silence)")
    for lang in sb["languages"]:
        if lang not in sb["voices"]:
            problems.append(f"no voice configured for language '{lang}'")
    if problems:
        raise StoryboardError("storyboard.json failed consistency checks:\n" + "\n".join(f"  - {p}" for p in problems))
    return sb


def total_duration(sb: dict) -> float:
    return sum(s["duration_s"] for s in sb["shots"]) + sb.get("end_card", {}).get("duration_s", 0)


def select_shots(sb: dict, only: list[str] | None) -> list[dict]:
    if not only:
        return sb["shots"]
    wanted = set(only)
    shots = [s for s in sb["shots"] if s["id"] in wanted or s["id"].split("_")[0] in wanted]
    if not shots:
        raise SystemExit(f"No shots match {only}. Known: {[s['id'] for s in sb['shots']]}")
    return shots


# ---------------------------------------------------------------- caching

def cache_key(*parts: Any) -> str:
    """Stable short hash of everything that determines an output."""
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def stage_dir(stage: str) -> Path:
    d = OUTPUTS / stage
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- logging

def log_call(
    *,
    stage: str,
    provider: str,
    model: str,
    shot: str | None = None,
    params: dict | None = None,
    seed: int | None = None,
    latency_s: float = 0.0,
    cost_usd: float = 0.0,
    gpu_s: float = 0.0,
    status: str = "ok",
    cache_hit: bool = False,
    output: str | Path | None = None,
    attempt: int = 1,
    error: str | None = None,
) -> None:
    """Append one line per model call (or cache hit) to runs.jsonl."""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": RUN_ID,
        "stage": stage,
        "shot": shot,
        "provider": provider,
        "model": model,
        "params": params or {},
        "seed": seed,
        "latency_s": round(latency_s, 3),
        "gpu_s": round(gpu_s, 1),
        "cost_usd": round(cost_usd, 6),
        "status": status,
        "cache_hit": cache_hit,
        "attempt": attempt,
        "output": str(Path(output).relative_to(ROOT)) if output and Path(output).is_absolute() and ROOT in Path(output).parents else (str(output) if output else None),
        "error": error,
    }
    with open(RUNS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- retries

class QuotaError(Exception):
    """Raised for rate-limit / quota responses so callers can back off longer."""


@dataclass
class Attempt:
    number: int
    latency_s: float = 0.0
    extra: dict = field(default_factory=dict)


def with_retries(
    fn: Callable[[Attempt], Any],
    *,
    stage: str,
    provider: str,
    model: str,
    shot: str | None = None,
    params: dict | None = None,
    seed: int | None = None,
    max_attempts: int = 4,
    base_delay: float = 2.0,
    cost_usd: float | Callable[[Any], float] = 0.0,
    output: Path | None = None,
):
    """Call fn with exponential backoff + jitter. Every attempt, success or failure, is logged."""
    last_exc: Exception | None = None
    for n in range(1, max_attempts + 1):
        att = Attempt(number=n)
        t0 = time.perf_counter()
        try:
            result = fn(att)
            latency = time.perf_counter() - t0
            cost = cost_usd(result) if callable(cost_usd) else cost_usd
            log_call(stage=stage, provider=provider, model=model, shot=shot, params=params, seed=seed,
                     latency_s=latency, cost_usd=cost, output=output, attempt=n, **({"gpu_s": att.extra["gpu_s"]} if "gpu_s" in att.extra else {}))
            return result
        except Exception as e:  # noqa: BLE001 - we log and re-raise below
            latency = time.perf_counter() - t0
            last_exc = e
            quota = isinstance(e, QuotaError) or "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "quota" in str(e).lower()
            log_call(stage=stage, provider=provider, model=model, shot=shot, params=params, seed=seed,
                     latency_s=latency, status="quota" if quota else "error", attempt=n, error=str(e)[:500])
            if n == max_attempts:
                break
            delay = base_delay * (2 ** (n - 1)) * (3 if quota else 1) + random.uniform(0, 1)
            print(f"  ! {stage}/{shot or '-'} attempt {n} failed ({'quota' if quota else 'error'}): {str(e)[:160]}  -> retrying in {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------- ffmpeg helpers

def run_ffmpeg(args: list[str]) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit("ffmpeg not found on PATH. Install it (Windows: `winget install Gyan.FFmpeg`, "
                         "macOS: `brew install ffmpeg`, Linux: `apt install ffmpeg`) and open a new terminal.")
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd)}\n{res.stderr}")


def media_duration(path: Path) -> float:
    if not shutil.which("ffprobe"):
        raise SystemExit("ffprobe not found on PATH. It ships with ffmpeg: Windows `winget install Gyan.FFmpeg`, "
                         "then open a new terminal.")
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(res.stdout.strip())


def write_manifest(stage: str, data: dict) -> Path:
    """Each stage writes outputs/<stage>/manifest.json: which file is current for which shot.
    Later stages read manifests, never guess file names."""
    p = stage_dir(stage) / "manifest.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return p


def read_manifest(stage: str) -> dict:
    p = OUTPUTS / stage / "manifest.json"
    if not p.exists():
        raise SystemExit(f"No manifest for stage '{stage}'. Run that stage first.")
    with open(p, encoding="utf-8") as f:
        return json.load(f)
