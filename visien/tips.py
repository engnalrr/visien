"""Short English help shown when hovering a control (keyed by settings key / stage id / UI id)."""

STAGE_TIPS = {
    "neural_model": "DLSS 5 neural rendering. Rebuilds skin, hair, fabric and surface detail so AI footage looks "
                    "photographed instead of generated. Keeps size and frame rate.",
    "scale_method": "Classic resize without AI (Spline, Lanczos …). Useful to bring a big source down before AI stages.",
    "dlss_super_resolution": "NVIDIA DLSS upscaling. DLAA keeps the size and only cleans edges and fine detail.",
    "dlss_ray_reconstruction": "DLSS denoise and reconstruction at the same size. Cannot run together with DLSS "
                               "Super Resolution.",
    "super_resolution": "NVIDIA RTX Video Super Resolution: fast, clean upscaling with artifact removal.",
    "rtx_video_hdr": "Converts SDR to HDR10. Everything after it works in HDR; export needs 10-bit HDR.",
    "frame_generation": "DLSS frame generation: adds in-between frames for smoother motion (RTX 40/50).",
    "fsr_frame_generation": "AMD FSR frame generation: in-between frames on most DirectX 12 GPUs.",
    "reshade": "Runs a ReShade .ini preset on every frame. Without a preset it changes nothing.",
    "coloring": "Light and colour adjustments or a .cube LUT. Small negative saturation and highlights often "
                "make AI footage look less synthetic.",
    "cas_sharpening": "Adaptive sharpening (AMD CAS or NVIDIA NIS). Keep it low; AI footage over-sharpens easily.",
    "grain": "Adds film grain. A little grain hides the waxy, too-clean look of AI video.",
    "vfx_vsr": "NVIDIA VFX super resolution, denoise and deblur modes.",
    "vfx_upscale": "Fast lightweight NVIDIA upscaler with built-in sharpening.",
    "vfx_frame_generation": "NVIDIA VFX frame generation with automatic scene-cut detection (RTX 40/50).",
    "seedvr2": "SeedVR2 (ByteDance) one-step diffusion restoration. Removes the soft, compressed look of AI "
               "video and restores real texture. Heavy: best on short clips.",
    "rife": "RIFE 4.x frame interpolation: smooth motion or slow motion on any NVIDIA GPU, with scene-cut "
            "protection.",
    "face_restore": "Restores faces frame by frame (CodeFormer or GFPGAN). Use moderate strength on video to "
                    "avoid flicker. CodeFormer is licensed for non-commercial use only.",
    "color_match": "Pulls the source's colours back after rendering, so products, brands and skin keep their real "
                   "colour. Only broad colour is corrected; DLSS detail and lighting stay.",
    "export": "Codec, container and quality of the final file, plus a comparison copy and multi-shot handling.",
}

FIELD_TIPS = {
    # Neural rendering
    "nr_style": "Rendering look. Style 0 is the most natural; 1 and 2 are stronger, more stylised looks.",
    "nr_intensity": "How strongly neural rendering rebuilds detail. 1.0 is neutral; above 1.3 can look painted.",
    "nr_passes": "Runs neural rendering again on its own result. More passes add detail and time; 1 is usually "
                 "enough.",
    "local_tone_strength": "Local contrast and tonal shaping. Lower it if faces look too HDR or contrasty.",
    "local_structure_strength": "Micro-structure such as pores, threads and stone. Lower it if textures look "
                                "crunchy.",
    "automatic_mask": "Finds skin automatically and treats it separately from the rest of the picture.",
    "skin_structure_strength": "Detail strength on skin when Automatic Mask is on. Lower for softer, younger skin.",
    "nr_optical_flow_quality": "Motion analysis quality between frames. High is steadier; Low is faster.",
    # Scaling
    "video_scaling_filter": "Resize algorithm. Spline36 and Lanczos are sharp; Area is best for shrinking.",
    "upscaling_factor": "New size as a percentage of the current size.",
    # DLSS SR / RR
    "upscale_dlss_mode": "DLSS scale. DLAA keeps the size (anti-aliasing only); Quality is 1.5×, Performance 2×, "
                         "Ultra Performance 3×.",
    "upscale_dlss_preset": "DLSS model preset. Default lets DLSS choose; J, K, L and M are alternative models.",
    "upscale_optical_flow_quality": "Motion analysis used by DLSS. High is steadier; Low is faster.",
    "rr_optical_flow_quality": "Motion analysis used by Ray Reconstruction. High is steadier; Low is faster.",
    # RTX SR
    "upscale_vsr_quality": "RTX Video quality level. 4 - Ultra gives the cleanest result.",
    "upscale_size_mode": "Upscale by a factor, or to an exact width and height.",
    "upscale_scale_factor": "Upscale factor. 2× turns 1080p into 4K.",
    "upscale_width": "Output width in pixels.",
    "upscale_height": "Output height in pixels (follows the width while Lock Aspect Ratio is on).",
    "upscale_aspect_lock": "Keeps the source proportions when you type a width.",
    # RTX HDR
    "upscale_hdr_contrast": "HDR contrast. 100 is neutral.",
    "upscale_hdr_saturation": "HDR colour saturation. 100 is neutral.",
    "upscale_hdr_middle_gray": "Mid-tone brightness of the HDR result.",
    "upscale_hdr_peak_luminance": "Brightest highlights in nits. Match your display (1000 is common).",
    "upscale_hdr_precision": "Internal HDR format. FP16 is more precise and uses more memory.",
    # Frame generation (DLSS / FSR / VFX)
    "frame_interpolation_frame_rate_mode": "Multiply the frame rate, or aim for a fixed frame rate.",
    "frame_interpolation_multiplier": "How many frames per source frame (2× turns 24 into 48 fps).",
    "frame_interpolation_target_fps": "Frame rate of the result. Must be higher than the source.",
    "frame_interpolation_optical_flow_quality": "Motion analysis quality. High gives fewer warping artifacts.",
    "fsr_frame_generation_frame_rate_mode": "Multiply the frame rate, or aim for a fixed frame rate.",
    "fsr_frame_generation_multiplier": "How many frames per source frame.",
    "fsr_frame_generation_target_fps": "Frame rate of the result. Must be higher than the source.",
    "vfx_frame_generation_model": "Interpolation model size. High is the most accurate and the slowest.",
    "vfx_frame_rate_mode": "Multiply the frame rate, or aim for a fixed frame rate.",
    "vfx_frame_multiplier": "How many frames per source frame.",
    "vfx_target_fps": "Frame rate of the result, for example 60. Must be higher than the source.",
    "vfx_automatic_shot_detection": "Does not blend frames across cuts, so edits stay clean.",
    # ReShade
    "reshade_preset_path": "ReShade preset (.ini) to apply.",
    "reshade_mix": "How much of the ReShade result is blended over the picture.",
    "reshade_depth_mode": "Depth for depth-based effects. Auto generates AI depth only when the preset needs it.",
    "reshade_temporal_stability": "Stabilises generated depth between frames to avoid flicker.",
    "reshade_temporal_strength": "How strongly depth is smoothed over time.",
    "reshade_depth_resolution": "Detail of the generated depth map. Higher is sharper and slower.",
    "reshade_precision_policy": "Bit depth used for effects. Auto is right for most presets.",
    "reshade_hdr_policy": "How SDR presets are applied to HDR pictures.",
    "reshade_preserve_alpha": "Keeps transparency of images that have it.",
    "reshade_shader_search_paths": "Extra folder with .fx shaders the preset needs.",
    "reshade_texture_search_paths": "Extra folder with textures and LUTs the preset needs.",
    # Coloring
    "lut_path": "3D LUT file (.cube) for a colour grade.",
    "lut_resolution": "Internal LUT precision. 33 is enough for most grades.",
    "lut_mix": "How strongly the LUT is applied.",
    "lut_exposure": "Overall brightness in stops.",
    "lut_contrast": "Contrast. Small negative values make AI footage look less clipped.",
    "lut_highlights": "Brightness of bright areas. Lower it to recover blown highlights.",
    "lut_shadows": "Brightness of dark areas.",
    "lut_whites": "White point.",
    "lut_blacks": "Black point.",
    "lut_midtones": "Mid-tone brightness.",
    "lut_temperature": "Warmer (positive) or cooler (negative) colour.",
    "lut_tint": "Green (negative) or magenta (positive) tint.",
    "lut_hue": "Rotates all colours.",
    "lut_vibrance": "Saturation of the less saturated colours; protects skin tones.",
    "lut_saturation": "Saturation of all colours. AI video is often oversaturated; try -5.",
    # Sharpening
    "sharpening_method": "AMD CAS is adaptive and gentle; NVIDIA NIS is crisper.",
    "cas_sharpness": "Sharpening amount. 0 turns it off.",
    # Grain
    "grain_amount": "Grain strength. 8 to 15 is subtle on 4K.",
    "grain_size": "Grain particle size. Larger looks like film stock; smaller like a digital sensor.",
    "grain_color": "Colour variation in the grain. 0 is monochrome grain.",
    "grain_response": "How much more grain appears in mid-tones than in highlights and shadows.",
    "grain_seed": "Random pattern number. Change it to get a different grain pattern.",
    "grain_animated": "New grain on every frame, like real film. Off gives a static pattern.",
    # VFX
    "vfx_vsr_mode": "Upscale, denoise, deblur or high-bitrate mode and its strength level.",
    "vfx_vsr_strength": "How strongly the effect is applied.",
    "vfx_size_mode": "Upscale by a factor, or to an exact size.",
    "vfx_scale_factor": "Upscale factor.",
    "vfx_width": "Output width in pixels.",
    "vfx_height": "Output height in pixels.",
    "vfx_aspect_lock": "Keeps the source proportions.",
    "vfx_upscale_scale": "Upscale factor.",
    "vfx_upscale_strength": "Built-in sharpening of the lightweight upscaler.",
    # Export
    "codec": "Video codec. H.265 is the best general choice; ProRes and FFV1 are for editing and archiving.",
    "container": "File type (MP4, MKV or MOV). MP4 plays everywhere.",
    "quality": "Encoder quality. Best is visually lossless; Max makes very large files.",
    "hdr_mode": "Keeps or creates 10-bit HDR. Needs H.265, AV1, ProRes or FFV1.",
    "image_format": "Image file type. PNG and TIFF are lossless.",
    "image_bit_depth": "16-bit keeps more gradation for grading (PNG and TIFF only).",
    "image_quality": "Compression quality for JPEG, WebP and AVIF.",
    # SeedVR2
    "seedvr2_model": "3B is faster and fits 12-16 GB GPUs; 7B is more detailed and needs more memory and time.",
    "seedvr2_size_mode": "At least: small clips go up to the short side below, bigger ones keep their size. Short "
                         "side: always that size. Scale: a factor of the current size.",
    "seedvr2_scale": "1× restores without resizing; 2× also upscales.",
    "seedvr2_short_side": "Height of a landscape picture (width of a portrait one) after restoring.",
    "seedvr2_batch": "Frames restored together. More frames give steadier texture but need much more GPU memory; "
                     "keep 5 on 16 GB cards.",
    "seedvr2_overlap": "Frames shared by neighbouring windows and blended, so texture does not jump every few "
                       "frames. 2 is smooth; Off is about a third faster.",
    "seedvr2_color": "Keeps the original colours after restoring. LAB is the most natural.",
    "seedvr2_input_noise": "Adds noise before restoring so the model invents more detail. 0 keeps it faithful.",
    "seedvr2_latent_noise": "Variation inside the model. Small values add natural texture; high values drift.",
    "seedvr2_blend": "Mix of the restored result over the input. Lower it if the result looks too sharp.",
    "seedvr2_seed": "Random seed. Change it to get a slightly different result.",
    "seedvr2_blocks_to_swap": "Moves model blocks to system RAM to save GPU memory. Slower; raise it if you run "
                              "out of memory.",
    "seedvr2_vae_tiling": "Processes big frames in tiles to save memory. Keep on for 1440p and above.",
    # RIFE
    "rife_model": "RIFE version. 4.26 is the most accurate; 4.9 is faster.",
    "rife_mode": "Multiply the frame rate, or aim for a fixed frame rate.",
    "rife_multiplier": "How many frames per source frame (2× turns 24 into 48 fps).",
    "rife_target_fps": "Frame rate of the result, for example 60.",
    "rife_scene_detect": "Does not blend frames across cuts; repeats the frame instead.",
    "rife_scene_threshold": "How different two frames must be to count as a cut. Lower finds more cuts.",
    "rife_scale": "Motion analysis resolution. Half is faster and steadier on 4K.",
    # Face restore
    "face_model": "CodeFormer looks more natural (non-commercial licence). GFPGAN is allowed for commercial work.",
    "face_fidelity": "CodeFormer only. Higher keeps the original identity; lower invents more detail.",
    "face_blend": "How much of the restored face is used. 40-70% keeps video natural and steady.",
    "face_which": "Restore every face, or only the biggest one.",
    "face_min_size": "Ignores faces smaller than this share of the picture height.",
    "face_smoothing": "Steadies face tracking between frames to prevent shimmer.",
    # Color Match
    "color_match_strength": "How much of the source's hue and saturation comes back. 100 matches the source "
                            "exactly; 60-80 keeps a little of DLSS's colour.",
    "color_match_brightness": "How much of the source's overall brightness and contrast comes back. Keep it at 0 to "
                              "keep DLSS's lighting; raise it if the result got darker or brighter.",
    "color_match_scale": "Size of the areas compared. Broad corrects whole regions; Fine also small objects such "
                         "as labels and logos (can undo some of DLSS's local colour).",
    # Export extras
    "vz_compare": "Also writes <name>_compare next to the result: the source and the result in one labelled "
                  "video or image, frame-accurate.",
    "vz_compare_before": "Label on the source half.",
    "vz_compare_after": "Label on the result half, for example NEURAL ENHANCED, VISIEN or the client's name.",
    "vz_compare_size": "Fit 1080p keeps the comparison easy to share (each half up to 1920 px). Full size uses the "
                       "result's resolution.",
    "vz_shot_warmup": "Fixes the first frames of every shot looking unprocessed: DLSS and SeedVR2 need a few frames "
                      "to settle after a cut, so Visien gives each shot a short mirrored run-up and cuts it out "
                      "afterwards.",
}

UI_TIPS = {
    "kind": "Video and image pipelines are set up separately. Both are saved in the same preset.",
    "preset": "Ready-made settings. Your own presets are listed below the built-in ones.",
    "engine": "Visual Enhancer engine and the graphics card in use. Click for settings.",
    "settings": "Engine, GPU, output folder, previews and AI models.",
    "add": "Add videos or images. Files stay where they are.",
    "folder": "Add every video and image in a folder.",
    "render_all": "Tick to render every file in the list.",
    "remove": "Remove the ticked files from the list (files on disk are not touched).",
    "split": "Before and after with a draggable divider (1).",
    "side": "Before and after next to each other (2).",
    "stack": "Before on top, after below (5).",
    "source": "Original only (3).",
    "output": "Visien result only (4).",
    "lossless": "Shows exact lossless frames instead of the playback copies, for pixel-level checks (L).",
    "fit": "Fit the picture to the viewer (F).",
    "zoom100": "Actual pixels, 1:1 (Z).",
    "play": "Play or pause the preview (Space).",
    "prev": "Previous frame (←). Shift+← jumps 10 frames.",
    "next": "Next frame (→). Shift+→ jumps 10 frames.",
    "preview": "Renders a short excerpt from the playhead with the current settings (P).",
    "preview_length": "Length of the preview excerpt.",
    "preview_again": "Renders the preview again even if a cached one exists.",
    "open_output": "Opens the output folder.",
    "render": "Adds the ticked files (or the selected one) to the queue and starts rendering (Ctrl+Enter).",
    "queue_start": "Starts or pauses the queue.",
    "queue_stop": "Stops the current render and pauses the queue.",
    "queue_clear": "Removes finished, failed and cancelled items from the list.",
    "queue_log": "Shows the processing log.",
    "collapse": "Collapses or expands all cards.",
    "mode_easy": "A few simple controls for the current preset.",
    "mode_advanced": "Every stage and setting.",
    "card_switch": "Turns this stage on or off.",
    "card_up": "Runs this stage earlier.",
    "card_down": "Runs this stage later.",
    "card_toggle": "Shows or hides the settings of this stage.",
    "reset": "Back to the default value.",
}
