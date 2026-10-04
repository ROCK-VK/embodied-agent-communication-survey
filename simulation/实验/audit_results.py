"""Independent cross-artifact checks on measured results, accounting, and reproducibility."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
data=ROOT/"结果/数据实验"
runs=pd.read_csv(data/"runs.csv")
assert len(runs)==360
assert not runs.duplicated(["scenario","seed","budget_ratio","strategy","compute_mode"]).any()
assert runs[(runs.strategy!="all")].budget_violations.max()==0
assert runs[runs.compute_mode=="fixed_updates"].updates.eq(50).all()
assert np.isfinite(runs[["accuracy","macro_f1","test_log_loss"]].to_numpy()).all()
for (_,seed),group in runs[(runs.budget_ratio==1)&(runs.compute_mode=="fixed_updates")].groupby(["scenario","seed"]):
    assert group.macro_f1.nunique()==1,"At full budget all strategies must train same sorted data"
metadata=json.loads((data/"metadata.json").read_text())
assert metadata["config_sha256"]==hashlib.sha256((ROOT/"实验/config.json").read_bytes()).hexdigest()
for scenario in ("redundant","sensor_shift"):
    records=[json.loads(line) for line in (data/f"{scenario}-stream.jsonl").read_text().splitlines()]
    assert len(records)==1500
    assert all("label" not in r for r in records)
    assert all(len(json.dumps(r,separators=(",",":")).encode())==r["payload_bytes"] for r in records)
    selected=runs[(runs.seed==11)&(runs.scenario==scenario)]
    assert selected.candidate_bytes.eq(sum(r["payload_bytes"]+5 for r in records)).all()
    truth=np.load(data/f"{scenario}-truth-test.npz")
    assert len(truth["labels"])==1500 and len(truth["test_labels"])==1000
ros1=json.loads((ROOT/"结果/ROS1/summary.json").read_text())
assert len(ros1)==5
assert all(r["budget_violations"]==0 and r["unexplained_receiver_missing"]==0 for r in ros1)
normal=[json.loads(line)["seq"] for line in (ROOT/"结果/ROS1/normal/received.jsonl").read_text().splitlines()]
ros2=json.loads((ROOT/"结果/ROS2/summary.json").read_text())
assert ros2["pipeline"]["seqs"]==normal
assert ros2["pipeline"]["received_count"]==42
incompatible=next(q for q in ros2["qos"] if q["case"]=="incompatible")
assert incompatible["received"]==0 and incompatible["incompatible_events"]
a2a=json.loads((ROOT/"结果/A2A/summary.json").read_text())
assert all(a2a["checks"].values())
transcript=json.loads((ROOT/"结果/A2A/rpc-transcript.json").read_text())
task=next(t for t in transcript if t["method"]=="SendMessage")["response"]["result"]["task"]
assert task["artifacts"][0]["parts"][0]["data"]["samples"]==20
files=[]
for folder in (ROOT/"实验",ROOT/"环境"):
    for path in sorted(folder.glob("*")):
        if path.is_file() and path.suffix in (".py",".json",".yaml",".txt",".ps1"):
            files.append({"path":path.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
result={"status":"passed","checks":["360 unique trials","byte budgets","fixed update count",
    "finite metrics","full-budget equivalence","config hash","serialized byte self-consistency",
    "separate labels/test sizes","ROS1 five scenarios","ROS1/ROS2 sequence agreement",
    "DDS incompatible reliability","A2A actual task/artifact"],"files":files,
    "scope":"Offline cross-result audit; not hardware or independent replication"}
(ROOT/"结果/audit.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
print(json.dumps({"status":result["status"],"checks":len(result["checks"])}))
