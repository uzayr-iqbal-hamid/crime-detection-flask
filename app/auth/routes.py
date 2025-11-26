from flask import render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user

from . import auth_bp
from ..models import User
from ..extensions import db
from ..services.camera_manager import CameraManager
from ..config import Config
import time


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # If already logged in, don't show login page again
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.dashboard"))

    if request.method == "POST":
        username_or_email = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter(
            (User.username == username_or_email) | (User.email == username_or_email)
        ).first()

        if user and user.check_password(password):
            login_user(user)

            # start session uptime here
            session["login_start_ts"] = time.time()

            return redirect(url_for("dashboard.dashboard"))
        else:
            flash("Invalid username/email or password.", "danger")

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    # Stop all camera streams when user logs out
    cm = CameraManager.get_instance(Config.CRIME_MODEL_PATH)
    cm.stop_all()

    # reset session uptime
    session.pop("login_start_ts", None)

    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    # If already logged in, no need to register again
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        errors = []

        if not username:
            errors.append("Username is required.")
        if not email:
            errors.append("Email is required.")
        if not password:
            errors.append("Password is required.")
        if password and len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm_password:
            errors.append("Passwords do not match.")

        # Check for existing user by username or email
        if username or email:
            existing = User.query.filter(
                (User.username == username) | (User.email == email)
            ).first()
            if existing:
                errors.append("A user with that username or email already exists.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("register.html")

        # Force role to "viewer" for self-registration
        user = User(username=username, email=email, role="viewer")
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("Account created successfully. You can log in now.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")
