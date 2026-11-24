"""Stage: moving shots. Planned (Wednesday): Wan 2.2 image-to-video at 480p on a Kaggle GPU, batched and hash-cached,
with a Ken Burns (ffmpeg zoompan) fallback for any shot that fails or is marked video=kenburns.
"""
import sys

STAGE = "shots"


def main(argv=None) -> None:  # noqa: ARG001
    print(f"{STAGE}: not built yet, skipping", file=sys.stderr)


if __name__ == "__main__":
    main()
