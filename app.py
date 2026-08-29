import os
import math
from datetime import date
from collections import defaultdict
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
import io
from flask_migrate import Migrate
from email_validator import validate_email, EmailNotValidError
from sqlalchemy import func

# Seznam silových cviků + kardio
SILOVE_CVIKY = [
    "Dřepy", "Hip thrust", "Benchpress", "Rumuny", "Bulhary",
    "Abduction", "Adduction", "Kladivový zdvih", "Hyper extension",
    "Torso twist", "Lat pull down", "Cable row", "Leg press", "Shyb", "Triceps tlak",
    "Cable wood chop", "Cable Crunch", "Triceps Rope Pushdown",
    "Seated low row", "Lateral raises", "Běh na pásu"
]

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__, template_folder=os.path.join(basedir, "templates"))
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "super-secret-key")

db_url = os.environ.get("DATABASE_URL")

if db_url:
    db_url = db_url.replace("postgres://", "postgresql://")
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(basedir, "gym_2.db")

app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True
}

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# MODELY

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(
            password,
            method="pbkdf2:sha256"
        )

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Workout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    exercise = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    weight = db.Column(db.Float, nullable=True)
    reps = db.Column(db.Integer, nullable=True)
    set_number = db.Column(db.Integer, nullable=True)
    minutes = db.Column(db.Integer, nullable=True)
    speed = db.Column(db.Float, nullable=True)
    incline = db.Column(db.Float, nullable=True)
    band_color = db.Column(db.String(50), nullable=True)


class FavoriteExercise(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False
    )
    exercise = db.Column(db.String(100), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("user_id", "exercise", name="uq_favorite_exercise_user_exercise"),
    )

# LOGIN MANAGER
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def get_exercise_choices():
    favorite_exercises = {
        item.exercise
        for item in FavoriteExercise.query.filter_by(user_id=current_user.id).all()
    }
    ordered_exercises = sorted(
        SILOVE_CVIKY,
        key=lambda exercise_name: exercise_name not in favorite_exercises
    )
    return ordered_exercises, favorite_exercises


def parse_decimal(value, field_name):
    normalized_value = (value or "").strip().replace(",", ".")
    if not normalized_value:
        raise ValueError(f"Vyplň pole {field_name}.")

    try:
        number = float(normalized_value)
    except ValueError as exc:
        raise ValueError(
            f"Pole {field_name} musí být číslo. Můžeš použít čárku i tečku."
        ) from exc

    if not math.isfinite(number):
        raise ValueError(f"Pole {field_name} musí být běžné číslo.")
    if number < 0:
        raise ValueError(f"Pole {field_name} nemůže být záporné.")
    return number


def parse_positive_integer(value, field_name):
    try:
        number = int((value or "").strip())
    except ValueError as exc:
        raise ValueError(f"Pole {field_name} musí být celé číslo.") from exc

    if number < 1:
        raise ValueError(f"Pole {field_name} musí být alespoň 1.")
    return number


def get_exercise_progress(exercise, selected_date):
    previous_date = db.session.query(db.func.max(Workout.date)).filter(
        Workout.user_id == current_user.id,
        Workout.exercise == exercise,
        Workout.date < selected_date
    ).scalar()

    previous_workouts = []
    if previous_date:
        previous_workouts = Workout.query.filter_by(
            user_id=current_user.id,
            exercise=exercise,
            date=previous_date
        ).order_by(Workout.set_number.asc()).all()

    personal_record = None
    if exercise not in {"Běh na pásu", "Shyb"}:
        personal_record = Workout.query.filter(
            Workout.user_id == current_user.id,
            Workout.exercise == exercise,
            Workout.weight.isnot(None)
        ).order_by(Workout.weight.desc(), Workout.reps.desc()).first()

    return previous_date, previous_workouts, personal_record


@app.template_filter("number")
def format_number(value):
    if value is None:
        return ""
    return f"{float(value):g}"


@app.template_filter("czech_date")
def format_czech_date(value):
    parsed_date = date.fromisoformat(str(value))
    return f"{parsed_date.day}. {parsed_date.month}. {parsed_date.year}"

# --- FUNKCE PRO TRANSFORMACI WORKOUTŮ ---
def transform_workouts(workouts):
    grouped = defaultdict(list)
    exercises = set()

    for w in workouts:
        grouped[w.date].append(w)
        exercises.add(w.exercise)

    exercises = sorted(exercises)
    table_data = []

    for date_val, items in grouped.items():
        max_set = max((w.set_number or 1) for w in items)

        for s in range(max_set, 0, -1):
            row = {
                "date": date_val if s == max_set else "",
                "workout_actions": []
            }

            for ex in exercises:
                found = next(
                    (
                        w for w in items
                        if w.exercise == ex
                        and (w.set_number or 1) == s
                    ),
                    None
                )

                if found:
                    row[f"{ex}_weight"] = (
                        found.weight if found.weight is not None else ""
                    )
                    row[f"{ex}_reps"] = (
                        found.reps if found.reps is not None else ""
                    )

                    if found.exercise == "Běh na pásu":
                        action_label = (
                            f"{found.exercise} – "
                            f"{found.minutes or 0} min"
                        )
                    else:
                        action_label = (
                            f"{found.exercise} – série "
                            f"{found.set_number or 1}"
                        )

                    row["workout_actions"].append({
                        "id": found.id,
                        "label": action_label
                    })
                else:
                    row[f"{ex}_weight"] = ""
                    row[f"{ex}_reps"] = ""

            table_data.append(row)

    return table_data, exercises

# --- ROUTES ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email_input = request.form.get("email", "").strip()
        password = request.form.get("password")
        password_confirm = request.form.get("password_confirm")

        if not email_input or not password or not password_confirm:
            flash("Vyplň e-mail a obě pole s heslem.")
            return redirect(url_for("register"))
        if password != password_confirm:
            flash("Hesla se neshodují.")
            return redirect(url_for("register"))

        try:
            email = validate_email(
                email_input,
                check_deliverability=False
            ).normalized.lower()
        except EmailNotValidError:
            flash("Zadej platnou e-mailovou adresu.")
            return redirect(url_for("register"))

        if User.query.filter(func.lower(User.email) == email).first():
            flash("Uživatel už existuje!")
            return redirect(url_for("register"))
        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Registrace hotova! Teď se můžeš přihlásit.")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password")
        user = User.query.filter(func.lower(User.email) == email).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("index"))
        flash("Špatné údaje!")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Odhlášeno!")
    return redirect(url_for("login"))


@app.route("/favorite-exercise", methods=["POST"])
@login_required
def favorite_exercise():
    exercise = request.form.get("exercise", "").strip()
    is_favorite = request.form.get("is_favorite") == "true"

    if exercise not in SILOVE_CVIKY:
        return jsonify({"error": "Neznámý cvik"}), 400

    favorite = FavoriteExercise.query.filter_by(
        user_id=current_user.id,
        exercise=exercise
    ).first()

    if is_favorite and favorite is None:
        db.session.add(FavoriteExercise(
            user_id=current_user.id,
            exercise=exercise
        ))
    elif not is_favorite and favorite is not None:
        db.session.delete(favorite)

    db.session.commit()
    return jsonify({"exercise": exercise, "is_favorite": is_favorite})

@app.route("/zadat", methods=["GET", "POST"])
@login_required
def zadat():
    date_val = request.form.get("date") or request.args.get("date") or date.today().isoformat()
    exercise_val = request.form.get("exercise") or request.args.get("exercise") or SILOVE_CVIKY[0]

    message = ""
    next_set = 1
    last_weight = ""

    if exercise_val != "Běh na pásu":
        last_set_today = Workout.query.filter_by(
            date=date_val, exercise=exercise_val, user_id=current_user.id
        ).order_by(Workout.set_number.desc()).first()

        next_set = last_set_today.set_number + 1 if last_set_today and last_set_today.set_number else 1

        last_set_ever = Workout.query.filter_by(
            exercise=exercise_val, user_id=current_user.id
        ).order_by(Workout.id.desc()).first()

        if last_set_ever and last_set_ever.weight:
            last_weight = last_set_ever.weight
    else:
        next_set = None

    if request.method == "POST":
        try:
            if exercise_val == "Běh na pásu":
                minutes = parse_positive_integer(request.form.get("minutes"), "čas")
                speed = parse_decimal(request.form.get("speed"), "rychlost")
                incline = parse_decimal(request.form.get("incline"), "stoupání")
                novy_trenink = Workout(
                    date=date_val, exercise=exercise_val,
                    minutes=minutes, speed=speed, incline=incline,
                    user_id=current_user.id
                )
                message = "Kardio záznam uložen!"
            else:
                weight = (
                    None
                    if exercise_val == "Shyb"
                    else parse_decimal(request.form.get("weight"), "váha")
                )
                reps = parse_positive_integer(request.form.get("reps"), "opakování")
                band_color = request.form.get("band_color") if exercise_val == "Shyb" else None

                novy_trenink = Workout(
                    date=date_val,
                    exercise=exercise_val,
                    weight=weight,
                    reps=reps,
                    set_number=next_set,
                    user_id=current_user.id,
                    band_color=band_color
                )
                message = f"Série {next_set} uložena!"
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("zadat", date=date_val, exercise=exercise_val))

        db.session.add(novy_trenink)
        db.session.commit()
        flash(message, "success")
        return redirect(url_for("zadat", date=date_val, exercise=exercise_val))

    ordered_exercises, favorite_exercises = get_exercise_choices()
    previous_date, previous_workouts, personal_record = get_exercise_progress(
        exercise_val,
        date_val
    )

    return render_template(
        "zadat.html", today=date_val, exercise=exercise_val,
        next_set=next_set, message=message, silove_cviky=ordered_exercises,
        favorite_exercises=favorite_exercises,
        previous_date=previous_date,
        previous_workouts=previous_workouts,
        personal_record=personal_record,
        last_weight=last_weight
    )

@app.route("/historie")
@login_required
def historie():
    selected_exercise = request.args.get("exercise", "").strip()
    today = date.today()
    current_month_prefix = today.strftime("%Y-%m")

    month_names = [
        "Leden", "Únor", "Březen", "Duben",
        "Květen", "Červen", "Červenec", "Srpen",
        "Září", "Říjen", "Listopad", "Prosinec"
    ]

    current_month_name = month_names[today.month - 1]

    workout_dates = db.session.query(Workout.date).filter(
        Workout.user_id == current_user.id
    ).all()

    current_month_workout_dates = {
        str(row[0])
        for row in workout_dates
        if str(row[0]).startswith(current_month_prefix)
    }

    monthly_workout_count = len(current_month_workout_dates)

    all_exercises = [
        row[0]
        for row in db.session.query(Workout.exercise)
        .filter(Workout.user_id == current_user.id)
        .distinct()
        .order_by(Workout.exercise)
        .all()
    ]

    workouts_query = Workout.query.filter_by(
        user_id=current_user.id
    )

    if selected_exercise:
        workouts_query = workouts_query.filter(
            Workout.exercise == selected_exercise
        )

    workouts = workouts_query.order_by(
        Workout.date.desc(),
        Workout.set_number.desc()
    ).all()

    table_data, exercises = transform_workouts(workouts)

    chart_labels = []
    chart_weights = []
    chart_reps = []

    if selected_exercise:
        best_by_date = {}

        for workout in workouts:
            if workout.weight is None:
                continue

            date_key = str(workout.date)
            current_best = best_by_date.get(date_key)

            if (
                current_best is None
                or workout.weight > current_best.weight
                or (
                    workout.weight == current_best.weight
                    and (workout.reps or 0) > (current_best.reps or 0)
                )
            ):
                best_by_date[date_key] = workout

        for date_key in sorted(best_by_date):
            best_workout = best_by_date[date_key]

            chart_labels.append(date_key)
            chart_weights.append(float(best_workout.weight))
            chart_reps.append(best_workout.reps or 0)
    return render_template(
        "historie.html",
        table_data=table_data,
        exercises=exercises,
        all_exercises=all_exercises,
        selected_exercise=selected_exercise,
        chart_labels=chart_labels,
        chart_weights=chart_weights,
        chart_reps=chart_reps,
        current_month_name=current_month_name,
        monthly_workout_count=monthly_workout_count
    )
@app.route("/export_excel")
@login_required
def export_excel():
    workouts = Workout.query.filter_by(user_id=current_user.id).order_by(Workout.date.asc()).all()
    table_data, exercises = transform_workouts(workouts)
    df = pd.DataFrame(table_data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="Workouts")
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        download_name="workouts.xlsx",
        as_attachment=True
    )

@app.route("/delete/<int:workout_id>")
@login_required
def delete_workout(workout_id):
    workout = Workout.query.get_or_404(workout_id)
    if workout.user_id != current_user.id:
        flash("Nemáš oprávnění mazat tento záznam!")
        return redirect(url_for("historie"))
    db.session.delete(workout)
    db.session.commit()
    flash("Záznam smazán!")
    return redirect(url_for("historie"))

@app.route("/edit/<int:workout_id>", methods=["GET", "POST"], endpoint="edit_workout")
@login_required
def edit_workout(workout_id):
    workout = Workout.query.get_or_404(workout_id)
    if workout.user_id != current_user.id:
        flash("Nemáš oprávnění upravit tento záznam!")
        return redirect(url_for("historie"))

    if request.method == "POST":
        workout.date = request.form.get("date")
        workout.exercise = request.form.get("exercise")
        try:
            if workout.exercise == "Běh na pásu":
                workout.minutes = parse_positive_integer(request.form.get("minutes"), "čas")
                workout.speed = parse_decimal(request.form.get("speed"), "rychlost")
                workout.incline = parse_decimal(request.form.get("incline"), "stoupání")
                workout.weight = None
                workout.reps = None
                workout.set_number = None
                workout.band_color = None
            else:
                workout.weight = (
                    None
                    if workout.exercise == "Shyb"
                    else parse_decimal(request.form.get("weight"), "váha")
                )
                workout.reps = parse_positive_integer(request.form.get("reps"), "opakování")
                workout.set_number = parse_positive_integer(request.form.get("set_number"), "série")
                workout.band_color = request.form.get("band_color") if workout.exercise == "Shyb" else None
                workout.minutes = None
                workout.speed = None
                workout.incline = None
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("edit_workout", workout_id=workout.id))

        db.session.commit()
        flash("Záznam upraven!")
        return redirect(url_for("historie"))

    ordered_exercises, favorite_exercises = get_exercise_choices()
    return render_template(
        "edit_workout.html",
        workout=workout,
        silove_cviky=ordered_exercises,
        favorite_exercises=favorite_exercises
    )

@app.route('/service-worker.js')
def service_worker():
    return send_from_directory(
        'static',
        'service-worker.js',
        mimetype='application/javascript'
    )


@app.route('/pwa-test')
def pwa_test():
    return render_template('pwa_test.html')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
