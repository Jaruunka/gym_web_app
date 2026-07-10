print("START MIGRACE")
from app import app, db, User, Workout
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# připojení ke staré SQLite databázi
sqlite_engine = create_engine("sqlite:///gym_2.db")
SQLiteSession = sessionmaker(bind=sqlite_engine)

old_session = SQLiteSession()

with app.app_context():

    # načteme stará data
    old_users = old_session.query(User).all()
    old_workouts = old_session.query(Workout).all()

    print("Starých uživatelů:", len(old_users))
    print("Starých tréninků:", len(old_workouts))

    # vložení uživatelů do Supabase
    for old_user in old_users:
        exists = User.query.filter_by(email=old_user.email).first()

        if not exists:
            new_user = User(
                id=old_user.id,
                email=old_user.email,
                password_hash=old_user.password_hash
            )
            db.session.add(new_user)

    db.session.commit()

    # vložení tréninků
    for old_workout in old_workouts:
        new_workout = Workout(
            id=old_workout.id,
            date=old_workout.date,
            exercise=old_workout.exercise,
            user_id=old_workout.user_id,
            weight=old_workout.weight,
            reps=old_workout.reps,
            set_number=old_workout.set_number,
            minutes=old_workout.minutes,
            speed=old_workout.speed,
            incline=old_workout.incline,
            band_color=old_workout.band_color
        )

        db.session.add(new_workout)

    db.session.commit()

    print("Migrace dokončena!")

old_session.close()