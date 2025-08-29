# app.py
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from recommender import RecipeRecommender
from nlp_utils import parse_message
from dialogue import IDLE, AWAIT_SELECTION, CONFIRM, next_turn

from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

# tolerate models.py or model.py filename
try:
    from models import db, User, ChatSession, Message
except ImportError:
    from model import db, User, ChatSession, Message

import uuid
import re

app = Flask(__name__, static_folder="static", template_folder="templates")

# ==============================
# Core (unchanged)
# ==============================
rec = RecipeRecommender(data_path="data/recipes.csv")

# session memory: sid -> {"state":..., "mem":...}
SESSIONS = {}

def ensure_session(sid):
    if sid not in SESSIONS:
        SESSIONS[sid] = {"state": IDLE, "mem": {}}
    return SESSIONS[sid]

# ==============================
# Config: DB + Login
# ==============================
app.config["SECRET_KEY"] = "dev-secret-change-me"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(uid):
    try:
        return User.query.get(int(uid))
    except Exception:
        return None

with app.app_context():
    db.create_all()

# ==============================
# Security questions (for register/forgot)
# ==============================
SECURITY_QUESTIONS = [
    "What is your favorite dish?",
    "What is your mother’s maiden name?",
    "What city were you born in?",
    "What is the name of your first school?",
    "What is your favorite movie?",
    "What is your pet’s name?"
]

# ==============================
# INDEX (guest dashboard)
# ==============================
@app.route("/")
def index():
    # If logged in → show dashboard with server sessions
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    # Guest dashboard (no server sessions)
    sid = request.args.get("sid") or str(uuid.uuid4())
    ensure_session(sid)
    return render_template("dashboard.html", sessions=[], sid=sid, guest=True)

# ==============================
# CHAT (same payload; DB only for logged-in)
# ==============================
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True, silent=True) or {}
    sid = data.get("sid")
    msg = (data.get("message") or "").strip()
    if not sid:
        return jsonify({"reply":"Missing session id.","results":[]}), 400

    session = ensure_session(sid)
    parsed = parse_message(msg)

    def search_fn(p):  return rec.search(p, top_k=5)
    def detail_fn(t):  return rec.details(t)

    # Persist to DB ONLY for logged-in users
    if current_user.is_authenticated:
        # ensure session row
        cs = ChatSession.query.filter_by(id=sid, user_id=current_user.id).first()
        if cs is None:
            # title will be set to first user msg (trimmed) if available
            title = (re.sub(r"\s+", " ", msg).strip() or "New chat")[:40]
            cs = ChatSession(id=sid, user_id=current_user.id, title=title)
            db.session.add(cs)
            db.session.commit()
        else:
            if not cs.title and msg:
                cs.title = (re.sub(r"\s+", " ", msg).strip() or "New chat")[:40]
                db.session.commit()
        # save user message
        if msg:
            db.session.add(Message(session_id=sid, role="user", content=msg))
            db.session.commit()

    # dialogue core
    new_state, new_mem, reply = next_turn(session["state"], session["mem"], parsed, search_fn, detail_fn)
    session["state"] = new_state
    session["mem"]   = new_mem

    # results to render cards
    results = []
    if new_state == AWAIT_SELECTION and "last_candidates" in session["mem"]:
        results = session["mem"]["last_candidates"]

    # persist bot reply for logged-in users
    if current_user.is_authenticated and reply:
        db.session.add(Message(session_id=sid, role="bot", content=reply))
        db.session.commit()

    return jsonify({
        "reply": reply,
        "results": results,
        "ui_suggestions": [],
        "state": session["state"]  # "await_selection" / "confirm" / "idle" / "closed"
    })

# ==============================
# AUTH: Login / Register / Logout / Forgot
# ==============================
USERNAME_RE = re.compile(r"^[a-z0-9_\.]{3,32}$", re.I)
PASSWORD_RE = re.compile(r"^[A-Za-z0-9@#$%^&+=!.\-_]{8,64}$")
EMAIL_RE    = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

@app.get("/login")
def login():
    return render_template("login.html")

@app.post("/login")
def login_post():
    u = (request.form.get("username_or_email") or "").strip().lower()
    pw = request.form.get("password") or ""
    if not u or not pw:
        return render_template("login.html", error="Enter username/email and password.")
    user = User.query.filter((User.email == u) | (User.username == u)).first()
    if not user or not check_password_hash(user.password_hash, pw):
        return render_template("login.html", error="Invalid credentials.")
    login_user(user)
    return redirect(url_for("dashboard"))

@app.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))

@app.get("/register")
def register():
    return render_template("register.html", questions=SECURITY_QUESTIONS)

@app.post("/register")
def register_post():
    fn = (request.form.get("first_name") or "").strip()
    ln = (request.form.get("last_name") or "").strip()
    un = (request.form.get("username") or "").strip()
    em = (request.form.get("email") or "").strip().lower()
    pw = request.form.get("password") or ""
    cpw = request.form.get("confirm_password") or ""
    q = request.form.get("sec_question") or ""
    a = (request.form.get("sec_answer") or "").strip()

    if not (fn and un and em and pw and cpw and q and a):
        return render_template("register.html", questions=SECURITY_QUESTIONS, error="Fill all required fields.")
    if not USERNAME_RE.match(un):
        return render_template("register.html", questions=SECURITY_QUESTIONS, error="Username: 3–32 chars, letters/numbers/._ only.")
    if User.query.filter_by(username=un).first():
        return render_template("register.html", questions=SECURITY_QUESTIONS, error="Username already taken.")
    if not EMAIL_RE.match(em):
        return render_template("register.html", questions=SECURITY_QUESTIONS, error="Invalid email format.")
    if User.query.filter_by(email=em).first():
        return render_template("register.html", questions=SECURITY_QUESTIONS, error="Email already registered.")
    if pw != cpw:
        return render_template("register.html", questions=SECURITY_QUESTIONS, error="Passwords do not match.")
    if not PASSWORD_RE.match(pw):
        return render_template("register.html", questions=SECURITY_QUESTIONS,
            error="Password: 8–64 chars; letters, numbers, and @ # $ % ^ & + = ! . - _ allowed.")

    user = User(
        first_name=fn, last_name=ln, username=un, email=em,
        password_hash=generate_password_hash(pw),
        sec_question=q, sec_answer_hash=generate_password_hash(a)
    )
    db.session.add(user); db.session.commit()
    flash("Account created successfully. Please log in.", "success")
    return redirect(url_for("login"))

@app.get("/forgot")
def forgot():
    return render_template("forgot.html")

@app.post("/forgot")
def forgot_post():
    u = (request.form.get("username_or_email") or "").strip().lower()
    user = User.query.filter((User.email == u) | (User.username == u)).first()
    if not user:
        return render_template("forgot.html", error="User not found.")
    return render_template("forgot.html", step="question", question=user.sec_question, who=u)

@app.post("/forgot/verify")
def forgot_verify():
    u = (request.form.get("who") or "").strip().lower()
    ans = (request.form.get("answer") or "").strip()
    user = User.query.filter((User.email == u) | (User.username == u)).first()
    if not user:
        return render_template("forgot.html", error="Session expired. Start again.")
    if not check_password_hash(user.sec_answer_hash, ans):
        return render_template("forgot.html", step="question", question=user.sec_question, who=u, error="Incorrect answer. Try again.")
    return render_template("forgot.html", step="reset", who=u)

@app.post("/forgot/reset")
def forgot_reset():
    u = (request.form.get("who") or "").strip().lower()
    pw = request.form.get("password") or ""
    cpw = request.form.get("confirm_password") or ""
    user = User.query.filter((User.email == u) | (User.username == u)).first()
    if not user:
        return render_template("forgot.html", error="Session expired. Start again.")
    if pw != cpw:
        return render_template("forgot.html", step="reset", who=u, error="Passwords do not match.")
    if not PASSWORD_RE.match(pw):
        return render_template("forgot.html", step="reset", who=u,
            error="Password: 8–64 chars; letters, numbers, and @ # $ % ^ & + = ! . - _ allowed.")
    user.password_hash = generate_password_hash(pw)
    db.session.commit()
    return redirect(url_for("login"))

# ==============================
# DASHBOARD (auth)
# ==============================
@app.get("/dashboard")
@login_required
def dashboard():
    sessions = ChatSession.query.filter_by(user_id=current_user.id)\
                                .order_by(ChatSession.created_at.desc()).all()
    sid = uuid.uuid4().hex  # fresh chat sid
    return render_template("dashboard.html", sessions=sessions, sid=sid)

# ==============================
# Session APIs (used by sidebar)
# ==============================

@app.post("/api/sessions")
def api_create_session():
    """Create a chat session.
       - Logged-in: create DB row
       - Guest: return ok (UI stores in localStorage)
    """
    data = request.get_json(force=True) if request.data else {}
    sid = data.get("sid") or uuid.uuid4().hex
    title = (data.get("title") or "New chat")[:255]

    if current_user.is_authenticated:
        cs = ChatSession(id=sid, user_id=current_user.id, title=title)
        db.session.merge(cs)
        db.session.commit()
        return jsonify({"ok": True, "sid": sid})
    else:
        # guest handled client-side
        return jsonify({"ok": True, "sid": sid, "guest": True})

@app.get("/api/sessions/<sid>/messages")
def api_get_messages(sid):
    """Return messages for a session (DB for auth; empty for guest)."""
    if not current_user.is_authenticated:
        return jsonify({"ok": True, "messages": []})
    sess = ChatSession.query.filter_by(id=sid, user_id=current_user.id).first()
    if not sess:
        return jsonify({"ok": False, "error": "Not found"}), 404
    msgs = Message.query.filter_by(session_id=sid).order_by(Message.id.asc()).all()
    return jsonify({"ok": True, "messages": [
        {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()} for m in msgs
    ]})

# ==============================
# Main
# ==============================
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
