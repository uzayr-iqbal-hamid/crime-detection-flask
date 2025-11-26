import time
from flask import Flask, session
from flask_login import current_user

from .config import Config
from .extensions import db, migrate, login_manager
from .models import User
from .auth import auth_bp
from .dashboard import dashboard_bp
from .detection import detection_bp


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Login manager setup
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    login_manager.login_view = "auth.login"

    # Blueprints
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(detection_bp, url_prefix="/detection")

    # Make uptime available in templates (per-login session uptime)
    @app.context_processor
    def inject_uptime():
        """
        uptime_seconds:
        - If user is authenticated and we have login_start_ts in session:
              now - login_start_ts
        - Otherwise: 0
        """
        if current_user.is_authenticated:
            login_ts = session.get("login_start_ts")
            if login_ts:
                uptime_seconds = max(0, int(time.time() - login_ts))
            else:
                uptime_seconds = 0
        else:
            uptime_seconds = 0

        return dict(uptime_seconds=uptime_seconds)

    return app
