# Experiments

Format: **hypothesis → change → result** (with the `run_id` from runs.jsonl as evidence).

## E1. Batched vs per-shot narration
- **Hypothesis:** reading all of a language's lines in one TTS request (then splitting on pauses) costs 1/9 of the quota and gives a more consistent voice across shots, at the risk of bad split points.
- **Change:** `narration --mode batch` vs `--mode per-shot`, same storyboard.
- **Result:** _to fill: requests used, split success, listening notes._

## E2. Is the style direction read aloud?
- **Observation:** first real English clips were 1.7-2.1x their shots (e.g. s01: 14 words -> 15.4 s, about 0.9 words/s; normal narration is about 2.5 words/s).
- **Hypothesis:** the multi-line style prompt ("Read this warmly and slowly, like a young man...") was spoken as part of the clip.
- **Check:** transcribed the clip with gemini-3.5-flash and ran ffmpeg `silencedetect`.
- **Result:** confirmed on gemini-3.8-flash-tts. Transcript: "Read this warmly and slowly, like a young man telling his family about a trip he loved. ... I had heard about Dire Dawa my whole life. One morning, I finally went." The direction is spoken from 0 to 5.5 s, then 4.2 s of silence, then the real line (9.7 to 15.4 s, about 5.7 s, which fits the 7 s shot). gemini-3.1-flash-tts-preview did **not** read it aloud (8.1 s clip). Same prompt, different model, different behaviour.
- **Change:** the direction now goes in `system_instruction`, with inline `<direction>: <text>` only as a fallback if a model rejects that. The stage also warns when a clip is >1.8x the expected speaking time for its word count, so this class of bug gets caught automatically.
- **Follow-up result:** _to fill after re-run._

## E3. Amharic TTS pronunciation
- Hypothesis:
- Change:
- Result:
