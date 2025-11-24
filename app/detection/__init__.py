from flask import Blueprint

detection_bp = Blueprint("detection", __name__, template_folder="../templates")

from . import routes  # noqa: E402,F401
