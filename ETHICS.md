# Ethics

## Consent
The film depicts my real family (father, mother, sister, brother) and me, as AI-generated likenesses
built from text descriptions only (no photos of them are given to any model). The narration is a
synthetic voice telling my story in first person; no family member is voiced.

**Enforced in code:** every real person in `storyboard.json` has `real_person: true` and a `consent_ref`.
`pipeline/keyframes.py` (and later `shots.py`) refuses to generate any shot showing a person whose row
below doesn't say `granted`. `python -m pipeline.validate` lists what is still pending.

| consent_ref | Person | Depicted / voiced | Status | Date, how given |
|---|---|---|---|---|
| `family-narrator` | Me (Kidus) | depicted (AI likeness), story told in first person | granted | 2026-11-26, written consent |
| `family-father` | My father | depicted (AI likeness), named as "my father" | granted | 2026-11-26, written consent |
| `family-mother` | My mother | depicted (AI likeness) | granted | 2026-11-26, written consent |
| `family-sister` | My sister | depicted (AI likeness) | granted | 2026-11-26, written consent |
| `family-brother` | My brother | depicted (AI likeness) | granted | 2026-11-26, written consent |

To record consent, change `pending` to `granted` and fill in the date and how it was given
(for example "in person, 25 Nov 2026, after seeing the storyboard").

## Religious content
The final shot shows the Kulubi Saint Gabriel pilgrimage. It is shown from behind my family, as part of
the crowd, without depicting the saint, icons or clergy in close-up, and the narration stays descriptive
and respectful.

## Licences
| Component | Model / tool | Licence / terms | Output use |
|---|---|---|---|
| Narration | Gemini TTS (free tier) | [Gemini API Additional Terms](https://aistudio.google.com/docs/terms) | Google claims no ownership of generated content; I'm responsible for how it's used. On the free ("unpaid") tier Google may use what's sent, and human reviewers may read API input and output, so only the narration script went to it, never a photo. |
| Keyframes | FLUX.1 [schnell] via Cloudflare Workers AI | Apache-2.0 ([model card](https://huggingface.co/black-forest-labs/FLUX.1-schnell)) | Card allows personal, scientific and commercial use; its out-of-scope list (e.g. non-consensual imagery) doesn't apply here. |
| Keyframes (family shots, not used yet) | Gemini image models | [Gemini API Additional Terms](https://aistudio.google.com/docs/terms) | Same terms as narration; needs a paid key (FAILURES.md F23), and paid-tier prompts aren't used to improve Google's products. |
| Moving shots | Wan 2.2 TI2V-5B (experiment E5 only) | Apache-2.0 ([model card](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers)) | Publisher claims no rights over generated content; use must not break laws or spread misinformation. |
| Music | ACE-Step 1.5 XL turbo | MIT weights, Apache-2.0 text encoder ([model card](https://huggingface.co/ACE-Step/acestep-v15-xl-turbo-diffusers)) | The card doesn't address output ownership; MIT puts no restriction on using what the model produces. |
| Edit | ffmpeg | LGPL/GPL | Tool only; nothing of it ships in the film. |

Checked against each page on 26 Nov 2026.

## Labelling
Visible end card ("Made with AI…", from `storyboard.end_card`), plus a disclosure in the public post and video description.
