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

IRRIGATION_PROFILES = {
    "Rice": {"base_mm": 6.0, "label": "Rice"},
    "Wheat": {"base_mm": 4.0, "label": "Wheat"},
    "Maize": {"base_mm": 5.0, "label": "Maize"},
    "Cotton": {"base_mm": 5.0, "label": "Cotton"},
    "Sugarcane": {"base_mm": 7.0, "label": "Sugarcane"},
    "Tomato": {"base_mm": 4.0, "label": "Tomato"},
    "Potato": {"base_mm": 3.5, "label": "Potato"},
    "Groundnut": {"base_mm": 4.5, "label": "Groundnut"},
}

IRRIGATION_TEXT = {
    "en": {
        "now": ("Irrigate now", "Rain is not expected to provide enough water in the next 24 hours. Consider irrigating during the cooler part of the day."),
        "tomorrow": ("Irrigate tomorrow", "Crop water demand is moderate today. Recheck tomorrow, preferably after the early forecast update."),
        "skip": ("Skip irrigation — rain expected", "Forecast rainfall is likely to cover much of the crop's immediate water need. Recheck soil moisture before irrigating."),
    },
    "te": {
        "now": ("ఇప్పుడే నీరు పెట్టండి", "తదుపరి 24 గంటల్లో తగినంత వర్షం కనిపించడం లేదు. చల్లని సమయంలో నీరు పెట్టడాన్ని పరిగణించండి."),
        "tomorrow": ("రేపు నీరు పెట్టండి", "ఈరోజు పంటకు నీటి అవసరం మధ్యస్థంగా ఉంది. రేపు మళ్లీ వాతావరణ సూచనను పరిశీలించండి."),
        "skip": ("నీరు పెట్టవద్దు — వర్షం వచ్చే అవకాశం ఉంది", "వచ్చే వర్షం పంటకు అవసరమైన నీటిలో ఎక్కువ భాగాన్ని అందించే అవకాశం ఉంది. నీరు పెట్టే ముందు నేల తేమను పరిశీలించండి."),
    },
    "hi": {
        "now": ("अभी सिंचाई करें", "अगले 24 घंटों में पर्याप्त बारिश की संभावना नहीं है। ठंडे समय में सिंचाई करने पर विचार करें।"),
        "tomorrow": ("कल सिंचाई करें", "आज फसल की पानी की जरूरत मध्यम है। कल फिर पूर्वानुमान और मिट्टी की नमी जांचें।"),
        "skip": ("सिंचाई छोड़ें — बारिश की संभावना", "आने वाली बारिश फसल की तत्काल पानी की जरूरत का बड़ा हिस्सा पूरा कर सकती है। सिंचाई से पहले मिट्टी की नमी जांचें।"),
    },
    "ta": {
        "now": ("இப்போது பாசனம் செய்யவும்", "அடுத்த 24 மணி நேரத்தில் போதுமான மழை எதிர்பார்க்கப்படவில்லை. குளிரான நேரத்தில் பாசனம் செய்யலாம்."),
        "tomorrow": ("நாளை பாசனம் செய்யவும்", "இன்று பயிரின் நீர் தேவை மிதமாக உள்ளது. நாளை மீண்டும் முன்னறிவிப்பை சரிபார்க்கவும்."),
        "skip": ("பாசனத்தை தவிர்க்கவும் — மழை எதிர்பார்ப்பு", "வரவிருக்கும் மழை பயிரின் உடனடி நீர் தேவையின் பெரும்பகுதியை பூர்த்தி செய்யலாம். பாசனத்திற்கு முன் மண் ஈரத்தை சரிபார்க்கவும்."),
    },
    "kn": {
        "now": ("ಈಗ ನೀರಾವರಿ ಮಾಡಿ", "ಮುಂದಿನ 24 ಗಂಟೆಗಳಲ್ಲಿ ಸಾಕಷ್ಟು ಮಳೆಯ ಸಾಧ್ಯತೆ ಕಡಿಮೆ. ತಂಪಾದ ಸಮಯದಲ್ಲಿ ನೀರಾವರಿ ಮಾಡುವುದನ್ನು ಪರಿಗಣಿಸಿ."),
        "tomorrow": ("ನಾಳೆ ನೀರಾವರಿ ಮಾಡಿ", "ಇಂದು ಬೆಳೆಗೆ ನೀರಿನ ಅವಶ್ಯಕತೆ ಮಧ್ಯಮವಾಗಿದೆ. ನಾಳೆ ಮತ್ತೆ ಮುನ್ಸೂಚನೆಯನ್ನು ಪರಿಶೀಲಿಸಿ."),
        "skip": ("ನೀರಾವರಿ ಬೇಡ — ಮಳೆಯ ಸಾಧ್ಯತೆ", "ಮುಂದಿನ ಮಳೆ ಬೆಳೆಯ ತಕ್ಷಣದ ನೀರಿನ ಅಗತ್ಯದ ಬಹುಪಾಲನ್ನು ಪೂರೈಸಬಹುದು. ನೀರಾವರಿಗೂ ಮೊದಲು ಮಣ್ಣಿನ ತೇವಾಂಶ ಪರಿಶೀಲಿಸಿ."),
    },
}

def build_irrigation_advice(weather, crop, area, lang="en"):
    profile = IRRIGATION_PROFILES.get(crop, IRRIGATION_PROFILES["Rice"])
    lang = lang if lang in IRRIGATION_TEXT else "en"
    daily = weather.get("daily", {})
    hourly = weather.get("hourly", {})
    rain_probs = (hourly.get("precipitation_probability", []) or [])[:24]
    next24_prob = max([float(v or 0) for v in rain_probs] or [0])
    daily_rain = (daily.get("precipitation_sum", []) or [])[:2]
    rain_24h = float(daily_rain[0] or 0) if daily_rain else 0.0
    rain_48h = sum(float(v or 0) for v in daily_rain[:2])
    current = weather.get("current", {})
    temp = float(current.get("temperature_2m", 25) or 25)
    humidity = float(current.get("relative_humidity_2m", 60) or 60)

    demand = profile["base_mm"]
    demand *= max(0.75, min(1.35, 1 + (temp - 28) * 0.025))
    demand *= max(0.75, min(1.15, 1 + (65 - humidity) * 0.004))
    effective_rain = min(demand, rain_24h * 0.75)

    if rain_24h >= 5 or (next24_prob >= 70 and rain_48h >= 5):
        action = "skip"
        net_mm = 0.0
    elif effective_rain >= demand * 0.45:
        action = "tomorrow"
        net_mm = max(0.0, demand - effective_rain)
    else:
        action = "now"
        net_mm = max(0.0, demand - effective_rain)

    area = max(float(area or 1), 0.1)
    litres_per_acre = round(net_mm * 4046.856, 0)
    total_litres = round(litres_per_acre * area, 0)
    title, message = IRRIGATION_TEXT[lang][action]
    return {
        "action": action,
        "title": title,
        "message": message,
        "crop": crop,
        "area_acres": round(area, 2),
        "estimated_need_mm": round(net_mm, 1),
        "estimated_litres_per_acre": int(litres_per_acre),
        "estimated_total_litres": int(total_litres),
        "rain_24h_mm": round(rain_24h, 1),
        "rain_probability_24h": round(next24_prob),
        "temperature_c": round(temp, 1),
        "humidity_percent": round(humidity),
        "method": "Rule-based estimate using crop baseline demand, temperature, humidity and forecast rainfall. Actual irrigation should be adjusted for soil moisture, crop stage and local agronomy.",
    }

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
        "hourly": {"precipitation_probability": (hourly.get("precipitation_probability", []) or [])[:24]},
        "daily": daily,
        "alerts": alerts,
        "source": "Open-Meteo forecast data; automatic agricultural rules generated by FarmProfit.",
    }
    _weather_cache[key] = {"ts": datetime.utcnow().timestamp(), "data": result}
    return result


def geocode_farm_location(query):
    query = (query or "").strip()
    if len(query) < 2:
        raise ValueError("Enter a village, town, district or city.")
    params = urlencode({
        "name": query,
        "count": 1,
        "language": "en",
        "format": "json",
    })
    req = Request("https://geocoding-api.open-meteo.com/v1/search?" + params,
                  headers={"User-Agent": "FarmProfit/1.1"})
    with urlopen(req, timeout=8) as response:
        data = json.loads(response.read().decode("utf-8"))
    results = data.get("results") or []
    if not results:
        raise ValueError("Farm location was not found. Try a nearby town or district.")
    place = results[0]
    return {
        "latitude": float(place["latitude"]),
        "longitude": float(place["longitude"]),
        "name": place.get("name") or query,
        "admin1": place.get("admin1") or "",
        "country": place.get("country") or "",
    }


@app.get("/api/geocode")
def api_geocode():
    query = request.args.get("q", "")
    try:
        return jsonify(geocode_farm_location(query))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": "Location search is temporarily unavailable.", "detail": str(exc)}), 502


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




def calculate_irrigation_profit_impact(irrigation, area, irrigation_cost_per_1000_litres=25.0):
    litres = float(irrigation.get("estimated_total_litres", 0) or 0)
    cost = (litres / 1000.0) * max(float(irrigation_cost_per_1000_litres or 0), 0)
    return {
        "estimated_water_litres": int(round(litres)),
        "irrigation_cost": round(cost, 2),
        "cost_per_1000_litres": round(float(irrigation_cost_per_1000_litres), 2),
    }


def build_weather_profit_impact(weather, irrigation, crop):
    current = weather.get("current", {}) or {}
    daily = weather.get("daily", {}) or {}
    alerts = weather.get("alerts", []) or []
    temp = float(current.get("temperature_2m", 0) or 0)
    rain = float((daily.get("precipitation_sum", []) or [0])[0] or 0)
    risk = 0
    factors = []
    if temp >= 38:
        risk += 3; factors.append("Heat may increase water demand and crop stress.")
    if rain >= 20:
        risk += 2; factors.append("Heavy rain may delay field operations.")
    if any(str(a.get("severity","")).lower() == "high" for a in alerts):
        risk += 2; factors.append("A high-severity weather alert is active.")
    if float(irrigation.get("irrigation_cost", 0) or 0) > 0:
        factors.append("Irrigation expense is included in the operating-cost estimate.")
    level = "high" if risk >= 5 else "medium" if risk >= 3 else "low"
    return {"crop": crop, "risk_level": level, "risk_points": risk, "factors": factors or ["Current forecast has no major automatic profit-risk factor."],
            "irrigation_cost": irrigation.get("irrigation_cost", 0), "rain_24h_mm": rain,
            "summary": "Weather conditions may affect operating costs and field timing. Use the estimate as a planning signal, not a guaranteed profit forecast."}


@app.get("/api/irrigation")
def api_irrigation():
    latitude = request.args.get("lat")
    longitude = request.args.get("lon")
    crop = request.args.get("crop", "Rice")
    lang = request.args.get("lang", "en")
    try:
        area = nfloat(request.args.get("area"), 1.0)
        if crop not in IRRIGATION_PROFILES:
            crop = "Rice"
        weather = fetch_weather(latitude, longitude)
        advice = build_irrigation_advice(weather, crop, area, lang)
        advice["profit_impact"] = calculate_irrigation_profit_impact(
            advice, area, request.args.get("water_cost_per_1000_litres", 25)
        )
        advice["weather_profit_impact"] = build_weather_profit_impact(weather, advice["profit_impact"], crop)
        return jsonify(advice)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": "Irrigation advisor unavailable.", "detail": str(exc)}), 502


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
