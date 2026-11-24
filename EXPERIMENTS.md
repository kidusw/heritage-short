# Experiments

Format: **hypothesis → change → result** (with the `run_id` from runs.jsonl as evidence).

## E1. Batched vs per-shot narration
- **Hypothesis:** reading all of a language's lines in one TTS request (then splitting on pauses) costs 1/9 of the quota and gives a more consistent voice across shots, at the risk of bad split points.
- **Change:** `narration --mode batch` vs `--mode per-shot`, same storyboard.
- **Result:** _to fill: requests used, split success, listening notes._

## E2. Is the style direction read aloud?
- **Observation:** first real English clips were 1.7-2.1x their shots (e.g. s01: 14 words -> 15.4 s, about 0.9 words/s; normal narration is about 2.5 words/s).
- **Hypothesis:** the multi-line style prompt ("Read this warmly and slowly, like a young man...") was spoken as part of the clip.
- **Check:** transcribe the clip with a non-TTS Gemini model and run `silencedetect`.
- **Change:** prompt now sent as a single line, `<direction>: <text>`.
- **Result:** _to fill._

## E3. Amharic TTS pronunciation
- Hypothesis:
- Change:
- Result:
