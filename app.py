import os
import sqlite3
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from openai import OpenAI, OpenAIError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "recycling.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "templates", "static", "uploads")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}
CATEGORIES = ("Recyclable", "Reusable", "E-waste", "Hazardous", "Biodegradable")
CATEGORY_COLORS = ("#35b86b", "#4386db", "#e7b64b", "#e34f4f", "#9a6844")

app = Flask(__name__, template_folder="templates", static_folder="templates/static")
app.secret_key = os.environ.get("SECRET_KEY", "development-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def connect_database():
	connection = sqlite3.connect(DATABASE)
	connection.row_factory = sqlite3.Row
	return connection


def initialize_database():
	with connect_database() as connection:
		connection.execute(
			"""CREATE TABLE IF NOT EXISTS users (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				email TEXT NOT NULL UNIQUE,
				password_hash TEXT NOT NULL
			)"""
		)
		connection.execute(
			"""CREATE TABLE IF NOT EXISTS scans (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				user_id INTEGER NOT NULL REFERENCES users(id),
				filename TEXT NOT NULL,
				category TEXT NOT NULL,
				created_at TEXT NOT NULL
			)"""
		)


initialize_database()


def login_required(view):
	@wraps(view)
	def wrapped_view(*args, **kwargs):
		if "user_id" not in session:
			return redirect(url_for("login"))
		return view(*args, **kwargs)

	return wrapped_view


def user_scans(user_id):
	with connect_database() as connection:
		return connection.execute(
			"SELECT filename, category, created_at FROM scans WHERE user_id = ? ORDER BY id DESC",
			(user_id,),
		).fetchall()


def dashboard_stats(scans):
	counts = {category: 0 for category in CATEGORIES}
	for scan in scans:
		if scan["category"] in counts:
			counts[scan["category"]] += 1
	category_data = [
		{"label": category, "count": counts[category], "color": color}
		for category, color in zip(CATEGORIES, CATEGORY_COLORS)
	]
	awaiting_review = len(scans) - sum(counts.values())
	category_data.append({"label": "Awaiting review", "count": awaiting_review, "color": "#82918a"})
	chart_total = len(scans)
	chart_stops = []
	chart_offset = 0
	if chart_total:
		for item in category_data:
			if item["count"]:
				chart_end = chart_offset + item["count"] * 100 / chart_total
				chart_stops.append(f"{item['color']} {chart_offset:.2f}% {chart_end:.2f}%")
				chart_offset = chart_end
	chart_gradient = (
		f"conic-gradient({', '.join(chart_stops)})"
		if chart_stops
		else "conic-gradient(#29463d 0% 100%)"
	)
	return {
		"total_scans": len(scans),
		"recyclable_count": counts["Recyclable"],
		"reusable_count": counts["Reusable"],
		"ewaste_count": counts["E-waste"],
		"hazardous_count": counts["Hazardous"],
		"biodegradable_count": counts["Biodegradable"],
		"co2_saved": 0,
		"category_data": category_data,
		"chart_gradient": chart_gradient,
		"max_category_count": max((item["count"] for item in category_data), default=0),
	}


def generate_recommendation(question):
	api_key = os.environ.get("OPENAI_API_KEY")
	if not api_key:
		raise RuntimeError("OPENAI_API_KEY is not configured")

	base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
	model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
	client = OpenAI(api_key=api_key, base_url=base_url, timeout=30)
	response = client.chat.completions.create(
		model=model,
		messages=[
			{
				"role": "system",
				"content": (
					"You are EcoCycle, a practical waste-sorting and reuse guide. Give a clear, "
					"actionable answer. Do not invent local recycling rules; ask for the user's "
					"location when local rules matter. For batteries, chemicals, e-waste, and "
					"other hazardous items, recommend authorized collection and safe handling."
				),
			},
			{"role": "user", "content": question},
		],
		temperature=0.4,
	)
	answer = response.choices[0].message.content
	if not isinstance(answer, str) or not answer.strip():
		raise ValueError("The model returned an empty answer")
	return answer.strip()


@app.route("/")
def index():
	return redirect(url_for("dashboard" if "user_id" in session else "login"))


@app.route("/register", methods=["GET", "POST"])
def register():
	if request.method == "POST":
		name = request.form.get("name", "").strip()
		email = request.form.get("email", "").strip().lower()
		password = request.form.get("password", "")
		if not name or not email or len(password) < 8:
			flash("Enter your name, a valid email, and a password of at least 8 characters.")
			return render_template("register.html"), 400
		try:
			with connect_database() as connection:
				cursor = connection.execute(
					"INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
					(name, email, generate_password_hash(password)),
				)
				session["user_id"] = cursor.lastrowid
				session["user_name"] = name
		except sqlite3.IntegrityError:
			flash("An account with that email already exists.")
			return render_template("register.html"), 409
		return redirect(url_for("dashboard"))
	return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
	if request.method == "POST":
		email = request.form.get("email", "").strip().lower()
		password = request.form.get("password", "")
		with connect_database() as connection:
			user = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
		if user is None or not check_password_hash(user["password_hash"], password):
			flash("Email or password is incorrect.")
			return render_template("login.html"), 401
		session["user_id"] = user["id"]
		session["user_name"] = user["name"]
		return redirect(url_for("dashboard"))
	return render_template("login.html")


@app.route("/logout")
def logout():
	session.clear()
	return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
	scans = user_scans(session["user_id"])
	return render_template("dashboard.html", **dashboard_stats(scans))


@app.route("/scan", methods=["GET", "POST"])
@login_required
def scan():
	if request.method == "POST":
		image = request.files.get("image")
		if image is None or not image.filename:
			flash("Choose an image to scan.")
			return redirect(url_for("scan"))
		original_name = secure_filename(image.filename)
		extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
		if extension not in ALLOWED_EXTENSIONS:
			flash("Upload a JPG, JPEG, or PNG image.")
			return redirect(url_for("scan"))
		stored_name = f"{uuid.uuid4().hex}.{extension}"
		image.save(os.path.join(UPLOAD_FOLDER, stored_name))
		category = "Awaiting review"
		created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
		with connect_database() as connection:
			connection.execute(
				"INSERT INTO scans (user_id, filename, category, created_at) VALUES (?, ?, ?, ?)",
				(session["user_id"], stored_name, category, created_at),
			)
		return render_template(
			"scan_result.html",
			image_url=url_for("static", filename=f"uploads/{stored_name}"),
			filename=original_name,
			category=category,
			description="No image-classification model is configured in this project.",
			recommendation="Check the item's material and follow your local waste-disposal guidance.",
			is_demo=True,
		)
	return render_template("scan.html")


@app.route("/history")
@login_required
def history():
	return render_template("history.html", scans=user_scans(session["user_id"]))


@app.route("/analytics")
@login_required
def analytics():
	return render_template("analytics.html", **dashboard_stats(user_scans(session["user_id"])))


@app.route("/assistant", methods=["GET", "POST"])
@login_required
def assistant():
	if request.method == "POST":
		data = request.get_json(silent=True) or {}
		question = data.get("question")
		if not isinstance(question, str) or not question.strip():
			return jsonify(error="Enter a question first."), 400
		if len(question) > 1000:
			return jsonify(error="Keep your question under 1,000 characters."), 400
		if not os.environ.get("OPENAI_API_KEY"):
			return jsonify(error="AI recommendations are not configured. Set OPENAI_API_KEY on the server."), 503
		try:
			return jsonify(answer=generate_recommendation(question.strip()))
		except (OpenAIError, ValueError, KeyError, IndexError, TypeError):
			app.logger.exception("OpenAI-compatible recommendation request failed")
			return jsonify(error="The recommendation service could not answer right now. Please try again."), 502
	return render_template("assistant.html")


@app.route("/digital-twin")
@login_required
def digital_twin():
	return render_template("digital_twin.html")


if __name__ == "__main__":
	app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
