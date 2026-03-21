import os
from datetime import date
from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# --- složka s app.py ---
basedir = os.path.abspath(os.path.dirname(__file__))

# --- vytvoření Flask app ---
app = Flask(__name__, template_folder=os.path.join(basedir, "templates"))
app.config["SECRET_KEY"] = "super-secret-key"  # potřebné pro Flask-Login a session
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(basedir, "gym.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# --- modely ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Workout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    exercise = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))  # propojení s User

    # silové cviky
    weight = db.Column(db.Integer, nullable=True)
    reps = db.Column(db.Integer, nullable=True)
    set_number = db.Column(db.Integer, nullable=True)

    # kardio cviky
    minutes = db.Column(db.Integer, nullable=True)
    speed = db.Column(db.Float, nullable=True)
    incline = db.Column(db.Float, nullable=True)

# --- LoginManager ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- routes ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        if User.query.filter_by(email=email).first():
            return "Uživatel už existuje!"

        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return "Registrace hotova! Teď se můžeš přihlásit."
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            return "Přihlášení úspěšné!"
        return "Špatné údaje!"
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return "Odhlášeno!"

@app.route("/zadat", methods=["GET", "POST"])
@login_required
def zadat():
    selected_date = request.form.get("date") or date.today().isoformat()
    exercise = request.form.get("exercise") or "Dřepy"
    message = ""

    count_sets = Workout.query.filter_by(date=selected_date, exercise=exercise, user_id=current_user.id).count()
    next_set = count_sets + 1

    if request.method == "POST":
        date_val = request.form.get("date") or date.today().isoformat()
        exercise_val = request.form.get("exercise") or "Dřepy"

        if exercise_val == "Běh na pásu":
            minutes = int(request.form.get("minutes") or 0)
            speed = float(request.form.get("speed") or 0)
            incline = float(request.form.get("incline") or 0)
            novy_trenink = Workout(date=date_val, exercise=exercise_val, minutes=minutes,
                                   speed=speed, incline=incline, user_id=current_user.id)
            message = "Kardio záznam uložen!"
        else:
            weight = int(request.form.get("weight") or 0)
            reps = int(request.form.get("reps") or 0)
            count_sets = Workout.query.filter_by(date=date_val, exercise=exercise_val, user_id=current_user.id).count()
            set_number = count_sets + 1
            novy_trenink = Workout(date=date_val, exercise=exercise_val, weight=weight, reps=reps,
                                   set_number=set_number, user_id=current_user.id)
            message = f"Série {set_number} uložena!"
            next_set = set_number + 1

        db.session.add(novy_trenink)
        db.session.commit()

        return render_template("zadat.html", today=date_val, next_set=next_set,
                               exercise=exercise_val, message=message)

    return render_template("zadat.html", today=selected_date, next_set=next_set,
                           exercise=exercise, message=message)

@app.route("/historie")
@login_required
def historie():
    workouts = Workout.query.filter_by(user_id=current_user.id).order_by(Workout.id.desc()).all()
    return render_template("historie.html", workouts=workouts)

# --- vytvoření tabulek ---
with app.app_context():
    db.create_all()

# --- spuštění ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)