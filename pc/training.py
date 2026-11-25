"""Select a small IMU classifier by session and evaluate it on untouched data."""

import argparse
import csv
import hashlib
import json
import os
import platform
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
import numpy as np
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.tree import DecisionTreeClassifier

from motion_data import (
    FEATURE_NAMES,
    LABELS,
    MAX_GAP_MS,
    MIN_SESSIONS,
    MIN_WINDOWS_PER_LABEL,
    WINDOW_SIZE,
    read_sessions,
    select_sessions,
    stack_sessions,
)

ROOT = Path(__file__).resolve().parents[1]
MODEL_HEADER = ROOT / "student" / "05_Project" / "Model.h"
DEPTHS = (2, 3, 4, 5)
SEED = 428
CLASS_IDS = tuple(range(len(LABELS)))


def make_model(depth: int | None):
    if depth is None:
        return DummyClassifier(strategy="most_frequent")
    return DecisionTreeClassifier(max_depth=depth, random_state=SEED)


def scores(actual: np.ndarray, predicted: np.ndarray) -> dict:
    return {
        "accuracy": float(accuracy_score(actual, predicted)),
        "macro_f1": float(f1_score(actual, predicted, labels=CLASS_IDS, average="macro", zero_division=0)),
    }


def compare_models(features: np.ndarray, labels: np.ndarray, groups: np.ndarray) -> list[dict]:
    folds = list(LeaveOneGroupOut().split(features, labels, groups))
    comparison = []
    for depth in (None, *DEPTHS):
        fold_scores = []
        for fit_idx, validation_idx in folds:
            model = make_model(depth).fit(features[fit_idx], labels[fit_idx])
            predicted = model.predict(features[validation_idx])
            fold_scores.append({
                "validation_session": str(groups[validation_idx[0]]),
                "validation_windows": len(validation_idx),
                **scores(labels[validation_idx], predicted),
            })
        accuracy = [row["accuracy"] for row in fold_scores]
        macro_f1 = [row["macro_f1"] for row in fold_scores]
        comparison.append({
            "model": "most_frequent" if depth is None else f"tree_depth_{depth}",
            "max_depth": depth,
            "mean_accuracy": float(np.mean(accuracy)),
            "std_accuracy": float(np.std(accuracy)),
            "mean_macro_f1": float(np.mean(macro_f1)),
            "std_macro_f1": float(np.std(macro_f1)),
            "folds": fold_scores,
        })
    return comparison


def evaluate_model(model, features: np.ndarray, labels: np.ndarray) -> dict:
    predicted = model.predict(features)
    return {
        **scores(labels, predicted),
        "confusion_matrix": confusion_matrix(labels, predicted, labels=CLASS_IDS).tolist(),
        "by_class": classification_report(
            labels, predicted, labels=CLASS_IDS, target_names=LABELS, output_dict=True, zero_division=0
        ),
    }


def model_header(model: DecisionTreeClassifier, run_id: str) -> str:
    tree = model.tree_
    lines = [
        "#pragma once",
        "",
        f"// Decision tree from training run {run_id}.",
        "static constexpr bool MODEL_TRAINED = true;",
        f"static constexpr const char* MODEL_RUN_ID = {json.dumps(run_id)};",
        'static constexpr const char* MODEL_LABELS[3] = {' + ", ".join(map(json.dumps, LABELS)) + "};",
        "",
        "inline int predictMotion(const float features[12]) {",
    ]

    def add_node(node: int, indent: str) -> None:
        left, right = int(tree.children_left[node]), int(tree.children_right[node])
        if left == right:
            class_id = int(model.classes_[int(np.argmax(tree.value[node][0]))])
            lines.append(f"{indent}return {class_id};  // {LABELS[class_id]}")
            return
        feature = int(tree.feature[node])
        # Keep sklearn's double threshold to preserve decisions at float32 boundaries.
        threshold = repr(float(tree.threshold[node]))
        lines.append(f"{indent}// {FEATURE_NAMES[feature]}")
        lines.append(f"{indent}if (static_cast<double>(features[{feature}]) <= {threshold}) {{")
        add_node(left, indent + "    ")
        lines.append(f"{indent}}} else {{")
        add_node(right, indent + "    ")
        lines.append(f"{indent}}}")

    if tree.node_count == 1:
        lines.append("    (void)features;")
    add_node(0, "    ")
    lines.extend(("}", ""))
    return "\n".join(lines)


def export_header(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, delete=False) as temp:
            temporary_path = Path(temp.name)
            temp.write(contents)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_figures(run_dir: Path, comparison: list[dict], matrix: list[list[int]], test_name: str) -> None:
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    figure, axis = plt.subplots(figsize=(7.4, 3.7), layout="constrained")
    names = ["Most frequent", *(f"Tree depth {depth}" for depth in DEPTHS)]
    values = [row["mean_macro_f1"] for row in comparison]
    spread = [row["std_macro_f1"] for row in comparison]
    axis.bar(names, values, yerr=spread, color="#2D667B", capsize=4)
    axis.set_title("Training sessions: leave one session out")
    axis.set_ylabel("Macro F1 (mean ± session SD)")
    axis.set_ylim(0, max(1.04, max(mean + sd for mean, sd in zip(values, spread)) + 0.03))
    axis.tick_params(axis="x", labelrotation=12)
    figure.savefig(run_dir / "cv_comparison.svg")
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(5.5, 4.3), layout="constrained")
    chart = axis.imshow(matrix, cmap="Blues", vmin=0)
    figure.colorbar(chart, ax=axis, label="Windows")
    axis.set_title(f"Final test session: {test_name}")
    axis.set_xlabel("Predicted class")
    axis.set_ylabel("Recorded class")
    axis.set_xticks(CLASS_IDS, LABELS, rotation=15)
    axis.set_yticks(CLASS_IDS, LABELS)
    midpoint = max(max(row) for row in matrix) / 2
    for i, row in enumerate(matrix):
        for j, count in enumerate(row):
            axis.text(j, i, count, ha="center", va="center", color="white" if count > midpoint else "black")
    figure.savefig(run_dir / "test_confusion.svg")
    plt.close(figure)


def run_training(args: argparse.Namespace) -> None:
    sessions, inputs = read_sessions(args.raw_dir)
    train_sessions, test_session = select_sessions(sessions, args.test_session)
    train_x, train_y, train_groups = stack_sessions(train_sessions)

    comparison = compare_models(train_x, train_y, train_groups)
    # The dummy is a reference. Among the deployable trees, favour shallower ties.
    selected = max(comparison[1:], key=lambda row: (row["mean_macro_f1"], -row["max_depth"]))
    tree = make_model(selected["max_depth"]).fit(train_x, train_y)
    baseline = make_model(None).fit(train_x, train_y)

    # The final test session enters the model workflow only after selection and fitting.
    test_x, test_y, _ = stack_sessions([test_session])
    test_results = evaluate_model(tree, test_x, test_y)
    baseline_results = evaluate_model(baseline, test_x, test_y)
    limitations = []
    if comparison[0]["mean_macro_f1"] >= selected["mean_macro_f1"]:
        limitations.append("The selected tree did not beat the most-frequent baseline in training-session CV (macro F1).")
    if baseline_results["macro_f1"] >= test_results["macro_f1"]:
        limitations.append("The selected tree did not beat the most-frequent baseline on the final test session (macro F1).")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = args.results_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    contents = model_header(tree, run_id)
    artifact = run_dir / "Model.h"
    artifact.write_text(contents, encoding="utf-8", newline="\n")
    model_record = {
        "artifact": artifact.name,
        "sha256": hashlib.sha256(contents.encode("utf-8")).hexdigest(),
        "firmware_export": "pending" if args.export else "not_requested",
    }
    train_names = {session.name for session in train_sessions}
    for item in inputs:
        if item["session"] in train_names:
            item["partition"] = "train"
        elif item["session"] == test_session.name:
            item["partition"] = "test"
        else:
            item["partition"] = "excluded"

    manifest = {
        "run_id_utc": run_id,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "matplotlib": matplotlib.__version__,
        },
        "classes_in_order": LABELS,
        "features_in_order": FEATURE_NAMES,
        "window_size": WINDOW_SIZE,
        "max_gap_ms": MAX_GAP_MS,
        "min_complete_sessions": MIN_SESSIONS,
        "min_windows_per_session_and_label": MIN_WINDOWS_PER_LABEL,
        "seed": SEED,
        "split": {
            "rule": "explicit --test-session" if args.test_session else "last complete session by sorted session ID",
            "train_sessions": sorted(train_names),
            "test_session": test_session.name,
            "train_windows": len(train_y),
            "test_windows": len(test_y),
            "excluded_sessions": {session.name: session.issues for session in sessions if session.issues},
        },
        "inputs": inputs,
        "model": model_record,
        "session_metadata": {
            session.name: {"status": session.metadata_status, "sha256": session.metadata_sha256}
            for session in sessions if session.metadata_sha256 is not None
        },
    }
    metrics = {
        "labels_for_confusion_matrix": LABELS,
        "selection_rule": "Highest mean training-session CV macro F1 among trees, shallower depth on ties",
        "selected_model": selected["model"],
        "selected_depth_limit": selected["max_depth"],
        "fitted_tree_depth": tree.get_depth(),
        "fitted_tree_nodes": int(tree.tree_.node_count),
        "limitations": limitations,
        "cv": comparison,
        "final_test": {"session": test_session.name, "tree": test_results, "most_frequent": baseline_results},
    }
    write_json(run_dir / "manifest.json", manifest)
    write_json(run_dir / "metrics.json", metrics)
    with (run_dir / "test_confusion.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["recorded/predicted", *LABELS])
        for label, counts in zip(LABELS, test_results["confusion_matrix"]):
            writer.writerow([label, *counts])
    write_figures(run_dir, comparison, test_results["confusion_matrix"], test_session.name)

    print(f"Results: {run_dir}")
    print(f"Selected {selected['model']} (training CV macro F1 = {selected['mean_macro_f1']:.3f}).")
    print(f"Test session {test_session.name}: tree macro F1 = {test_results['macro_f1']:.3f}; "
          f"baseline = {baseline_results['macro_f1']:.3f}.")
    for limitation in limitations:
        print(f"Warning: {limitation}", file=sys.stderr)
    if args.export:
        target = args.model_header or MODEL_HEADER
        try:
            export_header(target, contents)
        except OSError:
            model_record["firmware_export"] = "failed"
            write_json(run_dir / "manifest.json", manifest)
            raise
        model_record["firmware_export"] = "installed"
        write_json(run_dir / "manifest.json", manifest)
        print(f"Firmware model written to {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results")
    parser.add_argument("--test-session", help="Hold out this complete session (default: last sorted session ID).")
    parser.add_argument("--export", action="store_true", help="Replace the firmware Model.h with the selected tree.")
    parser.add_argument("--model-header", type=Path, help="Optional alternative header path for --export.")
    args = parser.parse_args()
    if args.model_header is not None and not args.export:
        parser.error("--model-header requires --export")
    try:
        run_training(args)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Training could not finish: {exc}\n")


if __name__ == "__main__":
    main()
