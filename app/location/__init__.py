from flask import Blueprint

location_bp = Blueprint('location', __name__)

from . import routes
