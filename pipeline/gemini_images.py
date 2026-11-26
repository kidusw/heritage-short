"""Gemini image generation for keyframes that show real people (storyboard shot field `image_provider: "gemini"`).

FLUX schnell on Cloudflare takes text only, so faces, skin tone and clothes drifted from shot to shot
(EXPERIMENTS.md E7, E8). Gemini image models accept reference images, so:
  1. one reference portrait per person, from their storyboard description: outputs/keyframes/refs/<id>_<hash>.png
  2. each shot is generated from the portraits of the people in it + the shot prompt.
Portraits are cached by description; change a description and that person's portrait (and their shots) regenerate.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .common import OUTPUTS, cache_key, log_call, rel, with_retries
from .narration import gemini_client, is_daily_quota

STAGE = "keyframes"
REFS = OUTPUTS / STAGE / "refs"
REFS_MANIFEST = REFS / "manifest.json"


def rank_image(n: str):
    """Flash before pro (free-tier quota), non-lite before lite, stable before preview, newest first."""
    v = re.search(r"(\d+(?:\.\d+)?)", n)
    return ("pro" in n, "lite" in n, "preview" in n, -float(v.group(1)) if v else 0, n)


def resolve_image_models(client) -> list[str]:
    listed = [m.name.removeprefix("models/") for m in client.models.list(config={"page_size": 200})]
    models = sorted((n for n in listed if n.startswith("gemini-") and "-image" in n), key=rank_image)
    if not models:
        raise SystemExit("No Gemini image models available on this key.")
    return models


class ImageChain:
    """Generates one image, failing over to the next model on a daily quota or an empty response."""

    def __init__(self):
        from google.genai import types
        self.types = types
        self.client = gemini_client()
        self.models = resolve_image_models(self.client)
        self.dead: dict[str, str] = {}
        print(f"keyframes: Gemini image models in failover order: {', '.join(self.models)}")

    def _call(self, model: str, contents: list) -> tuple[bytes, str]:
        t = self.types
        r = self.client.models.generate_content(
            model=model, contents=contents,
            config=t.GenerateContentConfig(response_modalities=["IMAGE"], image_config=t.ImageConfig(aspect_ratio="1:1")))
        for cand in r.candidates or []:
            for part in (cand.content.parts if cand.content else []) or []:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data, part.inline_data.mime_type or "image/png"
        reason = getattr((r.candidates or [None])[0], "finish_reason", None) if r.candidates else getattr(r, "prompt_feedback", None)
        raise RuntimeError(f"no image in response ({reason})")

    def generate(self, contents: list, *, shot: str, params: dict, out: Path) -> tuple[bytes, str]:
        for model in self.models:
            if model in self.dead:
                continue
            try:
                data, _ = with_retries(lambda att: self._call(model, contents), stage=STAGE, provider="gemini", model=model,
                                       shot=shot, params=params, output=out, max_attempts=2, give_up=is_daily_quota)
                return data, model
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                reason = ("not on the free tier (quota limit 0; needs billing on the key)" if "limit: 0" in msg else
                          "daily quota" if is_daily_quota(e) else f"{type(e).__name__}: {msg[:160]}")
                self.dead[model] = reason
                print(f"    ! {model} unavailable ({reason}); failing over", file=sys.stderr)
        raise SystemExit("All Gemini image models failed: " + "; ".join(f"{m} ({r})" for m, r in self.dead.items()))


def portrait_prompt(sb: dict, desc: str) -> str:
    return (f"{sb['style']['visual_prefix']} Reference portrait, head and shoulders, facing the camera, neutral expression, "
            f"plain softly lit background, the whole outfit's neckline visible: {desc}. Realistic photograph, no text.")


def ensure_refs(sb: dict, people: list[str], get_chain, *, force: bool = False) -> dict[str, Path]:
    """Reference portrait per real person in `people`, cached by description. Returns id -> file."""
    REFS.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(REFS_MANIFEST.read_text(encoding="utf-8")) if REFS_MANIFEST.exists() else {}
    chars = {c["id"]: c for c in sb["characters"]}
    out_files = {}
    for pid in people:
        prompt = portrait_prompt(sb, chars[pid]["description"])
        key = cache_key(STAGE, "gemini-ref", prompt)
        out = REFS / f"{pid}_{key}.png"
        params = {"prompt": prompt, "kind": "reference portrait"}
        if out.exists() and not force:
            log_call(stage=STAGE, provider="gemini", model=manifest.get(pid, {}).get("model", "?"), shot=f"ref_{pid}",
                     params=params, cache_hit=True, output=out)
            print(f"  = ref {pid} cached")
        else:
            data, model = get_chain().generate([prompt], shot=f"ref_{pid}", params=params, out=out)
            out.write_bytes(data)
            manifest[pid] = {"file": rel(out), "model": model, "prompt": prompt}
            print(f"  + ref {pid} ({model})")
        out_files[pid] = out
    REFS_MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_files


def shot_contents(prompt: str, people: list[str], refs: dict[str, Path]) -> tuple[list, str]:
    """Reference images first, each introduced by who it is, then the scene prompt."""
    from google.genai import types
    contents: list = []
    for i, pid in enumerate(people, 1):
        contents.append(f"Reference image {i}: the {pid}.")
        contents.append(types.Part.from_bytes(data=refs[pid].read_bytes(), mime_type="image/png"))
    instruction = (f"Make one new square photograph of this scene. The people in it are exactly the people in the reference "
                   f"images ({', '.join(people)}): keep each person's face, light-brown skin tone, hair and clothes the same "
                   f"as in their reference. Habesha Ethiopian family. No text, letters, logos or number plates anywhere.\n\n"
                   f"Scene: {prompt}")
    contents.append(instruction)
    return contents, instruction
