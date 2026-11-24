"""Stage: narration. One WAV per shot per language, via Gemini TTS.

    python -m pipeline.narration                 # all languages in the storyboard
    python -m pipeline.narration --lang am       # just Amharic
    python -m pipeline.narration --shots s03     # regenerate one shot
    python -m pipeline.narration --offline       # no API: placeholder tones sized to the text (for testing plumbing)

Output: outputs/narration/<shot>_<lang>_<hash>.wav and outputs/narration/manifest.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import os
import re
import sys
import wave
from pathlib import Path

from .common import (
    cache_key, load_env, load_storyboard, log_call, media_duration, run_ffmpeg,
    select_shots, stage_dir, with_retries, write_manifest, OUTPUTS,
)

STAGE = "narration"
SAMPLE_RATE = 24000  # Gemini TTS returns 24 kHz, 16-bit mono PCM


def gemini_client():
    """Gemini client pinned to v1beta. google-genai 3.x defaults to the v1 API, which rejects
    speechConfig with 400 INVALID_ARGUMENT (FAILURES.md F3). Override with GEMINI_API_VERSION."""
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY not set (see .env.example), or pass --offline.")
    return genai.Client(api_key=key, http_options=types.HttpOptions(api_version=os.environ.get("GEMINI_API_VERSION", "v1beta")))


def is_daily_quota(e: Exception) -> bool:
    """Free-tier TTS is ~10 requests/day/model. Retrying a daily cap within the run is pointless."""
    msg = str(e)
    return ("429" in msg or "RESOURCE_EXHAUSTED" in msg) and ("PerDay" in msg or "per day" in msg.lower())


def rank_tts(n: str):
    """Newest version first, then flash before pro, non-lite before lite, stable before preview."""
    v = re.search(r"(\d+(?:\.\d+)?)", n)
    return (-(float(v.group(1)) if v else 0), "flash" not in n, "lite" in n, "preview" in n, n)


def resolve_tts_models(client) -> list[str]:
    """Ordered list of TTS models to fail over through. No probe calls: each probe would burn
    one of the ~10 free requests/day (FAILURES.md F6).
    GEMINI_TTS_MODEL may be one id or a comma-separated list; otherwise every listed '*tts*' model, ranked."""
    env = os.environ.get("GEMINI_TTS_MODEL", "").strip()
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]
    listed = [m.name.removeprefix("models/") for m in client.models.list(config={"page_size": 200})]
    models = sorted((n for n in listed if "tts" in n.lower()), key=rank_tts)
    if not models:
        raise SystemExit("No TTS model visible to this key. Set GEMINI_TTS_MODEL in .env.\nVisible: " + ", ".join(sorted(listed)))
    return models


class TTSChain:
    """Calls Gemini TTS, failing over to the next model when one hits its daily quota or doesn't return audio.
    Each model has its own free quota, so a chain of 3 models triples the daily budget."""

    def __init__(self, client, models: list[str]):
        self.client, self.models, self.dead = client, models, {}

    def say(self, text: str, voice: str, style: str | None, *, shot: str, params: dict, out: Path) -> tuple[bytes, str]:
        for model in self.models:
            if model in self.dead:
                continue
            try:
                pcm = with_retries(lambda att: gemini_tts(self.client, model, text, voice, style),
                                   stage=STAGE, provider="gemini", model=model, shot=shot, params=params,
                                   output=out, max_attempts=3, give_up=is_daily_quota)
                return pcm, model
            except Exception as e:  # noqa: BLE001
                reason = "daily quota" if is_daily_quota(e) else f"{type(e).__name__}: {str(e)[:120]}"
                self.dead[model] = reason
                print(f"    ! {model} unavailable ({reason}); failing over", file=sys.stderr)
        raise SystemExit("All TTS models exhausted: " + "; ".join(f"{m} ({r})" for m, r in self.dead.items()) +
                         "\nFree-tier quotas reset daily (midnight Pacific). Re-run later: finished clips are cached.")


def write_wav(path: Path, pcm: bytes, rate: int = SAMPLE_RATE) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def gemini_tts(client, model: str, text: str, voice: str, style: str | None) -> bytes:
    from google.genai import types

    # One line, "<direction>: <text>", the form Gemini TTS documents for controllable speech. A multi-line
    # preamble risked being read aloud (EXPERIMENTS.md E2).
    prompt = f"{style.rstrip(': ')}: {text}" if style else text
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        ),
    )
    cand = resp.candidates[0] if resp.candidates else None
    if not cand or not cand.content or not cand.content.parts:
        raise RuntimeError(f"TTS returned no content (finish_reason={getattr(cand, 'finish_reason', None)})")
    part = cand.content.parts[0]
    if not getattr(part, "inline_data", None) or not part.inline_data.data:
        raise RuntimeError(f"TTS returned no audio: {resp}")
    return part.inline_data.data


def offline_tts(path: Path, text: str) -> None:
    """Placeholder: a soft tone whose length approximates speaking time (~2.6 words/s)."""
    secs = max(1.0, len(text.split()) / 2.6)
    run_ffmpeg(["-f", "lavfi", "-i", f"sine=frequency=220:duration={secs:.2f}:sample_rate={SAMPLE_RATE}",
                "-af", "volume=0.15", "-ac", "1", str(path)])


def split_on_silences(wav: Path, n: int, out_paths: list[Path]) -> bool:
    """Cut a batched reading into n clips at the n-1 longest silences. Returns False if it can't."""
    res = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(wav), "-af", "silencedetect=noise=-38dB:d=0.35", "-f", "null", "-"],
                         capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", res.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", res.stderr)]
    gaps = [(e - s_, s_, e) for s_, e in zip(starts, ends) if s_ > 0.2]
    total = media_duration(wav)
    gaps = [g for g in gaps if g[2] < total - 0.2]  # ignore trailing silence
    if len(gaps) < n - 1:
        return False
    cuts = sorted((s_ + e) / 2 for _, s_, e in sorted(gaps, reverse=True)[: n - 1])
    bounds = [0.0, *cuts, total]
    for i, out in enumerate(out_paths):
        a, b = bounds[i], bounds[i + 1]
        trim = "silenceremove=start_periods=1:start_threshold=-45dB"
        run_ffmpeg(["-i", str(wav), "-af", f"atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,{trim},areverse,{trim},areverse",
                    str(out)])
    return True


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", action="append", help="Language code(s); default: all in storyboard")
    ap.add_argument("--shots", nargs="*", help="Shot ids (or prefixes like s03) to (re)generate")
    ap.add_argument("--offline", action="store_true", help="Skip the API; write placeholder audio")
    ap.add_argument("--force", action="store_true", help="Ignore cache")
    ap.add_argument("--mode", choices=["auto", "batch", "per-shot"], default="auto",
                    help="batch = one TTS call per language, split on silences (saves quota); "
                         "auto = batch when 3+ clips are missing")
    args = ap.parse_args(argv)

    load_env()
    sb = load_storyboard()
    langs = args.lang or sb["languages"]
    out_dir = stage_dir(STAGE)

    chain = None
    if not args.offline:
        client = gemini_client()
        models = resolve_tts_models(client)
        chain = TTSChain(client, models)
        print(f"narration: TTS models in failover order: {', '.join(models)}")
    provider = "offline" if args.offline else "gemini"
    model_setting = "placeholder-tone" if args.offline else (os.environ.get("GEMINI_TTS_MODEL") or "auto")

    manifest_path = OUTPUTS / STAGE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    def record(lang, shot, out, model):
        dur = media_duration(out)
        fits = dur <= shot["duration_s"] - 0.3
        manifest[lang][shot["id"]] = {"file": str(out.relative_to(OUTPUTS.parent)), "model": model, "duration_s": round(dur, 2),
                                      "shot_duration_s": shot["duration_s"], "fits": fits}
        write_manifest(STAGE, manifest)  # after every clip, so a crash keeps progress
        if not fits:
            print(f"    ! {shot['id']} [{lang}] narration {dur:.1f}s is longer than the shot ({shot['duration_s']}s)")

    for lang in langs:
        voice = sb["voices"][lang]
        manifest.setdefault(lang, {})
        todo = []
        for shot in select_shots(sb, args.shots):
            text = shot["narration"].get(lang, "").strip()
            if not text:
                manifest[lang][shot["id"]] = None
                continue
            # Cache key covers text, voice and the *model setting*; the model actually used is in the manifest.
            key = cache_key(STAGE, provider, model_setting, text, voice)
            out = out_dir / f"{shot['id']}_{lang}_{key}.wav"
            params = {"lang": lang, "voice": voice["voice_name"], "style_prompt": voice.get("style_prompt"), "chars": len(text)}
            if out.exists() and not args.force:
                log_call(stage=STAGE, provider=provider, model=model_setting, shot=shot["id"], params=params, cache_hit=True, output=out)
                print(f"  = {shot['id']} [{lang}] cached")
                prev = manifest[lang].get(shot["id"]) or {}
                record(lang, shot, out, prev.get("model", model_setting))
            else:
                todo.append((shot, text, out, params))

        if not todo:
            continue
        if args.offline:
            for shot, text, out, params in todo:
                offline_tts(out, text)
                log_call(stage=STAGE, provider=provider, model=model_setting, shot=shot["id"], params=params, output=out)
                print(f"  + {shot['id']} [{lang}] placeholder")
                record(lang, shot, out, model_setting)
            continue

        batch = args.mode == "batch" or (args.mode == "auto" and len(todo) >= 3)
        if batch:
            # One request for the whole language: blank lines between shots become pauses we can cut on.
            joined = "\n\n".join(t for _, t, _, _ in todo)
            bkey = cache_key(STAGE, "batch", model_setting, joined, voice)
            bwav = out_dir / f"_batch_{lang}_{bkey}.wav"
            params = {"lang": lang, "voice": voice["voice_name"], "mode": "batch", "shots": len(todo), "chars": len(joined)}
            if not bwav.exists():
                style = (voice.get("style_prompt") or "Read aloud").rstrip(": ") + \
                    ", with a two-second pause between paragraphs"
                pcm, model = chain.say(joined, voice["voice_name"], style, shot=f"batch:{lang}", params=params, out=bwav)
                write_wav(bwav, pcm)
            else:
                model = (manifest.get("_batches", {}).get(bwav.name) or model_setting)
            manifest.setdefault("_batches", {})[bwav.name] = model
            if split_on_silences(bwav, len(todo), [o for _, _, o, _ in todo]):
                for shot, _, out, _ in todo:
                    print(f"  + {shot['id']} [{lang}] {media_duration(out):.1f}s (batched, {model})")
                    record(lang, shot, out, model)
                continue
            print(f"  ! [{lang}] couldn't find {len(todo) - 1} clean pauses in the batched reading; falling back to per-shot",
                  file=sys.stderr)
            log_call(stage=STAGE, provider="local", model="silencedetect", params={"lang": lang, "shots": len(todo)},
                     status="error", error="batch split failed; per-shot fallback", output=bwav)

        for shot, text, out, params in todo:
            pcm, model = chain.say(text, voice["voice_name"], voice.get("style_prompt"), shot=shot["id"], params=params, out=out)
            write_wav(out, pcm)
            print(f"  + {shot['id']} [{lang}] {media_duration(out):.1f}s ({model})")
            record(lang, shot, out, model)

    write_manifest(STAGE, manifest)


if __name__ == "__main__":
    main()
