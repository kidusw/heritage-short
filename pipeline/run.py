"""One command for the whole film:

    python -m pipeline.run                    # every stage, every language
    python -m pipeline.run --lang am          # Amharic only
    python -m pipeline.run --offline          # placeholders instead of API calls (tests the plumbing for free)
    python -m pipeline.run --from radio_cut   # start from a later stage
    python -m pipeline.run --shots s03        # regenerate one shot through every stage

Every stage is cached by a hash of its inputs, so re-running only regenerates what changed.
"""
from __future__ import annotations

import argparse
import importlib
import os
import time

from .common import RUN_ID

# (stage module, accepts --lang, accepts --shots, accepts --offline)
STAGES = [
    ("validate", False, False, False),
    ("narration", True, True, True),
    ("radio_cut", True, False, False),
    ("keyframes", False, True, True),
    ("shots", False, True, True),
    ("music", False, False, True),
    ("assemble", True, False, False),
]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", action="append")
    ap.add_argument("--shots", nargs="*")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--from", dest="start", choices=[s[0] for s in STAGES])
    ap.add_argument("--only", choices=[s[0] for s in STAGES])
    args = ap.parse_args(argv)
    os.environ["HS_RUN_ID"] = RUN_ID

    names = [s[0] for s in STAGES]
    todo = STAGES[names.index(args.start):] if args.start else STAGES
    if args.only:
        todo = [s for s in STAGES if s[0] == args.only]

    print(f"run {RUN_ID}")
    for name, has_lang, has_shots, has_offline in todo:
        stage_args = []
        if has_lang and args.lang:
            for l in args.lang:
                stage_args += ["--lang", l]
        if has_shots and args.shots:
            stage_args += ["--shots", *args.shots]
        if has_offline and args.offline:
            stage_args.append("--offline")
        print(f"\n== {name} {' '.join(stage_args)}")
        t0 = time.perf_counter()
        importlib.import_module(f"pipeline.{name}").main(stage_args)
        print(f"== {name} done in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
