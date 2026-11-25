# Architecture

## The contract
`storyboard.json` is the only input. It is validated twice before any stage runs:
1. **JSON Schema** (`schema/storyboard.schema.json`): types, required fields, ranges (shots 2–15 s),
   id patterns, and "a real person needs a `consent_ref`".
2. **Consistency checks** in `pipeline/common.py::load_storyboard`: unique shot ids, every referenced
   character exists, every shot has narration for every language (empty string = deliberate silence),
   every language has a voice.

Stages never write the storyboard. They write `outputs/<stage>/` and a `manifest.json` that says which
file is current for each shot. Later stages read manifests, never guess file names.

## Stages
| Stage | Reads | Writes | Provider |
|---|---|---|---|
| validate | storyboard | — | local |
| narration | storyboard (narration, voices) | `outputs/narration/<shot>_<lang>_<hash>.wav` | Gemini TTS |
| radio_cut | storyboard, narration manifest | `outputs/radio/radio_<lang>.mp3`, `timeline_<lang>.json`, `subtitles_<lang>_en.srt` | ffmpeg |
| keyframes | storyboard (style, characters, prompts, seeds) | `outputs/keyframes/<shot>_<hash>.jpg` | Cloudflare Workers AI |
| wan_kaggle | keyframes manifest, storyboard motion prompts | `outputs/shots/wan/<shot>_<hash>.mp4` + manifest | Wan 2.2 TI2V-5B on a Kaggle T4 (submit / status / collect) |
| shots | keyframes + wan manifests | `outputs/shots/<shot>_<method>_<hash>.mp4`, 1080x1080, 24 fps, exact shot length | ffmpeg: Wan clip fitted to length, else Ken Burns, else placeholder |
| music | storyboard.music, radio timelines (for length) | `outputs/music/<a|b|c>_<hash>.wav` + manifest {candidates, chosen, why} | ACE-Step 1.5 XL turbo (diffusers) on a Kaggle T4, 3 seeds |
| assemble | shots + music manifests, radio timeline, narration, subtitles | `outputs/final/<title>_<lang>_<16x9|9x16>.mp4` + .srt | ffmpeg: sidechain ducking, -14 LUFS, burned subtitles, end card drawn per aspect |

## Caching
Each output's file name contains `cache_key(...)`: a SHA-256 of **everything that determines it**
(stage, provider, model id, text/prompt, voice, seed, steps). If the file exists, the stage logs a
`cache_hit` and skips the call. Consequences:
- Edit shot 4's prompt → only shot 4's hash changes → only shot 4 regenerates.
- Change the TTS model → every narration hash changes → all narration regenerates (correct).
- Old versions stay on disk, so A/B comparisons in EXPERIMENTS.md can point at both files.

## Failure handling
`with_retries` wraps every remote call: up to 4 attempts, exponential backoff with jitter, and 3× longer
waits for quota errors (HTTP 429 / `RESOURCE_EXHAUSTED`). **Every attempt is logged**, so failures show
up in `runs.jsonl` and `make costs`. Visual shots fall back to Ken Burns (pan/zoom on the keyframe)
if the video model fails, so a quota outage degrades the film instead of blocking it.

## Logging
`runs.jsonl`, one JSON object per call: `ts, run_id, stage, shot, provider, model, params, seed,
latency_s, gpu_s, cost_usd, status, cache_hit, attempt, output, error`. `run_id` groups all calls from
one `make film`.

## Languages
Languages are data, not code: `storyboard.languages` lists them, each shot has `narration.<lang>`, and
`voices.<lang>` holds the TTS voice. Every stage takes `--lang`. Each language gets its own timeline,
because Amharic and English readings differ in length; English subtitles are timed to each timeline.

## Moving shots: why two steps
A Wan run on Kaggle takes tens of minutes to hours (queue, ~23 GB model download, minutes per clip on a T4),
so it is a separate, asynchronous step: `python -m pipeline.wan_kaggle submit` uploads the keyframes and a
`jobs.json` as a private Kaggle dataset and pushes a private GPU notebook (`pipeline/kaggle/wan_i2v.py`);
`collect` downloads the clips and a `results.json` with per-shot GPU seconds into runs.jsonl.
`pipeline.shots` never waits for the GPU: for each shot it uses the Wan clip if one exists for the current
keyframe, otherwise a Ken Burns move chosen from the motion prompt's words ("pull-back" -> zoom out,
"pan right"/"tracking" -> pan, default -> push in). So `make film` always produces a complete cut, and it gets
better as Wan clips arrive. A shot whose people lack recorded consent becomes a dark placeholder.
