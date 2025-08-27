from difflib import get_close_matches

# Dialogue states
IDLE = "idle"                    # waiting for ingredients/query
AWAIT_SELECTION = "await_selection"  # list shown, waiting for user to pick
CONFIRM = "confirm"              # recipe shown, ask yes/no

# NEW: compare sets (ignore order) so "palak, paneer" == "paneer, palak"
def is_query_changed(prev_parsed, new_parsed):
    if not prev_parsed:
        return True
    if set(prev_parsed.get("ingredients") or []) != set(new_parsed.get("ingredients") or []):
        return True
    if set(prev_parsed.get("exclude") or []) != set(new_parsed.get("exclude") or []):
        return True
    for k in ["diet", "cuisine", "time_limit"]:
        if prev_parsed.get(k) != new_parsed.get(k):
            return True
    return False

def normalize_title(t): return (t or "").strip().lower()

def pick_from_candidates(cands, selection_number=None, selection_name=None):
    if not cands: return None
    if selection_number is not None:
        idx = selection_number - 1
        if 0 <= idx < len(cands): return cands[idx]
    if selection_name:
        titles = [c["title"] for c in cands]
        matches = get_close_matches(selection_name.lower(), [t.lower() for t in titles], n=1, cutoff=0.6)
        if matches:
            target = matches[0]
            for c in cands:
                if c["title"].lower() == target:
                    return c
    return None

def build_list_reply(cands):
    lines = ["Here are some dishes you might like (reply with the **number** or **name**):"]
    for i, c in enumerate(cands, 1):
        meta = []
        if c.get("time"): meta.append(f"{c['time']} min")
        if c.get("cuisine"): meta.append(c["cuisine"])
        if c.get("diet"): meta.append(c["diet"])
        tag = " · ".join(meta)
        lines.append(f"{i}. **{c['title']}**" + (f" ({tag})" if tag else ""))
    return "\n".join(lines)

def build_confirm_reply(title):
    return f"Was this recipe for **{title}** helpful? Choose an option below."


def next_turn(state, memory, parsed, search_fn, detail_fn):
    """
    state: one of IDLE, AWAIT_SELECTION, CONFIRM
    memory: dict per-session (stores last_parsed, last_candidates, chosen_title)
    parsed: parsed dict for this user message
    search_fn(parsed) -> list of candidates (title,time,cuisine,diet)
    detail_fn(title) -> dict with {ingredients, steps}
    Returns: new_state, new_memory, reply_text
    """
    mem = memory or {}

    # 1) Greeting: friendly welcome, keep state
    if parsed["is_greet"] and state == IDLE:
        return IDLE, mem, "Hi, I’m **Mika** 👋\nTell me the ingredients (and any limits like veg/vegan or under 20 minutes)."

        # 2) Search / selection logic
    if state in (IDLE, AWAIT_SELECTION):
        # If we already showed a list, try to treat this as a selection first.
        if state == AWAIT_SELECTION:
            chosen = pick_from_candidates(
                mem.get("last_candidates", []),
                parsed["selection_number"],
                parsed["selection_name"]
            )
            if chosen:
                mem["chosen_title"] = chosen["title"]
                details = detail_fn(chosen["title"])
                reply = (
                    f"**{chosen['title']}**\n\n"
                    f"**Ingredients:** {details['ingredients']}\n\n"
                    f"**Steps:** {details['steps']}\n\n"
                    + build_confirm_reply(chosen["title"])
                )
                return CONFIRM, mem, reply

            # If the user didn’t pick a dish, only re-search if the query actually changed.
            if not is_query_changed(mem.get("last_parsed"), parsed):
                if mem.get("last_candidates"):
                    return AWAIT_SELECTION, mem, (
                        "Please reply with the **number** or **dish name** from the list. "
                        "If you want to change ingredients, just type them."
                    )

        # New or changed query → run search
        cands, rationale = search_fn(parsed)
        if not cands:
            return IDLE, mem, "I couldn’t find a good match. Add more details (e.g., cuisine/time) or remove exclusions."

        mem["last_parsed"] = {
            "ingredients": parsed["ingredients"],
            "diet": parsed["diet"],
            "cuisine": parsed["cuisine"],
            "time_limit": parsed["time_limit"],
            "exclude": parsed["exclude"]
        }
        mem["last_candidates"] = cands

        # Build reply header + list
        header_bits = []
        if parsed["ingredients"]: header_bits.append(", ".join(parsed["ingredients"]))
        if parsed["diet"]:        header_bits.append(parsed["diet"])
        if parsed["time_limit"]:  header_bits.append(f"≤ {parsed['time_limit']} min")
        if parsed["cuisine"]:     header_bits.append(parsed["cuisine"])
        reply = ("Got it — " + ", ".join(header_bits) + "\n\n") if header_bits else ""
        reply += build_list_reply(cands)
        return AWAIT_SELECTION, mem, reply

    # 3) Confirmation step
    if state == CONFIRM:
        if parsed["is_yes"]:
            title = mem.get("chosen_title","the recipe")
            mem.clear()
            return IDLE, mem, f"Great! Enjoy **{title}** 🎉\nIf you want another dish, just tell me new ingredients."
        if parsed["is_no"]:
            mem.pop("chosen_title", None)
            return IDLE, mem, "No problem. Share new ingredients or constraints, and I’ll suggest more dishes."
        # If user gives another number/name, try to pick from same candidates
        chosen = pick_from_candidates(mem.get("last_candidates", []),
                                      parsed["selection_number"], parsed["selection_name"])
        if chosen:
            mem["chosen_title"] = chosen["title"]
            details = detail_fn(chosen["title"])
            reply = f"**{chosen['title']}**\n\n**Ingredients:** {details['ingredients']}\n\n**Steps:** {details['steps']}\n\n" + build_confirm_reply(chosen["title"])
            return CONFIRM, mem, reply
        # Otherwise treat as new/changed query → go back to search
        return IDLE, mem, "Tell me your updated ingredients or constraints, and I’ll fetch a new list."

    # default fallback
    return IDLE, mem, "Tell me your ingredients (e.g., *paneer and tomato, veg, under 20 minutes*)."
