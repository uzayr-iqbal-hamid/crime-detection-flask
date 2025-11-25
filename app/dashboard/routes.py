from flask import render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from . import dashboard_bp
from ..models import Detection, Camera
from ..extensions import db
import os


@dashboard_bp.route("/")
@login_required
def dashboard():
    total_detections = Detection.query.count()
    latest_detections = Detection.query.order_by(Detection.timestamp.desc()).limit(10)
    total_cameras = Camera.query.count()

    return render_template(
        "dashboard.html",
        total_detections=total_detections,
        latest_detections=latest_detections,
        total_cameras=total_cameras,
    )


@dashboard_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        current_user.full_name = request.form.get("full_name", "")
        current_user.organization = request.form.get("organization", "")
        current_user.phone = request.form.get("phone", "")

        db.session.commit()
        flash("Profile updated", "success")
        return redirect(url_for("dashboard.profile"))

    return render_template("profile.html")


# ======================================================
#   ADD THESE TWO ROUTES **BELOW**
# ======================================================

@dashboard_bp.route("/detections/<int:detection_id>/save", methods=["POST"])
@login_required
def save_detection(detection_id):
    det = Detection.query.get_or_404(detection_id)
    det.is_saved = True
    db.session.commit()
    return redirect(url_for("dashboard.dashboard"))


@dashboard_bp.route("/detections/<int:detection_id>/delete", methods=["POST"])
@login_required
def delete_detection(detection_id):
    det = Detection.query.get_or_404(detection_id)

    # delete associated snapshot image if it exists
    if det.frame_path:
        try:
            static_root = current_app.static_folder
            file_path = os.path.join(static_root, det.frame_path.replace("/", os.sep))
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"[Detection] Failed to remove snapshot file: {e}")

    db.session.delete(det)
    db.session.commit()
    return redirect(url_for("dashboard.dashboard"))
