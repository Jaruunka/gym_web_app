import os
import math
import hmac
import json
import hashlib
from urllib.request import Request, urlopen
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
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# Seznam silových cviků + kardio
SILOVE_CVIKY = [
    "Dřepy", "Hip thrust", "Benchpress", "Rumuny", "Bulhary",
    "Abduction", "Adduction", "Kladivový zdvih", "Hyper extension",
    "Torso twist", "Lat pull down – široký úchop",
    "Lat pull down – úzký neutrální úchop", "Cable row", "Leg press", "Shyb", "Triceps tlak",
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
    note = db.Column(db.Text, nullable=True)


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

class CustomExercise(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    has_weight = db.Column(db.Boolean, default=True)
    has_reps = db.Column(db.Boolean, default=True)
    has_speed = db.Column(db.Boolean, default=False)
    has_note = db.Column(db.Boolean, default=False)

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_custom_exercise_user_name"),
    )

# LOGIN MANAGER
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@app.before_request
def migrate_renamed_exercises():
    """Jednorázově převede staré názvy cviků na jejich nové varianty."""
    if app.config.get("EXERCISE_NAMES_MIGRATED"):
        return

    old_name = "Lat pull down"
    new_name = "Lat pull down – široký úchop"

    Workout.query.filter_by(exercise=old_name).update(
        {Workout.exercise: new_name},
        synchronize_session=False
    )
    FavoriteExercise.query.filter_by(exercise=old_name).update(
        {FavoriteExercise.exercise: new_name},
        synchronize_session=False
    )
    db.session.commit()
    app.config["EXERCISE_NAMES_MIGRATED"] = True

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def get_exercise_choices():
    favorite_exercises = {
        item.exercise
        for item in FavoriteExercise.query.filter_by(user_id=current_user.id).all()
    }
    
    custom_exercises = CustomExercise.query.filter_by(user_id=current_user.id).all()
    custom_names = [ce.name for ce in custom_exercises]
    
    all_available = SILOVE_CVIKY + custom_names
    
    ordered_exercises = sorted(
        all_available,
        key=lambda exercise_name: exercise_name not in favorite_exercises
    )
    return ordered_exercises, favorite_exercises, custom_exercises


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


def get_password_reset_serializer():
    return URLSafeTimedSerializer(
        app.config["SECRET_KEY"],
        salt="password-reset"
    )


def create_password_reset_token(user):
    return get_password_reset_serializer().dumps({
        "user_id": user.id,
        "password_version": user.password_hash[-20:]
    })


def get_user_from_password_reset_token(token, max_age=3600):
    try:
        token_data = get_password_reset_serializer().loads(
            token,
            max_age=max_age
        )
    except (BadSignature, SignatureExpired):
        return None

    user = db.session.get(User, token_data.get("user_id"))
    if user is None:
        return None

    password_version = str(token_data.get("password_version", ""))
    if not hmac.compare_digest(password_version, user.password_hash[-20:]):
        return None
    return user


def send_password_reset_email(recipient, reset_url):
    webhook_url = os.environ.get("MAIL_WEBHOOK_URL", "").strip()
    webhook_secret = os.environ.get("MAIL_WEBHOOK_SECRET", "").strip()

    if not webhook_url or not webhook_secret:
        raise RuntimeError(
            "Chybí MAIL_WEBHOOK_URL nebo MAIL_WEBHOOK_SECRET."
        )

    payload = json.dumps({
        "secret": webhook_secret,
        "to": recipient,
        "reset_url": reset_url
    }).encode("utf-8")

    request_data = Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urlopen(request_data, timeout=15) as response:
        response_data = json.loads(response.read().decode("utf-8"))

    if not response_data.get("ok"):
        raise RuntimeError(
            response_data.get("error", "E-mail se nepodařilo odeslat.")
        )


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


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter(func.lower(User.email) == email).first()

        if user:
            reset_token = create_password_reset_token(user)
            reset_url = url_for(
                "reset_password",
                token=reset_token,
                _external=True,
                _scheme="https" if os.environ.get("RENDER") else None
            )
            try:
                send_password_reset_email(user.email, reset_url)
            except Exception:
                app.logger.exception("Nepodařilo se odeslat e-mail pro obnovu hesla.")

        flash(
            "Pokud je tento e-mail zaregistrovaný, poslaly jsme na něj "
            "odkaz pro nastavení nového hesla."
        )
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = get_user_from_password_reset_token(token)
    if user is None:
        flash("Odkaz pro změnu hesla je neplatný nebo už vypršel.")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        if len(password) < 8:
            flash("Nové heslo musí mít alespoň 8 znaků.")
            return redirect(url_for("reset_password", token=token))
        if password != password_confirm:
            flash("Zadaná hesla se neshodují.")
            return redirect(url_for("reset_password", token=token))

        user.set_password(password)
        db.session.commit()
        flash("Heslo bylo změněno. Teď se můžeš přihlásit.")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token)

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

    # Povolit i vlastní cviky
    custom_exists = CustomExercise.query.filter_by(user_id=current_user.id, name=exercise).first()
    if exercise not in SILOVE_CVIKY and not custom_exists:
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

@app.route("/custom-exercise/add", methods=["POST"])
@login_required
def add_custom_exercise():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Jméno cviku nesmí být prázdné.", "error")
        return redirect(url_for("zadat"))
    
    if name in SILOVE_CVIKY or CustomExercise.query.filter_by(user_id=current_user.id, name=name).first():
        flash("Tento cvik už existuje.", "error")
        return redirect(url_for("zadat"))

    has_weight = "has_weight" in request.form
    has_reps = "has_reps" in request.form
    has_speed = "has_speed" in request.form
    has_note = "has_note" in request.form

    new_ce = CustomExercise(
        user_id=current_user.id,
        name=name,
        has_weight=has_weight,
        has_reps=has_reps,
        has_speed=has_speed,
        has_note=has_note
    )
    db.session.add(new_ce)
    db.session.commit()
    flash(f"Cvik '{name}' byl přidán.", "success")
    return redirect(url_for("zadat", exercise=name))

@app.route("/custom-exercise/delete/<int:ce_id>", methods=["POST"])
@login_required
def delete_custom_exercise(ce_id):
    ce = CustomExercise.query.get_or_404(ce_id)
    if ce.user_id != current_user.id:
        flash("Nemáš oprávnění smazat tento cvik.")
        return redirect(url_for("zadat"))
    
    # Smazat i z oblíbených
    FavoriteExercise.query.filter_by(user_id=current_user.id, exercise=ce.name).delete()
    
    db.session.delete(ce)
    db.session.commit()
    flash(f"Cvik '{ce.name}' byl smazán.", "success")
    return redirect(url_for("zadat"))

@app.route("/zadat", methods=["GET", "POST"])
@login_required
def zadat():
    date_val = request.form.get("date") or request.args.get("date") or date.today().isoformat()
    
    # Získání seznamu cviků pro validaci a výběr
    ordered_exercises, favorite_exercises, custom_exercises = get_exercise_choices()
    
    exercise_val = request.form.get("exercise") or request.args.get("exercise") or (ordered_exercises[0] if ordered_exercises else SILOVE_CVIKY[0])

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
                weight = None
                reps = None
                speed = None
                note = request.form.get("note")

                # Pokud je to vlastní cvik, respektujeme jeho nastavení
                ce = next((c for c in custom_exercises if c.name == exercise_val), None)
                
                is_shyb = (exercise_val == "Shyb")
                
                if ce:
                    if ce.has_weight:
                        weight = parse_decimal(request.form.get("weight"), "váha")
                    if ce.has_reps:
                        reps = parse_positive_integer(request.form.get("reps"), "opakování")
                    if ce.has_speed:
                        speed = parse_decimal(request.form.get("speed"), "rychlost")
                else:
                    # Standardní cviky
                    if not is_shyb:
                        weight = parse_decimal(request.form.get("weight"), "váha")
                    reps = parse_positive_integer(request.form.get("reps"), "opakování")

                band_color = request.form.get("band_color") if is_shyb else None

                novy_trenink = Workout(
                    date=date_val,
                    exercise=exercise_val,
                    weight=weight,
                    reps=reps,
                    speed=speed,
                    note=note,
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

    previous_date, previous_workouts, personal_record = get_exercise_progress(
        exercise_val,
        date_val
    )

    return render_template(
        "zadat.html", today=date_val, exercise=exercise_val,
        next_set=next_set, message=message, silove_cviky=ordered_exercises,
        favorite_exercises=favorite_exercises,
        custom_exercises=custom_exercises,
        previous_date=previous_date,
        previous_workouts=previous_workouts,
        personal_record=personal_record,
        last_weight=last_weight
    )

@app.route("/historie")
@login_required
def historie():
    workout_dates = [
        str(row[0])
        for row in db.session.query(Workout.date)
        .filter(Workout.user_id == current_user.id)
        .distinct()
        .order_by(Workout.date.desc())
        .all()
    ]

    return render_template(
        "historie.html",
        workout_dates=workout_dates,
        today_iso=date.today().isoformat()
    )


@app.route("/historie/den/<date_value>")
@login_required
def trenink_dne(date_value):
    workouts = Workout.query.filter_by(
        user_id=current_user.id,
        date=date_value
    ).order_by(
        Workout.id.asc()
    ).all()

    if not workouts:
        flash("Pro tento den nebyl nalezen žádný trénink.")
        return redirect(url_for("historie"))

    grouped = {}

    for workout in workouts:
        grouped.setdefault(workout.exercise, []).append(workout)

    exercise_groups = [
        {
            "name": exercise_name,
            "workouts": exercise_workouts
        }
        for exercise_name, exercise_workouts in grouped.items()
    ]

    custom_exercises = CustomExercise.query.filter_by(
        user_id=current_user.id
    ).all()
    custom_exercise_settings = {
        exercise.name: exercise
        for exercise in custom_exercises
    }

    return render_template(
        "trenink_dne.html",
        selected_date=date_value,
        exercise_groups=exercise_groups,
        custom_exercise_settings=custom_exercise_settings,
    )


@app.route("/historie/cvik/<path:exercise>")
@login_required
def detail_cviku(exercise):
    workouts = Workout.query.filter_by(
        user_id=current_user.id,
        exercise=exercise
    ).order_by(
        Workout.date.desc(),
        Workout.set_number.asc(),
        Workout.id.asc()
    ).all()

    if not workouts:
        flash("Pro tento cvik nebyly nalezeny žádné záznamy.")
        return redirect(url_for("historie"))

    grouped_dates = {}

    for workout in workouts:
        grouped_dates.setdefault(
            str(workout.date),
            []
        ).append(workout)

    date_groups = [
        {
            "date": workout_date,
            "workouts": date_workouts
        }
        for workout_date, date_workouts in grouped_dates.items()
    ]

    workouts_with_weight = [
        workout
        for workout in workouts
        if workout.weight is not None
    ]

    workouts_with_reps = [
        workout
        for workout in workouts
        if workout.reps is not None
    ]

    workouts_with_speed = [
        workout
        for workout in workouts
        if workout.speed is not None
    ]

    if workouts_with_weight:
        personal_record = max(
            workouts_with_weight,
            key=lambda workout: (
                workout.weight,
                workout.reps or 0
            )
        )
    elif workouts_with_reps:
        personal_record = max(
            workouts_with_reps,
            key=lambda workout: workout.reps
        )
    elif workouts_with_speed:
        personal_record = max(
            workouts_with_speed,
            key=lambda workout: workout.speed
        )
    else:
        personal_record = None

    best_by_date = {}

    for workout in workouts:
        if workout.weight is None and workout.reps is None:
            continue

        date_key = str(workout.date)
        current_best = best_by_date.get(date_key)

        workout_score = (
            workout.weight if workout.weight is not None else -1,
            workout.reps if workout.reps is not None else -1
        )

        if current_best is None:
            best_by_date[date_key] = workout
            continue

        current_score = (
            current_best.weight
            if current_best.weight is not None
            else -1,
            current_best.reps
            if current_best.reps is not None
            else -1
        )

        if workout_score > current_score:
            best_by_date[date_key] = workout

    chart_labels = []
    chart_weights = []
    chart_reps = []

    for date_key in sorted(best_by_date):
        best_workout = best_by_date[date_key]

        chart_labels.append(date_key)
        chart_weights.append(
            float(best_workout.weight)
            if best_workout.weight is not None
            else None
        )
        chart_reps.append(best_workout.reps)

    return render_template(
        "detail_cviku.html",
        exercise=exercise,
        personal_record=personal_record,
        date_groups=date_groups,
        chart_labels=chart_labels,
        chart_weights=chart_weights,
        chart_reps=chart_reps
    )


@app.route("/historie/vse")
@login_required
def vsechny_treninky():
    selected_exercise = request.args.get(
        "exercise",
        ""
    ).strip()

    today = date.today()
    current_month_prefix = today.strftime("%Y-%m")

    month_names = [
        "Leden", "Únor", "Březen", "Duben",
        "Květen", "Červen", "Červenec", "Srpen",
        "Září", "Říjen", "Listopad", "Prosinec"
    ]

    current_month_name = month_names[today.month - 1]

    workout_dates = db.session.query(
        Workout.date
    ).filter(
        Workout.user_id == current_user.id
    ).all()

    current_month_workout_dates = {
        str(row[0])
        for row in workout_dates
        if str(row[0]).startswith(current_month_prefix)
    }

    monthly_workout_count = len(
        current_month_workout_dates
    )

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
                    and (workout.reps or 0)
                    > (current_best.reps or 0)
                )
            ):
                best_by_date[date_key] = workout

        for date_key in sorted(best_by_date):
            best_workout = best_by_date[date_key]

            chart_labels.append(date_key)
            chart_weights.append(
                float(best_workout.weight)
            )
            chart_reps.append(
                best_workout.reps or 0
            )

    return render_template(
        "vsechny_treninky.html",
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

@app.route("/api/offline-manifest")
@login_required
def offline_manifest():
    """Malý offline balíček: zápis a pouze dnešní trénink."""
    today_iso = date.today().isoformat()
    today_workouts = Workout.query.filter_by(
        user_id=current_user.id,
        date=today_iso,
    ).order_by(Workout.id.asc()).all()

    custom_exercises = CustomExercise.query.filter_by(
        user_id=current_user.id
    ).order_by(CustomExercise.id.asc()).all()

    favorite_exercises = FavoriteExercise.query.filter_by(
        user_id=current_user.id
    ).order_by(FavoriteExercise.id.asc()).all()

    urls = [
        url_for("index"),
        url_for("zadat"),
        url_for("historie"),
    ]

    if today_workouts:
        urls.append(url_for("trenink_dne", date_value=today_iso))

    version_payload = {
        "today": today_iso,
        "today_workouts": [
            [
                workout.id,
                str(workout.date),
                workout.exercise,
                workout.weight,
                workout.reps,
                workout.set_number,
                workout.minutes,
                workout.speed,
                workout.incline,
                workout.band_color,
                workout.note,
            ]
            for workout in today_workouts
        ],
        "custom_exercises": [
            [
                exercise.id,
                exercise.name,
                exercise.has_weight,
                exercise.has_reps,
                exercise.has_speed,
                exercise.has_note,
            ]
            for exercise in custom_exercises
        ],
        "favorites": [
            [favorite.id, favorite.exercise]
            for favorite in favorite_exercises
        ],
    }
    version = hashlib.sha256(
        json.dumps(
            version_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:20]

    return jsonify({
        "version": version,
        "urls": list(dict.fromkeys(urls)),
    })


@app.route("/delete/<int:workout_id>", methods=["POST"])
@login_required
def delete_workout(workout_id):
    # Offline fronta nebo starší cachovaná stránka může stejný požadavek
    # odeslat podruhé. Smazání proto držíme idempotentní: neexistující záznam
    # není chyba a uživatel se místo 404 bezpečně vrátí do historie.
    workout = db.session.get(Workout, workout_id)
    if workout is None:
        flash("Záznam už byl smazán.", "success")
        return redirect(url_for("historie"))
    if workout.user_id != current_user.id:
        flash("Nemáš oprávnění mazat tento záznam!")
        return redirect(url_for("historie"))
    workout_date = str(workout.date)
    db.session.delete(workout)
    db.session.commit()
    flash("Záznam smazán!")
    if request.form.get("return_to_day") == "1":
        remaining = Workout.query.filter_by(
            user_id=current_user.id,
            date=workout_date,
        ).first()
        if remaining:
            return redirect(url_for("trenink_dne", date_value=workout_date))
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
                custom_exercise = CustomExercise.query.filter_by(
                    user_id=current_user.id,
                    name=workout.exercise,
                ).first()

                if custom_exercise:
                    workout.weight = (
                        parse_decimal(request.form.get("weight"), "váha")
                        if custom_exercise.has_weight
                        else None
                    )
                    workout.reps = (
                        parse_positive_integer(request.form.get("reps"), "opakování")
                        if custom_exercise.has_reps
                        else None
                    )
                    workout.speed = (
                        parse_decimal(request.form.get("speed"), "rychlost")
                        if custom_exercise.has_speed
                        else None
                    )
                    if custom_exercise.has_note and "note" in request.form:
                        workout.note = request.form.get("note")
                else:
                    workout.weight = (
                        None
                        if workout.exercise == "Shyb"
                        else parse_decimal(request.form.get("weight"), "váha")
                    )
                    workout.reps = parse_positive_integer(request.form.get("reps"), "opakování")
                    workout.speed = None

                workout.set_number = parse_positive_integer(request.form.get("set_number"), "série")
                workout.band_color = request.form.get("band_color") if workout.exercise == "Shyb" else None
                workout.minutes = None
                workout.incline = None
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("edit_workout", workout_id=workout.id))

        db.session.commit()
        flash("Záznam upraven!")
        if request.form.get("return_to_day") == "1":
            return redirect(url_for("trenink_dne", date_value=workout.date))
        return redirect(url_for("historie"))

    ordered_exercises, favorite_exercises, custom_exercises = get_exercise_choices()
    return render_template(
        "edit_workout.html",
        workout=workout,
        silove_cviky=ordered_exercises,
        favorite_exercises=favorite_exercises
    )

@app.route('/service-worker.js')
def service_worker():
    response = send_from_directory(
        'static',
        'service-worker.js',
        mimetype='application/javascript'
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.route('/pwa-test')
def pwa_test():
    return render_template('pwa_test.html')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
