from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin,
    login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from sqlalchemy.exc import IntegrityError
from sqlalchemy import UniqueConstraint
import calendar
import os

# -------------------- APP SETUP --------------------
app = Flask(__name__)

os.makedirs(app.instance_path, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = \
    'sqlite:///' + os.path.join(app.instance_path, 'habits.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'qwertyuiop'

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

# -------------------- MODELS --------------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    habits = db.relationship('Habit', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    theme = db.Column(db.String(10), default='light')

class Habit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    color = db.Column(db.String(9), default='#3b82f6')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'name', name='user_habit_unique'),
    )


class CheckIn(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    habit_id = db.Column(db.Integer, db.ForeignKey('habit.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)

    __table_args__ = (
        UniqueConstraint('habit_id', 'date', name='habit_checkin_unique'),
    )


with app.app_context():
    db.create_all()

# -------------------- LOGIN MANAGER --------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# -------------------- HELPERS --------------------
def get_streak(habit, today):
    checks = {
        c.date for c in CheckIn.query.filter_by(habit_id=habit.id).all()
    }
    streak = 0
    d = today
    while d in checks:
        streak += 1
        d -= timedelta(days=1)
    return streak


def monthly_calendar(habit, year, month):
    checks = {
        c.date for c in CheckIn.query.filter_by(habit_id=habit.id).all()
    }

    cal = calendar.Calendar(calendar.SUNDAY)
    weeks = cal.monthdatescalendar(year, month)

    grid = []
    for week in weeks:
        row = []
        for d in week:
            row.append({
                "date": d,
                "in_month": d.month == month,
                "checked": d in checks
            })
        grid.append(row)
    return grid

# -------------------- AUTH ROUTES --------------------
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'error')
            return redirect('/signup')

        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        return redirect('/')

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect('/')
        flash('Invalid credentials', 'error')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

# -------------------- DASHBOARD --------------------
@app.route('/')
@login_required
def index():
    today = date.today()
    days = [today - timedelta(days=i) for i in reversed(range(7))]

    habits = Habit.query.filter_by(user_id=current_user.id).all()

    check_map = {
        (c.habit_id, c.date)
        for c in CheckIn.query.filter(CheckIn.date >= days[0]).all()
    }

    streaks = {h.id: get_streak(h, today) for h in habits}

    return render_template(
        'index.html',
        habits=habits,
        days=days,
        today=today,
        check_map=check_map,
        streaks=streaks
    )

# -------------------- HABITS --------------------
@app.route('/habits')
@login_required
def habits():
    habits = Habit.query.filter_by(user_id=current_user.id).all()
    return render_template('habits.html', habits=habits)


@app.route('/habits/create', methods=['POST'])
@login_required
def create_habit():
    name = request.form['name']
    color = request.form.get('color', '#3b82f6')

    habit = Habit(
        name=name,
        color=color,
        user_id=current_user.id
    )

    try:
        db.session.add(habit)
        db.session.commit()
        flash('Habit added!', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('Habit already exists', 'error')

    return redirect('/habits')


@app.route('/habits/<int:habit_id>/delete', methods=['POST'])
@login_required
def delete_habit(habit_id):
    habit = Habit.query.get_or_404(habit_id)
    if habit.user_id != current_user.id:
        return "Unauthorized", 403

    db.session.delete(habit)
    db.session.commit()
    return redirect('/habits')

# -------------------- CHECKINS --------------------
@app.route('/toggle', methods=['POST'])
@login_required
def toggle():
    habit_id = request.form.get('habit_id', type=int)
    day = date.fromisoformat(request.form.get('day'))

    habit = Habit.query.get_or_404(habit_id)
    if habit.user_id != current_user.id:
        return {"error": "Unauthorized"}, 403

    existing = CheckIn.query.filter_by(habit_id=habit_id, date=day).first()

    if existing:
        db.session.delete(existing)
    else:
        db.session.add(CheckIn(habit_id=habit_id, date=day))

    db.session.commit()
    return {"status": "ok"}
@app.route('/toggle-theme', methods=['POST'])
@login_required
def toggle_theme():
    current_user.theme = 'light' if current_user.theme == 'dark' else 'dark'
    db.session.commit()
    return {"theme": current_user.theme}


# -------------------- ANALYTICS --------------------
@app.route('/analytics.json')
@login_required
def analytics_json():
    today = date.today()
    days = [today - timedelta(days=i) for i in reversed(range(7))]

    labels = [d.strftime('%a') for d in days]
    counts = [
        CheckIn.query.join(Habit)
        .filter(Habit.user_id == current_user.id, CheckIn.date == d)
        .count()
        for d in days
    ]

    return jsonify(labels=labels, counts=counts)


@app.route('/analytics')
@login_required
def analytics():
    today = date.today()
    year, month = today.year, today.month

    habits = Habit.query.filter_by(user_id=current_user.id).all()

    calendars = {
        h.id: monthly_calendar(h, year, month)
        for h in habits
    }

    return render_template(
        'analytics.html',
        habits=habits,
        calendars=calendars,
        year=year,
        month=month
    )


# -------------------- RUN --------------------
if __name__ == '__main__':
    app.run(debug=True)
