from mongoengine import connect
from flask_login import LoginManager
from flask_bcrypt import Bcrypt

# We'll initialize mongoengine in app.py directly
login_manager = LoginManager()
bcrypt = Bcrypt()

def init_db(app):
    connect(host=app.config['MONGODB_SETTINGS']['host'])
