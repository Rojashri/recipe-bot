# nlp_utils.py  — robust parsing for Mika
import re

# ---- Lexicons ----
GREETINGS = {"hi", "hello", "hey", "hola", "namaste", "yo", "hii", "helo"}
YES_WORDS = {
    "yes","y","yeah","yep","sure","ok","okay","ya","proceed","confirm","go","goahead","looks","good","helpful"
}
NO_WORDS  = {
    "no","n","nope","nah","cancel","back","another","different","unhelpful","not"
}

# Common typos -> fixes
COMMON_FIXES = {
    "tomatos":"tomato","spinch":"spinach","chilli":"chili","chillies":"chili",
    "pototo":"potato","paneeer":"paneer","tamoto":"tomato",
}

CUISINES = {"indian","italian","chinese","thai","mexican","american","mediterranean","japanese","korean"}

# Diet detectors
NONVEG_RE = re.compile(r"\b(?:non[-\s]?veg(?:etarian)?|nonvegetarian|n\s*veg|nv)\b", re.I)
VEG_RE    = re.compile(r"\b(?:veg(?:etarian)?)\b", re.I)
VEGAN_RE  = re.compile(r"\bvegan\b", re.I)

# Words we never want as ingredients
STOPWORDS = {
    "the","a","an","and","or","to","of","for","in","on","with","is","are","be","it","this","that",
    "i","you","me","my","your","please","some","make","do","like","want","show","give","need",
    "have","got","something","dish","recipe","recipes","find","cook","prepare",
    "under","within","less","more","than","time","minutes","minute","mins","min",
    "without","no","not","can","quick","easy","fast","hi","hello","hey"
}

# ---- Helpers ----
def clean_text(s: str) -> str:
    s = (s or "").lower().strip()
    for w, r in COMMON_FIXES.items():
        s = s.replace(w, r)
    # keep hyphens/spaces (for non-veg), strip other punctuation
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def extract_time(s: str):
    m = re.search(r"(?:under|<=?|less\s+than)\s*(\d{1,3})\s*(?:min|mins|minutes?)\b", s)
    if m: return int(m.group(1))
    m = re.search(r"\b(\d{1,3})\s*(?:min|mins|minutes?)\b", s)
    if m: return int(m.group(1))
    if "half an hour" in s or "half hour" in s: return 30
    return None

def detect_diet(s: str):
    """Return 'non-veg', 'veg', 'vegan', or None."""
    if VEGAN_RE.search(s):
        return "vegan"
    if NONVEG_RE.search(s):
        return "non-veg"
    if VEG_RE.search(s):
        return "veg"
    return None

def strip_diet_terms(s: str):
    """Remove diet phrases so they don't become ingredients."""
    s = VEGAN_RE.sub(" ", s)
    s = NONVEG_RE.sub(" ", s)
    s = VEG_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()

def tokens(s: str):
    return [t for t in s.split() if t and t not in STOPWORDS and not t.isdigit() and len(t) > 1]

# ---- Main parser ----
def parse_message(raw: str):
    s = clean_text(raw)

    # Detect diet first (so 'non veg' doesn't split into 'non' + 'veg')
    diet = detect_diet(s)
    s_wo_diet = strip_diet_terms(s)

    # Intent flags
    words = set(s_wo_diet.split())
    is_greet = any(w in GREETINGS for w in words) and len(words) <= 3
    is_yes   = any(w in YES_WORDS for w in words) or ("go ahead" in s or "looks good" in s)
    is_no    = any(w in NO_WORDS  for w in words) or ("not helpful" in s or "other options" in s or "see other" in s)

    # Selection by number (e.g., "2")
    mnum = re.match(r"^\s*(\d{1,2})\s*$", s_wo_diet)
    selection_number = int(mnum.group(1)) if mnum else None

    # Possible selection by dish name (short text, not a pure yes/no/greet)
    maybe_name = None
    if not is_greet and not is_yes and not is_no:
        if 1 <= len(s_wo_diet.split()) <= 6:
            maybe_name = raw.strip()

    # Cuisine
    cuisine = None
    for c in CUISINES:
        if re.search(rf"\b{c}\b", s): cuisine = c; break

    # Time
    time_limit = extract_time(s)

    # Exclusions: "without onion", "no garlic"
    exclude_ingredients = set()
    for ex in re.findall(r"\bwithout\s+([a-z\s,]+)", s_wo_diet):
        for w in re.split(r"[,\s]+", ex):
            w = w.strip()
            if w: exclude_ingredients.add(w)
    for ex in re.findall(r"\bno\s+([a-z]+)\b", s_wo_diet):
        exclude_ingredients.add(ex.strip())

    # Ingredients from the remaining text (after removing diet words)
    ctrl = {"under","within","time","minutes","minute","mins","min","without","no"}
    ing = [t for t in tokens(s_wo_diet) if t not in ctrl and t not in exclude_ingredients]

    return {
        "raw": raw,
        "is_greet": is_greet,
        "is_yes": is_yes,
        "is_no": is_no,
        "selection_number": selection_number,
        "selection_name": maybe_name,
        "diet": diet,                 # 'veg' | 'non-veg' | 'vegan' | None
        "cuisine": cuisine,           # or None
        "time_limit": time_limit,     # or None
        "ingredients": ing,           # list[str]
        "exclude": sorted(exclude_ingredients)
    }
