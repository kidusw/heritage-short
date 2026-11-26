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
- **Implication:** about 20 minutes per shot means about 3 hours of GPU for all 11 shots, before queueing, with artifacts on top. Ken Burns takes about 2 s per shot locally and never fails. **Decision (25 Nov): Ken Burns for every shot in the film**; Wan kept as an experiment (E5).

## E5. Blind test: Wan 2.2 vs Ken Burns on the same still (s03, camels at Awash)
- **Hypothesis:** viewers prefer real generated motion (Wan) over a pan/zoom on a still, enough to justify ~20 GPU-minutes per shot.
- **Method:** `python -m pipeline.abtest s03` renders both versions at the same length and size, labelled A/B in random order (key kept in `outputs/abtest/s03_key.json`). Viewers watch both without being told which is which, and answer: "Which feels more like a real memory, and why?"
- **Result:** _votes and quotes from 3+ viewers to fill in._
- **Note (26 Nov):** the A/B pair was rendered from the storyboard v4 still, which shows the old white car. Storyboard v5 makes the car blue-green, so the film's s03 no longer matches the test still. The experiment is left as is: it compares motion methods on one still, and the car colour doesn't change that question.

## E6. Keyframe review after the car colour change (FLUX schnell, 4 shots)
- **What I checked:** every regenerated still (s03, s05, s06, s10) for car colour, garbled text, hands/faces and modern cars.
- **Car colour:** all four came out teal, matching the v5 description on the first try.
- **Text:** every still painted fake badge and plate text ("HLANTRA", "HYUNGLATRA", "DIRE-DAWON"). The character description names the make and model and asks for an Ethiopian number plate, and FLUX schnell takes no negative prompt, so the style's "text" negative never reaches it.
- **Retries:** s06 and s10 got two new seeds each (the limit). s10's last take (seed 410) is the best. s06 never showed the temperature gauge the prompt asks for; the kept take (seed 306) is the one with the least text, but it misses the gauge.
- **Next:** dropping "Hyundai Elantra" and "number plate" from the prompt (or describing the car only by shape and colour) is the likely fix for the text; s06's prompt should lead with the gauge close-up rather than the car.
- **Follow-up (storyboard v6, 26 Nov):** the car is now described by shape and colour only ("a boxy blue-green early-1990s four-door sedan..."), with no make, model or plate. The fake text dropped from large readable badges to small marks on most stills (s03, s05, s10 near clean). s06 was rewritten to lead with "extreme close-up of an old analogue dashboard temperature gauge" and no longer lists the car: the gauge now shows up, though the dashboard reads modern and the dial text is garbled.

## E7. Family keyframes after consent (FLUX schnell, 6 shots, 3 rounds)
- **First round:** the father came out light-skinned or European-looking in 4 of 5 shots, although his description said "an Ethiopian father". s09 had six people including a toddler.
- **Change:** the father's description became "an Ethiopian (Habesha) father in his fifties with brown skin...", and s09's prompt names "the five of them ... all adults".
- **Result:** the father reads as Ethiopian in every shot after that, and s09 shows five adults. The mother's white netela came through every time. s01, s02 and s06 used both retries (seeds 301, 402, 606); s05 one (305). Kept with known flaws: s02 is a front view rather than from the back seat, s07 doesn't show steam or the open bonnet, and modern cars still creep into the foreground of several frames (FLUX schnell takes no negative prompt).

## E8. Consistent family looks without reference images (storyboard v7, pending)
- **Why:** after v6 I asked for a review, and the feedback was that the family looked Indian or South Asian (the father in s02, the mother in s09), the siblings far too dark, and nobody looked like the same person from shot to shot. We are a Habesha family from Addis Ababa with light-brown skin.
- **Change:** each of the five has one fixed description that starts "a Habesha Ethiopian ... from Addis Ababa ... with light-brown skin", plus a fixed outfit and hairstyle (father: beige jacket over a light-blue collared shirt and a moustache; mother: white netela with a tibeb border over a cream dress; sister: long braids and a mustard-yellow top; brother: short curly hair and a dark-green t-shirt; narrator: plain white shirt). Every family shot's prompt now says "Ethiopian Habesha family", and `keyframes.build_prompt` inserts the descriptions in storyboard order so they sit in the same place in every prompt.
- **Status:** not generated yet. Cloudflare's free daily allocation (10,000 neurons) ran out after the v6 retries; it resets at 00:00 UTC.
- **Limit to expect:** FLUX schnell has no reference-image input and isn't seed-reproducible on Cloudflare, so text alone can make skin tone and clothing repeat, but not faces. If the faces still drift, the cheapest step up is to generate one approved portrait per person and condition every shot on it (an image-reference or face-ID model such as FLUX Kontext / PuLID / IP-Adapter on the free Kaggle T4, the way the Wan and ACE-Step stages already run).
- **Follow-up (26 Nov):** built a Gemini image provider for the family shots: one reference portrait per person (`outputs/keyframes/refs/`), then each shot generated from the portraits of the people in it, which is the reference-image consistency FLUX schnell can't do. Not run yet: Gemini image models need billing on the key (FAILURES.md F23).
