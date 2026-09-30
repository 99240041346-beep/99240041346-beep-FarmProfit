import os
import json
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import urlopen, Request

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")
app.url_map.strict_slashes = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "farmprofit-dev-secret-change-me")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

raw_db_url = os.environ.get("DATABASE_URL", "").strip()
if raw_db_url.startswith("postgres://"):
    raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = raw_db_url or (
    "sqlite:///" + os.path.join(INSTANCE_DIR, "farmprofit.db")
)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "error"


CROPS = {
    "Rice": {"yield": 22, "price": 2400},
    "Wheat": {"yield": 20, "price": 2300},
    "Maize": {"yield": 25, "price": 2100},
    "Cotton": {"yield": 8, "price": 6500},
    "Sugarcane": {"yield": 35, "price": 3600},
    "Tomato": {"yield": 18, "price": 3200},
    "Potato": {"yield": 24, "price": 1800},
    "Groundnut": {"yield": 10, "price": 6200},
}

COST_FIELDS = [
    ("seed", "Seed", 9000),
    ("fertilizer", "Fertilizer", 15000),
    ("pesticide", "Pesticide", 6000),
    ("labor", "Labor", 13000),
    ("machinery", "Machinery", 7000),
    ("irrigation", "Irrigation", 5000),
    ("transport", "Transport", 4000),
    ("other", "Other", 2500),
]


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    plans = db.relationship("FarmPlan", backref="owner", lazy=True, cascade="all, delete-orphan")


class FarmPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    crop = db.Column(db.String(80), nullable=False)
    area = db.Column(db.Float, nullable=False)
    yield_per_acre = db.Column(db.Float, nullable=False)
    price = db.Column(db.Float, nullable=False)
    seed = db.Column(db.Float, default=0, nullable=False)
    fertilizer = db.Column(db.Float, default=0, nullable=False)
    pesticide = db.Column(db.Float, default=0, nullable=False)
    labor = db.Column(db.Float, default=0, nullable=False)
    machinery = db.Column(db.Float, default=0, nullable=False)
    irrigation = db.Column(db.Float, default=0, nullable=False)
    transport = db.Column(db.Float, default=0, nullable=False)
    other = db.Column(db.Float, default=0, nullable=False)
    revenue = db.Column(db.Float, nullable=False)
    total_cost = db.Column(db.Float, nullable=False)
    profit = db.Column(db.Float, nullable=False)
    roi = db.Column(db.Float, nullable=False)
    risk = db.Column(db.String(30), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def nfloat(value, default=0.0):
    try:
        number = float(value)
        return max(number, 0.0)
    except (TypeError, ValueError):
        return default


def calculate(data):
    area = nfloat(data.get("area"), 5.0)
    yield_per_acre = nfloat(data.get("yield_per_acre"), 22.0)
    price = nfloat(data.get("price"), 2400.0)

    costs = {key: nfloat(data.get(key), default) for key, _, default in COST_FIELDS}
    production = area * yield_per_acre
    revenue = production * price
    total_cost = sum(costs.values())
    profit = revenue - total_cost
    roi = (profit / total_cost * 100) if total_cost else 0.0
    margin = (profit / revenue * 100) if revenue else 0.0

    if profit < 0 or margin < 10:
        risk = "High"
    elif margin < 25:
        risk = "Medium"
    else:
        risk = "Low"

    break_even_price = total_cost / production if production else 0.0
    break_even_yield = total_cost / price / area if price and area else 0.0

    return {
        "area": area,
        "yield_per_acre": yield_per_acre,
        "price": price,
        "production": production,
        "revenue": revenue,
        "total_cost": total_cost,
        "profit": profit,
        "roi": roi,
        "margin": margin,
        "risk": risk,
        "break_even_price": break_even_price,
        "break_even_yield": break_even_yield,
        **costs,
    }


def save_plan_from_result(form, result):
    crop = form.get("crop", "Rice")
    if crop not in CROPS:
        crop = "Rice"
    plan = FarmPlan(
        user_id=current_user.id,
        crop=crop,
        area=result["area"],
        yield_per_acre=result["yield_per_acre"],
        price=result["price"],
        seed=result["seed"],
        fertilizer=result["fertilizer"],
        pesticide=result["pesticide"],
        labor=result["labor"],
        machinery=result["machinery"],
        irrigation=result["irrigation"],
        transport=result["transport"],
        other=result["other"],
        revenue=result["revenue"],
        total_cost=result["total_cost"],
        profit=result["profit"],
        roi=result["roi"],
        risk=result["risk"],
    )
    db.session.add(plan)
    db.session.commit()
    return plan


@app.context_processor
def inject_globals():
    return {"crops": CROPS, "cost_fields": COST_FIELDS, "now": datetime.utcnow()}


@app.route("/")
def index():
    return redirect(url_for("dashboard")) if current_user.is_authenticated else render_template("landing.html")


@app.route("/home")
def home_alias():
    return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if len(name) < 2:
            flash("Enter a valid name.", "error")
        elif "@" not in email or len(email) < 5:
            flash("Enter a valid email address.", "error")
        elif len(password) < 6:
            flash("Password must contain at least 6 characters.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        elif User.query.filter(func.lower(User.email) == email).first():
            flash("That email is already registered. Please log in.", "error")
        else:
            user = User(name=name, email=email, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            login_user(user, remember=True)
            flash("Account created successfully.", "success")
            return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter(func.lower(User.email) == email).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            flash("Welcome back!", "success")
            next_url = request.args.get("next")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    plans = FarmPlan.query.filter_by(user_id=current_user.id).order_by(FarmPlan.created_at.desc()).all()
    total_revenue = sum(p.revenue for p in plans)
    total_cost = sum(p.total_cost for p in plans)
    total_profit = sum(p.profit for p in plans)
    avg_roi = sum(p.roi for p in plans) / len(plans) if plans else 0
    return render_template(
        "dashboard.html",
        plans=plans[:5],
        total_revenue=total_revenue,
        total_cost=total_cost,
        total_profit=total_profit,
        avg_roi=avg_roi,
    )


@app.route("/simulator", methods=["GET", "POST"])
@login_required
def simulator():
    result = None
    form = {
        "crop": "Rice",
        "area": "5",
        "yield_per_acre": "22",
        "price": "2400",
        **{key: str(default) for key, _, default in COST_FIELDS},
    }

    if request.method == "POST":
        form.update(request.form.to_dict())
        crop = form.get("crop", "Rice")
        if crop in CROPS and not request.form.get("yield_per_acre"):
            form["yield_per_acre"] = str(CROPS[crop]["yield"])
        if crop in CROPS and not request.form.get("price"):
            form["price"] = str(CROPS[crop]["price"])

        result = calculate(form)

        if request.form.get("save_plan") == "1":
            save_plan_from_result(form, result)
            flash("Farm analysis saved successfully.", "success")

    return render_template("simulator.html", result=result, form=form)


@app.route("/compare")
@login_required
def compare():
    results = []
    for crop_name, crop in CROPS.items():
        demo = {
            "crop": crop_name,
            "area": 5,
            "yield_per_acre": crop["yield"],
            "price": crop["price"],
            "seed": 9000,
            "fertilizer": 15000,
            "pesticide": 6000,
            "labor": 13000,
            "machinery": 7000,
            "irrigation": 5000,
            "transport": 4000,
            "other": 2500,
        }
        result = calculate(demo)
        result["crop"] = crop_name
        results.append(result)
    results.sort(key=lambda item: item["profit"], reverse=True)
    return render_template("compare.html", results=results)


@app.route("/history")
@login_required
def history():
    plans = FarmPlan.query.filter_by(user_id=current_user.id).order_by(FarmPlan.created_at.desc()).all()
    return render_template("history.html", plans=plans)


@app.post("/history/<int:plan_id>/delete")
@login_required
def delete_plan(plan_id):
    plan = FarmPlan.query.filter_by(id=plan_id, user_id=current_user.id).first_or_404()
    db.session.delete(plan)
    db.session.commit()
    flash("Saved analysis deleted.", "success")
    return redirect(url_for("history"))


@app.route("/report")
@login_required
def report():
    plans = FarmPlan.query.filter_by(user_id=current_user.id).order_by(FarmPlan.created_at.desc()).all()
    return render_template("report.html", plans=plans)


@app.post("/api/calculate")
@login_required
def api_calculate():
    data = request.get_json(silent=True) or request.form
    return jsonify(calculate(data))


WEATHER_CACHE_SECONDS = 300
_weather_cache = {}


def fetch_weather(latitude, longitude):
    try:
        lat = max(-90.0, min(90.0, float(latitude)))
        lon = max(-180.0, min(180.0, float(longitude)))
    except (TypeError, ValueError):
        raise ValueError("Invalid coordinates")

    key = (round(lat, 3), round(lon, 3))
    cached = _weather_cache.get(key)
    if cached and (datetime.utcnow().timestamp() - cached["ts"]) < WEATHER_CACHE_SECONDS:
        return cached["data"]

    params = urlencode({
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,weather_code,cloud_cover,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m,visibility",
        "hourly": "temperature_2m,precipitation_probability,precipitation,rain,weather_code,wind_speed_10m,relative_humidity_2m,uv_index",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,rain_sum,precipitation_probability_max,wind_speed_10m_max,uv_index_max",
        "forecast_days": 7,
        "timezone": "auto",
    })
    req = Request("https://api.open-meteo.com/v1/forecast?" + params, headers={"User-Agent": "FarmProfit/1.0"})
    with urlopen(req, timeout=8) as response:
        data = json.loads(response.read().decode("utf-8"))

    current = data.get("current", {})
    hourly = data.get("hourly", {})
    daily = data.get("daily", {})
    alerts = []
    code = int(current.get("weather_code", 0) or 0)
    rain_next = max((hourly.get("precipitation_probability", []) or [])[:6] or [0])
    wind = float(current.get("wind_speed_10m", 0) or 0)
    humidity = float(current.get("relative_humidity_2m", 0) or 0)
    temp = float(current.get("temperature_2m", 0) or 0)
    uv = max((hourly.get("uv_index", []) or [])[:6] or [0])

    if code in (95, 96, 99):
        alerts.append({"level": "danger", "icon": "⛈️", "title": "Thunderstorm alert", "message": "Avoid spraying, irrigation work and exposed field activity during thunderstorms."})
    elif code in (51, 53, 55, 61, 63, 65, 80, 81, 82) or rain_next >= 60:
        alerts.append({"level": "warning", "icon": "🌧️", "title": "Rain alert", "message": "Rain is possible soon. Consider delaying pesticide or fertilizer spraying and review irrigation needs."})
    if wind >= 35:
        alerts.append({"level": "danger", "icon": "💨", "title": "Strong wind alert", "message": "Secure young plants and equipment. Avoid spraying in strong winds."})
    if temp >= 38:
        alerts.append({"level": "warning", "icon": "🌡️", "title": "Heat stress alert", "message": "Increase crop monitoring and plan irrigation during cooler hours."})
    if humidity >= 85:
        alerts.append({"level": "warning", "icon": "💧", "title": "High humidity alert", "message": "High humidity can increase fungal disease pressure. Inspect crops and avoid unnecessary leaf wetness."})
    if uv >= 7:
        alerts.append({"level": "info", "icon": "☀️", "title": "High UV alert", "message": "Schedule intensive field work outside peak UV hours where practical."})
    if not alerts:
        alerts.append({"level": "good", "icon": "🌱", "title": "Favorable conditions", "message": "No major automatic weather risk detected right now. Continue routine crop monitoring."})

    result = {
        "location": {"latitude": lat, "longitude": lon, "timezone": data.get("timezone"), "elevation": data.get("elevation")},
        "updated_at": current.get("time"),
        "current": current,
        "daily": daily,
        "alerts": alerts,
        "source": "Open-Meteo forecast data; automatic agricultural rules generated by FarmProfit.",
    }
    _weather_cache[key] = {"ts": datetime.utcnow().timestamp(), "data": result}
    return result


@app.get("/api/weather")
def api_weather():
    latitude = request.args.get("lat")
    longitude = request.args.get("lon")
    if latitude is None or longitude is None:
        return jsonify({"error": "Latitude and longitude are required."}), 400
    try:
        return jsonify(fetch_weather(latitude, longitude))
    except Exception as exc:
        return jsonify({"error": "Weather service unavailable.", "detail": str(exc)}), 502


@app.get("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "error"
    return jsonify({"status": "ok", "application": "FarmProfit", "database": database})


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_error(_error):
    db.session.rollback()
    return render_template("500.html"), 500


def initialize_database():
    with app.app_context():
        db.create_all()
        if os.environ.get("ENABLE_DEMO", "1") == "1":
            demo_email = os.environ.get("DEMO_EMAIL", "demo@farmprofit.app").lower()
            demo_password = os.environ.get("DEMO_PASSWORD", "Demo@12345")
            if not User.query.filter_by(email=demo_email).first():
                demo = User(
                    name="Demo Farmer",
                    email=demo_email,
                    password_hash=generate_password_hash(demo_password),
                )
                db.session.add(demo)
                db.session.commit()


initialize_database()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
