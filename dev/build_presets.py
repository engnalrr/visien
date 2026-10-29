"""Writes the built-in presets (presets/*.json) from the definitions below.

    python dev/build_presets.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from visien import stages, ve  # noqa: E402

# The neural-rendering settings from the Visual Enhancer screenshot this preset family is built on.
NEURAL = {"nr_style": "Style 0", "nr_intensity": 1.2, "nr_passes": 1, "local_tone_strength": 1.0,
          "local_structure_strength": 0.85, "skin_structure_strength": 1.0, "automatic_mask": True,
          "nr_optical_flow_quality": "High"}

CORE = {
    **NEURAL,
    "upscale_dlss_mode": "DLAA", "upscale_dlss_preset": "Default", "upscale_optical_flow_quality": "High",
    "upscale_image_dlss_mode": "DLAA", "upscale_image_dlss_preset": "Default",
    "upscale_vsr_quality": 4, "upscale_size_mode": "Scale factor", "upscale_scale_factor": 2.0,
    "upscale_image_vsr_quality": 4, "upscale_image_size_mode": "Scale factor", "upscale_image_scale_factor": 2.0,
    "codec": "H.265", "container": "MP4", "quality": "Best", "hdr_mode": False,
    "image_format": "PNG", "image_bit_depth": 8,
    "video_enabled_stages": ["neural_model", "dlss_super_resolution", "super_resolution"],
    "image_enabled_stages": ["neural_model", "dlss_super_resolution", "super_resolution"],
}

# SeedVR2 brings soft 480p/720p AI clips up to 1080p (bigger clips keep their size); RTX SR then makes the 4K.
SEEDVR2 = {"seedvr2_model": "seedvr2_ema_3b_fp8_e4m3fn.safetensors", "seedvr2_size_mode": "min",
           "seedvr2_short_side": 1080, "seedvr2_scale": 1.0, "seedvr2_batch": 5, "seedvr2_overlap": 2,
           "seedvr2_color": "lab",
           "seedvr2_blend": 100, "seedvr2_blocks_to_swap": 0, "seedvr2_vae_tiling": True}
GENTLE = {"nr_intensity": 1.0, "local_structure_strength": 0.7, "skin_structure_strength": 0.8}
FOUR_K = {"vz_output_short": 2160, "upscale_vsr_quality": 4, "upscale_image_vsr_quality": 4}
GRAIN = {"grain_amount": 8, "grain_size": 1.0, "grain_color": 0, "grain_response": 70, "grain_animated": True}
CHAIN = ["neural_model", "dlss_super_resolution", "super_resolution", "grain"]


def both(stages_: list[str], ai: list[str] | None = None, video_ai: list[str] | None = None) -> dict:
    """Same stages for the video and the image pipeline (RIFE only exists for video)."""
    ai = ai or []
    return {"video_enabled_stages": stages_, "image_enabled_stages": stages_,
            "vz_video_ai": ai + (video_ai or []), "vz_image_ai": ai}


V, R, M = "Visien", "Realism for AI footage", "Motion and size"
P = "Products and brands"
TRUE_COLOR = {"color_match_strength": 100, "color_match_brightness": 25, "color_match_scale": "fine"}

PRESETS = [
    (V, "Visien", 1,
     "Recommended. Neural rendering from your Visual Enhancer setup, DLAA clean-up, then RTX Super Resolution "
     "to 4K by the short side (1080p → 2160p; 4K clips stay 4K). H.265, Best quality.", {**FOUR_K}),
    (V, "Visien 60", 2,
     "Visien plus NVIDIA frame generation to 60 fps with scene-cut detection. For 24, 25 and 30 fps clips.",
     {**FOUR_K,
      "video_enabled_stages": ["neural_model", "dlss_super_resolution", "super_resolution", "vfx_frame_generation"],
      "vfx_frame_generation_model": 1, "vfx_frame_rate_mode": "Target FPS", "vfx_target_fps": "60",
      "vfx_automatic_shot_detection": True}),
    (V, "Visien Film", 3,
     "Visien with light animated film grain, which hides the waxy look AI footage can have. Keeps the "
     "source frame rate.",
     {**FOUR_K, "video_enabled_stages": ["neural_model", "dlss_super_resolution", "super_resolution", "grain"],
      "image_enabled_stages": ["neural_model", "dlss_super_resolution", "super_resolution", "grain"],
      "grain_amount": 12, "grain_size": 1.0, "grain_color": 0, "grain_response": 70, "grain_animated": True}),
    (V, "Visien Native", 4,
     "Neural rendering and DLAA only, at the source size. The fastest way to judge the neural look, and for "
     "clips that are already 4K.",
     {"video_enabled_stages": ["neural_model", "dlss_super_resolution"],
      "image_enabled_stages": ["neural_model", "dlss_super_resolution"]}),

    (R, "Realism · Natural Skin", 10,
     "For AI clips that look plastic or over-saturated. Gentle neural rendering, calmer colour and highlights, "
     "4K by the short side and fine grain. No extra downloads.",
     {**GENTLE, **FOUR_K, **GRAIN, **both(["neural_model", "dlss_super_resolution", "super_resolution", "coloring",
                                           "grain"]),
      "lut_saturation": -6, "lut_vibrance": -4, "lut_highlights": -12, "lut_contrast": -4}),
    (R, "Realism · SeedVR2 Restore", 11,
     "Strongest clean-up for soft, smeary or compressed AI video (Kling, Veo, Sora, Seedance …). SeedVR2 3B "
     "restores real texture and brings small clips up to 1080p, then neural rendering, RTX 4K and fine grain. "
     "About 3 s per frame on a 16 GB RTX card: preview a second or two first.",
     {**SEEDVR2, **GENTLE, **FOUR_K, **GRAIN, **both(CHAIN, ["seedvr2"])}),
    (R, "Realism · SeedVR2 Detail (7B)", 12,
     "Like SeedVR2 Restore with the larger 7B model tuned for crisp detail. About three times slower; for "
     "hero shots and stills.",
     {**SEEDVR2, **GENTLE, **FOUR_K, **GRAIN, **both(CHAIN, ["seedvr2"]),
      "seedvr2_model": "seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors",
      "seedvr2_blocks_to_swap": 16}),
    (R, "Realism · Faces", 13,
     "For shots with people whose faces drift or melt. GFPGAN face restoration (commercial use allowed) at "
     "natural strength, then neural rendering, 4K and fine grain.",
     {**GENTLE, **FOUR_K, **GRAIN, **both(CHAIN, ["face_restore"]),
      "face_model": "gfpgan", "face_blend": 45, "face_which": "all", "face_min_size": 5, "face_smoothing": 60}),
    (R, "Realism · Faces · CodeFormer", 14,
     "The most natural face restoration (CodeFormer, fidelity 0.7) with the same chain. CodeFormer's licence "
     "allows non-commercial use only.",
     {**GENTLE, **FOUR_K, **GRAIN, **both(CHAIN, ["face_restore"]),
      "face_model": "codeformer", "face_fidelity": 0.7, "face_blend": 55, "face_which": "all", "face_min_size": 5,
      "face_smoothing": 60}),

    (P, "Product · True Color", 15,
     "For product, packaging and brand shots: Visien's neural rendering and 4K, then Color Match puts the "
     "source's exact colours back (fine precision, so labels and logos keep theirs). The detail and lighting "
     "from DLSS stay.",
     {**GENTLE, **FOUR_K, **both(["neural_model", "dlss_super_resolution", "super_resolution"], ["color_match"]),
      **TRUE_COLOR}),
    (P, "Realism · Natural Colors", 16,
     "Visien's look with most of the source's colours kept (Color Match 70%): for skin, food and fashion where "
     "DLSS shifts colour a little too much.",
     {**FOUR_K, **GRAIN, **both(CHAIN, ["color_match"]),
      "color_match_strength": 70, "color_match_brightness": 0, "color_match_scale": "balanced"}),

    (M, "Smooth 60 · RIFE", 20,
     "Visien with RIFE 4.26 interpolation to 60 fps before the upscale, with scene-cut protection. Works on "
     "any NVIDIA GPU.",
     {**FOUR_K, **both(["neural_model", "dlss_super_resolution", "super_resolution"], video_ai=["rife"]),
      "rife_model": "rife426.pth", "rife_mode": "Target FPS", "rife_target_fps": "60", "rife_scene_detect": True,
      "rife_scene_threshold": 0.15, "rife_scale": "auto"}),
    (M, "Clean 4K", 21,
     "Upscale without changing the look: DLAA clean-up and RTX Super Resolution to 4K by the short side. "
     "Fast; no neural rendering.",
     {**FOUR_K, **both(["dlss_super_resolution", "super_resolution"])}),
]


def main() -> None:
    folder = ROOT / "presets"
    folder.mkdir(exist_ok=True)
    for old in folder.glob("*.json"):
        old.unlink()
    for group, name, order, description, changes in PRESETS:
        settings = stages.normalize({**CORE, **changes})
        for kind in ("video", "image"):
            problems = stages.validate(settings, kind)
            if problems:
                raise SystemExit(f"{name} ({kind}): {problems}")
        doc = ve.preset_document(settings, name)
        doc["visien"] = {"description": description, "order": order, "group": group}
        slug = "".join(c if c.isalnum() else "_" for c in name.replace(" · ", " ")).strip("_")
        path = folder / (slug.replace("__", "_") + ".json")
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
