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
    def __init__(self, camera_id: int, source: str, model: CrimeModel, app):
        self.camera_id = camera_id
        self.source = source
        self.model = model
        self.app = app

        self.capture = None
        self.lock = threading.Lock()
        self.running = False

        self.latest_detection: Optional[Tuple[str, float]] = None
        self._last_frame = None

        # Sliding window of frames for VideoMAE
        self.clip_buffer: List = []
        self.clip_max_len = self.model.num_frames  # 16
        self.inference_stride = 8  # run inference every 8 frames
        self._frame_count = 0

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._capture_loop, daemon=True).start()

    def stop(self):
        self.running = False
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def _open_capture(self):
        # Source can be webcam index ("0", "1") or RTSP/HTTP URL
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

            self._frame_count += 1

            # Update sliding buffer
            self.clip_buffer.append(frame.copy())
            if len(self.clip_buffer) > self.clip_max_len:
                self.clip_buffer.pop(0)

            # Run inference every 'inference_stride' frames,
            # but only when we have enough frames in the buffer
            if len(self.clip_buffer) >= self.clip_max_len and \
               (self._frame_count % self.inference_stride == 0):
                try:
                    label, conf = self.model.predict_clip(self.clip_buffer)
                    self.latest_detection = (label, conf)

                    # Save detection to DB if anomalous and confident
                    if label != "Normal Videos" and conf >= 0.8:
                        try:
                            # Push an app context so db.session is valid in this thread
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
                    # Do not crash the stream on model errors
                    print(f"[CameraStream] Inference error on camera {self.camera_id}: {e}")

            # Overlay last known prediction on the current frame
            if self.latest_detection:
                label, conf = self.latest_detection
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

            with self.lock:
                self._last_frame = frame

            time.sleep(0.03)  # ~30 FPS

        self.stop()

    def frames(self):
        """Generator that yields JPEG bytes for MJPEG streaming."""
        while self.running:
            frame = None
            with self.lock:
                frame = self._last_frame

            if frame is None:
                time.sleep(0.05)
                continue

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
