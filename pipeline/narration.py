"""Stage: narration. One WAV per shot per language, via Gemini TTS.

    python -m pipeline.narration                 # all languages in the storyboard
    python -m pipeline.narration --lang am       # just Amharic
    python -m pipeline.narration --shots s03     # regenerate one shot
    python -m pipeline.narration --offline       # no API: placeholder tones sized to the text (for testing plumbing)

Output: outputs/narration/<shot>_<lang>_<hash>.wav and outputs/narration/manifest.json
"""
from __future__ import annotations

import argparse
import os
import wave
from pathlib import Path

from .common import (
    cache_key, load_env, load_storyboard, log_call, media_duration, run_ffmpeg,
    select_shots, stage_dir, with_retries, write_manifest, OUTPUTS,
)

STAGE = "narration"
SAMPLE_RATE = 24000  # Gemini TTS returns 24 kHz, 16-bit mono PCM


# Ids to try when the API's model list doesn't name a TTS model. The Gemini API has hidden TTS ids from
# models.list() before, and ids get renamed often (see FAILURES.md F3), so we probe instead of trusting the list.
TTS_CANDIDATES = [
    "gemini-3.8-flash-tts",
    "gemini-3.8-flash-preview-tts",
    "gemini-3.8-flash",
    "gemini-omni-flash-preview",
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-flash-tts",
]


def probe_tts(client, candidates: list[str], verbose: bool = False) -> str | None:
    """Return the first model id that actually returns audio for a tiny request. Every probe is logged."""
    import time

    for model in candidates:
        t0 = time.perf_counter()
        try:
            pcm = gemini_tts(client, model, "Hello.", "Charon", None)
            log_call(stage="tts_probe", provider="gemini", model=model, latency_s=time.perf_counter() - t0,
                     params={"bytes": len(pcm)})
            if verbose:
                print(f"    probe {model}: OK ({len(pcm)} bytes of audio)")
            return model
        except Exception as e:  # noqa: BLE001
            log_call(stage="tts_probe", provider="gemini", model=model, latency_s=time.perf_counter() - t0,
                     status="error", error=str(e)[:300])
            if verbose:
                print(f"    probe {model}: {type(e).__name__}: {str(e)[:140]}")
    return None


def resolve_tts_model(client, verbose: bool = False) -> str:
    """GEMINI_TTS_MODEL if set; else any listed model with 'tts' in its id; else probe known candidates."""
    if os.environ.get("GEMINI_TTS_MODEL"):
        return os.environ["GEMINI_TTS_MODEL"]
    listed = [m.name.removeprefix("models/") for m in client.models.list(config={"page_size": 200})]
    tts_listed = sorted((n for n in listed if "tts" in n.lower()), key=lambda n: ("flash" not in n, n))
    candidates = tts_listed + [c for c in TTS_CANDIDATES if c not in tts_listed]
    model = probe_tts(client, candidates, verbose=verbose)
    if not model:
        raise SystemExit("No model returned audio. Tried: " + ", ".join(candidates) +
                         "\nFind the current TTS model id in Google AI Studio and set GEMINI_TTS_MODEL in .env.")
    print(f"  TTS model resolved to {model}. Put GEMINI_TTS_MODEL={model} in .env to skip probing next time.")
    return model


def write_wav(path: Path, pcm: bytes, rate: int = SAMPLE_RATE) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def gemini_tts(client, model: str, text: str, voice: str, style: str | None) -> bytes:
    from google.genai import types

    prompt = f"{style}\n\n{text}" if style else text
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
    part = resp.candidates[0].content.parts[0]
    if not getattr(part, "inline_data", None) or not part.inline_data.data:
        raise RuntimeError(f"TTS returned no audio: {resp}")
    return part.inline_data.data


def offline_tts(path: Path, text: str) -> None:
    """Placeholder: a soft tone whose length approximates speaking time (~2.6 words/s)."""
    secs = max(1.0, len(text.split()) / 2.6)
    run_ffmpeg(["-f", "lavfi", "-i", f"sine=frequency=220:duration={secs:.2f}:sample_rate={SAMPLE_RATE}",
                "-af", "volume=0.15", "-ac", "1", str(path)])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", action="append", help="Language code(s); default: all in storyboard")
    ap.add_argument("--shots", nargs="*", help="Shot ids (or prefixes like s03) to (re)generate")
    ap.add_argument("--offline", action="store_true", help="Skip the API; write placeholder audio")
    ap.add_argument("--force", action="store_true", help="Ignore cache")
    args = ap.parse_args(argv)

    load_env()
    sb = load_storyboard()
    langs = args.lang or sb["languages"]
    out_dir = stage_dir(STAGE)

    client = model = None
    if not args.offline:
        from google import genai

        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise SystemExit("GEMINI_API_KEY not set (see .env.example), or pass --offline.")
        client = genai.Client(api_key=key)
        model = resolve_tts_model(client)
        print(f"narration: using {model}")
    provider = "offline" if args.offline else "gemini"
    model_name = "placeholder-tone" if args.offline else model

    # Keep entries from previous runs for shots/langs we don't touch this time.
    manifest_path = OUTPUTS / STAGE / "manifest.json"
    import json
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    for lang in langs:
        voice = sb["voices"][lang]
        manifest.setdefault(lang, {})
        for shot in select_shots(sb, args.shots):
            text = shot["narration"].get(lang, "").strip()
            sid = shot["id"]
            if not text:
                manifest[lang][sid] = None
                continue
            params = {"lang": lang, "voice": voice["voice_name"], "style_prompt": voice.get("style_prompt"), "chars": len(text)}
            key = cache_key(STAGE, provider, model_name, text, voice)
            out = out_dir / f"{sid}_{lang}_{key}.wav"

            if out.exists() and not args.force:
                log_call(stage=STAGE, provider=provider, model=model_name, shot=sid, params=params, cache_hit=True, output=out)
                print(f"  = {sid} [{lang}] cached")
            elif args.offline:
                offline_tts(out, text)
                log_call(stage=STAGE, provider=provider, model=model_name, shot=sid, params=params, output=out)
                print(f"  + {sid} [{lang}] placeholder")
            else:
                pcm = with_retries(
                    lambda att: gemini_tts(client, model, text, voice["voice_name"], voice.get("style_prompt")),
                    stage=STAGE, provider=provider, model=model_name, shot=sid, params=params, output=out,
                    cost_usd=0.0,  # free tier; list-price equivalent is computed in COSTS.md
                )
                write_wav(out, pcm)
                print(f"  + {sid} [{lang}] {media_duration(out):.1f}s")

            dur = media_duration(out)
            manifest[lang][sid] = {"file": str(out.relative_to(OUTPUTS.parent)), "duration_s": round(dur, 2),
                                   "shot_duration_s": shot["duration_s"], "fits": dur <= shot["duration_s"] - 0.3}
            if dur > shot["duration_s"] - 0.3:
                print(f"    ! {sid} [{lang}] narration {dur:.1f}s is longer than the shot ({shot['duration_s']}s); shorten text or lengthen shot")

    write_manifest(STAGE, manifest)


if __name__ == "__main__":
    main()
