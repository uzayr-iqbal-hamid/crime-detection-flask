import threading
from typing import Tuple, List

import numpy as np
import torch
import cv2
from transformers import VideoMAEForVideoClassification


class CrimeModel:
    """
    Wrapper around OPear/videomae-large-finetuned-UCF-Crime.

    Expects a clip of frames (BGR, from OpenCV), samples 16 frames,
    resizes to 224x224, normalizes as in the model card example,
    and returns (label, confidence).
    """
    _instance = None
    _lock = threading.Lock()

    def __init__(self, model_name_or_path: str):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        print("[CrimeModel] Loading model:", model_name_or_path)

        # Load model from Hugging Face (will download on first run)
        self.model = VideoMAEForVideoClassification.from_pretrained(
            model_name_or_path,
            ignore_mismatched_sizes=True,
        ).to(self.device)
        self.model.eval()

        # id2label mapping is stored in the config
        self.id2label = self.model.config.id2label or {}

        # Default clip settings (same as README: 16 frames, 224x224) :contentReference[oaicite:2]{index=2}
        self.num_frames = 16
        self.input_size = (224, 224)

    @classmethod
    def get_instance(cls, model_name_or_path: str):
        with cls._lock:
            if cls._instance is None:
                cls._instance = CrimeModel(model_name_or_path)
        return cls._instance

    def _prepare_clip_tensor(self, frames_bgr: List[np.ndarray]) -> torch.Tensor:
        """
        frames_bgr: list of OpenCV BGR frames (H, W, 3)

        Returns:
            tensor of shape [1, num_frames, 3, H, W] on self.device
        """
        if len(frames_bgr) == 0:
            raise ValueError("No frames provided to CrimeModel")

        total_frames = len(frames_bgr)

        # sample indices across the clip (same logic as README video loader)
        frame_indices = np.linspace(
            0, total_frames - 1, self.num_frames, dtype=int
        )

        sampled = []
        for i, frame in enumerate(frames_bgr):
            if i in frame_indices:
                # BGR -> RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame_resized = cv2.resize(frame_rgb, self.input_size)
                sampled.append(frame_resized)

        if len(sampled) == 0:
            raise ValueError("Sampling failed, no frames selected")

        # Pad if fewer than num_frames
        if len(sampled) < self.num_frames:
            sampled.extend([sampled[-1]] * (self.num_frames - len(sampled)))

        frames_np = np.stack(sampled, axis=0)  # [T, H, W, 3]
        frames_t = torch.tensor(frames_np, dtype=torch.float32)  # [T, H, W, 3]
        frames_t = frames_t.permute(0, 3, 1, 2) / 255.0  # [T, 3, H, W]
        frames_t = frames_t.unsqueeze(0)  # [1, T, 3, H, W]

        return frames_t.to(self.device)

    @torch.no_grad()
    def predict_clip(self, frames_bgr: List[np.ndarray]) -> Tuple[str, float]:
        """
        Run inference on a short video clip (sliding window of frames).

        Returns:
            (label, confidence) where confidence is in [0, 1].
        """
        clip_tensor = self._prepare_clip_tensor(frames_bgr)

        outputs = self.model(pixel_values=clip_tensor)
        probs = torch.softmax(outputs.logits, dim=-1)[0]  # [num_labels]
        conf, idx = torch.max(probs, dim=-1)

        idx_int = int(idx.item())
        label = self.id2label.get(idx_int, str(idx_int))
        confidence = float(conf.item())

        return label, confidence
