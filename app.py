

import sys
import os

print("Running Python version:", sys.version)

from flask import Flask, render_template, request
from datetime import date
from flask_sqlalchemy import SQLAlchemy  # <- tohle musí být před db = SQLAlchemy(app)

# --- cesta k šablonám ---
templates_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

# --- vytvoření Flask aplikace ---
app = Flask(__name__, template_folder=templates_path)

# --- test existence ---
print("Current working directory:", os.getcwd())
print("Templates folder exists?", os.path.exists(templates_path))
print("Index.html exists?", os.path.exists(os.path.join(templates_path, "index.html")))
print("Flask template folder:", app.template_folder)

# --- Nastavení databáze ---
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///gym.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)  # <- teď už bude fungovat

# --- Třída Workout ---
class Workout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    exercise = db.Column(db.String(100))

    # silové cviky
    weight = db.Column(db.Integer, nullable=True)
    reps = db.Column(db.Integer, nullable=True)
    set_number = db.Column(db.Integer, nullable=True)

    # kardio cviky
    minutes = db.Column(db.Integer, nullable=True)
    speed = db.Column(db.Float, nullable=True)
    incline = db.Column(db.Float, nullable=True)

# --- Routes ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/zadat", methods=["GET", "POST"])
def zadat():
    selected_date = request.form.get("date") or request.args.get("date") or date.today().isoformat()
    exercise = request.form.get("exercise") or request.args.get("exercise") or "Dřepy"
    message = ""

    count_sets = Workout.query.filter_by(date=selected_date, exercise=exercise).count()
    next_set = count_sets + 1

    if request.method == "POST":
        date_val = request.form.get("date") or date.today().isoformat()
        exercise_val = request.form.get("exercise") or "Dřepy"

        if exercise_val == "Běh na pásu":
            minutes = int(request.form.get("minutes") or 0)
            speed = float(request.form.get("speed") or 0)
            incline = float(request.form.get("incline") or 0)
            novy_trenink = Workout(date=date_val, exercise=exercise_val, minutes=minutes, speed=speed, incline=incline)
            message = "Kardio záznam uložen!"
        else:
            weight = int(request.form.get("weight") or 0)
            reps = int(request.form.get("reps") or 0)
            count_sets = Workout.query.filter_by(date=date_val, exercise=exercise_val).count()
            set_number = count_sets + 1
            novy_trenink = Workout(date=date_val, exercise=exercise_val, weight=weight, reps=reps, set_number=set_number)
            message = f"Série {set_number} uložena!"
            next_set = set_number + 1

        db.session.add(novy_trenink)
        db.session.commit()

        return render_template("zadat.html", today=date_val, next_set=next_set, exercise=exercise_val, message=message)

    return render_template("zadat.html", today=selected_date, next_set=next_set, exercise=exercise, message=message)

@app.route("/historie")
def historie():
    workouts = Workout.query.order_by(Workout.id.desc()).all()
    return render_template("historie.html", workouts=workouts)

# --- Vytvoření tabulek ---
with app.app_context():
    db.create_all()
 

# --- cesta k šablonám ---
templates_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

# --- vytvoření Flask aplikace ---
app = Flask(__name__, template_folder=templates_path)

# --- test existence ---
print("Current working directory:", os.getcwd())
print("Templates folder exists?", os.path.exists(templates_path))
print("Index.html exists?", os.path.exists(os.path.join(templates_path, "index.html")))
print("Flask template folder:", app.template_folder)

# --- Nastavení databáze ---
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///gym.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)  # <- teď už bude fungovat

# --- Třída Workout ---
class Workout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    exercise = db.Column(db.String(100))

    # silové cviky
    weight = db.Column(db.Integer, nullable=True)
    reps = db.Column(db.Integer, nullable=True)
    set_number = db.Column(db.Integer, nullable=True)

    # kardio cviky
    minutes = db.Column(db.Integer, nullable=True)
    speed = db.Column(db.Float, nullable=True)
    incline = db.Column(db.Float, nullable=True)

# --- Routes ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/zadat", methods=["GET", "POST"])
def zadat():
    selected_date = request.form.get("date") or request.args.get("date") or date.today().isoformat()
    exercise = request.form.get("exercise") or request.args.get("exercise") or "Dřepy"
    message = ""

    count_sets = Workout.query.filter_by(date=selected_date, exercise=exercise).count()
    next_set = count_sets + 1

    if request.method == "POST":
        date_val = request.form.get("date") or date.today().isoformat()
        exercise_val = request.form.get("exercise") or "Dřepy"

        if exercise_val == "Běh na pásu":
            minutes = int(request.form.get("minutes") or 0)
            speed = float(request.form.get("speed") or 0)
            incline = float(request.form.get("incline") or 0)
            novy_trenink = Workout(date=date_val, exercise=exercise_val, minutes=minutes, speed=speed, incline=incline)
            message = "Kardio záznam uložen!"
        else:
            weight = int(request.form.get("weight") or 0)
            reps = int(request.form.get("reps") or 0)
            count_sets = Workout.query.filter_by(date=date_val, exercise=exercise_val).count()
            set_number = count_sets + 1
            novy_trenink = Workout(date=date_val, exercise=exercise_val, weight=weight, reps=reps, set_number=set_number)
            message = f"Série {set_number} uložena!"
            next_set = set_number + 1

        db.session.add(novy_trenink)
        db.session.commit()

        return render_template("zadat.html", today=date_val, next_set=next_set, exercise=exercise_val, message=message)

    return render_template("zadat.html", today=selected_date, next_set=next_set, exercise=exercise, message=message)

@app.route("/historie")
def historie():
    workouts = Workout.query.order_by(Workout.id.desc()).all()
    return render_template("historie.html", workouts=workouts)

# --- Vytvoření tabulek ---
with app.app_context():
    db.create_all()

# --- Spuštění ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)