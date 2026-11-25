# Experiments

Format: **hypothesis → change → result** (with the `run_id` from runs.jsonl as evidence).

## E1. Batched vs per-shot narration
- **Hypothesis:** reading all of a language's lines in one TTS request (then splitting on pauses) costs 1/9 of the quota and gives a more consistent voice across shots, at the risk of bad split points.
- **Change:** `narration --mode batch` vs `--mode per-shot`, same storyboard.
- **Result (run 1, gemini-3.8-flash-lite-tts):** 2 requests instead of 18, but the split failed in both languages.
  - English: the model *spoke the direction aloud even as a system instruction* ("Narrate warmly and calmly... Leave a two-second pause between paragraphs"), so that became "s01" and every shot shifted by one.
  - Amharic: no direction spoken, but the 18 pauses were 0.45-1.0 s with pauses inside paragraphs as long as those between them, so "the 8 longest pauses" cut mid-sentence (s07-s09 became 1-2 s fragments).
- **Changes:** (a) per-shot is now the default; batch is opt-in. (b) Batch sends no direction at all. (c) The splitter picks, for each boundary, the pause nearest where it should fall if speaking time is proportional to text length, instead of the longest pauses. Tested on a synthetic file with pauses inside paragraphs: correct 2/8/2 s split. (d) `CACHE_VERSION` bumped so the mis-cut clips aren't reused.
- **Conclusion so far:** quota savings are real, but pause-splitting is fragile. Per-shot plus failover across 5 TTS models (~50 free requests/day) is enough for 18 clips.

## E2. Is the style direction read aloud?
- **Observation:** first real English clips were 1.7-2.1x their shots (e.g. s01: 14 words -> 15.4 s, about 0.9 words/s; normal narration is about 2.5 words/s).
- **Hypothesis:** the multi-line style prompt ("Read this warmly and slowly, like a young man...") was spoken as part of the clip.
- **Check:** transcribed the clip with gemini-3.5-flash and ran ffmpeg `silencedetect`.
- **Result:** confirmed on gemini-3.8-flash-tts. Transcript: "Read this warmly and slowly, like a young man telling his family about a trip he loved. ... I had heard about Dire Dawa my whole life. One morning, I finally went." The direction is spoken from 0 to 5.5 s, then 4.2 s of silence, then the real line (9.7 to 15.4 s, about 5.7 s, which fits the 7 s shot). gemini-3.1-flash-tts-preview did **not** read it aloud (8.1 s clip). Same prompt, different model, different behaviour.
- **Change:** the direction now goes in `system_instruction`, with inline `<direction>: <text>` only as a fallback if a model rejects that. The stage also warns when a clip is >1.8x the expected speaking time for its word count, so this class of bug gets caught automatically.
- **Follow-up:** gemini-3.8-flash-lite-tts spoke the direction even from `system_instruction` (in batch mode). So per-shot narration now checks each clip's length against its word count; if it is >1.8x, it regenerates once **without** the direction and logs `retry_reason: direction_spoken`.

## E3. Amharic TTS pronunciation
- **Hypothesis:** Gemini Flash TTS pronounces Amharic well enough for a family audience without phonetic respelling.
- **Change:** storyboard v2 narrated in Amharic (11 clips, run `9943b62` in runs.jsonl); 3 clips transcribed back with gemini-3.5-flash as an automatic check.
- **Result:** s08 transcribed exactly. s01 "ብዙዎች" (many people) came back as something like "by buses", and s11 "ላይም" came back as "ያም": possible mispronunciations, to confirm by ear. Round-trip transcription is a cheap way to flag words to listen to, not proof of an error.
- **Also:** no clip needed a "direction spoken" redo; `tts_quirks.json` stopped the direction from reaching the two models that speak it, so each clip cost one successful call. The whole 85 s Amharic cut needed 11 clips (s02 stretched by 0.1 s only).

## E4. Wan 2.2 image-to-video on a free Kaggle T4: what it really costs
- **Hypothesis:** Wan 2.2 TI2V-5B can animate every keyframe on free Kaggle GPU time within the 3-day window.
- **Change:** `pipeline.wan_kaggle` at 640x640, 81 frames (3.4 s at 24 fps), 30 steps, fp16 transformer, fp32 VAE, CPU offload.
- **Result (s03, run in runs.jsonl):** three attempts. Run 1 ran out of GPU memory (text encoder stayed on the GPU, F13). Run 2 finished sampling (~15 s/step) and was killed by host-RAM OOM in the VAE decode (F14). Run 3 succeeded: **275.8 s model setup + 929 s GPU for one shot (1278 s for the whole notebook)**, plus about an hour of queue time before it started. Visible artifacts: a camel ends up on the car's roof rack, and a hand enters at the bottom edge.
- **Implication:** about 20 minutes per shot means about 3 hours of GPU for all 11 shots, before queueing, with artifacts on top. Ken Burns takes about 2 s per shot locally and never fails. Decision pending (DESIGN.md).
