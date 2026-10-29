"""Color Match: brings the source's colours back after rendering without undoing DLSS detail.

Only the low-frequency part of the picture is corrected. Both the result and the source are reduced to a small,
blurred version (a few hundred pixels across) and compared in CIELAB; the difference is scaled up again and added
to the result. Fine texture, sharp edges and local contrast (what DLSS and SeedVR2 add) stay untouched, while a
shifted hue, a changed saturation or a different overall brightness is pulled back toward the source:

    Original Colors      share of the a/b (hue and saturation) difference that is corrected
    Original Brightness  share of the L (lightness) difference; 0 keeps DLSS's lighting
    Precision            size of the comparison grid: Broad (whole areas) to Fine (small objects such as labels)

Where a source colour cannot exist at the result's lightness (DLSS often renders a yellow logo darker, and a dark
saturated yellow clips to orange), the source's lightness is brought back only there, so brand colours keep their hue.

Runs on the GPU with PyTorch when one is available, otherwise on the CPU with NumPy and OpenCV.
"""

from __future__ import annotations

import subprocess
import warnings
from fractions import Fraction

import numpy as np

# frames arrive as read-only buffers from ffmpeg; PyTorch only reads them
warnings.filterwarnings("ignore", message="The given NumPy array is not writable")

from . import common

GRID = {"broad": 96, "balanced": 192, "fine": 384}  # long side of the comparison grid in pixels
SIGMA = 1.6  # blur of the grid, in grid pixels


def _grid_size(width: int, height: int, scale: str) -> tuple[int, int]:
    long_side = GRID.get(scale, GRID["balanced"])
    factor = long_side / max(width, height)
    return max(8, int(round(width * factor))), max(8, int(round(height * factor)))


class _Reference:
    """The source video at the result's frame rate, already reduced to the comparison grid (RGB, 8-bit)."""

    def __init__(self, ffmpeg: str, path: str, size: tuple[int, int], fps: Fraction | None, matrix: str):
        self.width, self.height = size
        self.frame_bytes = self.width * self.height * 3
        scale = f"scale={self.width}:{self.height}:flags=area"
        if matrix:
            scale += f":in_color_matrix={matrix}"
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", path, "-map", "0:v:0"]
        if fps:
            cmd += ["-fps_mode", "cfr", "-r", f"{fps.numerator}/{fps.denominator}"]
        cmd += ["-vf", scale, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     creationflags=common.NO_WINDOW)
        self.last: np.ndarray | None = None

    def read(self) -> np.ndarray | None:
        data = self.proc.stdout.read(self.frame_bytes)
        if data and len(data) == self.frame_bytes:
            self.last = np.frombuffer(data, np.uint8).reshape(self.height, self.width, 3)
        return self.last  # the source can end a frame early (rounding); keep using its last frame

    def close(self) -> None:
        try:
            self.proc.stdout.close()
        except OSError:
            pass
        self.proc.kill()
        self.proc.wait()


class _DeepReader:
    """16-bit RGB frames of the result, so a 10-bit picture keeps its precision through Color Match."""

    def __init__(self, ffmpeg: str, path: str, info: dict):
        self.width, self.height = info["width"], info["height"]
        self.frame_bytes = self.width * self.height * 6
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", path, "-map", "0:v:0",
               "-fps_mode", "cfr", "-r", f"{info['fps'].numerator}/{info['fps'].denominator}"]
        if info.get("matrix"):
            cmd += ["-vf", f"scale=in_color_matrix={info['matrix']}:flags=bicubic+accurate_rnd+full_chroma_int"]
        cmd += ["-f", "rawvideo", "-pix_fmt", "rgb48le", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     creationflags=common.NO_WINDOW)

    def read(self) -> np.ndarray | None:
        data = self.proc.stdout.read(self.frame_bytes)
        if not data or len(data) < self.frame_bytes:
            return None
        return np.frombuffer(data, "<u2").reshape(self.height, self.width, 3)

    def close(self) -> None:
        try:
            self.proc.stdout.close()
        except OSError:
            pass
        self.proc.kill()
        self.proc.wait()


class _DeepWriter:
    """Lossless 16-bit planar RGB FFV1 from rgb48 frames."""

    def __init__(self, ffmpeg: str, path: str, width: int, height: int, fps: Fraction):
        self.proc = subprocess.Popen([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                                      "-f", "rawvideo", "-pix_fmt", "rgb48le", "-s", f"{width}x{height}",
                                      "-r", f"{fps.numerator}/{fps.denominator}", "-i", "-",
                                      "-vf", common.RGB_TAGS, "-c:v", "ffv1", "-level", "3", "-g", "1",
                                      "-pix_fmt", "gbrp16le", *common.RGB_TAG_ARGS, path],
                                     stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=common.NO_WINDOW)

    def write(self, frame: np.ndarray) -> None:
        common.pipe_write(self.proc, np.ascontiguousarray(frame, dtype="<u2").tobytes())

    def close(self) -> None:
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace")
        if self.proc.wait() != 0:
            raise RuntimeError("ffmpeg could not write the result: " + err[-400:])


# ---------------------------------------------------------------- the correction


class Matcher:
    def __init__(self, params: dict, size: tuple[int, int], grid: tuple[int, int]):
        self.color = max(0.0, min(1.0, float(params.get("color_match_strength", 80)) / 100.0))
        self.light = max(0.0, min(1.0, float(params.get("color_match_brightness", 0)) / 100.0))
        self.width, self.height = size
        self.grid = grid
        self.torch = None
        try:
            import torch  # noqa: WPS433

            if torch.cuda.is_available():
                self.torch = torch
                self.device = torch.device("cuda")
                self._kernel = self._gauss_kernel()
        except Exception:  # noqa: BLE001 - CPU path below
            self.torch = None
        self.device_name = "cuda" if self.torch is not None else "cpu"

    # -- GPU (PyTorch) --------------------------------------------------------

    def _gauss_kernel(self):
        torch = self.torch
        radius = int(SIGMA * 3 + 0.5)
        x = torch.arange(-radius, radius + 1, dtype=torch.float32, device=self.device)
        k = torch.exp(-(x ** 2) / (2 * SIGMA ** 2))
        return k / k.sum()

    def _blur(self, t):
        """Separable Gaussian blur of a (3, h, w) tensor with reflected borders."""
        torch = self.torch
        F = torch.nn.functional  # noqa: N806
        k = self._kernel
        pad = k.numel() // 2
        x = t.unsqueeze(0)
        x = F.pad(x, (pad, pad, 0, 0), mode="reflect")
        x = F.conv2d(x, k.view(1, 1, 1, -1).expand(3, 1, 1, -1), groups=3)
        x = F.pad(x, (0, 0, pad, pad), mode="reflect")
        x = F.conv2d(x, k.view(1, 1, -1, 1).expand(3, 1, -1, 1), groups=3)
        return x[0]

    # -- colour maths, shared by the GPU (torch) and CPU (numpy) paths ---------

    @staticmethod
    def _to_lab(rgb, xp):
        """sRGB (3, h, w) in 0..1 -> CIELAB (D65)."""
        lin = xp.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        r, g, b = lin[0], lin[1], lin[2]
        x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
        y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
        z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883
        eps, kappa = 216 / 24389, 24389 / 27

        def f(t):
            return xp.where(t > eps, xp.clip(t, 1e-12, None) ** (1 / 3), (kappa * t + 16) / 116)

        fx, fy, fz = f(x), f(y), f(z)
        return xp.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)])

    @staticmethod
    def _to_linear(light, a, b, xp):
        """CIELAB -> linear sRGB (3, h, w), not clipped, so colours outside sRGB can be detected."""
        fy = (light + 16) / 116
        fx = fy + a / 500
        fz = fy - b / 200
        eps, kappa = 216 / 24389, 24389 / 27

        def finv(t):
            t3 = t ** 3
            return xp.where(t3 > eps, t3, (116 * t - 16) / kappa)

        x = finv(fx) * 0.95047
        y = xp.where(light > kappa * eps, fy ** 3, light / kappa)
        z = finv(fz) * 1.08883
        return xp.stack([3.2404542 * x - 1.5371385 * y - 0.4985314 * z,
                         -0.9692660 * x + 1.8760108 * y + 0.0415560 * z,
                         0.0556434 * x - 0.2040259 * y + 1.0572252 * z])

    @staticmethod
    def _encode(lin, xp):
        lin = xp.clip(lin, 0.0, 1.0)
        return xp.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)

    def _fits(self, light, a, b, xp):
        lin = self._to_linear(light, a, b, xp)
        return ((lin >= -1e-3) & (lin <= 1 + 1e-3)).all(0)

    def _combine(self, lab, delta, xp):
        """Adds the corrected colour to the result and keeps it displayable.

        A colour from the source does not always exist at the result's lightness: DLSS often renders a yellow logo
        darker, and a bright saturated yellow cannot be dark (sRGB clips it to orange or brown). Where the corrected
        colour falls outside sRGB, the source's lightness is brought back only as far as needed (found per pixel by
        bisection, so there are no steps); if even full lightness is not enough, saturation is reduced while the
        hue is kept. Everywhere else DLSS's lighting stays as set by Original Brightness.
        """
        base, dl = lab[0], delta[0]
        ab = lab[1:] + delta[1:] * self.color
        lo = xp.full_like(base, self.light)
        light = base + dl * lo
        ok = self._fits(light, ab[0], ab[1], xp)
        if not bool(ok.all()):
            hi = xp.ones_like(base)
            reachable = self._fits(base + dl, ab[0], ab[1], xp)
            t_lo, t_hi = lo.clone() if xp is not np else lo.copy(), hi
            for _ in range(7):
                mid = (t_lo + t_hi) / 2
                fits = self._fits(base + dl * mid, ab[0], ab[1], xp)
                t_hi = xp.where(fits, mid, t_hi)
                t_lo = xp.where(fits, t_lo, mid)
            t = xp.where(ok, lo, xp.where(reachable, t_hi, hi))
            light = base + dl * t
            scale = xp.ones_like(base)
            if not bool(reachable.all()):
                s_lo, s_hi = xp.zeros_like(base), xp.ones_like(base)
                for _ in range(7):
                    mid = (s_lo + s_hi) / 2
                    fits = self._fits(light, ab[0] * mid, ab[1] * mid, xp)
                    s_lo = xp.where(fits, mid, s_lo)
                    s_hi = xp.where(fits, s_hi, mid)
                scale = xp.where(ok | reachable, scale, s_lo)
            ab = ab * scale
        return self._encode(self._to_linear(light, ab[0], ab[1], xp), xp)

    # -- GPU (PyTorch) --------------------------------------------------------

    def _gauss_kernel(self):
        torch = self.torch
        radius = int(SIGMA * 3 + 0.5)
        x = torch.arange(-radius, radius + 1, dtype=torch.float32, device=self.device)
        k = torch.exp(-(x ** 2) / (2 * SIGMA ** 2))
        return k / k.sum()

    def _blur(self, t):
        """Separable Gaussian blur of a (3, h, w) tensor with reflected borders."""
        torch = self.torch
        F = torch.nn.functional  # noqa: N806
        k = self._kernel
        pad = k.numel() // 2
        x = t.unsqueeze(0)
        x = F.pad(x, (pad, pad, 0, 0), mode="reflect")
        x = F.conv2d(x, k.view(1, 1, 1, -1).expand(3, 1, 1, -1), groups=3)
        x = F.pad(x, (0, 0, pad, pad), mode="reflect")
        x = F.conv2d(x, k.view(1, 1, -1, 1).expand(3, 1, -1, 1), groups=3)
        return x[0]

    # -- colour maths, shared by the GPU (torch) and CPU (numpy) paths ---------

    @staticmethod
    def _to_lab(rgb, xp):
        """sRGB (3, h, w) in 0..1 -> CIELAB (D65)."""
        lin = xp.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        r, g, b = lin[0], lin[1], lin[2]
        x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
        y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
        z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883
        eps, kappa = 216 / 24389, 24389 / 27

        def f(t):
            return xp.where(t > eps, xp.clip(t, 1e-12, None) ** (1 / 3), (kappa * t + 16) / 116)

        fx, fy, fz = f(x), f(y), f(z)
        return xp.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)])

    @staticmethod
    def _to_linear(light, a, b, xp):
        """CIELAB -> linear sRGB (3, h, w), not clipped, so colours outside sRGB can be detected."""
        fy = (light + 16) / 116
        fx = fy + a / 500
        fz = fy - b / 200
        eps, kappa = 216 / 24389, 24389 / 27

        def finv(t):
            t3 = t ** 3
            return xp.where(t3 > eps, t3, (116 * t - 16) / kappa)

        x = finv(fx) * 0.95047
        y = xp.where(light > kappa * eps, fy ** 3, light / kappa)
        z = finv(fz) * 1.08883
        return xp.stack([3.2404542 * x - 1.5371385 * y - 0.4985314 * z,
                         -0.9692660 * x + 1.8760108 * y + 0.0415560 * z,
                         0.0556434 * x - 0.2040259 * y + 1.0572252 * z])

    @staticmethod
    def _encode(lin, xp):
        lin = xp.clip(lin, 0.0, 1.0)
        return xp.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)

    def _combine(self, lab, delta, xp):
        """Adds the corrected colour to the result and keeps it displayable.

        A colour from the source does not always exist at the result's lightness: DLSS often renders a yellow logo
        darker, and a bright saturated yellow cannot be dark (sRGB clips it to orange or brown). Where the corrected
        colour falls outside sRGB, the source's lightness is brought back step by step, only as far as needed;
        if even that is not enough, saturation is reduced while the hue is kept. Everywhere else DLSS's lighting
        stays as set by Original Brightness.
        """
        tol = 1e-3
        light0, ab = lab[0], lab[1:] + delta[1:] * self.color
        steps = [self.light + (1.0 - self.light) * k / 4 for k in range(5)]
        final_l = light0 + delta[0] * steps[-1]
        settled = None
        for t in steps:
            candidate = light0 + delta[0] * t
            lin = self._to_linear(candidate, ab[0], ab[1], xp)
            fits = ((lin >= -tol) & (lin <= 1 + tol)).all(0)
            new = fits if settled is None else fits & ~settled
            final_l = xp.where(new, candidate, final_l)
            settled = fits if settled is None else settled | fits
            if bool(settled.all()):
                break
        scale = xp.ones_like(final_l)
        if not bool(settled.all()):
            for s in (0.9, 0.8, 0.7, 0.6, 0.5, 0.4):
                lin = self._to_linear(final_l, ab[0] * s, ab[1] * s, xp)
                fits = ((lin >= -tol) & (lin <= 1 + tol)).all(0)
                new = fits & ~settled
                scale = xp.where(new, s, scale)
                settled = settled | fits
                if bool(settled.all()):
                    break
            scale = xp.where(settled, scale, 0.4)
        return self._encode(self._to_linear(final_l, ab[0] * scale, ab[1] * scale, xp), xp)

    # -- GPU (PyTorch) --------------------------------------------------------

    def _apply_torch(self, frame: np.ndarray, ref_small: np.ndarray, peak: float) -> np.ndarray:
        torch = self.torch
        F = torch.nn.functional  # noqa: N806
        with torch.inference_mode():
            src = torch.from_numpy(frame.astype(np.float32) if frame.dtype != np.uint8 else frame).to(self.device)
            out = src.permute(2, 0, 1).float() / peak
            ref = torch.from_numpy(ref_small).to(self.device).permute(2, 0, 1).float() / 255.0
            gw, gh = self.grid
            small = F.interpolate(out.unsqueeze(0), size=(gh, gw), mode="area")[0]
            delta = self._blur(self._to_lab(ref, torch)) - self._blur(self._to_lab(small, torch))
            delta = F.interpolate(delta.unsqueeze(0), size=(self.height, self.width), mode="bicubic",
                                  align_corners=False)[0]
            rgb = self._combine(self._to_lab(out, torch), delta, torch)
            result = (rgb * peak).round().clamp(0, peak).permute(1, 2, 0)
            dtype = torch.uint8 if peak == 255 else torch.int32
            return result.to(dtype).cpu().numpy().astype(frame.dtype)

    # -- CPU (NumPy / OpenCV) -------------------------------------------------

    def _apply_cpu(self, frame: np.ndarray, ref_small: np.ndarray, peak: float) -> np.ndarray:
        import cv2  # noqa: WPS433

        out = frame.astype(np.float32) / peak
        gw, gh = self.grid
        small = cv2.resize(out, (gw, gh), interpolation=cv2.INTER_AREA)
        ref = ref_small.astype(np.float32) / 255.0

        def blur(image):
            return np.stack([cv2.GaussianBlur(c, (0, 0), SIGMA, borderType=cv2.BORDER_REFLECT) for c in image])

        lab_of = lambda image: self._to_lab(np.moveaxis(image, 2, 0), np)  # noqa: E731
        delta = blur(lab_of(ref)) - blur(lab_of(small))
        delta = np.stack([cv2.resize(c, (self.width, self.height), interpolation=cv2.INTER_CUBIC) for c in delta])
        rgb = np.moveaxis(self._combine(lab_of(out), delta, np), 0, 2)
        return np.round(rgb * peak).astype(frame.dtype)

    def apply(self, frame: np.ndarray, ref_small: np.ndarray) -> np.ndarray:
        peak = 255.0 if frame.dtype == np.uint8 else 65535.0
        if self.color == 0 and self.light == 0:
            return frame
        if self.torch is not None:
            return self._apply_torch(frame, ref_small, peak)
        return self._apply_cpu(frame, ref_small, peak)


def _check_aspect(width: int, height: int, ref_width: int, ref_height: int) -> None:
    if not ref_width or not ref_height:
        common.fail("Color Match: the source could not be read.")
    if abs(width / height - ref_width / ref_height) > 0.02 * (width / height):
        common.fail(f"Color Match needs the same framing as the source ({ref_width}×{ref_height} vs "
                    f"{width}×{height}); a card before it crops or changes the aspect ratio.")


def run(args, params: dict) -> None:
    reference = str(params.get("_color_reference") or "")
    if not reference:
        common.fail("Color Match: no source to compare with.")
    common.progress(0.01, "Color Match")
    if args.kind == "image":
        import cv2  # noqa: WPS433

        frame = common.read_image(args.input)
        source = common.read_image(reference)
        h, w = frame.shape[:2]
        _check_aspect(w, h, source.shape[1], source.shape[0])
        grid = _grid_size(w, h, str(params.get("color_match_scale") or "balanced"))
        matcher = Matcher(params, (w, h), grid)
        ref_small = cv2.resize(source, grid, interpolation=cv2.INTER_AREA)
        out = matcher.apply(frame, ref_small)
        common.write_image(str(args.output), out)
        common.result(width=w, height=h, device=matcher.device_name)
        return
    info = common.probe(args.ffprobe, args.input)
    ref_info = common.probe(args.ffprobe, reference)
    width, height, total = info["width"], info["height"], info["frames"] or 0
    _check_aspect(width, height, ref_info["width"], ref_info["height"])
    grid = _grid_size(width, height, str(params.get("color_match_scale") or "balanced"))
    matcher = Matcher(params, (width, height), grid)
    common.progress(0.02, f"Color Match ({'GPU' if matcher.device_name == 'cuda' else 'CPU'})")
    frames = _DeepReader(args.ffmpeg, args.input, info)
    ref = _Reference(args.ffmpeg, reference, grid, info["fps"], ref_info.get("matrix", ""))
    writer = _DeepWriter(args.ffmpeg, str(args.output), width, height, info["fps"])
    done = 0
    try:
        while True:
            frame = frames.read()
            if frame is None:
                break
            ref_small = ref.read()
            if ref_small is None:
                common.fail("Color Match: the source has no frames.")
            writer.write(matcher.apply(frame, ref_small))
            done += 1
            common.progress(0.02 + 0.97 * (done / total if total else 0.5), f"Color Match {done}/{total or '?'}")
    finally:
        frames.close()
        ref.close()
    writer.close()
    common.result(width=width, height=height, frames=done, device=matcher.device_name)
