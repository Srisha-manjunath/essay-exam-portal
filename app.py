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
client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017/"))
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

# Error handlers
@app.errorhandler(403)
def forbidden(error):
    return render_template("errors/403.html"), 403

@app.errorhandler(404)
def not_found(error):
    return render_template("errors/404.html"), 404

@app.route("/")
def index():
    user = current_user()
    if user:
        return redirect(url_for("dashboard"))
    return render_template("base.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        invite = request.form.get("invite_code", "").strip()
        
        # Validation
        if not name or not email or not password:
            flash("All fields are required", "danger")
            return render_template("auth/register.html")
        
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
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        
        if not email or not password:
            flash("Email and password are required", "danger")
            return render_template("auth/login.html")
            
        user = db.users.find_one({"email": email})
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = str(user["_id"])
            return redirect(url_for("dashboard"))
        flash("Invalid login credentials", "danger")
    return render_template("auth/login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out", "success")
    return redirect(url_for("index"))

# -------------------- Dashboards --------------------
@app.route("/dashboard")
@login_required()
def dashboard():
    user = current_user()
    if user["role"] == "student":
        exams = list(db.exams.find({}))
        # Add submission status for each exam
        for exam in exams:
            submission = db.submissions.find_one({
                "exam_id": exam["_id"], 
                "user_id": user["_id"]
            })
            exam["submitted"] = submission is not None
            exam["submission"] = submission
        return render_template("student/dashboard.html", exams=exams, user=user)
    else:
        exams = list(db.exams.find({"created_by": user["_id"]}))
        # Add submission counts for each exam
        for exam in exams:
            exam["submission_count"] = db.submissions.count_documents({"exam_id": exam["_id"]})
        return render_template("staff/dashboard.html", exams=exams, user=user)

# -------------------- Staff --------------------
@app.route("/staff/exams/create", methods=["GET","POST"])
@login_required("staff")
def create_exam():
    if request.method == "POST":
        try:
            title = request.form.get("title", "").strip()
            prompt = request.form.get("prompt", "").strip()
            open_at_str = request.form.get("open_at", "")
            close_at_str = request.form.get("close_at", "")
            time_limit = request.form.get("time_limit", "")
            max_score = request.form.get("max_score", "")
            
            # Validation
            if not all([title, prompt, open_at_str, close_at_str, time_limit, max_score]):
                flash("All fields are required", "danger")
                return render_template("staff/create_exam.html")
            
            # Parse datetime strings
            open_at = datetime.datetime.fromisoformat(open_at_str)
            close_at = datetime.datetime.fromisoformat(close_at_str)
            
            # Validate dates
            if close_at <= open_at:
                flash("Close time must be after open time", "danger")
                return render_template("staff/create_exam.html")
            
            exam = {
                "title": title,
                "prompt": prompt,
                "open_at": open_at,
                "close_at": close_at,
                "time_limit_min": int(time_limit),
                "max_score": int(max_score),
                "created_by": current_user()["_id"],
                "created_at": datetime.datetime.utcnow()
            }
            db.exams.insert_one(exam)
            flash("Exam created successfully!", "success")
            return redirect(url_for("dashboard"))
        except ValueError as e:
            flash("Invalid date format or numeric values", "danger")
        except Exception as e:
            flash("Error creating exam. Please try again.", "danger")
    
    return render_template("staff/create_exam.html")

@app.route("/staff/exams/<exam_id>/submissions")
@login_required("staff")
def submissions(exam_id):
    try:
        exam = db.exams.find_one({"_id": ObjectId(exam_id)})
        if not exam:
            flash("Exam not found", "danger")
            return redirect(url_for("dashboard"))
        
        # Check if current user owns this exam
        if exam["created_by"] != current_user()["_id"]:
            abort(403)
        
        subs = list(db.submissions.find({"exam_id": ObjectId(exam_id)}))
        # Get user names for submissions
        for sub in subs:
            user = db.users.find_one({"_id": sub["user_id"]})
            sub["user_name"] = user["name"] if user else "Unknown"
        
        return render_template("staff/submissions.html", subs=subs, exam=exam)
    except Exception as e:
        flash("Error loading submissions", "danger")
        return redirect(url_for("dashboard"))

@app.route("/staff/grade/<sub_id>", methods=["GET","POST"])
@login_required("staff")
def grade(sub_id):
    try:
        sub = db.submissions.find_one({"_id": ObjectId(sub_id)})
        if not sub:
            flash("Submission not found", "danger")
            return redirect(url_for("dashboard"))
        
        # Check if current user owns the exam this submission belongs to
        exam = db.exams.find_one({"_id": sub["exam_id"]})
        if not exam or exam["created_by"] != current_user()["_id"]:
            abort(403)
        
        if request.method == "POST":
            try:
                score = int(request.form.get("score", 0))
                comments = request.form.get("comments", "").strip()
                
                # Validate score
                if score < 0 or score > exam["max_score"]:
                    flash(f"Score must be between 0 and {exam['max_score']}", "danger")
                    return render_template("staff/grade.html", sub=sub, exam=exam)
                
                db.submissions.update_one(
                    {"_id": ObjectId(sub_id)},
                    {"$set": {
                        "score": score, 
                        "comments": comments,
                        "graded_at": datetime.datetime.utcnow(),
                        "graded_by": current_user()["_id"]
                    }}
                )
                flash("Submission graded successfully!", "success")
                return redirect(url_for("submissions", exam_id=sub["exam_id"]))
            except ValueError:
                flash("Invalid score value", "danger")
        
        # Get user info for display
        user = db.users.find_one({"_id": sub["user_id"]})
        sub["user_name"] = user["name"] if user else "Unknown"
        
        return render_template("staff/grade.html", sub=sub, exam=exam)
    except Exception as e:
        flash("Error processing grade", "danger")
        return redirect(url_for("dashboard"))

# -------------------- Student --------------------
@app.route("/exam/<exam_id>", methods=["GET","POST"])
@login_required("student")
def take_exam(exam_id):
    try:
        exam = db.exams.find_one({"_id": ObjectId(exam_id)})
        if not exam:
            flash("Exam not found", "danger")
            return redirect(url_for("dashboard"))
        
        # Check if exam is open
        now = datetime.datetime.utcnow()
        if now < exam["open_at"]:
            flash("Exam is not yet open", "warning")
            return redirect(url_for("dashboard"))
        
        if now > exam["close_at"]:
            flash("Exam is closed", "warning")
            return redirect(url_for("dashboard"))
        
        # Check if student already submitted
        existing_submission = db.submissions.find_one({
            "exam_id": ObjectId(exam_id),
            "user_id": current_user()["_id"]
        })
        
        if existing_submission:
            flash("You have already submitted this exam", "info")
            return redirect(url_for("result", exam_id=exam_id))
        
        if request.method == "POST":
            essay_text = request.form.get("essay", "").strip()
            
            if not essay_text:
                flash("Essay cannot be empty", "danger")
                return render_template("student/take_exam.html", exam=exam)
            
            # Anti-cheating: plagiarism check
            existing_essays = [s["essay_text"] for s in db.submissions.find({"exam_id": ObjectId(exam_id)})]
            plagiarism_score = 0
            
            if existing_essays:
                try:
                    vectorizer = TfidfVectorizer(stop_words='english', max_features=1000)
                    all_essays = [essay_text] + existing_essays
                    vectors = vectorizer.fit_transform(all_essays)
                    similarities = cosine_similarity(vectors[0:1], vectors[1:]).flatten()
                    plagiarism_score = max(similarities) if similarities.size > 0 else 0
                except Exception:
                    plagiarism_score = 0  # If plagiarism check fails, continue with 0
            
            sub = {
                "exam_id": ObjectId(exam_id),
                "user_id": current_user()["_id"],
                "essay_text": essay_text,
                "submitted_at": datetime.datetime.utcnow(),
                "plagiarism_score": float(plagiarism_score)
            }
            db.submissions.insert_one(sub)
            flash("Essay submitted successfully!", "success")
            return redirect(url_for("dashboard"))
        
        return render_template("student/take_exam.html", exam=exam)
    except Exception as e:
        flash("Error processing exam", "danger")
        return redirect(url_for("dashboard"))

@app.route("/result/<exam_id>")
@login_required("student")
def result(exam_id):
    try:
        exam = db.exams.find_one({"_id": ObjectId(exam_id)})
        if not exam:
            flash("Exam not found", "danger")
            return redirect(url_for("dashboard"))
        
        sub = db.submissions.find_one({
            "exam_id": ObjectId(exam_id), 
            "user_id": current_user()["_id"]
        })
        
        return render_template("student/result.html", sub=sub, exam=exam)
    except Exception as e:
        flash("Error loading result", "danger")
        return redirect(url_for("dashboard"))

# Template context processor to make current_user available in templates
@app.context_processor
def inject_user():
    return dict(current_user=current_user())

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
