from flask import Flask, render_template, request, jsonify
from recommender import RecipeRecommender
from nlp_utils import parse_message
from dialogue import IDLE, AWAIT_SELECTION, CONFIRM, next_turn

import uuid

app = Flask(__name__, static_folder="static", template_folder="templates")
rec = RecipeRecommender(data_path="data/recipes.csv")

# session memory: sid -> {"state":..., "mem":...}
SESSIONS = {}

def ensure_session(sid):
    if sid not in SESSIONS:
        SESSIONS[sid] = {"state": IDLE, "mem": {}}
    return SESSIONS[sid]

@app.route("/")
def index():
    sid = request.args.get("sid") or str(uuid.uuid4())
    ensure_session(sid)
    return render_template("index.html", sid=sid, bot_name="Mika")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True, silent=True) or {}
    sid = data.get("sid")
    msg = (data.get("message") or "").strip()
    if not sid:
        return jsonify({"reply":"Missing session id.","results":[]}), 400
    session = ensure_session(sid)

    parsed = parse_message(msg)

    def search_fn(p):
        return rec.search(p, top_k=5)
    def detail_fn(title):
        return rec.details(title)

    new_state, new_mem, reply = next_turn(session["state"], session["mem"], parsed, search_fn, detail_fn)
    session["state"] = new_state
    session["mem"] = new_mem

   # If we just listed candidates, also return them so UI can card-render
    results = []
    if new_state == AWAIT_SELECTION and "last_candidates" in session["mem"]:
        results = session["mem"]["last_candidates"]

# Single, unified return payload (use `reply` from next_turn)
    return jsonify({
        "reply": reply,
        "results": results,
        "ui_suggestions": [],
        "state": session["state"]  # e.g., "await_selection" / "confirm" / "idle"
    })

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))  # Render provides PORT
    app.run(host="0.0.0.0", port=port, debug=False)
   
