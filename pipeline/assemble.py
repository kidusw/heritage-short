"""Stage: assemble. Picture + narration + ducked score + English subtitles + AI end card -> final films.

    python -m pipeline.assemble                 # every language, both aspect ratios
    python -m pipeline.assemble --lang am --aspect 9x16

Reads (never guesses file names):
  outputs/shots/manifest.json        one 1080x1080 clip per shot
  outputs/radio/timeline_<lang>.json slot lengths per shot (a slot may be longer than planned if narration ran long)
  outputs/radio/radio_<lang>.mp3     narration on that timeline
  outputs/radio/subtitles_<lang>_en.srt
  outputs/music/manifest.json        chosen score (optional: the film is made without music if it's missing)
Writes outputs/final/<slug>_<lang>_<aspect>.mp4 (+ .srt beside it) and manifest.json.

Audio: the score is ducked under the voice with a sidechain compressor keyed on the narration, faded out at
the end, and the mix is loudness-normalised to -14 LUFS (typical for social platforms).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .common import (
    OUTPUTS, ROOT, from_manifest, load_env, load_storyboard, log_call, media_duration, read_manifest, rel,
    run_ffmpeg, stage_dir, write_manifest,
)

STAGE = "final"
FPS = 24
ASPECTS = {"16x9": (1920, 1080), "9x16": (1080, 1920)}
FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]


def font_file() -> str | None:
    if os.environ.get("HS_FONT"):
        return os.environ["HS_FONT"]
    return next((f for f in FONT_CANDIDATES if Path(f).exists()), None)


def ff_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\u2019").replace("%", "\\%")


LOUDNORM = "I=-14:TP=-1.5:LRA=11"


def loudnorm_filter(inputs: list[str], af: str, total: float) -> str:
    """Two-pass loudnorm. Single-pass (dynamic) mode undershot the -14 LUFS target by ~1.3 LU on speech with
    pauses (FAILURES.md F18), so measure the mix first and apply the measured values in linear mode."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-y", *[a for i, a in enumerate(inputs) if i >= 2],
           "-filter_complex", af.replace("[1:a]", "[0:a]").replace("[2:a]", "[1:a]") + f",loudnorm={LOUDNORM}:print_format=json[a]",
           "-map", "[a]", "-t", f"{total:.3f}", "-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    blob = res.stderr[res.stderr.rfind("{"):res.stderr.rfind("}") + 1]
    try:
        m = json.loads(blob)
    except ValueError:
        print("  ! loudnorm measurement failed; falling back to single-pass")
        return f"loudnorm={LOUDNORM}[a]"
    return (f"loudnorm={LOUDNORM}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true[a]")


def picture_track(sb: dict, timeline: dict, shots: dict, tmp: Path) -> Path:
    """Concatenate shot clips, each padded (last frame held) to its slot on the narration timeline,
    then the end card. Output: square master."""
    parts = []
    slots = {s["shot"]: s["duration_s"] for s in timeline["shots"]}
    for i, shot in enumerate(sb["shots"]):
        sid = shot["id"]
        if sid not in shots:
            raise SystemExit(f"No clip for {sid}. Run: python -m pipeline.shots")
        src, slot = from_manifest(shots[sid]["file"]), slots[sid]
        seg = tmp / f"{i:02}_{sid}.mp4"
        hold = max(0.0, slot - media_duration(src))
        run_ffmpeg(["-i", str(src), "-vf", f"fps={FPS},tpad=stop_mode=clone:stop_duration={hold:.3f},format=yuv420p",
                    "-t", f"{slot:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(seg)])
        parts.append(seg)

    card = sb.get("end_card")
    if card:
        # Blank card here; its text is drawn per aspect ratio in export(), so it is never cropped off.
        seg = tmp / "99_endcard.mp4"
        run_ffmpeg(["-f", "lavfi", "-i", f"color=c=0x14110e:s=1080x1080:r={FPS}:d={card['duration_s']}",
                    "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(seg)])
        parts.append(seg)

    lst = tmp / "concat.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    master = tmp / "picture_master.mp4"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(master)])
    return master


def music_file() -> Path | None:
    p = OUTPUTS / "music" / "manifest.json"
    if not p.exists():
        return None
    m = json.loads(p.read_text(encoding="utf-8"))
    chosen = m.get("chosen")
    return from_manifest(m["candidates"][chosen]["file"]) if chosen else None


def export(sb: dict, lang: str, aspect: str, master: Path, total: float, tmp: Path) -> Path:
    w, h = ASPECTS[aspect]
    radio = OUTPUTS / "radio" / f"radio_{lang}.mp3"
    srt_src = OUTPUTS / "radio" / f"subtitles_{lang}_en.srt"
    slug = re.sub(r"[^a-z0-9]+", "-", sb["title"].lower()).strip("-")
    out = stage_dir(STAGE) / f"{slug}_{lang}_{aspect}.mp4"

    # Crop the square master to the target shape (centre), then scale up.
    crop = f"crop=iw:iw*{h}/{w}" if w > h else f"crop=ih*{w}/{h}:ih"
    # Subtitles: copy the .srt next to the work dir and reference it relatively (Windows drive letters
    # break ffmpeg's filter syntax).
    shutil.copy(srt_src, tmp / "subs.srt")
    font_size = 16 if w > h else 11  # libass scales from a 384x288 reference
    margin = 28 if w > h else 70
    subs = (f"subtitles=subs.srt:force_style='FontName=Arial,FontSize={font_size},PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H80000000,BorderStyle=1,Outline=1.2,Shadow=0,MarginV={margin}'")
    card = sb.get("end_card")
    draws = ""
    if card:
        font = font_file()
        lines = card["text"].split("\n")
        start = total - card["duration_s"]
        base = int(w * (0.032 if w > h else 0.044))  # headline size relative to frame width
        for j, line in enumerate(lines):
            size = base if j == 0 else int(base * 0.58)
            y = f"(h/2)-{(len(lines) - 1) * base * 0.7:.0f}+{j * base * 1.4:.0f}"
            fopt = f"fontfile='{ff_escape(font)}':" if font else ""  # quoted: Windows paths have a drive colon
            draws += (f",drawtext={fopt}text='{ff_escape(line)}':"
                      f"fontcolor=white:fontsize={size}:x=(w-text_w)/2:y={y}:"
                      f"alpha='if(lt(t,{start:.3f}),0,min(1,(t-{start:.3f})/0.6))'")
    vf = f"[0:v]{crop},scale={w}:{h}:flags=lanczos,{subs}{draws},format=yuv420p[v]"

    music = music_file()
    duck_db = sb["music"].get("duck_db", -14)
    if music:
        # Score sits at -20 dB under nothing and is pushed down a further ~|duck_db| when the voice speaks.
        ratio = max(2, round(10 ** (abs(duck_db) / 20)))
        af = (f"[1:a]aresample=48000,asplit=2[voice][key];"
              f"[2:a]aresample=48000,aloop=loop=-1:size=2e9,atrim=0:{total:.3f},volume=-6dB,"
              f"afade=t=in:st=0:d=1.5,afade=t=out:st={max(0, total - 3):.3f}:d=3[mus];"
              f"[mus][key]sidechaincompress=threshold=0.03:ratio={ratio}:attack=30:release=600[ducked];"
              f"[voice][ducked]amix=inputs=2:duration=first:normalize=0")
        inputs = ["-i", str(master), "-i", str(radio), "-i", str(music)]
    else:
        af = "[1:a]aresample=48000"
        inputs = ["-i", str(master), "-i", str(radio)]

    af += "," + loudnorm_filter(inputs, af, total)

    # The audio mix is rendered on its own first. Run in the same filtergraph as the video chain,
    # loudnorm dropped ~3 s blocks of audio at four points, so voice and score ran up to 12 s ahead
    # of the picture (FAILURES.md F20). Audio-only, the same graph keeps every sample.
    mix = tmp / f"mix_{aspect}.wav"
    audio_af = af.replace("[1:a]", "[0:a]").replace("[2:a]", "[1:a]").removesuffix("[a]") + ",aresample=48000[a]"
    run_ffmpeg([*inputs[2:], "-filter_complex", audio_af, "-map", "[a]", "-t", f"{total:.3f}",
                "-c:a", "pcm_s24le", str(mix)])

    cwd = os.getcwd()
    os.chdir(tmp)
    try:
        run_ffmpeg(["-i", str(master), "-i", str(mix), "-filter_complex", vf, "-map", "[v]", "-map", "1:a",
                    "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    finally:
        os.chdir(cwd)
    shutil.copy(srt_src, out.with_suffix(".srt"))
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", action="append")
    ap.add_argument("--aspect", action="append", choices=list(ASPECTS))
    args = ap.parse_args(argv)
    load_env()
    sb = load_storyboard()
    shots = read_manifest("shots")
    final_dir = stage_dir(STAGE)
    mpath = final_dir / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
    if not music_file():
        print("  ! no chosen music in outputs/music/manifest.json: exporting without a score")

    for lang in args.lang or sb["languages"]:
        tl_path = OUTPUTS / "radio" / f"timeline_{lang}.json"
        if not tl_path.exists():
            raise SystemExit(f"No timeline for '{lang}'. Run: python -m pipeline.radio_cut --lang {lang}")
        timeline = json.loads(tl_path.read_text(encoding="utf-8"))
        tmp = final_dir / f"_tmp_{lang}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        t0 = time.perf_counter()
        master = picture_track(sb, timeline, shots, tmp)
        for aspect in args.aspect or list(ASPECTS):
            t1 = time.perf_counter()
            out = export(sb, lang, aspect, master, timeline["total_s"], tmp)
            dur = media_duration(out)
            methods = {}
            for v in shots.values():
                methods[v["method"]] = methods.get(v["method"], 0) + 1
            manifest[f"{lang}_{aspect}"] = {"file": rel(out), "duration_s": round(dur, 2), "shot_methods": methods,
                                            "music": rel(music_file()) if music_file() else None}
            write_manifest(STAGE, manifest)
            log_call(stage=STAGE, provider="local", model="ffmpeg", params={"lang": lang, "aspect": aspect},
                     latency_s=time.perf_counter() - t1, output=out)
            print(f"final [{lang} {aspect}]: {rel(out)}  {dur:.1f}s  shots {methods}")
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"  ({time.perf_counter() - t0:.0f}s for {lang})")


if __name__ == "__main__":
    main()
