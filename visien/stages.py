"""Pipeline stages of Visual Enhancer v18 (Neural Rendering workflow) and their settings.

Every key, stored value and range here was taken from the Visual Enhancer v18.0
source (src/configuration/settings_fields.inc, settings.cpp validate(),
src/desktop/qml/components/*Controls.qml, processing/pipeline.cpp). Visien
sends these keys to VE_CLI.exe as a schema 41 preset.
"""

from __future__ import annotations

import math
from typing import Any

BOTH = ("video", "image")
VIDEO = ("video",)

VIDEO_ORDER = ["neural_model", "scale_method", "dlss_super_resolution", "dlss_ray_reconstruction",
               "super_resolution", "rtx_video_hdr", "frame_generation", "fsr_frame_generation", "reshade", "coloring",
               "cas_sharpening", "grain", "vfx_vsr", "vfx_upscale", "vfx_frame_generation"]
IMAGE_ORDER = ["neural_model", "scale_method", "dlss_super_resolution", "dlss_ray_reconstruction",
               "super_resolution", "reshade", "coloring", "cas_sharpening", "grain"]
ORDERS = {"video": VIDEO_ORDER, "image": IMAGE_ORDER}

FLOW = [("High", "High"), ("Medium", "Medium"), ("Low", "Low")]
FPS_CHOICES = ["23.976", "25", "29.97", "30", "50", "59.94", "60", "90", "119.88", "120", "144", "165", "180",
               "240", "360", "480"]
MULTIPLIERS = [(m, f"{m}×") for m in range(2, 9)]
CODECS = ["H.264", "H.264 (NVIDIA NVENC)", "H.265", "H.265 (NVIDIA NVENC)", "AV1", "AV1 (NVIDIA NVENC)",
          "ProRes Proxy", "ProRes HQ", "FFV1 Lossless RGB 10-bit"]
CODEC_ALIASES = {"HEVC": "H.265", "H265": "H.265", "H.265 (HEVC)": "H.265", "HEVC (NVIDIA NVENC)": "H.265 (NVIDIA NVENC)"}
IMAGE_EXT = {"PNG": "png", "JPEG": "jpg", "WebP": "webp", "AVIF": "avif", "TIFF": "tiff"}
PREVIEW_CODEC = "FFV1 Lossless RGB 10-bit"
DLSS_FACTORS = {"DLAA": 1.0, "Quality": 1.5, "Balanced": 1.724, "Performance": 2.0, "Ultra Performance": 3.0}

# Keys Visien does not edit but keeps when they come from an imported preset.
PASSTHROUGH = {
    "reshade_parameter_overrides": ("str", VIDEO), "reshade_image_parameter_overrides": ("str", ("image",)),
    "reshade_deterministic_seed": ("int", VIDEO), "reshade_image_deterministic_seed": ("int", ("image",)),
    "lut_reference_image": ("str", BOTH),
    # Visien: final size by the short side (0 = use the RTX Super Resolution card as set). Resolved per file.
    "vz_output_short": ("int", BOTH),
}


def containers_for(codec: str) -> list[str]:
    if codec.startswith("ProRes"):
        return ["MOV", "MKV"]
    if codec.startswith("AV1"):
        return ["MKV", "MP4"]
    if codec.startswith("H.264"):
        return ["MP4", "MKV", "MOV"]
    return ["MKV", "MP4", "MOV"]


# ---------------------------------------------------------------- field helpers


def _f(key: str, label: str, kind: str, vtype: str, default: Any, *, image_key: str | None = None,
       image_default: Any = None, kinds=BOTH, **extra) -> dict:
    field = {"key": key, "label": label, "type": kind, "vtype": vtype, "default": default, "kinds": list(kinds)}
    if image_key:
        field["image_key"] = image_key
        field["image_default"] = default if image_default is None else image_default
    field.update({k: v for k, v in extra.items() if v is not None})
    return field


def slider(key, label, lo, hi, step, default, precision=2, vtype="float", **extra) -> dict:
    return _f(key, label, "slider", vtype, default, min=lo, max=hi, step=step, precision=precision, **extra)


def islider(key, label, lo, hi, default, step=1, **extra) -> dict:
    return slider(key, label, lo, hi, step, default, 0, "int", **extra)


def select(key, label, options, default, vtype="str", **extra) -> dict:
    return _f(key, label, "select", vtype, default,
              options=[{"value": v, "label": l} for v, l in options], **extra)


def segment(key, label, options, default, vtype="str", **extra) -> dict:
    return _f(key, label, "segment", vtype, default,
              options=[{"value": v, "label": l} for v, l in options], **extra)


def toggle(key, label, default, **extra) -> dict:
    return _f(key, label, "toggle", "bool", default, **extra)


def number(key, label, lo, hi, default, **extra) -> dict:
    return _f(key, label, "number", "int", default, min=lo, max=hi, **extra)


def path(key, label, default="", filter_=None, folder=False, **extra) -> dict:
    return _f(key, label, "path", "str", default, filter=filter_, folder=folder, **extra)


def heading(label: str, kinds=BOTH, **extra) -> dict:
    return {"type": "heading", "label": label, "kinds": list(kinds), **extra}


# ---------------------------------------------------------------- stages

STAGES: list[dict] = [
    {"id": "neural_model", "title": "DLSS Neural Rendering", "short": "Neural Rendering", "kinds": list(BOTH),
     "about": "DLSS 5 neural rendering: rebuilds skin, hair and material detail. Keeps size and frame rate.",
     "fields": [
         segment("nr_style", "NR Style", [("Style 0", "Style 0"), ("Style 1", "Style 1"), ("Style 2", "Style 2")],
                 "Style 0"),
         slider("nr_intensity", "NR Intensity", 0, 2, 0.05, 1.0),
         islider("nr_passes", "NR Passes", 1, 4, 1),
         slider("local_tone_strength", "Local Tone Strength", 0, 1, 0.05, 1.0),
         slider("local_structure_strength", "Local Structure Strength", 0, 1, 0.05, 1.0),
         toggle("automatic_mask", "Automatic Mask", False, hint="Detects skin and limits the effect there."),
         slider("skin_structure_strength", "Skin Structure Strength", 0, 1, 0.05, 1.0,
                enabled_if={"automatic_mask": True}),
         select("nr_optical_flow_quality", "Optical Flow Quality", FLOW, "High", kinds=VIDEO),
     ]},
    {"id": "scale_method", "title": "Scaling", "short": "Scaling", "kinds": list(BOTH),
     "about": "Classic resize (no AI) to a percentage of the current size.",
     "fields": [
         select("video_scaling_filter", "Scaling Method",
                [(v, v) for v in ("Spline36", "Lanczos", "Bicubic", "Area", "Bilinear")], "Spline36",
                image_key="image_scaling_filter", image_default="Lanczos4",
                image_options=[{"value": v, "label": v} for v in ("Lanczos4", "Area", "Bicubic", "Bilinear",
                                                                  "Nearest")]),
         select("upscaling_factor", "Scale",
                [(0.25, "25%"), (0.5, "50%"), (0.75, "75%"), (1.0, "Source (Original)"), (1.25, "125%"),
                 (1.5, "150%"), (1.75, "175%"), (2.0, "200%"), (3.0, "300%"), (4.0, "400%"), (8.0, "800%"),
                 (16.0, "1600%")], 1.0, vtype="float"),
     ]},
    {"id": "dlss_super_resolution", "title": "DLSS Super Resolution", "short": "DLSS SR", "kinds": list(BOTH),
     "about": "DLSS upscaling. DLAA keeps the size and only reconstructs edges and fine detail.",
     "excludes": ["dlss_ray_reconstruction"],
     "fields": [
         select("upscale_dlss_mode", "DLSS Mode",
                [("DLAA", "DLAA · 1×"), ("Quality", "Quality · 1.5×"), ("Balanced", "Balanced · 1.72×"),
                 ("Performance", "Performance · 2×"), ("Ultra Performance", "Ultra Performance · 3×")], "Quality",
                image_key="upscale_image_dlss_mode"),
         select("upscale_dlss_preset", "DLSS Preset", [(v, v) for v in ("Default", "J", "K", "L", "M")], "Default",
                image_key="upscale_image_dlss_preset"),
         select("upscale_optical_flow_quality", "Optical Flow Quality", FLOW, "High", kinds=VIDEO),
     ]},
    {"id": "dlss_ray_reconstruction", "title": "DLSS Ray Reconstruction", "short": "DLSS RR", "kinds": list(BOTH),
     "about": "Native-resolution (1×) DLSS denoise and reconstruction.",
     "excludes": ["dlss_super_resolution"],
     "fields": [select("rr_optical_flow_quality", "Optical Flow Quality", FLOW, "High", kinds=VIDEO)]},
    {"id": "super_resolution", "title": "RTX Super Resolution", "short": "RTX SR", "kinds": list(BOTH),
     "about": "NVIDIA RTX Video Super Resolution upscaling.",
     "fields": [
         select("upscale_vsr_quality", "VSR Quality", [(1, "1 - Low"), (2, "2 - Medium"), (3, "3 - High"),
                                                       (4, "4 - Ultra")], 4, vtype="int",
                image_key="upscale_image_vsr_quality"),
         segment("upscale_size_mode", "Sizing Mode", [("Scale factor", "Scale factor"),
                                                      ("Custom dimensions", "Custom size")], "Scale factor",
                 image_key="upscale_image_size_mode"),
         select("upscale_scale_factor", "Scale Factor", [(1.0, "1×"), (1.5, "1.5×"), (2.0, "2×"), (3.0, "3×"),
                                                         (4.0, "4×")], 2.0, vtype="float",
                image_key="upscale_image_scale_factor", show_if={"upscale_size_mode": "Scale factor"}),
         number("upscale_width", "Width (px)", 2, 32768, 3840, image_key="upscale_image_width",
                show_if={"upscale_size_mode": "Custom dimensions"}, pair="start"),
         number("upscale_height", "Height (px)", 2, 32768, 2160, image_key="upscale_image_height",
                show_if={"upscale_size_mode": "Custom dimensions"}, pair="end",
                enabled_if={"upscale_aspect_lock": False}),
         toggle("upscale_aspect_lock", "Lock Aspect Ratio", True, image_key="upscale_image_aspect_lock",
                show_if={"upscale_size_mode": "Custom dimensions"}),
     ]},
    {"id": "rtx_video_hdr", "title": "RTX Video HDR", "short": "RTX HDR", "kinds": list(VIDEO),
     "about": "Turns SDR into HDR10. Everything after this card works in HDR; export needs 10-bit HDR.",
     "fields": [
         islider("upscale_hdr_contrast", "HDR Contrast", 0, 200, 100),
         islider("upscale_hdr_saturation", "HDR Saturation", 0, 200, 100),
         islider("upscale_hdr_middle_gray", "Middle Gray", 10, 100, 50),
         islider("upscale_hdr_peak_luminance", "Peak Luminance", 400, 2000, 1000, step=50, unit="nits"),
         segment("upscale_hdr_precision", "HDR Precision", [("Packed 10-bit", "Packed 10-bit"), ("FP16", "FP16")],
                 "Packed 10-bit"),
     ]},
    {"id": "frame_generation", "title": "DLSS Frame Generation", "short": "DLSS FG", "kinds": list(VIDEO),
     "about": "Generates in-between frames with DLSS. Only one frame-generation card can be on.",
     "group": "frame_generation",
     "fields": [
         segment("frame_interpolation_frame_rate_mode", "Frame-rate Mode", [("Multiplier", "Multiplier"),
                                                                            ("Target FPS", "Target FPS")],
                 "Target FPS"),
         select("frame_interpolation_multiplier", "Multiplier", MULTIPLIERS, 2, vtype="int",
                show_if={"frame_interpolation_frame_rate_mode": "Multiplier"}),
         select("frame_interpolation_target_fps", "Target Output Frame Rate", [(v, f"{v} FPS") for v in FPS_CHOICES],
                "60", show_if={"frame_interpolation_frame_rate_mode": "Target FPS"}),
         select("frame_interpolation_optical_flow_quality", "Optical Flow Quality", FLOW, "High"),
     ]},
    {"id": "fsr_frame_generation", "title": "FSR Frame Generation", "short": "FSR FG", "kinds": list(VIDEO),
     "about": "AMD FidelityFX frame generation. Needs an H.264, H.265 or AV1 export.",
     "group": "frame_generation",
     "fields": [
         segment("fsr_frame_generation_frame_rate_mode", "Frame-rate Mode", [("Multiplier", "Multiplier"),
                                                                             ("Target FPS", "Target FPS")],
                 "Target FPS"),
         select("fsr_frame_generation_multiplier", "Multiplier", MULTIPLIERS, 2, vtype="int",
                show_if={"fsr_frame_generation_frame_rate_mode": "Multiplier"}),
         select("fsr_frame_generation_target_fps", "Target Output Frame Rate", [(v, f"{v} FPS") for v in FPS_CHOICES],
                "60", show_if={"fsr_frame_generation_frame_rate_mode": "Target FPS"}),
     ]},
    {"id": "reshade", "title": "ReShade", "short": "ReShade", "kinds": list(BOTH),
     "about": "Runs a ReShade preset (.ini) on every frame. Without a preset this card only costs time.",
     "fields": [
         path("reshade_preset_path", "ReShade Preset (.ini)", filter_="ReShade preset (*.ini)",
              image_key="reshade_image_preset_path"),
         islider("reshade_mix", "Effect Mix", 0, 100, 100, image_key="reshade_image_mix", unit="%"),
         select("reshade_depth_mode", "Depth Input", [("Auto", "Auto"), ("AI Depth", "Always Generate AI Depth"),
                                                      ("Off", "Disabled")], "Auto",
                image_key="reshade_image_depth_mode"),
         select("reshade_temporal_stability", "Video Motion & Depth Stabilization",
                [("Auto", "Auto"), ("Quality", "Optical Flow"), ("Spatial Only (Off)", "Off (Per-Frame Depth)")],
                "Auto", kinds=VIDEO),
         heading("Advanced", collapsible=True),
         islider("reshade_temporal_strength", "Temporal Depth Blend", 0, 100, 75, kinds=VIDEO, advanced=True,
                 show_if={"reshade_temporal_stability": ["Auto", "Quality"]}),
         select("reshade_depth_resolution", "Depth Detail", [(280, "Fast (280)"), (504, "Standard (504)"),
                                                             (756, "High (756)"), (1008, "Maximum (1008)")], 1008,
                vtype="int", image_key="reshade_image_depth_resolution", advanced=True),
         select("reshade_precision_policy", "Effect Precision", [("Auto", "Auto"), ("FP16", "FP16"),
                                                                 ("8-bit sRGB Compatibility",
                                                                  "8-bit sRGB Compatibility")], "Auto",
                image_key="reshade_image_precision_policy", advanced=True),
         select("reshade_hdr_policy", "HDR Handling", [("Auto", "Auto (SDR Preset Adapter)"),
                                                       ("HDR Aware", "HDR-Aware Preset"),
                                                       ("SDR Adapter", "SDR Adapter"),
                                                       ("Reject Unsupported", "Reject Unsupported")], "Auto",
                image_key="reshade_image_hdr_policy", advanced=True),
         toggle("reshade_preserve_alpha", "Preserve Source Transparency", True, image_key="reshade_image_preserve_alpha",
                advanced=True),
         path("reshade_shader_search_paths", "Shader Search Folder (.fx / .fxh)", folder=True,
              image_key="reshade_image_shader_search_paths", advanced=True),
         path("reshade_texture_search_paths", "Texture & LUT Search Folder", folder=True,
              image_key="reshade_image_texture_search_paths", advanced=True),
     ]},
    {"id": "coloring", "title": "Coloring", "short": "Coloring", "kinds": list(BOTH),
     "about": "Light and colour adjustments, or a .cube LUT.",
     "fields": [
         {"type": "tabs", "key": "_coloring_tab", "kinds": list(BOTH),
          "options": [{"value": "adjust", "label": "Color Adjustment"}, {"value": "lut", "label": "LUT File"}]},
         path("lut_path", "LUT File (.cube)", filter_="Cube LUT (*.cube)", tab="lut"),
         select("lut_resolution", "LUT Resolution", [(33, "33³"), (65, "65³"), (129, "129³")], 33, vtype="int",
                tab="lut"),
         islider("lut_mix", "LUT Strength", 0, 200, 100, tab="lut", unit="%"),
         heading("Light", tab="adjust"),
         slider("lut_exposure", "Exposure", -3, 3, 0.05, 0.0, tab="adjust", unit="EV"),
         islider("lut_contrast", "Contrast", -100, 100, 0, tab="adjust"),
         islider("lut_highlights", "Highlights", -100, 100, 0, tab="adjust"),
         islider("lut_shadows", "Shadows", -100, 100, 0, tab="adjust"),
         islider("lut_whites", "Whites", -100, 100, 0, tab="adjust"),
         islider("lut_blacks", "Blacks", -100, 100, 0, tab="adjust"),
         islider("lut_midtones", "Midtones", -100, 100, 0, tab="adjust"),
         heading("Color", tab="adjust"),
         islider("lut_temperature", "Temperature", -100, 100, 0, tab="adjust"),
         islider("lut_tint", "Tint", -100, 100, 0, tab="adjust"),
         islider("lut_hue", "Hue Shift", -180, 180, 0, tab="adjust", unit="°"),
         islider("lut_vibrance", "Vibrance", -100, 100, 0, tab="adjust"),
         islider("lut_saturation", "Saturation", -100, 100, 0, tab="adjust"),
     ]},
    {"id": "cas_sharpening", "title": "Sharpening", "short": "Sharpen", "kinds": list(BOTH),
     "about": "AMD CAS or NVIDIA NIS sharpening.",
     "fields": [
         segment("sharpening_method", "Sharpening Method", [("AMD CAS", "AMD CAS"), ("NVIDIA NIS", "NVIDIA NIS")],
                 "AMD CAS"),
         islider("cas_sharpness", "Sharpness", 0, 100, 50),
     ]},
    {"id": "grain", "title": "Grain", "short": "Grain", "kinds": list(BOTH),
     "about": "Film grain. A light touch hides the plastic look of AI footage.",
     "fields": [
         islider("grain_amount", "Grain Amount", 0, 100, 20),
         slider("grain_size", "Grain Size", 0.5, 4, 0.05, 1.0),
         islider("grain_color", "Color Grain", 0, 100, 0),
         islider("grain_response", "Tonal Response", 0, 100, 70),
         number("grain_seed", "Grain Seed", 0, 65535, 0),
         toggle("grain_animated", "Animated Grain", True, kinds=VIDEO),
     ]},
    {"id": "vfx_vsr", "title": "Video Super Resolution", "short": "VFX VSR", "kinds": list(VIDEO),
     "about": "NVIDIA Maxine VFX super resolution, denoise and deblur.",
     "fields": [
         _f("vfx_vsr_mode", "Mode", "vsr_mode", "int", 3,
            families=[{"label": "Standard Upscaling", "levels": [[0, "Bicubic"], [1, "Low"], [2, "Medium"],
                                                                  [3, "High"], [4, "Ultra"]]},
                      {"label": "Denoise", "levels": [[8, "Low"], [9, "Medium"], [10, "High"], [11, "Ultra"]]},
                      {"label": "Deblur", "levels": [[12, "Low"], [13, "Medium"], [14, "High"], [15, "Ultra"]]},
                      {"label": "High-Bitrate", "levels": [[16, "Low"], [17, "Medium"], [18, "High"],
                                                           [19, "Ultra"]]}]),
         slider("vfx_vsr_strength", "Strength", 0, 1, 0.01, 1.0),
         segment("vfx_size_mode", "Sizing Mode", [("Scale factor", "Scale factor"),
                                                  ("Custom dimensions", "Custom size")], "Scale factor",
                 show_if={"vfx_vsr_mode": [0, 1, 2, 3, 4, 16, 17, 18, 19]}),
         select("vfx_scale_factor", "Scale Factor", [(1.0, "1×"), (1.5, "1.5×"), (2.0, "2×"), (3.0, "3×"),
                                                     (4.0, "4×")], 2.0, vtype="float",
                show_if={"vfx_size_mode": "Scale factor", "vfx_vsr_mode": [0, 1, 2, 3, 4, 16, 17, 18, 19]}),
         number("vfx_width", "Width (px)", 2, 32768, 3840, pair="start",
                show_if={"vfx_size_mode": "Custom dimensions", "vfx_vsr_mode": [0, 1, 2, 3, 4, 16, 17, 18, 19]}),
         number("vfx_height", "Height (px)", 2, 32768, 2160, pair="end", enabled_if={"vfx_aspect_lock": False},
                show_if={"vfx_size_mode": "Custom dimensions", "vfx_vsr_mode": [0, 1, 2, 3, 4, 16, 17, 18, 19]}),
         toggle("vfx_aspect_lock", "Lock Aspect Ratio", True,
                show_if={"vfx_size_mode": "Custom dimensions", "vfx_vsr_mode": [0, 1, 2, 3, 4, 16, 17, 18, 19]}),
     ]},
    {"id": "vfx_upscale", "title": "Upscale (Lightweight)", "short": "VFX Upscale", "kinds": list(VIDEO),
     "about": "Fast NVIDIA VFX upscaler with sharpening.",
     "fields": [
         select("vfx_upscale_scale", "Scale Factor", [(4 / 3, "4/3×"), (1.5, "1.5×"), (2.0, "2×"), (3.0, "3×"),
                                                      (4.0, "4×")], 2.0, vtype="float"),
         slider("vfx_upscale_strength", "Sharpening Strength", 0, 1, 0.01, 0.4),
     ]},
    {"id": "vfx_frame_generation", "title": "Video Frame Generation", "short": "VFX FG", "kinds": list(VIDEO),
     "about": "NVIDIA VFX frame generation with scene-cut detection. Only one frame-generation card can be on.",
     "group": "frame_generation",
     "fields": [
         select("vfx_frame_generation_model", "Model", [(0, "Low"), (1, "Medium"), (2, "High")], 1, vtype="int"),
         segment("vfx_frame_rate_mode", "Frame-rate Mode", [("Multiplier", "Multiplier"), ("Target FPS", "Target FPS")],
                 "Multiplier"),
         select("vfx_frame_multiplier", "Multiplier", MULTIPLIERS, 2, vtype="int",
                show_if={"vfx_frame_rate_mode": "Multiplier"}),
         _f("vfx_target_fps", "Target FPS", "fps", "str", "60",
            suggestions=["24", "25", "29.97", "30", "48", "50", "59.94", "60", "90", "120"],
            show_if={"vfx_frame_rate_mode": "Target FPS"}),
         toggle("vfx_automatic_shot_detection", "Automatic Scene-cut Detection", True),
     ]},
]

EXPORT: list[dict] = [
    select("codec", "Codec", [(c, c) for c in CODECS], "H.264", kinds=VIDEO),
    select("container", "Container", [(c, c) for c in ("MP4", "MKV", "MOV")], "MP4", kinds=VIDEO),
    segment("quality", "Encoding Quality", [("Auto (Default)", "Auto"), ("Good", "Good"), ("Best", "Best"),
                                            ("Max", "Max")], "Auto (Default)", kinds=VIDEO,
            hide_for_codec=["FFV1 Lossless RGB 10-bit", "ProRes HQ"]),
    toggle("hdr_mode", "Preserve / Export 10-bit HDR", False, kinds=VIDEO),
    segment("image_format", "Format", [(f, f) for f in IMAGE_EXT], "PNG", kinds=("image",)),
    segment("image_bit_depth", "Bit Depth", [(8, "8 Bit"), (16, "16 Bit")], 8, vtype="int", kinds=("image",)),
    islider("image_quality", "Quality", 1, 100, 95, kinds=("image",),
            show_if={"image_format": ["JPEG", "WebP", "AVIF"]}),
    # Visien extras (not used by Visual Enhancer)
    heading("Comparison copy"),
    segment("vz_compare", "Comparison", [("off", "Off"), ("stack", "Top / bottom"), ("side", "Side by side")], "off"),
    _f("vz_compare_before", "Before Label", "text", "str", "RAW", show_if={"vz_compare": ["stack", "side"]}),
    _f("vz_compare_after", "After Label", "text", "str", "NEURAL ENHANCED", show_if={"vz_compare": ["stack", "side"]}),
    segment("vz_compare_size", "Comparison Size", [("fit", "Fit 1080p"), ("full", "Full size")], "fit",
            show_if={"vz_compare": ["stack", "side"]}),
    heading("Multi-shot video", kinds=VIDEO),
    toggle("vz_shot_warmup", "Clean Shot Starts", True, kinds=VIDEO),
]

# ---------------------------------------------------------------- Visien AI stages (run outside Visual Enhancer)

SEEDVR2_MODELS = [("seedvr2_ema_3b_fp8_e4m3fn.safetensors", "3B · fast (FP8)"),
                  ("seedvr2_ema_3b_fp16.safetensors", "3B · FP16"),
                  ("seedvr2_ema_7b_fp8_e4m3fn_mixed_block35_fp16.safetensors", "7B · detail (FP8)"),
                  ("seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors", "7B sharp · detail (FP8)")]
RIFE_MODELS = [("rife426.pth", "RIFE 4.26 · best"), ("rife417.pth", "RIFE 4.17"), ("rife49.pth", "RIFE 4.9 · fast")]

AI_STAGES: list[dict] = [
    {"id": "seedvr2", "engine": "ai", "title": "SeedVR2 Restore", "short": "SeedVR2", "kinds": list(BOTH),
     "about": "One-step diffusion restoration by ByteDance (Apache 2.0). Runs on your GPU before or after the "
              "Visual Enhancer stages.",
     "fields": [
         select("seedvr2_model", "Model", SEEDVR2_MODELS, SEEDVR2_MODELS[0][0]),
         segment("seedvr2_size_mode", "Output Size", [("min", "At least"), ("short", "Short side"),
                                                     ("scale", "Scale")], "min"),
         select("seedvr2_scale", "Scale", [(1.0, "1× · restore only"), (1.5, "1.5×"), (2.0, "2×")], 1.0,
                vtype="float", show_if={"seedvr2_size_mode": "scale"}),
         select("seedvr2_short_side", "Short Side", [(720, "720 px"), (1080, "1080 px"), (1440, "1440 px"),
                                                    (2160, "2160 px")], 1080, vtype="int",
                show_if={"seedvr2_size_mode": ["short", "min"]}),
         select("seedvr2_batch", "Temporal Window", [(1, "1 frame"), (5, "5 frames"), (9, "9 frames"),
                                                    (13, "13 frames"), (21, "21 frames")], 5, vtype="int",
                kinds=VIDEO),
         select("seedvr2_overlap", "Batch Overlap", [(0, "Off"), (1, "1 frame"), (2, "2 frames"), (3, "3 frames")],
                2, vtype="int", kinds=VIDEO),
         select("seedvr2_color", "Color Correction", [("lab", "LAB · natural"), ("wavelet", "Wavelet"),
                                                      ("wavelet_adaptive", "Wavelet adaptive"), ("adain", "AdaIN"),
                                                      ("none", "Off")], "lab"),
         islider("seedvr2_blend", "Blend", 0, 100, 100, unit="%"),
         heading("Advanced", collapsible=True),
         slider("seedvr2_input_noise", "Input Noise", 0, 1, 0.05, 0.0, advanced=True),
         slider("seedvr2_latent_noise", "Latent Noise", 0, 1, 0.05, 0.0, advanced=True),
         number("seedvr2_seed", "Seed", 0, 999999, 42, advanced=True),
         select("seedvr2_blocks_to_swap", "Block Swap", [(0, "Off"), (8, "8 blocks"), (16, "16 blocks"),
                                                         (24, "24 blocks"), (32, "32 blocks")], 0, vtype="int",
                advanced=True),
         toggle("seedvr2_vae_tiling", "VAE Tiling", True, advanced=True),
     ]},
    {"id": "rife", "engine": "ai", "title": "RIFE Interpolation", "short": "RIFE", "kinds": list(VIDEO),
     "about": "Practical-RIFE frame interpolation (MIT). Only one frame-generation card can be on.",
     "group": "frame_generation",
     "fields": [
         select("rife_model", "Model", RIFE_MODELS, RIFE_MODELS[0][0]),
         segment("rife_mode", "Frame-rate Mode", [("Multiplier", "Multiplier"), ("Target FPS", "Target FPS")],
                 "Target FPS"),
         select("rife_multiplier", "Multiplier", [(2, "2×"), (3, "3×"), (4, "4×")], 2, vtype="int",
                show_if={"rife_mode": "Multiplier"}),
         _f("rife_target_fps", "Target FPS", "fps", "str", "60",
            suggestions=["30", "48", "50", "59.94", "60", "120"], show_if={"rife_mode": "Target FPS"}),
         toggle("rife_scene_detect", "Scene-cut Detection", True),
         slider("rife_scene_threshold", "Cut Sensitivity", 0.05, 0.6, 0.01, 0.15,
                enabled_if={"rife_scene_detect": True}),
         segment("rife_scale", "Motion Analysis", [("auto", "Auto"), ("full", "Full"), ("half", "Half")], "auto"),
     ]},
    {"id": "face_restore", "engine": "ai", "title": "Face Restore", "short": "Faces", "kinds": list(BOTH),
     "about": "CodeFormer (NTU S-Lab licence, non-commercial use only) or GFPGAN 1.4 (Apache 2.0).",
     "fields": [
         segment("face_model", "Model", [("gfpgan", "GFPGAN 1.4"), ("codeformer", "CodeFormer")], "gfpgan"),
         slider("face_fidelity", "Fidelity", 0, 1, 0.05, 0.7, show_if={"face_model": "codeformer"}),
         islider("face_blend", "Strength", 0, 100, 60, unit="%"),
         segment("face_which", "Faces", [("all", "All"), ("largest", "Largest")], "all"),
         islider("face_min_size", "Min Face Size", 2, 40, 5, unit="%"),
         islider("face_smoothing", "Temporal Smoothing", 0, 100, 60, kinds=VIDEO),
     ]},
    {"id": "color_match", "engine": "ai", "title": "Color Match", "short": "Color Match", "kinds": list(BOTH),
     "about": "Brings back the source's colours after the other cards (product, brand and skin colours) while "
              "keeping the detail and lighting that DLSS adds.",
     "fields": [
         islider("color_match_strength", "Original Colors", 0, 100, 80, unit="%"),
         islider("color_match_brightness", "Original Brightness", 0, 100, 0, unit="%"),
         segment("color_match_scale", "Precision", [("broad", "Broad"), ("balanced", "Balanced"), ("fine", "Fine")],
                 "balanced"),
     ]},
]
for _stage in STAGES:
    _stage.setdefault("engine", "ve")
STAGES.extend(AI_STAGES)
AI_IDS = [stage["id"] for stage in AI_STAGES]
TITLES = {stage["id"]: stage["title"] for stage in STAGES}

# Full Visien order (Visual Enhancer stages and AI stages together).
VZ_ORDERS = {
    # Face Restore runs before neural rendering, which then puts real skin texture back on the restored faces.
    # RIFE runs before the upscale (4× fewer pixels to interpolate) and before grain and sharpening, so those are
    # added to every output frame instead of being blended between frames. Color Match compares the finished
    # picture with the source, so it runs last.
    "video": ["seedvr2", "face_restore", "neural_model", "scale_method", "dlss_super_resolution",
              "dlss_ray_reconstruction", "rife", "super_resolution", "rtx_video_hdr", "frame_generation",
              "fsr_frame_generation", "reshade", "coloring", "cas_sharpening", "grain", "vfx_vsr",
              "vfx_upscale", "vfx_frame_generation", "color_match"],
    "image": ["seedvr2", "face_restore", "neural_model", "scale_method", "dlss_super_resolution",
              "dlss_ray_reconstruction", "super_resolution", "reshade", "coloring", "cas_sharpening", "grain",
              "color_match"],
}

STAGE_BY_ID = {stage["id"]: stage for stage in STAGES}


# ---------------------------------------------------------------- key tables


def _all_fields():
    for stage in STAGES:
        for field in stage["fields"]:
            yield stage["id"], field
    for field in EXPORT:
        yield "export", field


def _key_specs() -> dict[str, dict]:
    """settings key -> {vtype, default, field, kinds}"""
    specs: dict[str, dict] = {}
    for stage_id, field in _all_fields():
        if "key" not in field or field["key"].startswith("_"):
            continue
        kinds = field["kinds"]
        if "image_key" in field:
            video_kinds = [k for k in kinds if k == "video"]
            specs[field["key"]] = {"vtype": field["vtype"], "default": field["default"], "field": field,
                                   "kinds": video_kinds, "stage": stage_id}
            specs[field["image_key"]] = {"vtype": field["vtype"], "default": field["image_default"], "field": field,
                                         "kinds": ["image"], "stage": stage_id, "image": True}
        else:
            specs[field["key"]] = {"vtype": field["vtype"], "default": field["default"], "field": field,
                                   "kinds": list(kinds), "stage": stage_id}
    return specs


KEYS = _key_specs()


def defaults() -> dict:
    values = {key: spec["default"] for key, spec in KEYS.items()}
    values.update(video_enabled_stages=["neural_model"], image_enabled_stages=["neural_model"],
                  video_stage_order=list(VIDEO_ORDER), image_stage_order=list(IMAGE_ORDER),
                  vz_video_order=list(VZ_ORDERS["video"]), vz_image_order=list(VZ_ORDERS["image"]),
                  vz_video_ai=[], vz_image_ai=[])
    return values


def _merge_order(ve_order: list[str], kind: str) -> list[str]:
    """Full Visien order from a Visual Enhancer order, AI stages at their default neighbours."""
    result = list(ve_order)
    default = VZ_ORDERS[kind]
    for ai in [s for s in default if s in AI_IDS]:
        index = default.index(ai)
        after = next((s for s in reversed(default[:index]) if s in result), None)
        result.insert(result.index(after) + 1 if after else 0, ai)
    return result


# ---------------------------------------------------------------- normalising


def _coerce(value: Any, spec: dict) -> Any:
    vtype, field = spec["vtype"], spec["field"]
    default = spec["default"]
    try:
        if vtype == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if vtype == "int":
            number = int(round(float(value)))
        elif vtype == "float":
            number = float(value)
            if not math.isfinite(number):
                return default
        else:
            text = "" if value is None else str(value)
            if spec["field"]["key"] == "codec":
                text = CODEC_ALIASES.get(text, text)
            return text
    except (TypeError, ValueError):
        return default
    lo, hi = field.get("min"), field.get("max")
    if lo is not None and number < lo:
        number = type(number)(lo)
    if hi is not None and number > hi:
        number = type(number)(hi)
    return number


def _stage_list(value: Any, valid: list[str]) -> list[str]:
    result: list[str] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str) and item in valid and item not in result:
            result.append(item)
    return result


def normalize(settings: dict | None) -> dict:
    """Complete, typed and valid-shaped settings (unknown and machine-specific keys dropped)."""
    settings = settings or {}
    result = defaults()
    for key, value in settings.items():
        if key in KEYS:
            result[key] = _coerce(value, KEYS[key])
        elif key in PASSTHROUGH and value is not None:
            vtype = PASSTHROUGH[key][0]
            try:
                result[key] = int(value) if vtype == "int" else str(value)
            except (TypeError, ValueError):
                continue
    for key, spec in KEYS.items():
        field = spec["field"]
        if field["type"] in ("select", "segment") and spec["vtype"] != "float":
            options = field.get("image_options") if spec.get("image") and field.get("image_options") \
                else field.get("options")
            if options and result[key] not in [o["value"] for o in options]:
                result[key] = spec["default"]
    for kind, order in ORDERS.items():
        given = _stage_list(settings.get(f"{kind}_stage_order"), order)
        result[f"{kind}_stage_order"] = given + [s for s in order if s not in given]
        if f"{kind}_enabled_stages" in settings:
            result[f"{kind}_enabled_stages"] = _stage_list(settings.get(f"{kind}_enabled_stages"), order)
        vz_all = VZ_ORDERS[kind]
        vz_given = _stage_list(settings.get(f"vz_{kind}_order"), vz_all)
        if vz_given:
            vz = vz_given + [s for s in vz_all if s not in vz_given]
        else:
            vz = _merge_order(result[f"{kind}_stage_order"], kind)
        result[f"vz_{kind}_order"] = vz
        result[f"{kind}_stage_order"] = [s for s in vz if s in order]
        result[f"vz_{kind}_ai"] = _stage_list(settings.get(f"vz_{kind}_ai"), [s for s in vz_all if s in AI_IDS])
    if result["vfx_vsr_mode"] not in (*range(0, 5), *range(8, 20)):
        result["vfx_vsr_mode"] = 3
    if result["video_scaling_filter"] not in ("Spline36", "Lanczos", "Bicubic", "Area", "Bilinear"):
        result["video_scaling_filter"] = "Spline36"
    if result["image_scaling_filter"] not in ("Lanczos4", "Area", "Bicubic", "Bilinear", "Nearest"):
        result["image_scaling_filter"] = "Lanczos4"
    for key in ("upscale_vsr_quality", "upscale_image_vsr_quality"):
        if result[key] == 0:
            result[key] = 4
    enabled = result["video_enabled_stages"]
    result["vfx_vsr_enabled"] = "vfx_vsr" in enabled
    result["vfx_upscale_enabled"] = "vfx_upscale" in enabled
    result["vfx_frame_generation_enabled"] = "vfx_frame_generation" in enabled
    return result


def for_kind(settings: dict, kind: str) -> dict:
    """Only the keys that matter for this media kind (missing keys fall back to VE defaults)."""
    result = {}
    for key, value in settings.items():
        spec = KEYS.get(key)
        if spec is not None:
            if kind in spec["kinds"]:
                result[key] = value
        elif key in PASSTHROUGH:
            if kind in PASSTHROUGH[key][1]:
                result[key] = value
        elif key in (f"{kind}_enabled_stages", f"{kind}_stage_order", f"vz_{kind}_order", f"vz_{kind}_ai"):
            result[key] = value
        elif key.startswith("vfx_") and key.endswith("_enabled") and kind == "video":
            result[key] = value
    if kind == "image":
        # Use exactly the ReShade settings shown on the Image pipeline (VE would otherwise fall back to the
        # video ReShade keys when the image ones are at their defaults).
        result["reshade_image_configured"] = True
    return result


def preview_settings(settings: dict, kind: str) -> dict:
    result = dict(settings)
    if kind == "video":
        result.update(codec=PREVIEW_CODEC, container="MKV", quality="Auto (Default)")
    else:
        result.update(image_format="PNG")
        if result.get("image_bit_depth") not in (8, 16):
            result["image_bit_depth"] = 8
    return result


def output_extension(settings: dict, kind: str) -> str:
    if kind == "video":
        container = str(settings.get("container") or "MP4").upper()
        return container.lower() if container in ("MP4", "MKV", "MOV") else "mp4"
    return IMAGE_EXT.get(str(settings.get("image_format") or "PNG"), "png")


def active_stages(settings: dict, kind: str) -> list[str]:
    """Enabled stages (Visual Enhancer and AI) in Visien order."""
    enabled = set(settings.get(f"{kind}_enabled_stages") or []) | set(settings.get(f"vz_{kind}_ai") or [])
    order = settings.get(f"vz_{kind}_order") or VZ_ORDERS[kind]
    return [s for s in order if s in enabled]


def segments(settings: dict, kind: str) -> list[tuple[str, list[str]]]:
    """[("ve", [stage, ...]) | ("ai", [stage])] in run order; consecutive VE stages share one VE run."""
    result: list[tuple[str, list[str]]] = []
    for stage in active_stages(settings, kind):
        if stage in AI_IDS:
            result.append(("ai", [stage]))
        elif result and result[-1][0] == "ve":
            result[-1][1].append(stage)
        else:
            result.append(("ve", [stage]))
    return result


def uses_ai(settings: dict, kind: str) -> bool:
    return bool(set(settings.get(f"vz_{kind}_ai") or []) & set(AI_IDS))


def ve_segment_settings(settings: dict, kind: str, stages_: list[str]) -> dict:
    """Settings for one Visual Enhancer run that executes only `stages_`."""
    result = dict(settings)
    result[f"{kind}_enabled_stages"] = list(stages_)
    result[f"vz_{kind}_ai"] = []
    if kind == "video":
        result["vfx_vsr_enabled"] = "vfx_vsr" in stages_
        result["vfx_upscale_enabled"] = "vfx_upscale" in stages_
        result["vfx_frame_generation_enabled"] = "vfx_frame_generation" in stages_
    return result


def seedvr2_size(settings: dict, width: float, height: float) -> tuple[int, int]:
    """Output size of SeedVR2 (short side resized, long side truncated; Visien keeps both even)."""
    short = min(width, height)
    mode = settings.get("seedvr2_size_mode")
    if mode == "short":
        target = int(settings.get("seedvr2_short_side") or 1080)
    elif mode == "min":
        target = max(int(short), int(settings.get("seedvr2_short_side") or 1080))
    else:
        target = int(round(short * float(settings.get("seedvr2_scale") or 1.0)))
    target -= target % 2
    long_ = int(target * max(width, height) / short) if short else target
    long_ -= long_ % 2
    return (long_, target) if width >= height else (target, long_)


def without_ve(settings: dict, kind: str) -> dict:
    """The same settings with every Visual Enhancer card turned off (only Visien's AI cards run)."""
    result = dict(settings)
    result[f"{kind}_enabled_stages"] = []
    if kind == "video":
        result.update(vfx_vsr_enabled=False, vfx_upscale_enabled=False, vfx_frame_generation_enabled=False)
    return result


def skipped_ve(settings: dict, kind: str) -> list[str]:
    """Visual Enhancer cards this PC cannot run (no NVIDIA RTX GPU); they are skipped and the AI cards still run."""
    from . import ve  # noqa: WPS433 - lazy: stages is imported by ve's users

    if not settings.get(f"{kind}_enabled_stages") or not ve.rtx_problem():
        return []
    return [TITLES.get(s, s) for s in settings.get(f"{kind}_enabled_stages") or []]


def resolve(settings: dict, info) -> dict:
    """Per-file settings: turns "vz_output_short" (output size by the short side, set in Easy mode) into the
    RTX Super Resolution size for this file. Portrait and landscape clips both end up at the same short side.
    On a PC without an NVIDIA RTX GPU the Visual Enhancer cards are dropped."""
    if skipped_ve(settings, info.kind):
        settings = without_ve(settings, info.kind)
    target = int(settings.get("vz_output_short") or 0)
    kind = info.kind
    active = active_stages(settings, kind)
    if target <= 0 or "super_resolution" not in active or not info.width or not info.height:
        return settings
    before = active[:active.index("super_resolution")]
    probe = dict(settings)
    probe[f"{kind}_enabled_stages"] = [s for s in before if s not in AI_IDS]
    probe[f"vz_{kind}_ai"] = [s for s in before if s in AI_IDS]
    est = estimate(probe, info) if before else {"width": info.width, "height": info.height}
    width, height = float(est["width"]), float(est["height"])
    short = min(width, height)
    result = dict(settings)
    prefix = "upscale_image_" if kind == "image" else "upscale_"
    if target <= short + 1:
        result[prefix + "size_mode"] = "Scale factor"
        result[prefix + "scale_factor"] = 1.0
        return result
    factor = min(target / short, 4.0)  # RTX Video Super Resolution goes up to 4×
    new_w, new_h = width * factor, height * factor
    if kind == "video":
        new_w, new_h = _even_nearest(new_w), _even_nearest(new_h)
    else:
        new_w, new_h = round(new_w), round(new_h)
    result[prefix + "size_mode"] = "Custom dimensions"
    result[prefix + "aspect_lock"] = False
    result[prefix + "width"] = int(new_w)
    result[prefix + "height"] = int(new_h)
    return result


# ---------------------------------------------------------------- checks


def _even_ceil(value: float) -> int:
    number = math.ceil(value - 1e-9)
    return number + (number % 2)


def _even_nearest(value: float) -> int:
    return int(round(value / 2.0)) * 2


def _fps_value(text: str) -> float:
    exact = {"23.976": 24000 / 1001, "29.97": 30000 / 1001, "59.94": 60000 / 1001, "119.88": 120000 / 1001}
    try:
        return exact.get(str(text), float(text))
    except (TypeError, ValueError):
        return 0.0


def estimate(settings: dict, info) -> dict:
    """Local plan of the output size and frame rate, plus warnings.

    Visual Enhancer's own dry run is authoritative; this mirrors pipeline.cpp so the panel can explain
    problems even before Visual Enhancer is connected.
    """
    kind = info.kind
    width, height = float(info.width), float(info.height)
    fps = float(getattr(info, "fps_value", 0.0) or 0.0)
    hdr = bool(getattr(info, "hdr", False))
    problems, warnings = [], []
    get = settings.get

    def k(key: str) -> str:
        field = KEYS[key]["field"]
        return field.get("image_key", key) if kind == "image" and "image_key" in field else key

    for stage in active_stages(settings, kind):
        title = STAGE_BY_ID[stage]["title"]
        if stage == "scale_method":
            if hdr and kind == "video":
                problems.append(f"{title} can't run on HDR. Move it before RTX Video HDR.")
            factor = float(get("upscaling_factor", 1.0))
            width, height = (_even_nearest(width * factor), _even_nearest(height * factor)) if kind == "video" \
                else (round(width * factor), round(height * factor))
            if factor == 1.0:
                warnings.append(f"{title} is at 100%: it has no effect.")
        elif stage == "dlss_super_resolution":
            if hdr and kind == "video":
                problems.append(f"{title} can't run on HDR. Move it before RTX Video HDR.")
            factor = DLSS_FACTORS.get(str(get(k("upscale_dlss_mode"), "Quality")), 1.5)
            width, height = (_even_ceil(width * factor), _even_ceil(height * factor)) if kind == "video" \
                else (math.ceil(width * factor), math.ceil(height * factor))
        elif stage == "super_resolution":
            if hdr and kind == "video":
                problems.append(f"{title} can't run on HDR. Move it before RTX Video HDR.")
            if get(k("upscale_size_mode")) == "Custom dimensions":
                new_w = float(get(k("upscale_width"), 3840))
                new_h = new_w * height / width if get(k("upscale_aspect_lock"), True) else float(get(k("upscale_height"), 2160))
            else:
                factor = float(get(k("upscale_scale_factor"), 2.0))
                new_w, new_h = width * factor, height * factor
            new_w, new_h = (_even_ceil(new_w), _even_ceil(new_h)) if kind == "video" else (math.ceil(new_w), math.ceil(new_h))
            if new_w < width or new_h < height:
                problems.append(f"{title} can't make the picture smaller ({int(width)}×{int(height)} → {new_w}×{new_h}).")
            width, height = new_w, new_h
        elif stage == "rtx_video_hdr":
            if hdr:
                problems.append("RTX Video HDR needs an SDR picture; this one is already HDR.")
            hdr = True
        elif stage in ("frame_generation", "fsr_frame_generation", "vfx_frame_generation"):
            if stage == "frame_generation":
                mode, mult, target = (get("frame_interpolation_frame_rate_mode"), get("frame_interpolation_multiplier"),
                                      get("frame_interpolation_target_fps"))
            elif stage == "fsr_frame_generation":
                mode, mult, target = (get("fsr_frame_generation_frame_rate_mode"), get("fsr_frame_generation_multiplier"),
                                      get("fsr_frame_generation_target_fps"))
                if not str(get("codec", "")).startswith(("H.264", "H.265", "AV1")):
                    problems.append("FSR Frame Generation needs an H.264, H.265 or AV1 export.")
            else:
                mode, mult, target = get("vfx_frame_rate_mode"), get("vfx_frame_multiplier"), get("vfx_target_fps")
                if not 0 < _fps_value(target) <= 1000:
                    problems.append("Video Frame Generation: enter a target frame rate between 1 and 1000.")
            new_fps = fps * int(mult or 2) if mode == "Multiplier" else _fps_value(target)
            if fps and new_fps <= fps + 1e-6:
                problems.append(f"{title}: the target ({new_fps:.3f} fps) must be higher than the "
                                f"incoming {fps:.3f} fps.")
            fps = new_fps
        elif stage == "vfx_vsr":
            mode = int(get("vfx_vsr_mode", 3))
            if not 8 <= mode <= 15:
                if get("vfx_size_mode") == "Custom dimensions":
                    new_w = float(get("vfx_width", 3840))
                    new_h = new_w * height / width if get("vfx_aspect_lock", True) else float(get("vfx_height", 2160))
                else:
                    factor = float(get("vfx_scale_factor", 2.0))
                    new_w, new_h = width * factor, height * factor
                new_w, new_h = _even_ceil(new_w), _even_ceil(new_h)
                if new_w < width or new_h < height:
                    problems.append(f"{title} can't make the picture smaller.")
                width, height = new_w, new_h
        elif stage == "vfx_upscale":
            if hdr:
                problems.append(f"{title} can't run on HDR. Move it before RTX Video HDR.")
            factor = float(get("vfx_upscale_scale", 2.0))
            width, height = width * factor, height * factor
            if abs(width - round(width)) > 1e-6 or abs(height - round(height)) > 1e-6:
                problems.append(f"{title}: {factor:g}× does not give whole pixels for this size. Pick another factor.")
            width, height = round(width), round(height)
        elif stage == "cas_sharpening":
            if hdr and kind == "video" and int(get("cas_sharpness", 50)) > 0:
                problems.append("Sharpening can't run on HDR. Move it before RTX Video HDR.")
            if int(get("cas_sharpness", 50)) == 0:
                warnings.append("Sharpening is at 0: it has no effect.")
        elif stage == "reshade":
            if not str(get(k("reshade_preset_path")) or "").strip():
                warnings.append("ReShade has no preset: the picture passes through unchanged, but the stage still "
                                "costs time. Pick a .ini or turn the card off.")
        elif stage == "grain":
            if int(get("grain_amount", 20)) == 0:
                warnings.append("Grain Amount is 0: it has no effect.")
        elif stage == "seedvr2":
            if hdr:
                problems.append("SeedVR2 works in SDR. Move RTX Video HDR after it (HDR sources are not supported).")
            width, height = seedvr2_size(settings, width, height)
            pixels = width * height
            if pixels > 3840 * 2160 * 1.01 and kind == "image":
                warnings.append(f"SeedVR2 output {width}×{height} is very large and slow. Restore at 1080p and "
                                "upscale with RTX Super Resolution instead.")
            if kind == "video" and info.frames:
                # Measured on a 16 GB RTX 5070 Ti (2-frame overlap): ~3.5 s per frame at 1080p, ~30 s at 3380×1440.
                overlap = int(get("seedvr2_overlap", 2) or 0)
                batch = int(get("seedvr2_batch", 5) or 5)
                factor = (batch / max(1, batch - min(overlap, batch - 1)) if batch > 1 else 1.0) / 1.67
                mp = pixels / 1e6
                per_frame = (1.7 * mp if mp <= 2.1 else 3.5 * (mp / 2.07) ** 2.5) * factor
                seconds = info.frames * per_frame
                from . import ve  # noqa: WPS433

                rtx = not ve.rtx_problem()
                if mp > 2.2:
                    advice = ("set Output Size to Short side 1080 and let RTX Super Resolution do the rest, or use "
                              "Realism · Natural Skin." if rtx else "lower SeedVR2's short side to 720-1080.")
                    warnings.append(f"SeedVR2 at {int(width)}×{int(height)} is very slow on a 16 GB card (about "
                                    f"{per_frame:.0f} s per frame, {seconds / 60:.0f} min for this clip). It is made for "
                                    f"480p-1080p sources: {advice}")
                elif seconds > 120:
                    warnings.append(f"SeedVR2 will take roughly {seconds / 60:.0f} min for this clip on a 16 GB card. "
                                    "Preview a second or two first.")
        elif stage == "rife":
            if hdr:
                problems.append("RIFE works in SDR. Move RTX Video HDR after it.")
            if get("rife_mode") == "Multiplier":
                new_fps = fps * int(get("rife_multiplier") or 2)
            else:
                new_fps = _fps_value(get("rife_target_fps"))
                if not 0 < new_fps <= 1000:
                    problems.append("RIFE: enter a target frame rate between 1 and 1000.")
            if fps and new_fps <= fps + 1e-6:
                problems.append(f"RIFE: the target ({new_fps:.3f} fps) must be higher than the incoming {fps:.3f} fps.")
            fps = new_fps
        elif stage == "face_restore":
            if hdr:
                problems.append("Face Restore works in SDR. Move RTX Video HDR after it.")
            if get("face_model") == "codeformer":
                warnings.append("CodeFormer is licensed for non-commercial use only. Use GFPGAN for client work.")
            if kind == "video" and int(get("face_blend", 60)) > 80:
                warnings.append("Face Restore above 80% strength can flicker on video.")
        elif stage == "color_match":
            if hdr:
                problems.append("Color Match works in SDR. Turn RTX Video HDR off or move Color Match before it.")
            if int(get("color_match_strength", 80)) == 0 and int(get("color_match_brightness", 0)) == 0:
                warnings.append("Color Match is at 0%: it has no effect.")
        elif stage == "coloring":
            adjust = [key for key in KEYS if key.startswith("lut_") and KEYS[key]["field"].get("tab") == "adjust"]
            if not str(get("lut_path") or "").strip() and all(not get(key) for key in adjust):
                warnings.append("Coloring has no LUT and no adjustments: it has no effect.")
        if max(width, height) > 32768:
            problems.append(f"{title} makes the picture larger than 32768 px.")
    width, height = int(round(width)), int(round(height))
    if kind == "video":
        codec = str(get("codec", "H.264"))
        if hdr and not get("hdr_mode"):
            problems.append("The output is HDR: turn on “Preserve / Export 10-bit HDR” in Export.")
        if hdr and codec.startswith("H.264"):
            problems.append("HDR needs H.265, AV1, ProRes or FFV1 (H.264 is 8-bit only).")
        if (width % 2 or height % 2) and not codec.startswith("FFV1"):
            problems.append(f"Video export needs even dimensions ({width}×{height}).")
        if codec.startswith("H.264") and max(width, height) > 4096:
            warnings.append(f"{width}×{height} is larger than H.264 hardware encoding allows (4096 px). "
                            "Use H.265 or AV1.")
        elif codec.startswith(("H.265", "AV1")) and max(width, height) > 8192:
            warnings.append(f"{width}×{height} is larger than NVENC allows (8192 px).")
    return {"width": width, "height": height, "fps": round(fps, 3) if kind == "video" else 0.0, "hdr": hdr,
            "stages": active_stages(settings, kind), "problems": problems, "warnings": warnings}


def validate(settings: dict, kind: str) -> list[str]:
    """Problems that make Visual Enhancer reject the settings regardless of the file."""
    problems = []
    enabled = set(settings.get(f"{kind}_enabled_stages") or []) | set(settings.get(f"vz_{kind}_ai") or [])
    if not enabled:
        problems.append("Turn on at least one stage.")
    if {"dlss_super_resolution", "dlss_ray_reconstruction"} <= enabled:
        problems.append("DLSS Super Resolution and DLSS Ray Reconstruction can't run together. Turn one off.")
    if len(enabled & {"frame_generation", "fsr_frame_generation", "vfx_frame_generation", "rife"}) > 1:
        problems.append("Only one frame-generation card can be on.")
    if kind == "video":
        codec = str(settings.get("codec", "H.264"))
        if codec not in CODECS:
            problems.append(f"Unknown codec “{codec}”.")
        elif str(settings.get("container", "MP4")) not in containers_for(codec):
            problems.append(f"{codec} can't be saved as {settings.get('container')}. "
                            f"Use {' or '.join(containers_for(codec))}.")
        if settings.get("hdr_mode") and codec.startswith("H.264"):
            problems.append("10-bit HDR export needs H.265, AV1, ProRes or FFV1.")
    else:
        if int(settings.get("image_bit_depth", 8)) == 16 and settings.get("image_format") not in ("PNG", "TIFF"):
            problems.append("16-bit images need PNG or TIFF.")
    return problems


# ---------------------------------------------------------------- schema for the UI


def _with_tips(items: list[dict]) -> list[dict]:
    from .tips import FIELD_TIPS  # noqa: WPS433

    result = []
    for field in items:
        field = dict(field)
        tip = FIELD_TIPS.get(field.get("key", "")) or FIELD_TIPS.get(field.get("image_key", ""))
        if tip:
            field["tip"] = tip
        result.append(field)
    return result


EASY = [
    {"id": "realism", "label": "Realism", "type": "slider", "min": 0, "max": 100,
     "tip": "Strength of DLSS 5 neural rendering, which rebuilds skin, hair and surfaces so AI footage looks "
            "photographed. 50 is gentle, 65-70 is the Visien default, Off skips it."},
    {"id": "restore", "label": "AI Restore", "type": "segment",
     "options": [{"value": "off", "label": "Off"}, {"value": "fast", "label": "Fast"},
                 {"value": "detail", "label": "Detail"}],
     "tip": "SeedVR2 diffusion restoration before everything else: removes the soft, smeary, compressed look of "
            "AI video and restores real texture. Fast uses the 3B model, Detail the 7B. Slow; preview first."},
    {"id": "size", "label": "Output Size", "type": "segment",
     "options": [{"value": "same", "label": "Same"}, {"value": "2x", "label": "2×"},
                 {"value": "1080", "label": "1080p"}, {"value": "2160", "label": "4K"}],
     "tip": "Final resolution, made with NVIDIA RTX Super Resolution. 1080p and 4K set the short side, so "
            "portrait clips work too. Same keeps the source size."},
    {"id": "detail", "label": "Sharpness", "type": "slider", "min": 0, "max": 100,
     "tip": "Adaptive sharpening on top (AMD CAS). Keep it low, around 10-25; AI footage over-sharpens easily."},
    {"id": "grain", "label": "Film Grain", "type": "slider", "min": 0, "max": 100,
     "tip": "Fine animated grain that hides the plastic, too-clean look of AI video. 8-20 is subtle; 30 and "
            "above is clearly visible."},
    {"id": "motion", "label": "Smooth Motion", "type": "segment", "kinds": ["video"],
     "options": [{"value": "off", "label": "Off"}, {"value": "48", "label": "48 fps"},
                 {"value": "60", "label": "60 fps"}],
     "tip": "Adds in-between frames for smoother motion: RIFE when it is installed, otherwise NVIDIA frame "
            "generation. Scene cuts are detected so they don't smear."},
    {"id": "colors", "label": "Original Colors", "type": "slider", "min": 0, "max": 100,
     "tip": "Brings the source's colours back after rendering (Color Match), so product and brand colours stay "
            "true while DLSS detail and lighting stay. 60-80 keeps a little of DLSS's colour; 100 matches the "
            "source exactly. Off keeps DLSS's colours."},
    {"id": "faces", "label": "Faces", "type": "segment",
     "options": [{"value": "off", "label": "Off"}, {"value": "natural", "label": "Natural"},
                 {"value": "strong", "label": "Strong"}],
     "tip": "Restores faces that drift or melt. GFPGAN 1.4 (commercial use allowed) unless the preset uses "
            "CodeFormer (non-commercial). Natural keeps identity and avoids flicker; Strong repairs badly "
            "deformed faces."},
]


def schema() -> dict:
    from .tips import STAGE_TIPS, UI_TIPS  # noqa: WPS433

    stages_ = []
    for stage in STAGES:
        stage = dict(stage)
        stage["tip"] = STAGE_TIPS.get(stage["id"], stage.get("about", ""))
        stage["fields"] = _with_tips(stage["fields"])
        stages_.append(stage)
    return {"stages": stages_, "export": _with_tips(EXPORT), "orders": ORDERS, "vz_orders": VZ_ORDERS,
            "ai_ids": AI_IDS, "defaults": defaults(),
            "containers": {codec: containers_for(codec) for codec in CODECS},
            "hdr_codecs": [c for c in CODECS if not c.startswith("H.264")],
            "fsr_codecs": [c for c in CODECS if c.startswith(("H.264", "H.265", "AV1"))],
            "dlss_factors": DLSS_FACTORS, "easy": EASY, "ui_tips": UI_TIPS,
            "export_tip": STAGE_TIPS["export"]}


# ---------------------------------------------------------------- Visual Enhancer config.ini


def from_ve_config(text: str) -> dict:
    """Settings from Visual Enhancer's own config.ini ([Settings] key = value)."""
    import json  # noqa: WPS433

    raw: dict[str, Any] = {}
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            continue
        if section != "Settings" or " = " not in line and not stripped.endswith(" ="):
            continue
        key, _, value = line.partition(" = ") if " = " in line else (stripped[:-2], "", "")
        key = key.strip()
        if key.endswith("_stages") or key.endswith("_stage_order"):
            try:
                raw[key] = json.loads(value)
            except ValueError:
                continue
        else:
            raw[key] = value
    return normalize(raw)
