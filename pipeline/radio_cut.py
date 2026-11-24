"""Stage: radio cut. The narration-only prototype, laid out on the real shot timeline,
so you can play it to your audience before a single image is generated.

    python -m pipeline.radio_cut               # every language
    python -m pipeline.radio_cut --lang am

Each shot becomes a slot of duration_s seconds; narration starts LEAD_IN seconds into the slot.
If narration is longer than its slot, the slot grows and a warning tells you to fix the storyboard.

Output: outputs/radio/radio_<lang>.mp3, outputs/radio/timeline_<lang>.json,
        outputs/radio/subtitles_<lang>_en.srt (English subtitles on that language's timeline)
"""
from __future__ import annotations

import argparse
import json

from .common import OUTPUTS, ROOT, load_storyboard, log_call, read_manifest, run_ffmpeg, stage_dir

STAGE = "radio"
LEAD_IN = 0.4
TAIL = 0.4


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def build(sb: dict, lang: str) -> None:
    narr = read_manifest("narration").get(lang)
    if not narr:
        raise SystemExit(f"No narration for '{lang}'. Run: python -m pipeline.narration --lang {lang}")
    missing = [s["id"] for s in sb["shots"] if s["narration"].get(lang, "").strip() and not narr.get(s["id"])]
    if missing:
        raise SystemExit(f"[{lang}] narration missing for {', '.join(missing)}. Run: python -m pipeline.narration --lang {lang}")
    out_dir = stage_dir(STAGE)
    tmp = out_dir / "_tmp"
    tmp.mkdir(exist_ok=True)

    timeline, segs, t = [], [], 0.0
    srt_lines = []
    for i, shot in enumerate(sb["shots"]):
        sid = shot["id"]
        entry = narr.get(sid)
        n_dur = entry["duration_s"] if entry else 0.0
        slot = max(shot["duration_s"], LEAD_IN + n_dur + TAIL)
        if slot > shot["duration_s"]:
            print(f"  ! {sid} [{lang}] slot stretched {shot['duration_s']}s -> {slot:.1f}s to fit narration")

        seg = tmp / f"{i:02}_{sid}_{lang}.wav"
        if entry:
            run_ffmpeg(["-i", str(ROOT / entry["file"]), "-af",
                        f"adelay={int(LEAD_IN*1000)},apad,atrim=0:{slot:.3f},aresample=48000", "-ac", "2", str(seg)])
        else:
            run_ffmpeg(["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo", "-t", f"{slot:.3f}", str(seg)])
        segs.append(seg)

        sub = shot.get("subtitle_en") or shot["narration"].get("en", "")
        if sub and entry:
            srt_lines.append(f"{len(srt_lines)+1}\n{srt_time(t + LEAD_IN)} --> {srt_time(t + LEAD_IN + n_dur)}\n{sub}\n")
        timeline.append({"shot": sid, "start_s": round(t, 3), "duration_s": round(slot, 3),
                         "narration_s": n_dur, "stretched": slot > shot["duration_s"]})
        t += slot

    end = sb.get("end_card", {}).get("duration_s", 0)
    if end:
        seg = tmp / f"99_endcard_{lang}.wav"
        run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(end), str(seg)])
        segs.append(seg)
        timeline.append({"shot": "end_card", "start_s": round(t, 3), "duration_s": end})
        t += end

    concat = tmp / f"concat_{lang}.txt"
    concat.write_text("".join(f"file '{s.as_posix()}'\n" for s in segs), encoding="utf-8")
    mp3 = out_dir / f"radio_{lang}.mp3"
    # loudnorm to -16 LUFS (typical for social/mobile playback)
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:a", "libmp3lame", "-b:a", "160k", str(mp3)])

    (out_dir / f"timeline_{lang}.json").write_text(json.dumps({"lang": lang, "total_s": round(t, 2), "shots": timeline}, indent=2), encoding="utf-8")
    (out_dir / f"subtitles_{lang}_en.srt").write_text("\n".join(srt_lines), encoding="utf-8")
    log_call(stage=STAGE, provider="local", model="ffmpeg", params={"lang": lang, "shots": len(sb["shots"])},
             output=mp3)
    verdict = "OK" if 60 <= t <= 90 else "OUTSIDE 60-90s TARGET"
    print(f"radio cut [{lang}]: {mp3.relative_to(ROOT)}  {t:.1f}s  ({verdict})")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", action="append")
    args = ap.parse_args(argv)
    sb = load_storyboard()
    for lang in args.lang or sb["languages"]:
        build(sb, lang)


if __name__ == "__main__":
    main()
