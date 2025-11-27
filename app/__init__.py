import time
from flask import Flask
from flask_login import current_user
from .config import Config
from .extensions import db, migrate, login_manager
from .models import User
from .auth import auth_bp
from .dashboard import dashboard_bp
from .detection import detection_bp

APP_START_TIME = time.time()  # used for uptime stats


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
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(detection_bp, url_prefix="/detection")

    # Root redirect to login if not authenticated
    @app.route("/")
    def index():
        if current_user.is_authenticated:
            from flask import redirect, url_for
            return redirect(url_for("dashboard.dashboard"))
        else:
            from flask import redirect, url_for
            return redirect(url_for("auth.login"))

    # Make uptime available in templates
    @app.context_processor
    def inject_uptime():
        uptime_seconds = int(time.time() - APP_START_TIME)
        return dict(uptime_seconds=uptime_seconds)

    return app
