from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from . import dashboard_bp
from ..models import Detection, Camera
from ..extensions import db


@dashboard_bp.route("/")
@login_required
def dashboard():
    total_detections = Detection.query.count()
    latest_detections = Detection.query.order_by(Detection.timestamp.desc()).limit(10)
    total_cameras = Camera.query.count()

    # Very naive system stats (uptime injected in context_processor in __init__.py)
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
