# Failures

What broke, what I tried, what fixed it.

## F1. Coding agent couldn't create the GitHub repo (day 1)
- **Broke:** creating `kidusw/heritage-short` through the GitHub integration returned `403 Resource not accessible by integration`.
- **Cause:** the Claude GitHub App wasn't yet granted access to my account's repositories.
- **Fixed:** granted the app access to all repositories; the same create call then succeeded and the scaffold was pushed.

## F2. TTS model ids move
- **Risk:** the brief notes models get renamed/retired within months, so a hard-coded TTS id would break.
- **Fix:** `narration.resolve_tts_model` uses `GEMINI_TTS_MODEL` if set, otherwise discovers a TTS model from `models.list()`. The chosen id is logged on every call.

## F3. No TTS model in the Gemini model list (day 1)
- **Broke:** the smoke test listed 28 models for my key and none had "tts" in its id, so auto-discovery failed. The brief says "Gemini 3.8 Flash TTS" is free, but no id with that name is listed.
- **Tried:** listing with page_size=200 to rule out pagination; checking supported actions (no model advertises audio output).
- **Fix:** `resolve_tts_model` now probes a list of candidate ids with a one-word request and takes the first that returns audio. Every probe is logged to runs.jsonl as stage `tts_probe`, so the evidence of which ids exist is kept.
- **Then:** every probe, even for ids that don't exist, failed with the same `400 INVALID_ARGUMENT: Unknown name "speechConfig" at 'generation_config'`. An identical error for real and fake ids meant the request shape was wrong, not the model.
- **Root cause:** google-genai 3.x defaults to the `v1` API; `speechConfig` only exists on `v1beta`.
- **Fix:** `gemini_client()` pins `api_version="v1beta"` (overridable with `GEMINI_API_VERSION`).
- **Result:** on v1beta the key sees 65 models instead of 28, five of them TTS (gemini-2.5-flash-preview-tts, gemini-2.5-pro-preview-tts, gemini-3.1-flash-tts-preview, gemini-3.8-flash-tts, gemini-3.8-flash-lite-tts). So the "no TTS model" symptom was also the v1 API, which simply doesn't list them. gemini-2.5-flash-preview-tts returned an empty candidate; gemini-3.1-flash-tts-preview returned audio.
- **Follow-up:** the probe tried oldest first. It now ranks newest version first (flash before pro, non-lite before lite, stable before preview), so it tries gemini-3.8-flash-tts first.

## F4. ffmpeg missing on a fresh Windows machine
- **Broke:** `pipeline.run --offline` crashed with `FileNotFoundError: [WinError 2]` inside `run_ffmpeg`.
- **Fix:** installed ffmpeg (`winget install Gyan.FFmpeg`); `run_ffmpeg` now exits with an install hint instead of a stack trace.
