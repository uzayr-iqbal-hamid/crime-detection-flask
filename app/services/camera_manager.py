import os
import cv2
import threading
import time
from typing import Dict, Optional, Tuple, List

from flask import Response, stream_with_context, current_app, url_for

from ..models import Camera, Detection
from ..extensions import db
from ..config import Config
from .model_inference import CrimeModel


class CameraStream:
    """
    v2.1: decouple capture and inference, add post-processing + alert snapshots.

    - Capture thread: grabs frames and updates shared buffers.
    - Inference thread: periodically runs the model on recent frames.
    - Streaming: always uses last_frame + latest_detection for overlay.
    - Post-processing:
        * low-confidence -> treated as Normal
        * crime alert only when label is confident AND stable
        * snapshot saved for each alert and shown on dashboard
        * OPTIONAL: send email alerts via Resend
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

        # What we expose to the rest of the app (overlay + /stats)
        self.latest_detection: Optional[Tuple[str, float]] = None  # (label, conf[0..1])

        # Inference scheduling
        self.inference_interval = 1.5  # seconds

        # Post-processing / alert logic
        self.conf_threshold = 0.75       # crime must exceed this to be considered
        self.stable_required = 1         # need the same crime label N times in a row
        self.alert_cooldown = 8.0        # seconds between alerts of the same type

        self._pending_label: Optional[str] = None
        self._pending_count: int = 0
        self._last_alert_ts: float = 0.0

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Capture
    # -------------------------------------------------------------------------

    def _open_capture(self):
        try:
            idx = int(self.source)
            # Prefer DirectShow on Windows
            self.capture = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        except ValueError:
            self.capture = cv2.VideoCapture(self.source)

        if not self.capture or not self.capture.isOpened():
            print(f"[CameraStream] Failed to open camera {self.camera_id} (source={self.source})")
            return


    def _capture_loop(self):
        print(f"[CameraStream] Capture loop starting for camera {self.camera_id}, source={self.source}")
        self._open_capture()
        if not self.capture or not self.capture.isOpened():
            print(f"[CameraStream] Failed to open camera {self.camera_id} (source={self.source})")
            self.running = False
            return

        fail_count = 0
        max_failures = 50
        frame_counter = 0

        while self.running:
            ret, frame = self.capture.read()
            if not ret or frame is None:
                fail_count += 1
                if fail_count >= max_failures:
                    print(f"[CameraStream] Too many failures on camera {self.camera_id}, stopping stream.")
                    self.running = False
                    break
                time.sleep(0.1)
                continue

            fail_count = 0
            frame_counter += 1

            if frame_counter % 30 == 0:
                print(f"[CameraStream] Camera {self.camera_id}: captured {frame_counter} frames")

            with self.lock:
                self._last_frame = frame.copy()
                self.clip_buffer.append(frame.copy())
                max_buffer = self.clip_max_len * 2
                if len(self.clip_buffer) > max_buffer:
                    self.clip_buffer = self.clip_buffer[-max_buffer:]

            time.sleep(0.03)

        self.stop()

    # -------------------------------------------------------------------------
    # Post-processing + alert logic
    # -------------------------------------------------------------------------

    def _post_process_label(self, label: str, conf: float) -> Tuple[str, float]:
        """
        Map raw (label, conf) from the model to what we show in UI.

        Rules:
        - If the model already says "Normal Videos" with decent confidence, keep it.
        - If confidence for a crime label is low -> treat as Normal for display.
        - Only high-confidence crimes will be displayed as such.
        """
        if label == "Normal Videos" and conf >= 0.5:
            return label, conf

        if conf >= self.conf_threshold:
            # Confident crime prediction
            return label, conf

        # Low-confidence -> show as Normal
        return "Normal Videos", 0.0

    def _maybe_log_alert(self, label: str, conf: float, frames_for_model: List):
        """
        Decide whether to create a Detection row + save a snapshot + send email.

        Uses:
        - confidence threshold
        - stability over multiple inference cycles
        - cooldown so we don't spam the DB / email
        """
        if label == "Normal Videos" or conf < self.conf_threshold:
            # Reset pending streak when model isn't sure or says normal
            self._pending_label = None
            self._pending_count = 0
            return

        # Crime candidate with sufficient confidence
        if self._pending_label == label:
            self._pending_count += 1
        else:
            self._pending_label = label
            self._pending_count = 1

        now_ts = time.time()

        if self._pending_count < self.stable_required:
            # Not stable enough yet
            return

        # Check cooldown
        if now_ts - self._last_alert_ts < self.alert_cooldown:
            return

        # At this point we consider it a real alert
        self._last_alert_ts = now_ts

        try:
            # Snapshot: take the middle frame of the clip used for this prediction
            mid_idx = len(frames_for_model) // 2
            snapshot = frames_for_model[mid_idx].copy()

            # Overlay the crime label + confidence on the snapshot
            text = f"{label} ({conf:.2f})"
            cv2.putText(
                snapshot,
                text,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 0, 255),  # red text
                2,
            )

            # DB + static files need the Flask app context
            with self.app.app_context():
                static_dir = os.path.join(self.app.root_path, "static")
                det_dir = os.path.join(static_dir, "detections")
                os.makedirs(det_dir, exist_ok=True)

                filename = f"cam{self.camera_id}_{int(now_ts)}.jpg"
                file_path = os.path.join(det_dir, filename)

                cv2.imwrite(file_path, snapshot)

                rel_path = f"detections/{filename}"

                det = Detection(
                    camera_id=self.camera_id,
                    crime_label=label,
                    confidence=conf,
                    frame_path=rel_path,
                )
                db.session.add(det)
                db.session.commit()

                # Send email alert (best-effort, non-fatal if it fails)
                self._send_alert_email(label, conf, rel_path, det.id)

        except Exception as e:
            print(f"[CameraStream] DB/snapshot error on camera {self.camera_id}: {e}")

    def _send_alert_email(self, label: str, conf: float, rel_path: str, detection_id: int):
        """
        Send an alert email via Resend for a newly created Detection.

        Uses:
        - RESEND_API_KEY
        - ALERT_EMAIL_FROM
        - ALERT_EMAIL_TO

        If any of these are missing or Resend is not installed, it silently skips.
        """
        try:
            # Config values from Flask app
            api_key = self.app.config.get("RESEND_API_KEY")
            from_email = self.app.config.get("ALERT_EMAIL_FROM")
            to_mail = self.app.config.get("ALERT_EMAIL_TO")

            if not api_key or not from_email or not to_mail:
                # Email alerts not configured
                return

            try:
                import resend
            except ImportError:
                print("[Email] 'resend' package not installed; skipping email alert.")
                return

            resend.api_key = api_key

            # Build useful links
            snapshot_url = url_for("static", filename=rel_path, _external=True)
            dashboard_url = url_for("dashboard.dashboard", _external=True)

            subject = f"[Crime Detection] {label} detected on camera {self.camera_id}"

            html = f"""
                <div style="font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 8px 0;">
                    <h2 style="margin: 0 0 8px;">Crime alert: {label}</h2>
                    <p style="margin: 4px 0;">Camera ID: <strong>{self.camera_id}</strong></p>
                    <p style="margin: 4px 0;">Confidence: <strong>{conf:.2f}</strong></p>
                    <p style="margin: 4px 0;">Detection ID: <strong>{detection_id}</strong></p>

                    <p style="margin: 12px 0;">
                        <a href="{snapshot_url}" style="color: #2563eb; text-decoration: none;">
                            View snapshot
                        </a>
                        &nbsp;·&nbsp;
                        <a href="{dashboard_url}" style="color: #2563eb; text-decoration: none;">
                            Open dashboard
                        </a>
                    </p>

                    <p style="font-size: 12px; color: #6b7280; margin-top: 16px;">
                        This email was generated automatically by the Crime Detection system.
                    </p>
                </div>
            """

            params: dict = {
                "from": from_email,
                "to": [to_mail],
                "subject": subject,
                "html": html,
            }

            resend.Emails.send(params)

        except Exception as e:
            print(f"[Email] Failed to send alert email: {e}")

    # -------------------------------------------------------------------------
    # Inference loop
    # -------------------------------------------------------------------------

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
                # Raw prediction from VideoMAE
                raw_label, raw_conf = self.model.predict_clip(frames_for_model)

                # What we show to UI (maps low-confidence crime -> Normal Videos)
                display_label, display_conf = self._post_process_label(raw_label, raw_conf)
                self.latest_detection = (display_label, display_conf)

                # Decide whether to log an alert + snapshot + email based on raw_label/conf
                self._maybe_log_alert(raw_label, raw_conf, frames_for_model)

            except Exception as e:
                # Do not crash the thread on model errors
                print(f"[CameraStream] Inference error on camera {self.camera_id}: {e}")

    # -------------------------------------------------------------------------
    # MJPEG streaming
    # -------------------------------------------------------------------------

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

    def stop_all(self):
        """
        Stop all running camera streams (used on logout).
        """
        for stream in self.streams.values():
            stream.stop()
        self.streams.clear()


def mjpeg_response(camera_stream: CameraStream) -> Response:
    return Response(
        stream_with_context(camera_stream.frames()),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )
