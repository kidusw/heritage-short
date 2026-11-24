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


def resolve_tts_model(client) -> str:
    """Use GEMINI_TTS_MODEL if set; otherwise discover a TTS model from the API.
    Model ids change often (see FAILURES.md), so we don't hard-code one."""
    if os.environ.get("GEMINI_TTS_MODEL"):
        return os.environ["GEMINI_TTS_MODEL"]
    names = [m.name.removeprefix("models/") for m in client.models.list() if "tts" in m.name.lower()]
    if not names:
        raise SystemExit("No TTS model visible to this API key. Set GEMINI_TTS_MODEL in .env.")
    names.sort(key=lambda n: ("flash" not in n, "preview" in n, n), reverse=False)
    return names[0]


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
