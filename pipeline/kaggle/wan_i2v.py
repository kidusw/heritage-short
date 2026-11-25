"""Runs ON KAGGLE (GPU T4), pushed by pipeline/wan_kaggle.py. Do not run locally.

Reads jobs.json from the attached keyframes dataset, makes one Wan 2.2 image-to-video clip per job,
and writes /kaggle/working/<out_name>.mp4 plus results.json (per-shot GPU seconds, errors).
One failed shot never stops the others: the local pipeline falls back to Ken Burns for it.
"""
import gc
import glob
import json
import os
import subprocess
import sys
import time
import traceback

os.environ.setdefault("HF_HOME", "/tmp/hf")  # /kaggle/working is only ~20 GB; the weights are ~23 GB
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
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
try:
    pipe.vae.enable_tiling()  # fp32 VAE decode of 81 frames is the other big allocation
except Exception as e:  # noqa: BLE001
    log(f"vae tiling unavailable: {e}")
results["setup_s"] = round(time.time() - t0, 1)
log(f"model loaded in {results['setup_s']}s")
save(results)

# Encode every prompt first, then drop the text encoder for good. Model offload keeps each component's
# weights in host RAM; the ~11 GB fp16 UMT5 plus the 10 GB transformer filled the ~30 GB Kaggle VM and the
# kernel was OOM-killed during VAE decode after denoising finished (FAILURES.md F14). Moving it to the CPU
# (F13) fixed GPU memory but not host memory.
embeds = {}
for job in spec["jobs"]:
    try:
        with torch.no_grad():
            embeds[job["shot"]] = pipe.encode_prompt(
                prompt=job["prompt"], negative_prompt=cfg.get("negative", ""),
                do_classifier_free_guidance=cfg["guidance"] > 1.0, num_videos_per_prompt=1,
                device=pipe._execution_device,
            )
    except Exception as e:  # noqa: BLE001
        results["jobs"][job["shot"]] = {"ok": False, "error": f"prompt encode: {type(e).__name__}: {str(e)[:300]}", "gpu_s": 0}
        traceback.print_exc()
pipe.text_encoder.to("cpu")
pipe.text_encoder = None
pipe.maybe_free_model_hooks()  # rebuilds the offload chain without the text encoder, dropping the hooks' references
gc.collect()
torch.cuda.empty_cache()
log(f"prompts encoded; text encoder released; GPU allocated {torch.cuda.memory_allocated() / 2**30:.1f} GiB")
save(results)

for job in spec["jobs"]:
    sid = job["shot"]
    if sid not in embeds:
        continue
    t0 = time.time()
    try:
        image = load_image(os.path.join(data_dir, job["image"])).resize((cfg["width"], cfg["height"]))
        pe, npe = embeds[sid]
        frames = pipe(
            image=image, prompt_embeds=pe, negative_prompt_embeds=npe,
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
