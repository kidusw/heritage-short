# The Long Road to Dire Dawa: a Heritage Short pipeline

A 60–90 second short film about my family's first trip to Dire Dawa and the Saint Gabriel celebration at Kulubi, narrated in **Amharic with English subtitles** (an English-narrated cut is one flag away: `--lang en`), made by a
code pipeline instead of by hand. One file, [`storyboard.json`](storyboard.json), is the contract between
every stage; each stage reads it and writes its own outputs, so changing one shot regenerates only that shot.

> Status: final cut, 26 Nov 2026. The Amharic film is 85.5 s in 16:9 and 9:16, at -14.4 LUFS. It has 11 shots, all
> as Ken Burns moves on FLUX keyframes (Wan 2.2 image-to-video was measured as an experiment, E4/E5), an original
> ACE-Step score (candidate b) ducked under the voice, burned-in English subtitles and an AI end card.
> Family likenesses were generated only after written consent was recorded in [ETHICS.md](ETHICS.md).

## Run it

```bash
git clone https://github.com/kidusw/heritage-short && cd heritage-short
python -m pip install -r requirements.txt     # Python 3.10+, plus ffmpeg on PATH
cp .env.example .env                          # add your keys (see below)
make film                                     # or, without make (Windows): python -m pipeline.run
```

Try the plumbing without any keys: `make offline` (or `python -m pipeline.run --offline`) produces
placeholder audio and images through the same stages, cache and logs.

| Command | What it does |
|---|---|
| `make validate` | Checks `storyboard.json` against [`schema/`](schema/storyboard.schema.json) plus cross-field rules |
| `make smoke` | Calls each provider once with a tiny request and logs it |
| `make radio` | Narration for every shot + the narration-only "radio cut" for each language |
| `make film LANG=am` | Whole pipeline, Amharic only |
| `make film SHOTS=s04` | Regenerate one shot through every stage |
| `python -m pipeline.wan_kaggle run` | Send keyframes to a free Kaggle GPU for Wan 2.2 image-to-video, wait, download the clips |
| `python -m pipeline.music run` | Three ACE-Step score candidates on Kaggle; then `python -m pipeline.music choose b "why"` |
| `make costs` | Per-stage table of calls, cache hits, latency, GPU minutes and cost from `runs.jsonl` |

Windows: install ffmpeg with `winget install Gyan.FFmpeg`, and use `python -m pipeline.<stage>` in place of `make`.

## Keys

| Variable | Where to get it | Used by |
|---|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) (free tier) | narration (TTS) |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | Cloudflare dashboard → Workers AI → "Use REST API" | keyframes (FLUX) |
| `KAGGLE_API_TOKEN` (a `KGAT_...` token; legacy `KAGGLE_USERNAME` + `KAGGLE_KEY` also work) | kaggle.com → Settings → API → Create New Token | moving shots, music (GPU) |

Keys live only in `.env`, which is gitignored.

## Pipeline

```
storyboard.json ──validate──┬─> narration (Gemini TTS, per language) ──> radio_cut (prototype + subtitles)
                            ├─> keyframes (Cloudflare FLUX) ──> shots (Ken Burns | Wan 2.2 on Kaggle, per shot)
                            ├─> music (ACE-Step on Kaggle)
                            └─> assemble (duck, loudnorm, subtitles, end card, 9:16 + 16:9 per language)
```

Outputs: `outputs/final/the-long-road-to-dire-dawa_<lang>_<16x9|9x16>.mp4` with a matching `.srt`. Media is
gitignored, while manifests, subtitles and `runs.jsonl` are committed.

Every model call appends one line to [`runs.jsonl`](runs.jsonl): model, parameters, seed, latency, cost,
status, attempt, cache hit. Details in [ARCHITECTURE.md](ARCHITECTURE.md).

## What it costs

$0 actual spend: everything ran on free tiers and Kaggle's free GPU quota. Everything we ran, failures included, would cost about $0.25 at list prices, and one clean run about $0.02. See [COSTS.md](COSTS.md).

## Documents

[DESIGN.md](DESIGN.md) (audience, intent, user tests) · [ARCHITECTURE.md](ARCHITECTURE.md) ·
[EXPERIMENTS.md](EXPERIMENTS.md) · [FAILURES.md](FAILURES.md) · [COSTS.md](COSTS.md) · [ETHICS.md](ETHICS.md)
