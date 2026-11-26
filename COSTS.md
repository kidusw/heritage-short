# Costs

**Actual spend: $0.00.** Every model call ran on a free tier: the Gemini API free tier (about 10 TTS requests per day per model), Cloudflare Workers AI's daily free allowance of 10,000 neurons, and Kaggle's free weekly GPU quota on a T4. The **list-price equivalent of everything we ran, failures included, is about $0.25**, worked out below.

## Per stage (from `runs.jsonl`)

Generated with `make costs` (`python -m pipeline.costs`) on 2026-11-26, from both PCs' logs (24–26 Nov). "calls" counts real calls, failed ones included. "cache hits" are calls the content-hash cache avoided. `local` rows are ffmpeg on the laptop. `offline placeholder-tone` and `ffmpeg-placeholder` rows are free stand-ins: dev tests, and the family shots before consent was recorded.

| stage | provider | model | calls | failed | cache hits | median latency (s) | GPU min | cost (USD) |
|---|---|---|---|---|---|---|---|---|
| abtest | local | ffmpeg | 1 | 0 | 0 | 0.00 | 0.0 | 0.0000 |
| final | local | ffmpeg | 20 | 0 | 0 | 34.38 | 0.0 | 0.0000 |
| keyframes | cloudflare | @cf/black-forest-labs/flux-1-schnell | 48 | 0 | 27 | 4.02 | 0.0 | 0.0000 |
| music | human | choice | 1 | 0 | 0 | 0.00 | 0.0 | 0.0000 |
| music | kaggle | ACE-Step/acestep-v15-xl-turbo-diffusers | 12 | 9 | 0 | 49.30 | 5.4 | 0.0000 |
| music | kaggle | kernels push | 3 | 0 | 0 | 4.71 | 0.0 | 0.0000 |
| narration | gemini | auto | 0 | 0 | 23 | 0.00 | 0.0 | 0.0000 |
| narration | gemini | gemini-2.5-flash-preview-tts | 3 | 3 | 0 | 0.00 | 0.0 | 0.0000 |
| narration | gemini | gemini-2.5-pro-preview-tts | 1 | 1 | 0 | 0.00 | 0.0 | 0.0000 |
| narration | gemini | gemini-3.1-flash-tts-preview | 12 | 3 | 0 | 5.79 | 0.0 | 0.0000 |
| narration | gemini | gemini-3.8-flash-lite-tts | 28 | 10 | 0 | 3.88 | 0.0 | 0.0000 |
| narration | gemini | gemini-3.8-flash-tts | 36 | 17 | 0 | 3.85 | 0.0 | 0.0000 |
| narration | offline | placeholder-tone | 11 | 0 | 0 | 0.00 | 0.0 | 0.0000 |
| radio | local | ffmpeg | 7 | 0 | 0 | 0.00 | 0.0 | 0.0000 |
| shots | local | ffmpeg-kenburns | 24 | 0 | 0 | 2.38 | 0.0 | 0.0000 |
| shots | local | ffmpeg-placeholder | 17 | 0 | 0 | 0.64 | 0.0 | 0.0000 |
| shots | local | ffmpeg-wan | 1 | 0 | 0 | 3.94 | 0.0 | 0.0000 |
| shots | local | kenburns | 0 | 0 | 11 | 0.00 | 0.0 | 0.0000 |
| shots | local | placeholder | 0 | 0 | 26 | 0.00 | 0.0 | 0.0000 |
| smoke | cloudflare | @cf/black-forest-labs/flux-1-schnell | 1 | 0 | 0 | 19.32 | 0.0 | 0.0000 |
| smoke | gemini | gemini-3.1-flash-tts-preview | 1 | 0 | 0 | 3.31 | 0.0 | 0.0000 |
| smoke | gemini | gemini-3.8-flash-tts | 3 | 0 | 0 | 2.63 | 0.0 | 0.0000 |
| smoke | gemini | models.list | 10 | 0 | 0 | 0.69 | 0.0 | 0.0000 |
| smoke | kaggle | kaggle-cli kernels list | 7 | 4 | 0 | 7.70 | 0.0 | 0.0000 |
| smoke | kaggle | kernels.list | 1 | 1 | 0 | 0.00 | 0.0 | 0.0000 |
| tts_probe | gemini | gemini-2.5-flash-preview-tts | 3 | 3 | 0 | 0.00 | 0.0 | 0.0000 |
| tts_probe | gemini | gemini-2.5-flash-tts | 1 | 1 | 0 | 0.00 | 0.0 | 0.0000 |
| tts_probe | gemini | gemini-3.1-flash-tts-preview | 2 | 0 | 0 | 3.04 | 0.0 | 0.0000 |
| tts_probe | gemini | gemini-3.8-flash | 1 | 1 | 0 | 0.00 | 0.0 | 0.0000 |
| tts_probe | gemini | gemini-3.8-flash-preview-tts | 1 | 1 | 0 | 0.00 | 0.0 | 0.0000 |
| tts_probe | gemini | gemini-3.8-flash-tts | 5 | 1 | 0 | 2.29 | 0.0 | 0.0000 |
| tts_probe | gemini | gemini-omni-flash-preview | 1 | 1 | 0 | 0.00 | 0.0 | 0.0000 |
| wan | kaggle | Wan-AI/Wan2.2-TI2V-5B-Diffusers | 3 | 2 | 0 | 928.80 | 15.7 | 0.0000 |
| wan | kaggle | datasets upload | 2 | 0 | 0 | 43.45 | 0.0 | 0.0000 |
| wan | kaggle | kernels push | 3 | 0 | 0 | 4.94 | 0.0 | 0.0000 |

## What the failures cost

- **Gemini TTS: 34 of 80 narration calls failed.** Almost all were daily-quota 429s, which is why the pipeline has a failover chain and a `give_up` rule, and makes no probe calls (FAILURES F2–F4). A failed call returns no audio and would not be billed on a paid tier.
- **Kaggle music: 9 of 12 attempts failed** (three runs of 3 candidates: out-of-memory, then silent/NaN output twice, F15/F19). About 5 GPU-minutes went on runs that produced nothing.
- **Kaggle Wan: 2 of 3 runs failed** (out-of-memory on the GPU, then in host RAM, F13/F14). The one good run took 929 s of T4 time for a single 3.4 s clip.

## List-price equivalent (if paid)

Prices are from the providers' pricing pages, read on 2026-11-26.

| Item | Usage | Unit price | Equivalent |
|---|---|---|---|
| Gemini 3.8 Flash TTS | 19 successful clips, about 6 s each, 25 audio tokens/s, about 2,900 tokens | $9.00 / 1M audio tokens | $0.03 |
| Gemini 3.8 Flash-Lite TTS | 18 clips, about 2,700 tokens | $6.00 / 1M | $0.02 |
| Gemini 3.1 Flash TTS (preview) | 9 clips, about 1,400 tokens | $20.00 / 1M | $0.03 |
| TTS input text | about 3,500 characters, under 2k tokens | $0.50–1.00 / 1M | < $0.01 |
| Cloudflare FLUX.1 schnell | 49 images at 1024×1024 (4 tiles), 8 steps: 4×4.8 + 8×9.6 = 96 neurons each, 4,700 neurons total | $0.011 / 1k neurons ($0.0000528/tile + $0.0001056/step) | $0.05 (**$0 in practice**: under the 10k-neuron daily free allowance) |
| Kaggle T4 GPU | 1,267 s logged (Wan 15.7 min, music 5.4 min), plus about 70 s of model load per run that isn't logged | assumed about $0.35/h for an on-demand cloud T4 (not a quoted price) | about $0.12 |
| **Total** | | | **about $0.25** |

Assumptions: the clip length is an average (the radio cut is 85 s for 11 lines including pauses). The T4 rate is a rough market figure, not a quoted price. Prices for the Gemini 3.8 TTS previews double on 1 Jan 2027.

## Cost per finished film

One clean run with a warm cache costs about **$0.02**: 11 TTS clips (about $0.01), 11 keyframes (about $0.01, free in practice) and 3 music candidates (about 3 GPU-minutes, about $0.02). Assembling is local and free. The spending went on iteration: re-takes for spoken style directions, storyboard rewrites v1 to v7, and the music and Wan failures above.

## Family shots on Gemini (built, not run)

The six family shots are set to use Gemini image generation with a reference portrait per person (E8). On this key, every Gemini image model has a free-tier limit of 0 (F23), so nothing was spent: the 12 refused calls on 26 Nov cost $0. With billing on, Gemini 2.5 Flash Image is listed at about $0.039 per 1024×1024 image. 5 portraits + 6 shots is about $0.43 per full pass, or about $0.80 with a retry or two per shot. Portraits are cached, so changing one shot later costs one image.

The free Cloudflare allowance (10,000 neurons a day, about 100 FLUX images) also ran out on 26 Nov, after three rounds of family-shot retries. That's another sign that getting likenesses right by text alone is the expensive part.

## What would change at scale

- **Wan image-to-video is the cost driver.** At 929 s of T4 per 3.4 s clip, animating all 11 shots would take about 2.8 GPU-hours. That's about $1 at list price, but it would use up most of Kaggle's weekly free quota and add hours of queueing. It's the main reason the film uses Ken Burns moves and Wan stays an experiment (E4/E5).
- **The TTS free tier, not the cost, is the real limit.** About 10 requests per day per model meant that one storyboard rewrite could use a whole day's quota. A paid key would cost a few cents per full regeneration.

Sources: [Cloudflare Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/), [Google Cloud Text-to-Speech pricing (Gemini-TTS)](https://cloud.google.com/text-to-speech/pricing).
