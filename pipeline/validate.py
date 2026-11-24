"""Validate storyboard.json against schema/ and print a timing summary.

    python -m pipeline.validate
"""
from .common import StoryboardError, load_storyboard, total_duration


def main(argv=None) -> None:
    try:
        sb = load_storyboard()
    except StoryboardError as e:
        raise SystemExit(str(e))
    t = total_duration(sb)
    print(f"storyboard OK: '{sb['title']}' v{sb['version']}, {len(sb['shots'])} shots, "
          f"{t:.0f}s planned ({'within' if 60 <= t <= 90 else 'OUTSIDE'} 60-90s), languages {sb['languages']}")
    for s in sb["shots"]:
        words = {l: len(s["narration"].get(l, "").split()) for l in sb["languages"]}
        print(f"  {s['id']:<16} {s['duration_s']:>4}s  words {words}  {s['purpose']}")


if __name__ == "__main__":
    main()
