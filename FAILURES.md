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

## F14. Wan kernel OOM-killed (host RAM) after denoising
- **Broke:** the F13-fixed s03 run loaded the model in 273 s, finished all 30 steps (~15 s/step on a T4), then the log just says `Killed` during VAE decode; `results.json` had no entry for the shot.
- **Cause:** model CPU offload keeps every component's weights in host RAM. Moving the ~11 GB fp16 UMT5 text encoder to the CPU (F13) only moved the problem: text encoder + 10 GB transformer + fp32 VAE + CUDA context filled the ~30 GB Kaggle VM and the OOM killer stopped the process.
- **Fix:** the kernel encodes all prompts up front, then sets `pipe.text_encoder = None` and rebuilds the offload hooks so nothing keeps it alive. New `wan_kaggle rerun` re-pushes the notebook for the last submission against the dataset already on Kaggle, so a machine without the keyframe images can retry.

## F15. ACE-Step music: CUDA OOM in the VAE decode on a T4
- **Broke:** first music run on Kaggle: the model loaded in 73.5 s and each 88 s candidate finished its 8 steps, then all three (seeds 42-44) failed with `CUDA out of memory. Tried to allocate 1.01 GiB` inside the Oobleck VAE `decode` (12 GiB already allocated by PyTorch).
- **Cause:** the kernel moved the whole pipeline to the GPU with `.to("cuda")`, so the transformer and text encoder were still resident when the VAE decoded 88 s of 48 kHz audio.
- **Fix:** `enable_model_cpu_offload()` (falls back to `.to("cuda")` if the pipeline has no offload sequence), `expandable_segments`, and `empty_cache()` after a failed candidate.

## F16. shots.py crashed on a fresh clone
- **Broke:** `KeyError: 'file'` in `pipeline.shots` on the personal PC.
- **Cause:** an errored Wan run is recorded in `shots/wan/manifest.json` without a `file`, and the keyframes manifest comes from git while the images don't, so a shot could point at a keyframe that isn't on this machine.
- **Fix:** shots treats a keyframe whose image is missing as "no keyframe yet" (placeholder) and only uses a Wan entry that has a file on disk.

## F17. End-card drawtext broke on a Windows font path
- **Broke:** `assemble` on the personal PC: ffmpeg `No option name near '/Windows/Fonts/segoeui.ttf:text=...'`.
- **Cause:** the escaped `fontfile=C\:/Windows/...` was not quoted, so the filtergraph parser consumed the backslash and the option parser then split on the drive-letter colon. Paths without a colon (Linux/macOS) never hit it.
- **Fix:** quote the value: `fontfile='C\:/Windows/Fonts/segoeui.ttf'`, the same way `text` already was.

## F18. Final mix 1.3 LU under the -14 LUFS target
- **Broke:** the first personal-PC export measured -15.3 LUFS integrated (ebur128) against a `loudnorm=I=-14` target.
- **Cause:** single-pass loudnorm runs in dynamic mode and has to guess the integrated level as it goes; narration with pauses and no music bed lands low.
- **Fix:** `assemble` measures the mix first (`loudnorm ... print_format=json`, audio only, a few seconds) and applies the measured values with `linear=true`. Re-measured: -13.9 LUFS, true peak -1.4 dBFS.

## F19. ACE-Step candidates came out silent/NaN in fp16
- **Broke:** after F15 the music kernel no longer OOMed, but all three candidates (seeds 42-44, 19-25 s GPU each) failed the kernel's own check: `generated audio is silent or NaN`.
- **Cause (likely):** the whole pipeline ran in fp16 because the T4 has no fast bf16, and the Oobleck VAE's snake activations overflow in fp16.
- **Fix:** the transformer stays fp16 and the VAE runs in fp32. A pre-hook on the VAE decoder casts the latents to fp32 and logs whether they were already non-finite, so if the transformer is the culprit the next error says so.
