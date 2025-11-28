from flask import render_template, abort, jsonify, session, request, current_app
from flask_login import login_required
from datetime import datetime, timedelta
from sqlalchemy import func
import time
import os
import cv2
import numpy as np

from . import detection_bp
from ..models import Camera, Detection
from ..config import Config
from ..services.camera_manager import CameraManager, mjpeg_response
from ..services.model_inference import CrimeModel
from ..extensions import db
from werkzeug.utils import secure_filename


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

    # Start camera uptime tracking when user accesses live view
    if "camera_start_ts" not in session:
        session["camera_start_ts"] = time.time()
        session.modified = True

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
    
    # Reset camera uptime tracking when camera stops
    if "camera_start_ts" in session:
        del session["camera_start_ts"]
        session.modified = True
    
    # No content needed; frontend just needs success
    return ("", 204)


@detection_bp.route("/statistics")
@login_required
def statistics():
    """Display graphical representation of detection statistics."""
    # Get detection counts by crime label
    detection_labels_query = db.session.query(
        Detection.crime_label,
        func.count(Detection.id).label('count')
    ).group_by(Detection.crime_label).all()
    
    # Convert Row objects to tuples for template
    detection_labels = [(row[0], row[1]) for row in detection_labels_query]
    
    # Get confidence distribution
    confidence_ranges = {
        'High (0.9-1.0)': db.session.query(func.count(Detection.id)).filter(
            Detection.confidence >= 0.9, Detection.confidence <= 1.0
        ).scalar() or 0,
        'Medium (0.7-0.9)': db.session.query(func.count(Detection.id)).filter(
            Detection.confidence >= 0.7, Detection.confidence < 0.9
        ).scalar() or 0,
        'Low (0.5-0.7)': db.session.query(func.count(Detection.id)).filter(
            Detection.confidence >= 0.5, Detection.confidence < 0.7
        ).scalar() or 0,
    }
    
    return render_template(
        "statistics.html",
        detection_labels=detection_labels,
        confidence_ranges=confidence_ranges
    )


@detection_bp.route("/statistics/data")
@login_required
def statistics_data():
    """API endpoint for dynamic statistics data."""
    # Get detection counts by crime label
    detection_labels_query = db.session.query(
        Detection.crime_label,
        func.count(Detection.id).label('count')
    ).group_by(Detection.crime_label).all()
    
    labels = [row[0] for row in detection_labels_query]
    counts = [row[1] for row in detection_labels_query]
    
    # Get hourly detection trend
    now = datetime.utcnow()
    twenty_four_hours_ago = now - timedelta(hours=24)
    
    hourly_data_query = db.session.query(
        func.date_format(Detection.timestamp, '%Y-%m-%d %H:00').label('hour'),
        func.count(Detection.id).label('count')
    ).filter(Detection.timestamp >= twenty_four_hours_ago).group_by('hour').order_by('hour').all()
    
    hourly = [{'hour': row[0], 'count': row[1]} for row in hourly_data_query]
    
    return jsonify({
        'labels': labels,
        'counts': counts,
        'hourly': hourly
    })


# ======================================================
#   UPLOAD PREDICTION ROUTES
# ======================================================

ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'flv', 'jpg', 'jpeg', 'png', 'gif', 'bmp'}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def is_image_file(filename):
    """Check if file is an image."""
    image_extensions = {'jpg', 'jpeg', 'png', 'gif', 'bmp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in image_extensions


def is_video_file(filename):
    """Check if file is a video."""
    video_extensions = {'mp4', 'avi', 'mov', 'flv'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in video_extensions


def extract_frames_from_image(image_path, num_frames=16):
    """Extract frames from an image by duplicating it (for consistency with video processing)."""
    frame = cv2.imread(image_path)
    if frame is None:
        raise ValueError("Could not read image file")
    
    # Duplicate frame to create a "clip" for the model
    frames = [frame] * num_frames
    return frames


def extract_frames_from_video(video_path, max_frames=16):
    """Extract frames from video file."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError("Could not open video file")
    
    frames = []
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    if total_frames == 0:
        raise ValueError("Video has no frames")
    
    # Sample frames uniformly across the video
    frame_indices = np.linspace(0, total_frames - 1, max_frames, dtype=int)
    
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        if frame_idx in frame_indices:
            frames.append(frame)
        
        frame_idx += 1
    
    cap.release()
    
    if len(frames) == 0:
        raise ValueError("Could not extract frames from video")
    
    return frames


@detection_bp.route("/predict-upload", methods=["GET", "POST"])
@login_required
def predict_upload():
    """Predict crime detection from uploaded image or video."""
    if request.method == "GET":
        # Just render the upload form
        return render_template("upload_predict.html")
    
    # Handle POST request - process uploaded file
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed. Use: image or video"}), 400
    
    if len(file.read()) > MAX_FILE_SIZE:
        file.seek(0)
        return jsonify({"error": "File too large (max 100 MB)"}), 400
    
    file.seek(0)
    
    try:
        # Save uploaded file temporarily
        upload_folder = os.path.join(current_app.static_folder, 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)
        
        # Extract frames based on file type
        is_image = is_image_file(filename)
        is_video = is_video_file(filename)
        
        if is_image:
            frames = extract_frames_from_image(filepath)
            file_type = "image"
        elif is_video:
            frames = extract_frames_from_video(filepath)
            file_type = "video"
        else:
            os.remove(filepath)
            return jsonify({"error": "Invalid file type"}), 400
        
        # Get model and make prediction
        model = CrimeModel.get_instance(Config.CRIME_MODEL_NAME)
        label, confidence = model.predict(frames)
        
        # Clean up
        try:
            os.remove(filepath)
        except:
            pass
        
        return jsonify({
            "success": True,
            "prediction": {
                "label": label,
                "confidence": float(confidence),
                "file_type": file_type,
                "filename": filename
            }
        })
    
    except Exception as e:
        print(f"[Upload Prediction] Error: {e}")
        try:
            os.remove(filepath)
        except:
            pass
        return jsonify({"error": str(e)}), 500
