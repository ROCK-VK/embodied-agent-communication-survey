"""Train only from records actually accepted over the network, with offline label lookup."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score,f1_score
from threadpoolctl import threadpool_limits
from image_selection import learner,train
ROOT=Path(__file__).resolve().parents[1]

def main():
    truth_file=ROOT/'结果/图像实验/network-truth.npz'
    truth=np.load(truth_file)
    initial=learner(11)
    initial.partial_fit(truth['warm_x'],truth['warm_y'],classes=np.arange(10))
    initial.partial_fit(truth['warm_x'],truth['warm_y'])
    rows=[]
    with threadpool_limits(limits=1):
        for case in json.loads((ROOT/'结果/网络实验/summary.json').read_text(encoding='utf-8')):
            received=ROOT/'结果/网络实验'/case['case']/'received.jsonl'
            records=[json.loads(line) for line in received.read_text(encoding='utf-8').splitlines() if line.strip()]
            ids=np.array([r['seq'] for r in records],dtype=int)
            x=np.array([r['vision'] for r in records],dtype=float).reshape(-1,64)/16
            labels=truth['labels'][ids]
            model,wall,processed=train(initial,x,labels,np.arange(len(records)),2400,11)
            pred=model.predict(truth['test_x'])
            rows.append({'case':case['case'],'actual_accepted':len(records),'learning_work':processed,
                'macro_f1':f1_score(truth['test_y'],pred,average='macro'),'accuracy':accuracy_score(truth['test_y'],pred),
                'baseline_f1':f1_score(truth['test_y'],initial.predict(truth['test_x']),average='macro'),
                'training_ms':wall,'annotation_bytes_charged':5*len(records),'received_sha256':hashlib.sha256(received.read_bytes()).hexdigest(),
                'truth_source_sha256':hashlib.sha256(truth_file.read_bytes()).hexdigest(),
                'scope':'offline receiver training, labels looked up after network acceptance; no online label service, no robot model'})
    pd.DataFrame(rows).to_csv(ROOT/'结果/网络实验/receiver-training.csv',index=False)
    print(pd.DataFrame(rows)[['case','actual_accepted','macro_f1']].to_string(index=False))

if __name__=='__main__':main()
