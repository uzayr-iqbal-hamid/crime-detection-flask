import cv2
import threading
import time
from typing import Dict, Optional, Tuple, List

from flask import Response, stream_with_context, current_app

from ..models import Camera, Detection
from ..extensions import db
from ..config import Config
from .model_inference import CrimeModel


class CameraStream:
    """
    v2: decouple capture and inference.

    - Capture thread: only reads frames and updates shared buffers.
    - Inference thread: periodically copies the buffer and runs the model.
    - Streaming: always reads last_frame, overlays latest_detection on-the-fly.

    Result: video stream stays smooth even if inference is slow.
    """

    def __init__(self, camera_id: int, source: str, model: CrimeModel, app):
        self.camera_id = camera_id
        self.source = source
        self.model = model
        self.app = app  # real Flask app object

        self.capture: Optional[cv2.VideoCapture] = None
        self.running = False

        self.capture_thread: Optional[threading.Thread] = None
        self.inference_thread: Optional[threading.Thread] = None

        self.lock = threading.Lock()
        self._last_frame = None  # last frame for streaming

        # Sliding buffer of recent frames for VideoMAE
        self.clip_buffer: List = []
        self.clip_max_len = self.model.num_frames  # e.g. 16 frames

        self.latest_detection: Optional[Tuple[str, float]] = None

        # How often to run inference (seconds)
        self.inference_interval = 1.5

    def start(self):
        if self.running:
            return

        self.running = True

        # Start capture loop (grabs frames continuously)
        self.capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True
        )
        self.capture_thread.start()

        # Start inference loop (periodically runs the model)
        self.inference_thread = threading.Thread(
            target=self._inference_loop, daemon=True
        )
        self.inference_thread.start()

    def stop(self):
        self.running = False
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def _open_capture(self):
        try:
            idx = int(self.source)
            self.capture = cv2.VideoCapture(idx)
        except ValueError:
            self.capture = cv2.VideoCapture(self.source)

    def _capture_loop(self):
        self._open_capture()
        if not self.capture or not self.capture.isOpened():
            print(f"[CameraStream] Failed to open camera {self.camera_id} (source={self.source})")
            self.running = False
            return

        while self.running:
            ret, frame = self.capture.read()
            if not ret or frame is None:
                time.sleep(0.1)
                continue

            # Update last_frame and clip_buffer under lock
            with self.lock:
                # Keep a copy for streaming
                self._last_frame = frame.copy()

                # Add to clip buffer for inference
                self.clip_buffer.append(frame.copy())
                # Keep up to 2 * clip_max_len frames to give inference some history
                max_buffer = self.clip_max_len * 2
                if len(self.clip_buffer) > max_buffer:
                    self.clip_buffer = self.clip_buffer[-max_buffer:]

            # Target ~30 FPS capture
            time.sleep(0.03)

        self.stop()

    def _inference_loop(self):
        while self.running:
            time.sleep(self.inference_interval)

            # Snapshot of the buffer
            with self.lock:
                if len(self.clip_buffer) < self.clip_max_len:
                    continue
                # Use the last `clip_max_len` frames
                frames_for_model = list(self.clip_buffer[-self.clip_max_len:])

            try:
                label, conf = self.model.predict_clip(frames_for_model)
                self.latest_detection = (label, conf)

                # Log only anomalous events with good confidence
                if label != "Normal Videos" and conf >= 0.8:
                    try:
                        # DB operations need an app context in this thread
                        with self.app.app_context():
                            det = Detection(
                                camera_id=self.camera_id,
                                crime_label=label,
                                confidence=conf,
                                frame_path=None,
                            )
                            db.session.add(det)
                            db.session.commit()
                    except Exception as e:
                        print(f"[CameraStream] DB error on camera {self.camera_id}: {e}")

            except Exception as e:
                # Do not crash the thread on model errors
                print(f"[CameraStream] Inference error on camera {self.camera_id}: {e}")

    def frames(self):
        """
        Generator that yields JPEG bytes for MJPEG streaming.

        Uses the most recent frame and overlays the latest prediction text.
        """
        while self.running:
            with self.lock:
                frame = None if self._last_frame is None else self._last_frame.copy()
                detection = self.latest_detection

            if frame is None:
                time.sleep(0.05)
                continue

            # Overlay prediction text (this is cheap)
            if detection:
                label, conf = detection
                text = f"{label} ({conf:.2f})"
            else:
                text = "Predicting..."

            cv2.putText(
                frame,
                text,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 255),
                2,
            )

            ret, jpeg = cv2.imencode(".jpg", frame)
            if not ret:
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
            )


class CameraManager:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, model_name_or_path: str):
        # Capture the real app object while in request context
        self.app = current_app._get_current_object()
        self.model = CrimeModel.get_instance(model_name_or_path)
        self.streams: Dict[int, CameraStream] = {}

    @classmethod
    def get_instance(cls, model_name_or_path: str):
        with cls._lock:
            if cls._instance is None:
                cls._instance = CameraManager(model_name_or_path)
        return cls._instance

    def get_or_create_stream(self, camera: Camera) -> CameraStream:
        if camera.id in self.streams:
            return self.streams[camera.id]

        stream = CameraStream(
            camera_id=camera.id,
            source=camera.source,
            model=self.model,
            app=self.app,
        )
        self.streams[camera.id] = stream
        stream.start()
        return stream


def mjpeg_response(camera_stream: CameraStream) -> Response:
    return Response(
        stream_with_context(camera_stream.frames()),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )
