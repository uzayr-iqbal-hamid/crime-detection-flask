from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from . import auth_bp
from ..models import User
from ..extensions import db


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.dashboard"))

    if request.method == "POST":
        username_or_email = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter(
            (User.username == username_or_email) | (User.email == username_or_email)
        ).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("dashboard.dashboard"))
        else:
            flash("Invalid credentials", "danger")

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


# Optional: a simple admin-only registration (create first admin manually via DB)
@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    # In real life, restrict this to admins only, or disable in production
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        role = request.form.get("role", "viewer")

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash("User already exists", "danger")
            return redirect(url_for("auth.register"))

        user = User(username=username, email=email, role=role)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()
        flash("User created. You can login now.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")
