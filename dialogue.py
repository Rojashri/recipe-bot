from difflib import get_close_matches

# Dialogue states
IDLE = "idle"                       # waiting for ingredients/query
AWAIT_SELECTION = "await_selection" # list shown, waiting for user to pick
CONFIRM = "confirm"                 # recipe shown, ask yes/no
CLOSED = "closed"                   # chat ended after success

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

def pick_from_candidates(cands, selection_number=None, selection_name=None):
    if not cands:
        return None
    if selection_number is not None:
        idx = selection_number - 1
        if 0 <= idx < len(cands):
            return cands[idx]
    if selection_name:
        titles = [c["title"] for c in cands]
        matches = get_close_matches(selection_name.strip().lower(), [t.lower() for t in titles], n=1, cutoff=0.6)
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
        if c.get("time"):    meta.append(f"{c['time']} min")
        if c.get("cuisine"): meta.append(c["cuisine"])
        if c.get("diet"):    meta.append(c["diet"])
        tag = " · ".join(meta)
        lines.append(f"{i}. **{c['title']}**" + (f" ({tag})" if tag else ""))
    return "\n".join(lines)

def build_confirm_reply(title):
    return f"Was this recipe for **{title}** helpful? Choose an option below."

def next_turn(state, memory, parsed, search_fn, detail_fn):
    """
    Returns: new_state, new_memory, reply_text
    """
    mem = memory or {}

    # If chat is closed, keep it closed.
    if state == CLOSED:
        return CLOSED, mem, "This chat is closed. Click **New chat** to start again."

    # Greeting
    if parsed["is_greet"] and state == IDLE:
        return IDLE, mem, (
            "Hi there! I’m **Mika** 👋\n"
            "What recipe you need? Just tell me the ingredients (and any limits like *veg / non-veg / vegan*, cuisine, or time)."
        )

    # Search / selection
    if state in (IDLE, AWAIT_SELECTION):
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

            if not is_query_changed(mem.get("last_parsed"), parsed):
                if mem.get("last_candidates"):
                    return AWAIT_SELECTION, mem, (
                        "Please reply with the **number** or **dish name** from the list. "
                        "If you want to change ingredients, just type them."
                    )

        cands, _ = search_fn(parsed)
        if not cands:
            return IDLE, mem, (
                "I couldn’t find a good match. Add more details (e.g., cuisine or time), or remove exclusions."
            )

        mem["last_parsed"] = {
            "ingredients": parsed["ingredients"],
            "diet": parsed["diet"],
            "cuisine": parsed["cuisine"],
            "time_limit": parsed["time_limit"],
            "exclude": parsed["exclude"]
        }
        mem["last_candidates"] = cands

        header_bits = []
        if parsed["ingredients"]: header_bits.append(", ".join(parsed["ingredients"]))
        if parsed["diet"]:        header_bits.append(parsed["diet"])
        if parsed["time_limit"]:  header_bits.append(f"≤ {parsed['time_limit']} min")
        if parsed["cuisine"]:     header_bits.append(parsed["cuisine"])
        reply = ("Got it — " + ", ".join(header_bits) + "\n\n") if header_bits else ""
        reply += build_list_reply(cands)
        return AWAIT_SELECTION, mem, reply

    # Confirm
    if state == CONFIRM:
        if parsed["is_yes"]:
            title = mem.get("chosen_title", "the recipe")
            mem.clear()
            # move to CLOSED state so this chat is finished
            return CLOSED, mem, f"Great! Enjoy **{title}** 🎉\nThis chat is now closed. Click **New chat** to start over."
        if parsed["is_no"]:
            mem.pop("chosen_title", None)
            return IDLE, mem, "No problem. Share new ingredients or constraints, and I’ll suggest more dishes."

        # Try another selection from the same list
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

        return IDLE, mem, "Tell me your updated ingredients or constraints, and I’ll fetch a new list."

    return IDLE, mem, "Tell me your ingredients (e.g., *paneer and tomato, veg/non-veg, under 20 minutes*)."
