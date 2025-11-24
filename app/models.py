from datetime import datetime
from .extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default="viewer")  # "admin" or "viewer"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Profile fields
    full_name = db.Column(db.String(120))
    organization = db.Column(db.String(120))
    phone = db.Column(db.String(30))

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def is_admin(self) -> bool:
        return self.role == "admin"


class Camera(db.Model):
    __tablename__ = "cameras"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    source = db.Column(db.String(255), nullable=False)  # webcam index or RTSP/HTTP url
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Detection(db.Model):
    __tablename__ = "detections"

    id = db.Column(db.Integer, primary_key=True)
    camera_id = db.Column(db.Integer, db.ForeignKey("cameras.id"), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    crime_label = db.Column(db.String(100), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    frame_path = db.Column(db.String(255))  # optional: store snapshot path

    camera = db.relationship("Camera", backref="detections")
