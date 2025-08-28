import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class RecipeRecommender:
    def __init__(self, data_path="data/recipes.csv"):
        self.df = pd.read_csv(data_path)

        # Ensure required columns exist
        for col in ["title", "ingredients", "steps", "time", "cuisine", "diet"]:
            if col not in self.df.columns:
                self.df[col] = "" if col != "time" else 0

        # Normalized diet category (exact match filtering)
        def norm_diet(x: str) -> str:
            s = str(x or "").strip().lower()
            s = s.replace(" ", "").replace("-", "").replace("_", "")
            if s in {"veg", "vegetarian", "veggie"}:
                return "veg"
            if s in {"nonveg", "nonvegetarian", "egg", "eggetarian", "chicken", "fish", "mutton", "prawn"}:
                return "non-veg"
            if s in {"vegan"}:
                return "vegan"
            return ""

        self.df["diet_norm"] = self.df["diet"].map(norm_diet)

        # Unified lowercase text for vector search
        self.df["combined"] = (
            self.df["title"].fillna("") + " " +
            self.df["ingredients"].fillna("") + " " +
            self.df["steps"].fillna("") + " " +
            self.df["cuisine"].fillna("") + " " +
            self.df["diet"].fillna("")
        ).str.lower()

        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1)
        self.tfidf = self.vectorizer.fit_transform(self.df["combined"])

    # ---------- helpers ----------
    def _filter_by_diet(self, mask, diet):
        """diet ∈ {'veg','non-veg','vegan', None} — exact category filtering"""
        if not diet:
            return mask
        dn = self.df["diet_norm"]
        if diet == "veg":
            mask &= (dn == "veg")
        elif diet == "non-veg":
            mask &= (dn == "non-veg")
        elif diet == "vegan":
            mask &= (dn == "vegan")
        return mask

    def _apply_filters(self, mask, parsed):
        # Diet (no default)
        mask = self._filter_by_diet(mask, (parsed.get("diet") or "").lower() or None)

        # Time (<= limit)
        tl = parsed.get("time_limit")
        if tl:
            mask &= (pd.to_numeric(self.df["time"], errors="coerce") <= tl)

        # Exclusions
        excludes = set(parsed.get("exclude") or [])
        if excludes:
            ing_col = self.df["ingredients"].fillna("").str.lower()
            mask &= ~ing_col.apply(lambda x: any(e in x for e in excludes))

        # Cuisine (only if specified)
        cuisine = (parsed.get("cuisine") or "").lower()
        if cuisine:
            mask &= self.df["cuisine"].fillna("").str.lower().str.contains(rf"\b{cuisine}\b")

        return mask

    # ---------- public API ----------
    def search(self, parsed, top_k=5):
        parts = []
        parts += parsed.get("ingredients") or []
        if parsed.get("diet"):    parts.append(parsed["diet"])
        if parsed.get("cuisine"): parts.append(parsed["cuisine"])
        q = " ".join(parts) if parts else "easy quick dinner"

        q_vec = self.vectorizer.transform([q.lower()])
        sim = cosine_similarity(q_vec, self.tfidf).ravel()

        # Soft ingredient-overlap boost
        inc = set(parsed.get("ingredients") or [])
        if inc:
            ing_col = self.df["ingredients"].fillna("").str.lower()
            boost = ing_col.apply(lambda x: sum(1 for t in inc if t in x)).astype(float).values
            if boost.max() > 0:
                boost /= boost.max()
                sim = 0.85 * sim + 0.15 * boost

        # Apply filters
        mask = pd.Series(True, index=self.df.index)
        mask = self._apply_filters(mask, parsed)
        masked = np.where(mask.values, sim, -1.0)

        idx = np.argsort(masked)[::-1][:top_k]
        idx = [i for i in idx if masked[i] > 0]

        out = []
        for i in idx:
            row = self.df.iloc[i]
            out.append({
                "title": row["title"],
                "time": int(row["time"]) if str(row["time"]).isdigit() else None,
                "cuisine": row["cuisine"],
                "diet": row["diet"]
            })

        # Rationale
        rp = []
        if parsed.get("ingredients"): rp.append(", ".join(parsed["ingredients"]))
        if parsed.get("diet"):        rp.append(parsed["diet"])
        if parsed.get("time_limit"):  rp.append(f"≤ {parsed['time_limit']} min")
        if parsed.get("cuisine"):     rp.append(parsed["cuisine"])
        return out, ", ".join(rp)

    def details(self, title):
        row = self.df[self.df["title"].str.lower() == str(title).lower()].head(1)
        if row.empty:
            return {"ingredients": "N/A", "steps": "N/A"}
        r = row.iloc[0]
        return {"ingredients": r["ingredients"], "steps": r["steps"]}
