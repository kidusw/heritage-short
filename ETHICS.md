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
| Narration | Gemini TTS | Gemini API terms | _to confirm_ |
| Keyframes | FLUX.1 [schnell] via Cloudflare | Apache-2.0 | _to confirm_ |
| Moving shots | Wan 2.2 | Apache-2.0 | _to confirm_ |
| Music | ACE-Step 1.5 | _to confirm_ | _to confirm_ |
| Edit | ffmpeg | LGPL/GPL | — |

## Labelling
Visible end card ("Made with AI…", from `storyboard.end_card`), plus a disclosure in the public post and video description.
