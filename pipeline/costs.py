"""Summarise runs.jsonl: calls, cache hits, failures, latency, GPU seconds and cost per stage/model.
Paste the output into COSTS.md.

    python -m pipeline.costs
"""
import json
from collections import defaultdict

from .common import RUNS_LOG


def main(argv=None) -> None:  # noqa: ARG001
    if not RUNS_LOG.exists():
        raise SystemExit("runs.jsonl is empty; run a stage first.")
    agg = defaultdict(lambda: {"calls": 0, "hits": 0, "fails": 0, "latency": [], "gpu_s": 0.0, "cost": 0.0})
    for line in RUNS_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        a = agg[(r["stage"], r["provider"], r["model"])]
        if r.get("cache_hit"):
            a["hits"] += 1
            continue
        a["calls"] += 1
        if r["status"] != "ok":
            a["fails"] += 1
        else:
            a["latency"].append(r["latency_s"])
        a["gpu_s"] += r.get("gpu_s", 0) or 0
        a["cost"] += r.get("cost_usd", 0) or 0
    print("| stage | provider | model | calls | failed | cache hits | median latency (s) | GPU min | cost (USD) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for (stage, prov, model), a in sorted(agg.items()):
        lat = sorted(a["latency"])
        med = lat[len(lat) // 2] if lat else 0
        print(f"| {stage} | {prov} | {model} | {a['calls']} | {a['fails']} | {a['hits']} | {med:.2f} | {a['gpu_s']/60:.1f} | {a['cost']:.4f} |")


if __name__ == "__main__":
    main()
