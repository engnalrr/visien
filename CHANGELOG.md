# Changelog

## 1.3.1
- Fixed: RIFE, SeedVR2, Face Restore and Color Match failed with "OSError: [Errno 22] Invalid argument" in 1.3.0
  (the lossless hand-off files were tagged with a colour-space name ffmpeg's encoder does not accept).
- Clean Shot Starts now also works with RGB sources (FFV1, PNG or QuickTime Animation video).
- When ffmpeg stops while an AI stage writes its result, the error now shows ffmpeg's own message.

## 1.3.0
- **Color Match** card (Easy: *Original Colors*): brings the source's hue, saturation and, optionally, brightness back
  after rendering while keeping the detail and lighting DLSS adds. New presets *Product · True Color* and
  *Realism · Natural Colors*.
- **Clean Shot Starts** (Export, on by default): the first frames of every shot in multi-shot videos no longer look
  unprocessed. Each shot gets a mirrored warm-up that is removed before the export.
- **Comparison copy** (Export): `<name>_compare.mp4` / `.png` with the source and the result, top/bottom or side by
  side, with editable labels (RAW / NEURAL ENHANCED).
- Viewer: *Top / bottom* compare mode (key 5).
- Lossless hand-off files now carry colour tags, so Visual Enhancer reads them exactly like the source (an untagged
  file rendered slightly darker).
- Settings › Updates: checks GitHub for a newer version.

## 1.2.0
- AMD Radeon RX 7000/9000 and Ryzen AI Max: the AI cards run with AMD's ROCm build of PyTorch, which Visien installs
  for the detected card; Visual Enhancer cards are skipped on PCs without an NVIDIA RTX GPU.
- AMD AMF hardware encoding for exports and playback copies.
- The app window opens after extracting a downloaded zip (Windows' download mark is removed from its libraries).
- Fixed a false "non-English characters" warning on Turkish Windows.

## 1.1.0
- SeedVR2 (ByteDance) restoration, RIFE 4.26 interpolation, GFPGAN 1.4 and CodeFormer face restoration.
- Realism presets, Easy mode, hover help on every control, full offline package, Share Visien.

## 1.0.0
- First release: Visual Enhancer pipeline with presets, previews, compare viewer and render queue.
