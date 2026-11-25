"""Runs ON KAGGLE (GPU T4), pushed by pipeline/wan_kaggle.py. Do not run locally.

Reads jobs.json from the attached keyframes dataset, makes one Wan 2.2 image-to-video clip per job,
and writes /kaggle/working/<out_name>.mp4 plus results.json (per-shot GPU seconds, errors).
One failed shot never stops the others: the local pipeline falls back to Ken Burns for it.
"""
import glob
import json
import os
import subprocess
import sys
import time
import traceback

os.environ.setdefault("HF_HOME", "/tmp/hf")  # /kaggle/working is only ~20 GB; the weights are ~23 GB
WORK = "/kaggle/working"
RESULTS = os.path.join(WORK, "results.json")
t_start = time.time()


def log(msg):
    print(f"[{time.time() - t_start:7.1f}s] {msg}", flush=True)


def save(results):
    with open(RESULTS, "w") as f:
        json.dump(results, f, indent=2)


jobs_path = (glob.glob("/kaggle/input/**/jobs.json", recursive=True) or [None])[0]
if not jobs_path:
    raise SystemExit("jobs.json not found under /kaggle/input: is the keyframes dataset attached?")
spec = json.load(open(jobs_path))
data_dir = os.path.dirname(jobs_path)
cfg = spec["config"]
results = {"config": cfg, "jobs": {}, "setup_s": None, "gpu": None}
save(results)

log("installing diffusers")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers>=0.35", "transformers", "accelerate",
                "ftfy", "imageio", "imageio-ffmpeg"], check=True)

import torch  # noqa: E402
from diffusers import AutoencoderKLWan, WanImageToVideoPipeline  # noqa: E402
from diffusers.utils import export_to_video, load_image  # noqa: E402

results["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none"
log(f"GPU: {results['gpu']}, count {torch.cuda.device_count()}")
# T4 has no fast bfloat16, so the transformer runs in float16; the VAE stays float32 (Wan's VAE is unstable in fp16).
dtype = torch.float16 if cfg.get("dtype", "float16") == "float16" else torch.bfloat16

t0 = time.time()
vae = AutoencoderKLWan.from_pretrained(cfg["model"], subfolder="vae", torch_dtype=torch.float32)
pipe = WanImageToVideoPipeline.from_pretrained(cfg["model"], vae=vae, torch_dtype=dtype)
pipe.enable_model_cpu_offload()  # 5B transformer + UMT5-XXL don't fit together in 15 GB
results["setup_s"] = round(time.time() - t0, 1)
log(f"model loaded in {results['setup_s']}s")
save(results)

for job in spec["jobs"]:
    sid = job["shot"]
    t0 = time.time()
    try:
        image = load_image(os.path.join(data_dir, job["image"])).resize((cfg["width"], cfg["height"]))
        frames = pipe(
            image=image, prompt=job["prompt"], negative_prompt=cfg.get("negative", ""),
            height=cfg["height"], width=cfg["width"], num_frames=cfg["num_frames"],
            num_inference_steps=cfg["steps"], guidance_scale=cfg["guidance"],
            generator=torch.Generator("cpu").manual_seed(job["seed"]),
        ).frames[0]
        out = os.path.join(WORK, job["out_name"] + ".mp4")
        export_to_video(frames, out, fps=cfg["fps"])
        results["jobs"][sid] = {"ok": True, "file": job["out_name"] + ".mp4", "gpu_s": round(time.time() - t0, 1)}
        log(f"{sid}: ok in {time.time() - t0:.0f}s")
    except Exception as e:  # noqa: BLE001
        results["jobs"][sid] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "gpu_s": round(time.time() - t0, 1)}
        log(f"{sid}: FAILED {e}")
        traceback.print_exc()
        if "out of memory" in str(e).lower():
            torch.cuda.empty_cache()
    save(results)

results["total_s"] = round(time.time() - t_start, 1)
save(results)
log("done")
