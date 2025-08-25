import os, datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv

# Plagiarism detection
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "devsecret")

# MongoDB setup
client = MongoClient(os.getenv("MONGODB_URI"))
db = client[os.getenv("DB_NAME", "exam_portal")]

# -------------------- Auth --------------------

def current_user():
    if "user_id" in session:
        return db.users.find_one({"_id": ObjectId(session["user_id"])})
    return None

def login_required(role=None):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Login required", "danger")
                return redirect(url_for("login"))
            if role and user["role"] != role:
                abort(403)
            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator

@app.route("/")
def index():
    user = current_user()
    if user:
        return redirect(url_for("dashboard"))
    return render_template("base.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name, email, password, invite = (
            request.form["name"],
            request.form["email"],
            request.form["password"],
            request.form.get("invite_code")
        )
        role = "student"
        if invite and invite == os.getenv("STAFF_INVITE_CODE"):
            role = "staff"
        if db.users.find_one({"email": email}):
            flash("Email already registered", "danger")
        else:
            user = {
                "name": name,
                "email": email,
                "password_hash": generate_password_hash(password),
                "role": role,
                "created_at": datetime.datetime.utcnow()
            }
            db.users.insert_one(user)
            flash("Registration successful, please login.", "success")
            return redirect(url_for("login"))
    return render_template("auth/register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email, password = request.form["email"], request.form["password"]
        user = db.users.find_one({"email": email})
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = str(user["_id"])
            return redirect(url_for("dashboard"))
        flash("Invalid login", "danger")
    return render_template("auth/login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# -------------------- Dashboards --------------------
@app.route("/dashboard")
@login_required()
def dashboard():
    user = current_user()
    if user["role"] == "student":
        exams = list(db.exams.find({}))
        return render_template("student/dashboard.html", exams=exams, user=user)
    else:
        exams = list(db.exams.find({"created_by": user["_id"]}))
        return render_template("staff/dashboard.html", exams=exams, user=user)

# -------------------- Staff --------------------
@app.route("/staff/exams/create", methods=["GET","POST"])
@login_required("staff")
def create_exam():
    if request.method == "POST":
        exam = {
            "title": request.form["title"],
            "prompt": request.form["prompt"],
            "open_at": datetime.datetime.fromisoformat(request.form["open_at"]),
            "close_at": datetime.datetime.fromisoformat(request.form["close_at"]),
            "time_limit_min": int(request.form["time_limit"]),
            "max_score": int(request.form["max_score"]),
            "created_by": current_user()["_id"],
            "created_at": datetime.datetime.utcnow()
        }
        db.exams.insert_one(exam)
        flash("Exam created!", "success")
        return redirect(url_for("dashboard"))
    return render_template("staff/create_exam.html")

@app.route("/staff/exams/<exam_id>/submissions")
@login_required("staff")
def submissions(exam_id):
    subs = list(db.submissions.find({"exam_id": ObjectId(exam_id)}))
    return render_template("staff/submissions.html", subs=subs)

@app.route("/staff/grade/<sub_id>", methods=["GET","POST"])
@login_required("staff")
def grade(sub_id):
    sub = db.submissions.find_one({"_id": ObjectId(sub_id)})
    if request.method == "POST":
        score = int(request.form["score"])
        comments = request.form["comments"]
        db.submissions.update_one(
            {"_id": ObjectId(sub_id)},
            {"$set": {"score": score, "comments": comments}}
        )
        flash("Submission graded!", "success")
        return redirect(url_for("submissions", exam_id=sub["exam_id"]))
    return render_template("staff/grade.html", sub=sub)

# -------------------- Student --------------------
@app.route("/exam/<exam_id>", methods=["GET","POST"])
@login_required("student")
def take_exam(exam_id):
    exam = db.exams.find_one({"_id": ObjectId(exam_id)})
    if request.method == "POST":
        essay_text = request.form["essay"]
        # ----- Anti-cheating: plagiarism check -----
        existing_essays = [s["essay_text"] for s in db.submissions.find({"exam_id": ObjectId(exam_id)})]
        vectorizer = TfidfVectorizer().fit([essay_text] + existing_essays) if existing_essays else None
        plagiarism_score = 0
        if vectorizer:
            vectors = vectorizer.transform([essay_text] + existing_essays)
            sims = cosine_similarity(vectors[0:1], vectors[1:]).flatten()
            plagiarism_score = max(sims) if sims.size > 0 else 0
        sub = {
            "exam_id": ObjectId(exam_id),
            "user_id": current_user()["_id"],
            "essay_text": essay_text,
            "submitted_at": datetime.datetime.utcnow(),
            "plagiarism_score": plagiarism_score
        }
        db.submissions.insert_one(sub)
        flash("Essay submitted!", "success")
        return redirect(url_for("dashboard"))
    return render_template("student/take_exam.html", exam=exam)

@app.route("/result/<exam_id>")
@login_required("student")
def result(exam_id):
    sub = db.submissions.find_one({"exam_id": ObjectId(exam_id), "user_id": current_user()["_id"]})
    return render_template("student/result.html", sub=sub)
if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)