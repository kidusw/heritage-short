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

## F5. Kaggle API check returned 404
- **Broke:** the smoke test's raw `GET https://www.kaggle.com/api/v1/kernels/list` returned 404 with my credentials.
- **Cause:** Kaggle moved its API to `api.kaggle.com` and to new API tokens (`KAGGLE_API_TOKEN`, `KGAT_...`); the old REST path I'd written from memory is gone.
- **Fix:** the smoke test now calls the official `kaggle` CLI (`python -m kaggle.cli kernels list --mine`), which tracks those changes, and accepts either a new token or legacy username+key.

## F6. Free-tier TTS quota ran out after 5 of 18 clips (day 1)
- **Broke:** `gemini-3.8-flash-tts` returned `429 RESOURCE_EXHAUSTED`: the free tier allows ~10 requests per day per model, and smoke tests and model probes had already used some. My retry loop then spent 3 more attempts on a quota that resets the next day.
- **Fixes:**
  1. **Don't retry daily quotas.** `with_retries(give_up=...)` stops at once when the error names a per-day quota.
  2. **Fail over across models.** `TTSChain` moves to the next TTS model (3.8-flash, 3.8-flash-lite, 3.1-flash-preview, 2.5...) when one is exhausted; each has its own daily quota.
  3. **Batch per language.** One TTS request reads all of a language's lines with pauses between them, and ffmpeg `silencedetect` cuts it at the n-1 longest pauses. A full film costs 2 requests instead of 18. If the pauses can't be found, it falls back to per-shot.
  4. **No probe calls.** Model discovery now uses the model list only; the smoke test reuses its sample instead of spending a request each run.
  5. **Manifest written after every clip,** so a crash mid-run keeps finished clips.

## F7. Stale clips survived in the narration manifest
- **Broke:** after the cache-version bump, the manifest still pointed en s04-s09 and all Amharic shots at the mis-cut batch clips, because entries were merged per clip and only overwritten when a shot was regenerated. A radio cut would have silently used them.
- **Fix:** narration now drops any manifest entry whose file name doesn't match the current cache key (text, voice, model setting, cache version), and radio_cut refuses to run if any narrated shot has no current clip.

## F8. All five free TTS models exhausted in one evening
- **Broke:** narration stopped after 3 of 18 clips. Two of those three cost two calls each, because gemini-3.8-flash-tts and 3.8-flash-lite-tts spoke the direction and the clip had to be redone. gemini-2.5-flash-preview-tts returned 500 INTERNAL.
- **Fix:** models caught speaking the direction are saved in `outputs/narration/tts_quirks.json` and never sent a direction again, so each clip costs one call. Lesson for the schedule: debugging cost more quota than the actual film. Final narration runs right after the daily reset (midnight Pacific, 11:00 EAT).

## F9. Work PC: TLS "self-signed certificate in chain" and Kaggle CLI missing `six` (day 2)
- **Broke:** on the work PC the smoke test failed for Cloudflare and then Kaggle with `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`, on different hosts on different runs, while a direct check showed the normal Google Trust Services chain. The network intercepts some HTTPS connections with a certificate that only the Windows store trusts. Separately, the `kaggle` CLI crashed with `ModuleNotFoundError: No module named 'six'`.
- **Fix:** `load_env()` injects `truststore`, so Python verifies TLS against the OS store (verification stays on). The kaggle CLI runs in a subprocess the injection doesn't reach, so `common.KAGGLE_CLI` launches it through a stub that injects truststore first. `truststore` and `six` are in requirements.txt.

## F10. flux-1-schnell rejects `seed`
- **Broke:** the first real Cloudflare call returned 400 `AiError: Bad input: Additional or unevaluated properties '/seed'` (code 5006).
- **Fix:** `cf_generate` only sends `seed` to models other than flux-1-schnell. Schnell keyframes aren't seed-reproducible; the hash cache is what keeps them stable between runs.

## F11. Manifests written on Windows broke on Linux/macOS
- **Broke:** the work PC wrote manifest paths like `outputs\keyframes\s03_....jpg`. On Linux `ROOT / "outputs\\keyframes\\..."` is one strange file name, so the shots stage couldn't find any keyframe from a clone on another OS.
- **Fix:** `common.rel()` writes every manifest/log path with forward slashes, and `common.from_manifest()` reads old backslash entries too. A repo meant to be cloned anywhere must not store OS-specific paths.

## F12. End card cut off in the vertical export
- **Broke:** the end card text was drawn on the square master, so the 9:16 centre crop (608 of 1080 px wide) cut both lines off. Caught by grabbing a frame from each export, not by any error.
- **Fix:** the card is blank in the master and its text is drawn after cropping, sized to each frame's width.

## F13. Wan 2.2 TI2V-5B ran out of GPU memory on a Kaggle T4
- **Broke:** the first Wan test (s03) loaded the model in 274 s, then failed after 15 s: `CUDA out of memory ... 14.39 GiB is allocated by PyTorch`, raised while moving the VAE to the GPU inside `prepare_latents`.
- **Cause:** `enable_model_cpu_offload()` chains text_encoder -> transformer -> vae and offloads each model only when the next one in the chain runs. The I2V pipeline calls `vae.encode` before the transformer, so the ~11 GB fp16 UMT5-XXL text encoder was still on the GPU when the fp32 VAE arrived.
- **Fix:** the kernel encodes the prompt itself, moves the text encoder to CPU and calls `maybe_free_model_hooks()` before the pipeline runs, then passes `prompt_embeds`. It also turns on VAE tiling and `expandable_segments`.
