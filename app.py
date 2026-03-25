import os
from datetime import date
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# --- složka s app.py ---
basedir = os.path.abspath(os.path.dirname(__file__))

# --- Flask app ---
app = Flask(__name__, template_folder=os.path.join(basedir, "templates"))
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "super-secret-key")

# --- databáze ---
db_url = os.environ.get("DATABASE_URL")
if db_url:
    db_url = db_url.replace("postgres://", "postgresql://")

app.config["SQLALCHEMY_DATABASE_URI"] = db_url or "sqlite:///" + os.path.join(basedir, "gym.db")
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
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    weight = db.Column(db.Integer, nullable=True)
    reps = db.Column(db.Integer, nullable=True)
    set_number = db.Column(db.Integer, nullable=True)

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
        try:
            email = request.form.get("email")
            password = request.form.get("password")

            if not email or not password:
                flash("Vyplň email i heslo")
                return redirect(url_for("register"))

            if User.query.filter_by(email=email).first():
                flash("Uživatel už existuje!")
                return redirect(url_for("register"))

            user = User(email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

            flash("Registrace hotova! Teď se můžeš přihlásit.")
            return redirect(url_for("login"))

        except Exception as e:
            flash(f"Chyba při registraci: {e}")
            return redirect(url_for("register"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            email = request.form.get("email")
            password = request.form.get("password")

            user = User.query.filter_by(email=email).first()

            if user and user.check_password(password):
                login_user(user)
                return redirect(url_for("index"))
            else:
                flash("Špatné údaje!")
                return redirect(url_for("login"))

        except Exception as e:
            flash(f"Chyba při přihlášení: {e}")
            return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Odhlášeno!")
    return redirect(url_for("login"))


@app.route("/zadat", methods=["GET", "POST"])
@login_required
def zadat():
    message = ""

    # --- určení aktuálního cviku a data podle POST (pokud existuje) nebo GET ---
    date_val = request.form.get("date") or date.today().isoformat()
    exercise_val = request.form.get("exercise") or "Dřepy"

    # --- počet sérií pro tento cvik a datum ---
    if exercise_val != "Běh na pásu":
        count_sets = Workout.query.filter_by(
            date=date_val,
            exercise=exercise_val,
            user_id=current_user.id
        ).count()
        next_set = count_sets + 1
    else:
        next_set = None

    if request.method == "POST":
        if exercise_val == "Běh na pásu":
            minutes = int(request.form.get("minutes") or 0)
            speed = float(request.form.get("speed") or 0)
            incline = float(request.form.get("incline") or 0)

            novy_trenink = Workout(
                date=date_val,
                exercise=exercise_val,
                minutes=minutes,
                speed=speed,
                incline=incline,
                user_id=current_user.id,
            )
            message = "Kardio záznam uložen!"
            next_set = None

        else:
            weight = int(request.form.get("weight") or 0)
            reps = int(request.form.get("reps") or 0)

            # Počet sérií jen pro tento cvik a datum
            count_sets = Workout.query.filter_by(
                date=date_val,
                exercise=exercise_val,
                user_id=current_user.id
            ).count()
            set_number = count_sets + 1

            novy_trenink = Workout(
                date=date_val,
                exercise=exercise_val,
                weight=weight,
                reps=reps,
                set_number=set_number,
                user_id=current_user.id,
            )
            message = f"Série {set_number} uložena!"
            next_set = set_number + 1

        db.session.add(novy_trenink)
        db.session.commit()
        flash(message)
        return redirect(url_for("zadat"))

    return render_template(
        "zadat.html",
        today=date_val,
        next_set=next_set,
        exercise=exercise_val,
        message=message
    )


@app.route("/historie")
@login_required
def historie():
    workouts = Workout.query.filter_by(
        user_id=current_user.id
    ).order_by(Workout.id.desc()).all()

    return render_template("historie.html", workouts=workouts)


# --- inicializace databáze při startu ---
with app.app_context():
    db.create_all()


# --- spuštění ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)