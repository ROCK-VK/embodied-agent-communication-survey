"""Train offline from actual ROS receiver files, keeping long work out of callbacks."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score,f1_score,log_loss
from threadpoolctl import threadpool_limits

ROOT=Path(__file__).resolve().parents[1]
truth=np.load(ROOT/"结果/数据实验/redundant-truth-test.npz")
rows=[]
with threadpool_limits(limits=1):
    for folder in sorted((ROOT/"结果/ROS1").iterdir()):
        if not folder.is_dir():continue
        records=[json.loads(line) for line in (folder/"received.jsonl").read_text(encoding="utf-8").splitlines()]
        if not records:
            rows.append(dict(case=folder.name,received=0,updates=0,status="no fresh data; training skipped"))
            continue
        x=np.array([r["features"] for r in records]);y=truth["labels"][[r["seq"] for r in records]]
        rng=np.random.default_rng(11)
        model=SGDClassifier(loss="log_loss",alpha=.001,learning_rate="constant",eta0=.03,random_state=11)
        for _ in range(30):
            batch=rng.integers(0,len(x),32);model.partial_fit(x[batch],y[batch],classes=np.arange(3))
        prob=model.predict_proba(truth["test_features"]);pred=prob.argmax(axis=1)
        rows.append(dict(case=folder.name,received=len(x),updates=30,class_coverage=len(np.unique(y)),
            accuracy=accuracy_score(truth["test_labels"],pred),
            macro_f1=f1_score(truth["test_labels"],pred,average="macro",zero_division=0),
            training_log_loss=log_loss(y,model.predict_proba(x),labels=np.arange(3)),
            test_log_loss=log_loss(truth["test_labels"],prob,labels=np.arange(3)),status="offline training passed"))
frame=pd.DataFrame(rows)
frame.to_csv(ROOT/"结果/ROS1/receiver-training.csv",index=False)
print(frame.to_string(index=False))
