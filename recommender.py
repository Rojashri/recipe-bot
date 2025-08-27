import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class RecipeRecommender:
    def __init__(self, data_path="data/recipes.csv"):
        self.df = pd.read_csv(data_path)
        for col in ["title","ingredients","steps","time","cuisine","diet"]:
            if col not in self.df.columns:
                self.df[col] = "" if col != "time" else 0

        self.df["combined"] = (
            self.df["title"].fillna("") + " " +
            self.df["ingredients"].fillna("") + " " +
            self.df["steps"].fillna("") + " " +
            self.df["cuisine"].fillna("") + " " +
            self.df["diet"].fillna("")
        ).str.lower()

        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1,2), min_df=1)
        self.tfidf = self.vectorizer.fit_transform(self.df["combined"])

    def _apply_filters(self, mask, parsed):
        diet = parsed.get("diet")
        if diet in {"veg","vegetarian"}:
            mask &= self.df["diet"].str.lower().str.contains("veg")
        elif diet in {"non-veg","nonveg","non vegetarian","non_veg"}:
            mask &= self.df["diet"].str.lower().str.contains("non")
        elif diet == "vegan":
            mask &= self.df["diet"].str.lower().str.contains("vegan")

        tl = parsed.get("time_limit")
        if tl:
            mask &= (pd.to_numeric(self.df["time"], errors="coerce") <= tl)

        excludes = set(parsed.get("exclude") or [])
        if excludes:
            ex_mask = ~self.df["ingredients"].str.lower().fillna("").apply(
                lambda x: any(e in x for e in excludes)
            )
            mask &= ex_mask

        return mask

    def search(self, parsed, top_k=5):
        # build query text
        parts = []
        parts += parsed.get("ingredients") or []
        if parsed.get("diet"): parts.append(parsed["diet"])
        if parsed.get("cuisine"): parts.append(parsed["cuisine"])
        q = " ".join(parts) if parts else "easy quick dinner"

        q_vec = self.vectorizer.transform([q.lower()])
        sim = cosine_similarity(q_vec, self.tfidf).ravel()

        # soft boost by ingredient overlap
        inc = set(parsed.get("ingredients") or [])
        if inc:
            boost = self.df["ingredients"].str.lower().fillna("").apply(
                lambda x: sum(1 for t in inc if t in x)
            ).astype(float).values
            if boost.max() > 0: boost /= boost.max()
            sim = 0.85*sim + 0.15*boost

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
        rationale = ", ".join(
            ([", ".join(parsed["ingredients"])] if parsed["ingredients"] else []) +
            ([parsed["diet"]] if parsed["diet"] else []) +
            ([f"≤ {parsed['time_limit']} min"] if parsed["time_limit"] else []) +
            ([parsed["cuisine"]] if parsed["cuisine"] else [])
        )
        return out, rationale

    def details(self, title):
        row = self.df[self.df["title"].str.lower() == str(title).lower()].head(1)
        if row.empty:
            return {"ingredients":"N/A","steps":"N/A"}
        r = row.iloc[0]
        return {"ingredients": r["ingredients"], "steps": r["steps"]}
