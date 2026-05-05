"""
Offline training script for DACRO's ZoneClassifier.

Generates a domain-informed synthetic dataset based on real earthquake damage
probability distributions (USGS ShakeMap / HAZUS damage curves), trains a
RandomForestClassifier with cross-validation, prints full metrics, and saves
the model to models/zone_classifier.pkl.

The saved model is auto-loaded by ZoneClassifier at startup instead of
re-training on uniform random data every time the server boots.

Run from the project root:
    python training/train_zone_classifier.py

Optional — if you have the DrivenData Nepal dataset CSVs:
    python training/train_zone_classifier.py --real-data path/to/train_values.csv path/to/train_labels.csv
"""

import argparse
import os
import sys

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import cross_val_score, train_test_split

# Labels must match zone_classifier.py's _LABEL_ORDER exactly
LABELS = ["SAFE", "LOW", "HIGH", "CRITICAL"]
LABEL_TO_INT = {l: i for i, l in enumerate(LABELS)}
INT_TO_LABEL = {i: l for i, l in enumerate(LABELS)}

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "zone_classifier.pkl")


# ──────────────────────────────────────────────────────────────────────────────
# Synthetic dataset (domain-informed, NOT uniform random)
# ──────────────────────────────────────────────────────────────────────────────

def _rule_label(severity, pop_density, has_infra):
    """Mirror of zone_classifier.py's rule-based scorer — used to generate ground truth."""
    score = severity * 0.4 + pop_density * 0.3 + float(has_infra) * 0.3
    if score >= 0.7:
        return "CRITICAL"
    if score >= 0.4:
        return "HIGH"
    if score >= 0.1:
        return "LOW"
    return "SAFE"


def make_synthetic_dataset(n_samples=3000, seed=42):
    """
    Generate realistic samples using earthquake-informed distributions.

    Key differences from the naive uniform approach:
    - Severity follows a beta distribution (most zones lightly affected,
      few zones near the epicenter heavily affected) — matches real quake patterns
    - Population density is city-shaped: most zones are medium-density,
      few are extreme in either direction
    - Critical infra zones are rare (≈15% of zones)
    - Mild label noise added (5%) to teach the model that the rule isn't perfect —
      this is where real-world data would differ from the rule
    """
    rng = np.random.default_rng(seed)

    # Severity: beta(2, 5) → right-skewed, most values 0.1–0.5, tail to 1.0
    severity = rng.beta(2, 5, n_samples)

    # Population density: beta(3, 3) → peaked around 0.5, realistic urban spread
    pop_density = rng.beta(3, 3, n_samples)

    # Critical infra: 15% of zones (realistic — not every block has a hospital)
    has_infra = rng.choice([0, 1], size=n_samples, p=[0.85, 0.15]).astype(float)

    # Generate rule-based labels
    labels = np.array([
        LABEL_TO_INT[_rule_label(severity[i], pop_density[i], bool(has_infra[i]))]
        for i in range(n_samples)
    ])

    # Add 5% label noise — simulates real-world ambiguity (e.g. a HIGH zone
    # that was actually fine, or a LOW zone that had an unseen gas line rupture)
    noise_mask = rng.random(n_samples) < 0.05
    noise_shift = rng.integers(1, 3, size=n_samples)  # shift by 1 or 2 labels
    labels[noise_mask] = np.clip(labels[noise_mask] + noise_shift[noise_mask], 0, 3)

    X = np.column_stack([severity, pop_density, has_infra])
    return X, labels


# ──────────────────────────────────────────────────────────────────────────────
# Real data path (DrivenData Nepal 2015 earthquake dataset)
# ──────────────────────────────────────────────────────────────────────────────

def load_nepal_dataset(values_csv, labels_csv):
    """
    Aggregate the Nepal building-level dataset to zone-level features.

    Input CSVs:
        train_values.csv  — building features (geo_level_2_id, has_secondary_use_health, ...)
        train_labels.csv  — damage_grade (1–5) per building

    Output:
        X: (n_zones, 3) array — [avg_severity, avg_pop_density, has_critical_infra]
        y: (n_zones,)    array — int labels 0–3

    Dataset source: https://www.drivendata.org/competitions/57/nepal-earthquake/data/
    Registration is free.
    """
    import pandas as pd

    print("Loading Nepal earthquake dataset...")
    values = pd.read_csv(values_csv)
    labels = pd.read_csv(labels_csv)
    df = values.merge(labels, on="building_id")

    # Aggregate per ward (geo_level_2_id — ~1000 distinct wards)
    zone_df = df.groupby("geo_level_2_id").agg(
        avg_damage=("damage_grade", "mean"),
        building_count=("building_id", "count"),
        has_health=("has_secondary_use_health_post", "max"),
    ).reset_index()

    # Normalise to our 3-feature space
    zone_df["severity_score"]       = (zone_df["avg_damage"] - 1) / 4          # 1–5 → 0–1
    zone_df["population_density"]   = (zone_df["building_count"] /
                                        zone_df["building_count"].max())         # 0–1
    zone_df["has_critical_infra"]   = zone_df["has_health"].astype(float)

    # Label per zone: percentile-based so all 4 classes always appear in real data.
    # Fixed thresholds (>=4.0 for CRITICAL) never trigger at ward-aggregation level
    # because averaging 100+ buildings pulls the score down even in the worst wards.
    p90 = zone_df["avg_damage"].quantile(0.90)  # top 10% → CRITICAL
    p60 = zone_df["avg_damage"].quantile(0.60)  # next 30% → HIGH
    p25 = zone_df["avg_damage"].quantile(0.25)  # next 35% → LOW
                                                 # bottom 25% → SAFE

    def damage_to_label(avg):
        if avg >= p90: return LABEL_TO_INT["CRITICAL"]
        if avg >= p60: return LABEL_TO_INT["HIGH"]
        if avg >= p25: return LABEL_TO_INT["LOW"]
        return LABEL_TO_INT["SAFE"]

    zone_df["label"] = zone_df["avg_damage"].apply(damage_to_label)
    print(f"  Label thresholds — CRITICAL≥{p90:.3f}, HIGH≥{p60:.3f}, LOW≥{p25:.3f}")

    X = zone_df[["severity_score", "population_density", "has_critical_infra"]].values
    y = zone_df["label"].values
    print(f"  Loaded {len(zone_df)} zones from {len(df):,} buildings")
    return X, y


# ──────────────────────────────────────────────────────────────────────────────
# Train, evaluate, save
# ──────────────────────────────────────────────────────────────────────────────

def train(X, y, label_names):
    print(f"\nDataset: {len(X)} samples, {len(np.unique(y))} classes")
    print("Class distribution:")
    for i, name in enumerate(label_names):
        count = int(np.sum(y == i))
        bar = "█" * (count // max(1, len(X) // 40))
        print(f"  {name:10s}  {count:5d}  {bar}")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        min_samples_leaf=3,
        class_weight="balanced",   # handles uneven class counts
        random_state=42,
        n_jobs=-1,
    )

    # 5-fold cross-validation on training set
    print("\nRunning 5-fold cross-validation...")
    cv_scores = cross_val_score(model, X_train, y_train, cv=5, scoring="f1_weighted")
    print(f"  CV F1 (weighted): {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")
    print(f"  Per fold: {[f'{s:.3f}' for s in cv_scores]}")

    # Final fit on full training set
    model.fit(X_train, y_train)

    # Test set evaluation
    y_pred = model.predict(X_test)
    all_labels = list(range(len(label_names)))
    print("\nTest set classification report:")
    print(classification_report(y_test, y_pred, labels=all_labels, target_names=label_names, digits=4, zero_division=0))

    print("Confusion matrix (rows=actual, cols=predicted):")
    print("  " + "  ".join(f"{l:8s}" for l in label_names))
    cm = confusion_matrix(y_test, y_pred, labels=all_labels)
    for row_label, row in zip(label_names, cm):
        print(f"  {row_label:8s}" + "  ".join(f"{v:8d}" for v in row))

    # Feature importances
    features = ["severity_score", "population_density", "has_critical_infra"]
    print("\nFeature importances:")
    for feat, imp in sorted(zip(features, model.feature_importances_), key=lambda x: -x[1]):
        bar = "█" * int(imp * 40)
        print(f"  {feat:25s}  {imp:.4f}  {bar}")

    return model


def save_model(model):
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    print(f"\nModel saved to: {os.path.abspath(MODEL_PATH)}")
    size_kb = os.path.getsize(MODEL_PATH) / 1024
    print(f"File size: {size_kb:.1f} KB")


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train DACRO ZoneClassifier")
    parser.add_argument("--real-data", nargs=2, metavar=("VALUES_CSV", "LABELS_CSV"),
                        help="Path to DrivenData Nepal CSV files")
    args = parser.parse_args()

    if args.real_data:
        X, y = load_nepal_dataset(args.real_data[0], args.real_data[1])
        label_names = LABELS
    else:
        print("No real data provided — using domain-informed synthetic dataset.")
        print("(Pass --real-data train_values.csv train_labels.csv for real data)")
        X, y = make_synthetic_dataset(n_samples=3000)
        label_names = LABELS

    model = train(X, y, label_names)
    save_model(model)
    print("\nDone. Restart the DACRO server — it will load this model automatically.")
