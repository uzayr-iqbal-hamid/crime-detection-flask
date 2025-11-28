from flask import render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from . import dashboard_bp
from ..models import Detection, Camera, EmergencyContact
from ..extensions import db
from ..location.routes import get_nearest_police_station
import os
import re


@dashboard_bp.route("/")
@login_required
def dashboard():
    total_detections = Detection.query.count()
    latest_detections = Detection.query.order_by(Detection.timestamp.desc()).limit(10)
    total_cameras = Camera.query.count()
    
    # Get nearest police station (default to Kengeri, Bangalore)
    default_lat = 12.9352
    default_lng = 77.5245
    nearest_station = get_nearest_police_station(default_lat, default_lng)

    return render_template(
        "dashboard.html",
        total_detections=total_detections,
        latest_detections=latest_detections,
        total_cameras=total_cameras,
        nearest_station=nearest_station,
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

    emergency_contacts = EmergencyContact.query.filter_by(user_id=current_user.id).all()
    return render_template("profile.html", emergency_contacts=emergency_contacts)


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


# ======================================================
#   EMERGENCY CONTACTS ROUTES
# ======================================================

def validate_phone_number(phone):
    """Validate phone number format (10-20 digits, optional +, dashes, spaces)"""
    # Remove common separators
    cleaned = re.sub(r'[\s\-\(\)]+', '', phone)
    # Check if it starts with + and has digits
    if cleaned.startswith('+'):
        return re.match(r'^\+\d{10,19}$', cleaned) is not None
    # Check if it has 10-20 digits
    return re.match(r'^\d{10,20}$', cleaned) is not None


@dashboard_bp.route("/emergency-contacts/add", methods=["POST"])
@login_required
def add_emergency_contact():
    """Add a new emergency contact"""
    contact_name = request.form.get("contact_name", "").strip()
    contact_phone = request.form.get("contact_phone", "").strip()
    relationship = request.form.get("relationship", "").strip()

    # Validation
    if not contact_name or len(contact_name) > 120:
        flash("Contact name is required and must be less than 120 characters", "danger")
        return redirect(url_for("dashboard.profile"))

    if not contact_phone or not validate_phone_number(contact_phone):
        flash("Please enter a valid phone number", "danger")
        return redirect(url_for("dashboard.profile"))

    if not relationship or len(relationship) > 50:
        flash("Relationship is required and must be less than 50 characters", "danger")
        return redirect(url_for("dashboard.profile"))

    # Check max contacts limit (3)
    existing_count = EmergencyContact.query.filter_by(user_id=current_user.id).count()
    if existing_count >= 3:
        flash("You can only add up to 3 emergency contacts", "danger")
        return redirect(url_for("dashboard.profile"))

    # Create new contact
    new_contact = EmergencyContact(
        user_id=current_user.id,
        contact_name=contact_name,
        contact_phone=contact_phone,
        relationship=relationship
    )

    db.session.add(new_contact)
    db.session.commit()
    flash(f"Emergency contact '{contact_name}' added successfully", "success")
    return redirect(url_for("dashboard.profile"))


@dashboard_bp.route("/emergency-contacts/<int:contact_id>/delete", methods=["POST"])
@login_required
def delete_emergency_contact(contact_id):
    """Delete an emergency contact"""
    contact = EmergencyContact.query.get_or_404(contact_id)

    # Verify ownership
    if contact.user_id != current_user.id:
        flash("You can only delete your own emergency contacts", "danger")
        return redirect(url_for("dashboard.profile"))

    contact_name = contact.contact_name
    db.session.delete(contact)
    db.session.commit()
    flash(f"Emergency contact '{contact_name}' deleted successfully", "success")
    return redirect(url_for("dashboard.profile"))


@dashboard_bp.route("/emergency-contacts/<int:contact_id>/edit", methods=["POST"])
@login_required
def edit_emergency_contact(contact_id):
    """Edit an emergency contact"""
    contact = EmergencyContact.query.get_or_404(contact_id)

    # Verify ownership
    if contact.user_id != current_user.id:
        flash("You can only edit your own emergency contacts", "danger")
        return redirect(url_for("dashboard.profile"))

    contact_name = request.form.get("contact_name", "").strip()
    contact_phone = request.form.get("contact_phone", "").strip()
    relationship = request.form.get("relationship", "").strip()

    # Validation
    if not contact_name or len(contact_name) > 120:
        flash("Contact name is required and must be less than 120 characters", "danger")
        return redirect(url_for("dashboard.profile"))

    if not contact_phone or not validate_phone_number(contact_phone):
        flash("Please enter a valid phone number", "danger")
        return redirect(url_for("dashboard.profile"))

    if not relationship or len(relationship) > 50:
        flash("Relationship is required and must be less than 50 characters", "danger")
        return redirect(url_for("dashboard.profile"))

    # Update contact
    contact.contact_name = contact_name
    contact.contact_phone = contact_phone
    contact.relationship = relationship

    db.session.commit()
    flash(f"Emergency contact '{contact_name}' updated successfully", "success")
    return redirect(url_for("dashboard.profile"))
