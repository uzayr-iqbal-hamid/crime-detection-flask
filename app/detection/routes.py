from flask import render_template, abort, jsonify
from flask_login import login_required

from . import detection_bp
from ..models import Camera
from ..config import Config
from ..services.camera_manager import CameraManager, mjpeg_response


@detection_bp.route("/live")
@login_required
def live_default():
    # Default: first active camera
    camera = Camera.query.filter_by(is_active=True).order_by(Camera.id.asc()).first()
    if not camera:
        abort(404, "No active cameras configured")
    return live_camera(camera.id)


@detection_bp.route("/live/<int:camera_id>")
@login_required
def live_camera(camera_id):
    camera = Camera.query.get_or_404(camera_id)
    if not camera.is_active:
        abort(404, "Camera not active")

    cameras = Camera.query.filter_by(is_active=True).all()
    return render_template(
        "live.html",
        selected_camera=camera,
        cameras=cameras,
    )


@detection_bp.route("/stream/<int:camera_id>")
@login_required
def stream(camera_id):
    camera = Camera.query.get_or_404(camera_id)
    if not camera.is_active:
        abort(404, "Camera not active")

    cm = CameraManager.get_instance(Config.CRIME_MODEL_PATH)
    stream = cm.get_or_create_stream(camera)
    return mjpeg_response(stream)


@detection_bp.route("/stats/<int:camera_id>")
@login_required
def camera_stats(camera_id):
    """Return latest prediction for this camera for frontend polling."""
    camera = Camera.query.get_or_404(camera_id)
    cm = CameraManager.get_instance(Config.CRIME_MODEL_PATH)
    stream = cm.get_or_create_stream(camera)

    label = "Unknown"
    conf = 0.0
    if stream.latest_detection:
        label, conf = stream.latest_detection

    return jsonify(
        {
            "camera_id": camera.id,
            "label": label,
            "confidence": conf,
        }
    )


@detection_bp.route("/stop/<int:camera_id>", methods=["POST"])
@login_required
def stop_camera(camera_id):
    """Stop a camera stream and its capture loop."""
    camera = Camera.query.get_or_404(camera_id)
    cm = CameraManager.get_instance(Config.CRIME_MODEL_PATH)
    cm.stop_stream(camera.id)
    # No content needed; frontend just needs success
    return ("", 204)
