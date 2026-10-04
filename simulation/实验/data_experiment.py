"""Reproducible synthetic byte-budget selection experiment; no labels in selector."""
import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
import hashlib
import json
import time
import ctypes
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import accuracy_score, f1_score, log_loss
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "结果" / "数据实验"
CONFIG = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))

def sample(rng, n, centers, noise=1.1):
    y = rng.integers(0, len(centers), n)
    return centers[y] + rng.normal(0, noise, (n, centers.shape[1])), y

def dataset(seed, scenario):
    rng = np.random.default_rng(seed)
    centers = rng.normal(0, 1.1, (CONFIG["n_classes"], CONFIG["n_features"]))
    warm_x, warm_y = sample(rng, 240, centers)
    teacher = LogisticRegression(max_iter=300).fit(warm_x, warm_y)
    target_centers = centers.copy()
    if scenario == "sensor_shift":
        # Unseen sensor coordinate offset; truth rules remain mixture component identity.
        target_centers += np.array([2.8, -2.0, 1.5, 0, 0, 0, 0, 0])
    x, y = sample(rng, CONFIG["n_stream"], target_centers)
    # Correlated repetition stays wholly inside training; independent test generated afterwards.
    for i in range(1, len(x)):
        if rng.random() < 0.7:
            x[i] = x[i - 1] + rng.normal(0, 0.025, x.shape[1])
            y[i] = y[i - 1]
    test_x, test_y = sample(rng, CONFIG["n_test"], target_centers)
    start = time.perf_counter()
    probabilities = teacher.predict_proba(x)
    perception_ms = (time.perf_counter() - start) * 1000
    # Sender sees features/predictions only. Receiver annotation is separate and charged.
    records = []
    for i, features in enumerate(x):
        packet = {"seq": i, "collected_at": round(i / 50, 3), "source": "synthetic-sensor",
                  "features": np.round(features, 4).tolist(),
                  "prediction": int(probabilities[i].argmax()),
                  "confidence": round(float(probabilities[i].max()), 6), "payload_bytes": 0}
        for _ in range(4):
            size = len(json.dumps(packet, separators=(",", ":")).encode("utf-8"))
            if packet["payload_bytes"] == size:
                break
            packet["payload_bytes"] = size
        assert len(json.dumps(packet, separators=(",", ":")).encode()) == packet["payload_bytes"]
        records.append(packet)
    # Train from exactly the transmitted rounded features.
    x = np.array([r["features"] for r in records])
    sizes = np.array([r["payload_bytes"] + CONFIG["annotation_bytes_per_sample"] for r in records])
    return x, y, test_x, test_y, records, sizes, perception_ms

def ranking(strategy, records, features, rng):
    n = len(records)
    if strategy == "interval":
        # Recursive midpoint order produces uniform coverage at arbitrary byte ratios.
        ranges, order = [(0, n)], []
        while ranges:
            lo, hi = ranges.pop(0)
            if lo < hi:
                mid = (lo + hi) // 2
                order.append(mid)
                ranges.extend([(lo, mid), (mid + 1, hi)])
        return order
    if strategy == "random":
        return rng.permutation(n).tolist()
    confidence = np.array([r["confidence"] for r in records])
    if strategy in ("confidence", "uncertainty"):
        return np.argsort(-confidence if strategy == "confidence" else confidence, kind="stable").tolist()
    if strategy == "novelty":
        # Greedy farthest-point coverage, raw features; no truth labels or test statistics.
        distances = np.full(n, np.inf)
        order, used = [], np.zeros(n, dtype=bool)
        next_index = 0
        for _ in range(n):
            order.append(next_index)
            used[next_index] = True
            distances = np.minimum(distances, np.sum((features - features[next_index]) ** 2, axis=1))
            distances[used] = -1
            next_index = int(distances.argmax())
        return order
    return list(range(n))

def select(strategy, ratio, records, x, sizes, seed):
    rng = np.random.default_rng(seed + 10000)
    picked, windows = [], []
    for start in range(0, len(records), CONFIG["window_size"]):
        stop = min(start + CONFIG["window_size"], len(records))
        budget = int(sizes[start:stop].sum() * ratio)
        order = (list(range(0, stop-start, max(1, round(1/ratio)))) if strategy == "interval" else ranking(strategy, records[start:stop], x[start:stop], rng))
        used = 0
        for local in order:
            index = start + local
            if strategy == "all" or used + sizes[index] <= budget:
                picked.append(index)
                used += int(sizes[index])
        windows.append({"window": start // CONFIG["window_size"], "budget": budget,
                        "sent": used, "violation": used > budget})
    return np.array(sorted(picked), dtype=int), windows

def train(x, y, chosen, seed, mode, overhead_ms):
    model = SGDClassifier(loss="log_loss", alpha=0.001, learning_rate="constant", eta0=0.03,
                          random_state=seed)
    rng = np.random.default_rng(seed + 20000)
    start = time.perf_counter()
    updates = 0
    while True:
        elapsed = (time.perf_counter() - start) * 1000
        if mode == "fixed_updates" and updates >= CONFIG["fixed_updates"]:
            break
        if mode == "wall_budget" and elapsed + overhead_ms >= CONFIG["wall_budget_ms"]:
            break
        batch = rng.choice(chosen, CONFIG["batch_size"], replace=True)
        model.partial_fit(x[batch], y[batch], classes=np.arange(CONFIG["n_classes"]))
        updates += 1
    train_ms = (time.perf_counter() - start) * 1000
    return model if updates else None, updates, train_ms

def peak_working_set():
    class Counters(ctypes.Structure):
        _fields_ = [("cb",ctypes.c_ulong),("faults",ctypes.c_ulong)] + [(name,ctypes.c_size_t) for name in
            ("peak","working","paged_peak","paged","nonpaged_peak","nonpaged","pagefile","pagefile_peak")]
    counters=Counters()
    counters.cb=ctypes.sizeof(counters)
    ctypes.windll.kernel32.GetCurrentProcess.restype=ctypes.c_void_p
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_ulong]
    ok=ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(counters),counters.cb)
    if not ok:
        raise ctypes.WinError()
    return counters.peak
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Memory sampled outside measured compute paths.
    results, window_rows = [], []
    run_start = time.perf_counter()
    with threadpool_limits(limits=1):
        for scenario in CONFIG["scenarios"]:
            for seed in CONFIG["seeds"]:
                x, y, test_x, test_y, records, sizes, perception_ms = dataset(seed, scenario)
                if seed == CONFIG["seeds"][0]:
                    (OUT / f"{scenario}-stream.jsonl").write_text(
                        "\n".join(json.dumps(r, separators=(",", ":")) for r in records) + "\n", encoding="utf-8")
                    np.savez_compressed(OUT / f"{scenario}-truth-test.npz", labels=y,
                                        test_features=test_x, test_labels=test_y)
                for ratio in CONFIG["budget_ratios"]:
                    for strategy in CONFIG["strategies"]:
                        start = time.perf_counter()
                        chosen, windows = select(strategy, ratio, records, x, sizes, seed)
                        selection_ms = (time.perf_counter() - start) * 1000
                        violations = sum(w["violation"] for w in windows)
                        if strategy != "all":
                            assert violations == 0, "Byte budget violated"
                        for window in windows:
                            window_rows.append(dict(scenario=scenario, seed=seed, ratio=ratio, strategy=strategy, **window))
                        for mode in ("fixed_updates", "wall_budget"):
                            model, updates, train_ms = train(x, y, chosen, seed, mode, selection_ms + perception_ms)
                            # Cold fallback prediction is documented if selection exhausts wall-clock budget.
                            probabilities = (model.predict_proba(test_x) if model else
                                             np.full((len(test_y), CONFIG["n_classes"]), 1 / CONFIG["n_classes"]))
                            predictions = probabilities.argmax(axis=1)
                            results.append(dict(scenario=scenario, seed=seed, budget_ratio=ratio, strategy=strategy,
                                compute_mode=mode, candidates=len(x), sent=len(chosen), dropped=len(x)-len(chosen),
                                candidate_bytes=int(sizes.sum()), sent_bytes=int(sizes[chosen].sum()),
                                saved_fraction=1-float(sizes[chosen].sum()/sizes.sum()), budget_violations=violations,
                                selection_ms=selection_ms, perception_ms=perception_ms,
                                train_ms=train_ms, total_compute_ms=selection_ms+perception_ms+train_ms,
                                wall_budget_overrun_ms=max(0, selection_ms+perception_ms+train_ms-CONFIG["wall_budget_ms"])
                                    if mode == "wall_budget" else 0,
                                updates=updates, processed_samples=updates*CONFIG["batch_size"],
                                class_coverage=len(np.unique(y[chosen])),
                                rounded_feature_unique_fraction=len(np.unique(x[chosen].round(1), axis=0))/len(chosen),
                                accuracy=accuracy_score(test_y,predictions),
                                macro_f1=f1_score(test_y,predictions,average="macro",zero_division=0),
                                test_log_loss=log_loss(test_y,probabilities,labels=np.arange(CONFIG["n_classes"]))))
                print(f"Finished {scenario} seed={seed}", flush=True)
    frame = pd.DataFrame(results)
    frame.to_csv(OUT / "runs.csv", index=False)
    pd.DataFrame(window_rows).to_csv(OUT / "window-budgets.csv", index=False)
    summary = frame.groupby(["scenario","compute_mode","budget_ratio","strategy"]).agg(
        accuracy_mean=("accuracy","mean"),accuracy_std=("accuracy","std"),
        f1_mean=("macro_f1","mean"),f1_std=("macro_f1","std"),
        bytes_mean=("sent_bytes","mean"),saved_mean=("saved_fraction","mean"),
        select_ms_mean=("selection_ms","mean"),train_ms_mean=("train_ms","mean"),
        updates_mean=("updates","mean"),wall_overrun_max=("wall_budget_overrun_ms","max"),
        violations_max=("budget_violations","max")).reset_index()
    summary.to_csv(OUT / "summary.csv", index=False)
    for scenario in CONFIG["scenarios"]:
        fig, axes = plt.subplots(1, 2, figsize=(11,4), constrained_layout=True)
        for ax, mode in zip(axes,("fixed_updates","wall_budget")):
            subset = summary[(summary.scenario==scenario)&(summary.compute_mode==mode)]
            for strategy in CONFIG["strategies"]:
                rows=subset[subset.strategy==strategy]
                ax.errorbar(rows.budget_ratio,rows.f1_mean,yerr=rows.f1_std,label=strategy,marker="o",capsize=3)
            ax.set(title=f"{scenario} / {mode}",xlabel="Payload+annotation budget ratio",ylabel="Independent test macro F1")
            ax.grid(alpha=.2)
        axes[1].legend(fontsize=8)
        fig.savefig(OUT / f"{scenario}-f1.png",dpi=160)
        plt.close(fig)
    peak = peak_working_set()

    metadata={"config":CONFIG,"runs":len(frame),"wall_seconds":time.perf_counter()-run_start,
              "process_peak_working_set_mb":peak/1024**2,"memory_scope":"Windows process peak working set; includes interpreter/libraries, not GPU or Docker",
              "config_sha256":hashlib.sha256((Path(__file__).parent / "config.json").read_bytes()).hexdigest(),
              "clock":"Wall-clock budget is soft: checked between mini-batches; max overrun recorded",
              "annotation":"5 bytes/sample (uint32 seq+uint8 label), simulated perfect label lookup at receiver; charged in every budget",
              "selector_label_access":False,"test_used_for_selection":False,
              "common_cost":"Teacher prediction charged once per whole stream in each trial; data generation/serialization excluded from wall-clock compute budget, common preprocessing",
              "novelty":"Full-window farthest-point ranking, O(window^2); extra cost explicitly counted",
              "all":"Full transmission is a reference, may exceed byte budget, not an optimality upper bound",
              "holdout":"Independent draws; repeated training observations do not cross into test; no hyperparameter tuning"}
    (OUT / "metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
    print(json.dumps({"runs":len(frame),"seconds":metadata["wall_seconds"],"output":str(OUT)}))

if __name__ == "__main__":
    main()


