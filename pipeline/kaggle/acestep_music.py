"""Runs ON KAGGLE (GPU), pushed by pipeline/music.py. Do not run locally.
SPEC (prepended by music.py) holds the prompt, duration and one seed per candidate.
Writes /kaggle/working/<name>.wav for each candidate and results.json (GPU seconds, errors)."""
import json
import os
import subprocess
import sys
import time
import traceback

os.environ.setdefault("HF_HOME", "/tmp/hf")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
WORK = "/kaggle/working"
t_start = time.time()
results = {"spec": SPEC, "candidates": {}}  # noqa: F821 - SPEC is prepended


def save():
    json.dump(results, open(os.path.join(WORK, "results.json"), "w"), indent=2)


def log(m):
    print(f"[{time.time() - t_start:7.1f}s] {m}", flush=True)


save()
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers>=0.39", "transformers", "accelerate",
                "soundfile"], check=True)
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
from diffusers import AceStepPipeline  # noqa: E402

cfg = SPEC["config"]  # noqa: F821
results["gpu"] = torch.cuda.get_device_name(0)
dtype = {"float16": torch.float16, "bfloat16": torch.bfloat16, "float32": torch.float32}[cfg["dtype"]]
t0 = time.time()
pipe = AceStepPipeline.from_pretrained(cfg["model"], torch_dtype=dtype)
# With everything resident on a T4, the Oobleck VAE decode of ~90 s of audio OOMed (FAILURES.md F15).
# Model offload moves the transformer and text encoder off the GPU before the VAE runs.
try:
    pipe.enable_model_cpu_offload()
    results["offload"] = "model"
except Exception as e:  # noqa: BLE001 - pipeline without an offload sequence
    log(f"model offload unavailable ({e}); keeping everything on the GPU")
    pipe.to("cuda")
    results["offload"] = None
results["setup_s"] = round(time.time() - t0, 1)
log(f"loaded {cfg['model']} on {results['gpu']} in {results['setup_s']}s")
save()

for cand in SPEC["candidates"]:  # noqa: F821
    t0 = time.time()
    try:
        out = pipe(prompt=SPEC["prompt"], lyrics=SPEC["lyrics"], audio_duration=SPEC["duration_s"],  # noqa: F821
                   bpm=SPEC.get("bpm"), num_inference_steps=cfg["steps"], guidance_scale=cfg["guidance"],  # noqa: F821
                   generator=torch.Generator(device="cuda").manual_seed(cand["seed"]))
        audio = out.audios[0]
        arr = audio.float().cpu().numpy()
        if arr.ndim == 2 and arr.shape[0] <= 2:  # [channels, samples] -> [samples, channels]
            arr = arr.T
        import numpy as np
        if not np.isfinite(arr).all() or np.abs(arr).max() < 1e-4:  # silent or NaN (fp16 overflow)
            raise RuntimeError("generated audio is silent or NaN")
        sf.write(os.path.join(WORK, cand["name"] + ".wav"), arr, pipe.sample_rate)
        results["candidates"][cand["name"]] = {"ok": True, "file": cand["name"] + ".wav", "gpu_s": round(time.time() - t0, 1)}
        log(f"{cand['name']}: ok")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        torch.cuda.empty_cache()
        results["candidates"][cand["name"]] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}",
                                               "gpu_s": round(time.time() - t0, 1)}
    save()
results["total_s"] = round(time.time() - t_start, 1)
save()
