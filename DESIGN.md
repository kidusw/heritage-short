# Design

## The story
My first visit to Dire Dawa, where my mother's side of the family comes from: my whole family (my father, mother, sister, brother and me) drove 525 km
from Addis Ababa in an early-1990s Hyundai Elantra to the yearly Saint Gabriel celebration at Kulubi,
near Dire Dawa. On the way we passed Awash (camels and monkeys) and the volcanic rocky mountains near
Asbe Teferi. As the road dropped into the lowlands the old car kept overheating, and we had to stop every
few kilometres while my father poured water on the engine and radiator. That roadside moment is what I
remember most.

## Audience
Anyone who wants to hear the story of my first visit to Dire Dawa: family, friends, and Ethiopians at
home and abroad who know the road east.

## Intent
By the end they should feel the length and heat of the journey, the warmth of a family pushing an old
car through it together, and why we made the trip: to stand before Saint Gabriel at Kulubi.

## Language
Narrated in **Amharic** (the language the story happened in), with **English subtitles** so anyone can
follow. Language is data, not code: `storyboard.languages` is `["am", "en"]`, the first is the default,
and every stage takes `--lang`, so the same pipeline also produces an English-narrated cut.

## Structure (11 shots, ~78 s + 4 s end card)
1. Departure (hook: my first trip to Dire Dawa, my mother's family's home). 2. The five of us in the old car, heading for Saint Gabriel's feast at Kulubi. 3-5. The road changes
the world: camels at Awash, monkeys, Asbe Teferi's volcanic rock. 6-7. Heat rises, the car gives out.
**8. My father pouring water on the engine: the heart of the film.** 9. What it meant: all of us
together by the road. 10. Arrival in Dire Dawa. 11. Kulubi: why we went.
Each shot's reason is in its `purpose` field in `storyboard.json`.

## Motion decision
Every shot uses a Ken Burns move chosen from its `motion_prompt` (`video: "kenburns"` in the storyboard). Wan 2.2 cost ~20 GPU-minutes per shot on a free T4 and its one test clip had visible artifacts (EXPERIMENTS.md E4), so it stays a measured experiment (E5) rather than a dependency of the film.

## User test 1: radio cut (narration only)
- Date:
- Who (3+ from the audience):
- What they said:
- What changed in the storyboard because of it:

## User test 2: near-final cut
- Date:
- Who:
- What they said:
- What changed:

## Changes from my own review (25 Nov)
- **Opening reframed:** v2 opened on "every year, many people travel to Kulubi", which made it a film about the pilgrimage in general. v4 opens with "this is the story of my first trip to Dire Dawa, where my mother's family comes from", so it is personal from the first line. The Kulubi feast moves to shot 2 as the reason for the trip, and the arrival shot names Dire Dawa as my mother's hometown, which ties the start and the end together.
- **Side effect:** s01's old line had a word ("ብዙዎች") that the TTS seemed to mispronounce (EXPERIMENTS.md E3). The rewrite removes it.

## Changes from my own review (26 Nov)
- **Score:** ACE-Step candidate **b** (seed 43), chosen by me after listening to all three. a and c stay in `outputs/music/manifest.json` for reference.
- **Car colour (storyboard v5):** our car was blue-green, not white. The `car` character is now "a blue-green (teal) early-1990s Hyundai Elantra", and s05's prompt says "small blue-green car". The car keyframes (s03, s05, s06, s10) were regenerated; s06 and s10 took new seeds (306, 410) after review.
- **Family shots (storyboard v6):** consent recorded in ETHICS.md, so all 11 shots are now real stills with Ken Burns moves (no placeholders). The car is described by shape and colour only, to stop the model painting fake badges and plates. The father's description says "Habesha ... with brown skin", because the model kept drawing a light-skinned man from "Ethiopian father". s09 asks for "the five of them, all adults".
- **Mix:** the score now sits 3 dB lower and ducks harder under the voice (F21), so every line is at least 6 dB above the music.
- **Looks (storyboard v7, my feedback on 26 Nov):** the v6 stills made us look Indian, and some of us far too dark, and no one looked the same from shot to shot. We are Habesha, from Addis Ababa, with light-brown skin. Each person now has one fixed description, outfit and hairstyle, repeated word for word in every shot (EXPERIMENTS.md E8).
