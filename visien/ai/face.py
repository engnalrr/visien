"""Face restoration with GFPGAN 1.4 or CodeFormer (PyTorch on the GPU), YuNet detection and 5-point alignment.

The model files are the official releases (TencentARC/GFPGAN, sczhou/CodeFormer). The network code comes from
spandrel (MIT) and, for CodeFormer only, spandrel_extra_arches, which is installed together with CodeFormer
after its non-commercial licence is accepted.
"""

from __future__ import annotations

import time

import numpy as np

from . import common

# FFHQ 512 template (eye left/right in the image, nose, mouth left/right) as used by facexlib/GFPGAN.
TEMPLATE = np.array([[192.98138, 239.94708], [318.90277, 240.19360], [256.63416, 314.01935],
                     [201.26117, 371.41043], [313.08905, 371.15118]], dtype=np.float32)
SIZE = 512
MODELS = {"codeformer": "codeformer.pth", "gfpgan": "GFPGANv1.4.pth"}
CORNERS = np.array([[0, 0, 1], [SIZE, 0, 1], [0, SIZE, 1], [SIZE, SIZE, 1]], dtype=np.float32)


def _mask() -> np.ndarray:
    import cv2  # noqa: WPS433

    mask = np.zeros((SIZE, SIZE), np.float32)
    cv2.ellipse(mask, (256, 280), (190, 236), 0, 0, 360, 1.0, -1)
    return cv2.GaussianBlur(mask, (0, 0), 22)


class Network:
    """GFPGAN or CodeFormer on the GPU. Takes and returns 512×512 RGB uint8 crops."""

    def __init__(self, path, kind: str, fidelity: float):
        import torch  # noqa: WPS433
        from spandrel import ModelLoader  # noqa: WPS433

        if kind == "codeformer":
            try:
                import spandrel_extra_arches  # noqa: WPS433
            except ImportError:
                common.fail("CodeFormer needs its add-on package. Install CodeFormer again in Settings > AI models.")
            spandrel_extra_arches.install()
        common.rocm_fixes()
        self.torch = torch
        self.kind = kind
        self.fidelity = fidelity
        self.device = common.torch_device()
        descriptor = ModelLoader(device="cpu").load_from_file(str(path))
        self.model = descriptor.model.eval().to(self.device)
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)

    def __call__(self, crops: list[np.ndarray]) -> list[np.ndarray]:
        torch = self.torch
        with torch.inference_mode():
            batch = torch.from_numpy(np.stack(crops)).to(self.device).permute(0, 3, 1, 2).contiguous().float()
            batch = batch / 127.5 - 1.0
            if self.kind == "codeformer":
                out = self.model(batch, weight=self.fidelity)[0]
            else:
                # fixed noise: the same face gets the same texture on every frame (no shimmer on video)
                out = self.model(batch, return_rgb=False, randomize_noise=False)[0]
            out = ((out.clamp(-1, 1) + 1.0) * 127.5).round().to(torch.uint8).permute(0, 2, 3, 1).cpu().numpy()
        return list(out)


class Restorer:
    def __init__(self, models_dir, params: dict):
        import cv2  # noqa: WPS433

        self.cv2 = cv2
        kind = params.get("face_model") or "gfpgan"
        kind = kind if kind in MODELS else "gfpgan"
        model_path = models_dir / "face" / MODELS[kind]
        detector_path = models_dir / "face" / "face_detection_yunet_2023mar.onnx"
        for needed in (model_path, detector_path):
            if not needed.is_file():
                common.fail(f"Face model {needed.name} is not installed (Settings > AI models).")
        self.kind = kind
        self.network = Network(model_path, kind, float(params.get("face_fidelity", 0.7)))
        self.strength = float(params.get("face_blend", 60)) / 100.0
        self.largest = params.get("face_which") == "largest"
        self.min_size = float(params.get("face_min_size", 5)) / 100.0
        self.smooth = float(params.get("face_smoothing", 60)) / 100.0 * 0.85
        self.detector = cv2.FaceDetectorYN.create(str(detector_path), "", (320, 320), 0.6, 0.3, 50)
        self.mask = _mask()
        self.tracks: list[np.ndarray] = []
        self.timing = {"detect": 0.0, "network": 0.0, "paste": 0.0}
        self.device = str(self.network.device)

    def _detect(self, frame: np.ndarray) -> list[np.ndarray]:
        cv2 = self.cv2
        h, w = frame.shape[:2]
        scale = min(1.0, 1280.0 / max(h, w))
        small = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else frame
        self.detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self.detector.detect(cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
        result = []
        if faces is None:
            return result
        for face in faces:
            box_h = face[3] / scale
            if box_h < self.min_size * h:
                continue
            points = face[4:14].reshape(5, 2) / scale
            result.append(points.astype(np.float32))
        if self.largest and result:
            result = [max(result, key=lambda p: np.linalg.norm(p[0] - p[1]))]
        return result

    def _smooth(self, faces: list[np.ndarray]) -> list[np.ndarray]:
        if self.smooth <= 0:
            self.tracks = faces
            return faces
        smoothed = []
        for points in faces:
            centre = points.mean(axis=0)
            match = None
            for prev in self.tracks:
                eye = np.linalg.norm(prev[0] - prev[1]) + 1e-6
                if np.linalg.norm(prev.mean(axis=0) - centre) < eye * 0.6:
                    match = prev
                    break
            smoothed.append(points if match is None else match * self.smooth + points * (1 - self.smooth))
        self.tracks = smoothed
        return smoothed

    def process(self, frame: np.ndarray, video: bool) -> tuple[np.ndarray, int]:
        cv2 = self.cv2
        started = time.perf_counter()
        faces = self._detect(frame)
        if video:
            faces = self._smooth(faces)
        detected = time.perf_counter()
        self.timing["detect"] += detected - started
        if not faces:
            return frame, 0
        h, w = frame.shape[:2]
        matrices, crops = [], []
        for points in faces:
            matrix, _ = cv2.estimateAffinePartial2D(points, TEMPLATE, method=cv2.LMEDS)
            if matrix is None:
                continue
            matrices.append(matrix)
            crops.append(cv2.warpAffine(frame, matrix, (SIZE, SIZE), flags=cv2.INTER_LINEAR,
                                        borderMode=cv2.BORDER_REFLECT101))
        if not crops:
            return frame, 0
        restored = self.network(crops)
        networked = time.perf_counter()
        self.timing["network"] += networked - detected
        result = frame.copy()
        for matrix, face in zip(matrices, restored):
            inverse = cv2.invertAffineTransform(matrix)
            # paste back only inside the face's bounding box (much faster than whole-frame warps on 4K)
            corners = CORNERS @ inverse.T
            x0, y0 = np.floor(corners.min(axis=0)).astype(int) - 2
            x1, y1 = np.ceil(corners.max(axis=0)).astype(int) + 2
            x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
            if x1 - x0 < 2 or y1 - y0 < 2:
                continue
            local = inverse.copy()
            local[:, 2] -= (x0, y0)
            size = (x1 - x0, y1 - y0)
            back = cv2.warpAffine(face, local, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT101)
            alpha = cv2.warpAffine(self.mask, local, size, flags=cv2.INTER_LINEAR, borderValue=0)
            alpha = (alpha * self.strength)[..., None]
            roi = result[y0:y1, x0:x1].astype(np.float32)
            result[y0:y1, x0:x1] = np.clip(roi * (1 - alpha) + back.astype(np.float32) * alpha, 0, 255).round()
        self.timing["paste"] += time.perf_counter() - networked
        return result, len(restored)


def run(args, params: dict) -> None:
    common.progress(0.01, "Loading Face Restore")
    restorer = Restorer(args.models, params)
    label = "GFPGAN" if restorer.kind == "gfpgan" else "CodeFormer"
    common.progress(0.02, f"Face Restore ({label}, {'GPU' if restorer.device.startswith('cuda') else 'CPU'})")
    if args.kind == "image":
        frame = common.read_image(args.input)
        out, count = restorer.process(frame, False)
        common.write_image(str(args.output), out)
        common.result(width=out.shape[1], height=out.shape[0], faces=count, device=restorer.device)
        return
    info = common.probe(args.ffprobe, args.input)
    width, height, total = info["width"], info["height"], info["frames"] or 0
    reader = common.reader(args.ffmpeg, args.input, info)
    writer = common.FrameWriter(args.ffmpeg, str(args.output), width, height, info["fps"])
    done = faces_seen = 0
    while True:
        frame = reader.read()
        if frame is None:
            break
        out, count = restorer.process(frame, True)
        faces_seen += count
        writer.write(out)
        done += 1
        common.progress(0.02 + 0.98 * (done / total if total else 0.5), f"Faces {done}/{total or '?'}")
    reader.close()
    writer.close()
    per = {k: round(v * 1000 / max(done, 1), 1) for k, v in restorer.timing.items()}
    common.result(width=width, height=height, frames=done, faces=faces_seen, device=restorer.device, ms_per_frame=per)
