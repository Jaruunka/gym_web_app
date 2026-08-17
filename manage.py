from app import app, db  # importuješ Flask app a SQLAlchemy db
from flask_migrate import Migrate

migrate = Migrate(app, db)

if __name__ == "__main__":
    app.run(debug=True)