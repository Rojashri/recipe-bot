import re

GREETINGS = {"hi","hello","hey","hola","namaste","yo","hii","helo"}
YES_WORDS = {"yes","y","yeah","yep","sure","ok","okay","ya"}
NO_WORDS  = {"no","n","nope","nah"}

STOPWORDS = {
    "the","a","an","and","or","to","of","for","in","on","with","is","are","be","it","this","that",
    "i","you","me","my","your","please","some","make","do","like","want","show","give","need","under",
    "less","more","without","no","not","can","quick","easy","fast","minutes","minute","mins","min",
    "have","got","something","dish","recipe","recipes","find","cook","prepare"
}

COMMON_FIXES = {
    "tomatos":"tomato","spinch":"spinach","chilli":"chili","chillies":"chili",
    "pototo":"potato","paneeer":"paneer","tamoto":"tomato",
}

DIET_KEYWORDS = {
    "veg":"veg","vegetarian":"veg","veggie":"veg",
    "non-veg":"non-veg","nonveg":"non-veg","non vegetarian":"non-veg",
    "vegan":"vegan","egg":"non-veg","chicken":"non-veg","fish":"non-veg","mutton":"non-veg"
}
CUISINES = {"indian","italian","chinese","thai","mexican","american","mediterranean","japanese","korean"}

def clean_text(s: str) -> str:
    s = s.lower().strip()
    for w,r in COMMON_FIXES.items():
        s = s.replace(w,r)
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def extract_time(s: str):
    m = re.search(r"(?:under|within)\s+(\d{1,3})\s*(?:min|mins|minutes)?", s)
    if m: return int(m.group(1))
    m = re.search(r"\b(\d{1,3})\s*(?:min|mins|minutes)\b", s)
    if m: return int(m.group(1))
    if "half an hour" in s or "half hour" in s: return 30
    return None

def tokens(s: str):
    return [t for t in s.split() if t not in STOPWORDS and len(t)>1 and not t.isdigit()]

def parse_message(raw: str):
    s = clean_text(raw)
    words = set(s.split())

    # Intent flags
    is_greet = any(w in GREETINGS for w in words) and len(words) <= 3
    is_yes   = any(w in YES_WORDS for w in words)
    is_no    = any(w in NO_WORDS  for w in words)

    # Detect a pure selection by number (e.g., "2" or "show 3")
    mnum = re.search(r"\b(\d{1,2})\b", s)
    selection_number = int(mnum.group(1)) if mnum else None

    # Selection by dish name: we treat any non-empty text that is not a greeting/help/yes/no
    # as potentially a name; actual matching is done in dialogue step with fuzzy match.
    maybe_name = None
    if not is_greet and not is_yes and not is_no:
        # short text (<=5 words) often a dish name
        if 1 <= len(s.split()) <= 6:
            maybe_name = s

    # Extract constraints for (re)ranking
    diet = None
    for k,v in DIET_KEYWORDS.items():
        if k in s: diet = v; break

    cuisine = None
    for c in CUISINES:
        if c in s: cuisine = c; break

    time_limit = extract_time(s)

    # Excludes: "without onion", "no garlic"
    exclude_ingredients = set()
    for neg in re.findall(r"(?:without|no)\s+([a-z\-]+)", s):
        w = neg.strip()
        if w: exclude_ingredients.add(w)

    # Ingredients (very light)
    ctrl = {"under","within","time","minutes","minute","mins","min"}
    ing = [t for t in tokens(s) if t not in ctrl and t not in exclude_ingredients]

    return {
        "raw": raw,
        "is_greet": is_greet,
        "is_yes": is_yes,
        "is_no": is_no,
        "selection_number": selection_number,
        "selection_name": maybe_name,
        "diet": diet,
        "cuisine": cuisine,
        "time_limit": time_limit,
        "ingredients": ing,
        "exclude": sorted(exclude_ingredients)
    }
