"""Independent public-image splits, sender-only selection and fixed learning-work budgets."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ.setdefault(key,'1')
import copy
import ctypes
import hashlib
import json
import platform
import time
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.datasets import load_digits
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score
from threadpoolctl import threadpool_limits

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'结果/图像实验'
CFG={'seeds':[11,23,37,51,71],'scenarios':['redundant','sensor_shift','annotation_noise'],
     'ratios':[.1,.25,.5],'strategies':['interval','random','confidence','uncertainty','diverse_cost'],
     'learning_work':[800,2400],'stream_frames':1400,'window':100,'batch':40,
     'repeat_probability':.65,'annotation_noise':.2,'annotation_bytes':5,
     'candidate_weights':{'entropy_floor':.2,'novelty_floor':.2},
     'scope':'digits images are not robot-camera data; IMU and payload padding are synthetic'}

def encode(record):
    return json.dumps(record,separators=(',',':')).encode('utf-8')

def learner(seed):
    return SGDClassifier(loss='log_loss',alpha=.001,learning_rate='constant',eta0=.035,random_state=seed)

def prepare(seed,scenario):
    digits=load_digits()
    ids=np.arange(len(digits.target))
    train_ids,test_ids=train_test_split(ids,test_size=.25,random_state=seed,stratify=digits.target)
    pool_ids,warm_ids=train_test_split(train_ids,test_size=300,random_state=seed+1,stratify=digits.target[train_ids])
    assert not (set(warm_ids)&set(pool_ids) or set(warm_ids)&set(test_ids) or set(pool_ids)&set(test_ids))
    warm_x=digits.data[warm_ids]/16
    warm_y=digits.target[warm_ids]
    teacher=LogisticRegression(max_iter=350).fit(warm_x,warm_y)
    initial=learner(seed)
    initial.partial_fit(warm_x,warm_y,classes=np.arange(10))
    initial.partial_fit(warm_x,warm_y)
    rng=np.random.default_rng(seed+2)
    source=[]
    for i in range(CFG['stream_frames']):
        source.append(source[-1] if i and rng.random()<CFG['repeat_probability'] else int(rng.choice(pool_ids)))
    image=digits.images[source].copy()
    test_image=digits.images[test_ids].copy()
    if scenario=='sensor_shift':
        # Same image transform on stream/test; never fit using test pixels or labels.
        image=np.roll(image,1,axis=2)
        test_image=np.roll(test_image,1,axis=2)
    x=image.reshape(-1,64)/16
    truth=digits.target[source].copy()
    labels=truth.copy()
    if scenario=='annotation_noise':
        mask=rng.random(len(labels))<CFG['annotation_noise']
        labels[mask]=(labels[mask]+rng.integers(1,10,mask.sum()))%10
    start=time.perf_counter()
    probs=teacher.predict_proba(x)
    perception_ms=(time.perf_counter()-start)*1000
    records=[]
    for seq,(pixels,prob) in enumerate(zip(image.reshape(-1,64),probs)):
        record={'seq':seq,'source_id':source[seq],'sampled_at_s':round(seq/20,3),
                'vision':pixels.astype(int).tolist(),'prediction':int(prob.argmax()),
                'probabilities':np.round(prob,6).tolist(),'confidence':round(float(prob.max()),6),
                'imu_simulated':np.round(rng.normal(0,.05,6),4).tolist(),
                'aux_payload_simulated':'x'*int(rng.choice([0,32,128,512]))}
        assert not any(k in record for k in ('label','truth','annotation'))
        records.append(record)
    # Application transport frame: uint32 length + JSON. Separate simulated label lookup costs 5 B/frame.
    costs=np.array([4+len(encode(r))+CFG['annotation_bytes'] for r in records])
    return x,labels,test_image.reshape(-1,64)/16,digits.target[test_ids],records,costs,initial,perception_ms,{
        'warm_ids':warm_ids.tolist(),'pool_ids':pool_ids.tolist(),'test_ids':test_ids.tolist(),
        'stream_source_ids':source,'dataset_sha256':hashlib.sha256(digits.data.tobytes()+digits.target.tobytes()).hexdigest()}

def select(records,x,costs,ratio,strategy,seed):
    rng=np.random.default_rng(seed+1000)
    selected=[];windows=[]
    for lo in range(0,len(records),CFG['window']):
        hi=min(lo+CFG['window'],len(records));count=hi-lo
        budget=int(costs[lo:hi].sum()*ratio);spent=0
        prob=np.array([r['probabilities'] for r in records[lo:hi]])
        entropy=-(prob*np.log(np.maximum(prob,1e-12))).sum(axis=1)
        if strategy=='interval':order=list(range(0,count,max(1,round(1/ratio))))
        elif strategy=='random':order=rng.permutation(count).tolist()
        elif strategy=='confidence':order=np.argsort(-prob.max(axis=1),kind='stable').tolist()
        elif strategy=='uncertainty':order=np.argsort(-entropy,kind='stable').tolist()
        else:order=None
        if order is None:
            remaining=np.ones(count,dtype=bool)
            novelty=np.ones(count)
            # A specified surrogate heuristic; no ground truth, no tuning on test scores.
            while True:
                eligible=remaining&(costs[lo:hi]<=budget-spent)
                if not eligible.any():break
                scores=(.2+entropy)*(.2+novelty)/costs[lo:hi]
                index=int(np.where(eligible,scores,-np.inf).argmax())
                selected.append(lo+index);spent+=int(costs[lo+index]);remaining[index]=False
                distance=np.linalg.norm(x[lo:hi]-x[lo+index],axis=1)/8
                novelty=np.minimum(novelty,distance)
        else:
            for local in order:
                if spent+costs[lo+local]<=budget:
                    selected.append(lo+local);spent+=int(costs[lo+local])
        windows.append({'window':lo//CFG['window'],'budget':budget,'spent':spent})
        assert spent<=budget
    return np.array(sorted(selected),dtype=int),windows

def train(initial,x,y,selected,work,seed):
    model=copy.deepcopy(initial);rng=np.random.default_rng(seed+2000)
    start=time.perf_counter();processed=0
    while len(selected) and processed<work:
        size=min(CFG['batch'],work-processed)
        batch=rng.choice(selected,size,replace=True)
        model.partial_fit(x[batch],y[batch]);processed+=size
    assert processed==work or not len(selected)
    return model,(time.perf_counter()-start)*1000,processed

def peak_memory():
    if os.name!='nt':return None
    from ctypes import wintypes
    class Info(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ('peak','working','quota_peak_paged','quota_paged','quota_peak_nonpaged','quota_nonpaged','page','peak_page')]
    info=Info();info.cb=ctypes.sizeof(info)
    ctypes.windll.kernel32.GetCurrentProcess.restype=ctypes.c_void_p
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(Info),wintypes.DWORD]
    handle=ctypes.windll.kernel32.GetCurrentProcess()
    if not ctypes.windll.psapi.GetProcessMemoryInfo(handle,ctypes.byref(info),info.cb):
        raise ctypes.WinError()
    return info.peak/(1024**2)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    (ROOT/'实验/image-config.json').write_text(json.dumps(CFG,indent=2),encoding='utf-8')
    start=time.perf_counter();cpu=time.process_time();rows=[];split_manifest=[];window_rows=[]
    with threadpool_limits(limits=1):
        for scenario in CFG['scenarios']:
            for seed in CFG['seeds']:
                x,y,tx,ty,records,costs,initial,perception_ms,split=prepare(seed,scenario)
                split_manifest.append({'scenario':scenario,'seed':seed,**split})
                baseline=f1_score(ty,initial.predict(tx),average='macro')
                for ratio in CFG['ratios']+[1.]:
                    strategies=CFG['strategies'] if ratio<1 else ['all_reference']
                    for strategy in strategies:
                        select_start=time.perf_counter()
                        chosen,windows=(np.arange(len(records)),[]) if strategy=='all_reference' else select(records,x,costs,ratio,strategy,seed)
                        selection_ms=(time.perf_counter()-select_start)*1000
                        for window in windows:window_rows.append({'scenario':scenario,'seed':seed,'ratio':ratio,'strategy':strategy,**window})
                        for work in CFG['learning_work']:
                            model,train_ms,processed=train(initial,x,y,chosen,work,seed)
                            pred=model.predict(tx)
                            rows.append({'scenario':scenario,'seed':seed,'ratio':ratio,'strategy':strategy,'learning_work':work,
                              'selected':len(chosen),'candidate_bytes':int(costs.sum()),'selected_bytes':int(costs[chosen].sum()),
                              'annotation_bytes':int(len(chosen)*CFG['annotation_bytes']),
                              'selection_ms':selection_ms,'training_ms':train_ms,'perception_ms':perception_ms,
                              'processed':processed,'baseline_f1':baseline,'macro_f1':f1_score(ty,pred,average='macro'),
                              'accuracy':accuracy_score(ty,pred),'budget_violations':sum(w['spent']>w['budget'] for w in windows)})
                        if seed==11 and scenario=='redundant' and ratio==.25 and strategy=='diverse_cost':
                            (OUT/'selected-stream.jsonl').write_text('\n'.join(encode(records[int(i)]).decode() for i in chosen)+'\n',encoding='utf-8')
                            (OUT/'network-input.json').write_text(json.dumps({'selected_seqs':chosen.tolist(),'windows':windows,
                                'transport_bytes':int(sum(4+len(encode(records[int(i)])) for i in chosen)),
                                'budget_bytes_with_annotation':int(costs[chosen].sum()),'stream':records}),encoding='utf-8')
                            np.savez_compressed(OUT/'network-truth.npz',labels=y,test_x=tx,test_y=ty,warm_x=load_digits().data[np.array(split['warm_ids'])]/16,warm_y=load_digits().target[np.array(split['warm_ids'])])
                print(f'finished {scenario} seed {seed}',flush=True)
    wall=time.perf_counter()-start;used_cpu=time.process_time()-cpu
    df=pd.DataFrame(rows);assert len(df)==480
    df.to_csv(OUT/'runs.csv',index=False)
    summary=df.groupby(['scenario','ratio','strategy','learning_work']).agg(
        f1_mean=('macro_f1','mean'),f1_std=('macro_f1','std'),baseline_f1=('baseline_f1','mean'),
        bytes_mean=('selected_bytes','mean'),frames_mean=('selected','mean'),selection_ms=('selection_ms','mean'),training_ms=('training_ms','mean')).reset_index()
    summary.to_csv(OUT/'summary.csv',index=False)
    pd.DataFrame(window_rows).to_csv(OUT/'window-budgets.csv',index=False)
    (OUT/'split-manifest.json').write_text(json.dumps(split_manifest),encoding='utf-8')
    differences=[]
    for keys,part in df[df.ratio<1].groupby(['scenario','ratio','learning_work']):
        baseline=part[part.strategy=='random'].set_index('seed').macro_f1
        for strategy,group in part.groupby('strategy'):
            delta=group.set_index('seed').macro_f1-baseline
            mean=float(delta.mean());spread=float(delta.std(ddof=1));half=2.776*spread/np.sqrt(5)
            differences.append({'scenario':keys[0],'ratio':keys[1],'learning_work':keys[2],'strategy':strategy,
                'paired_f1_delta_mean':mean,'ci95_low':mean-half,'ci95_high':mean+half,'scope':'exploratory n=5, no multiple-comparison correction'})
    pd.DataFrame(differences).to_csv(OUT/'paired-differences.csv',index=False)
    metadata={'dataset':'sklearn bundled UCI digits: 1797 8x8 handwritten digit images, ten classes',
      'dataset_url':'https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_digits.html',
      'config':CFG,'config_sha256':hashlib.sha256((ROOT/'实验/image-config.json').read_bytes()).hexdigest(),
      'python':platform.python_version(),'trials':len(df),'wall_seconds':wall,'cpu_seconds':used_cpu,
      'average_cpu_percent_one_core':used_cpu/wall*100,'logical_cpu_count':os.cpu_count(),'peak_process_working_set_mib':peak_memory(),
      'cpu_scope':'whole experiment before CSV/plot output; user+kernel CPU time/wall; Windows timer quantization averaged over complete run',
      'learning_budget_scope':'exact additional training examples processed, including repeated minibatch draws; common 600-example warm start excluded',
      'resource_scope':'Windows x86 CPU, not Orin NX/GPU; selection and training costs separately measured',
      'annotation_scope':'offline lookup with 5-byte simulated annotation charge; no physical annotation network implemented',
      'test_scope':'source IDs split before repeats/transforms; test never used for selection, fitting or hyperparameter tuning'}
    (OUT/'metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    fig,axes=plt.subplots(1,3,figsize=(13,4))
    for ax,scenario in zip(axes,CFG['scenarios']):
        section=summary[(summary.scenario==scenario)&(summary.learning_work==2400)&(summary.ratio<1)]
        for strategy,group in section.groupby('strategy'):
            group=group.sort_values('ratio');ax.errorbar(group.ratio,group.f1_mean,yerr=group.f1_std,label=strategy,marker='o')
        ax.set_title(scenario);ax.set_xlabel('Maximum byte budget ratio');ax.set_ylabel('Macro F1 (mean +/- SD)')
    axes[-1].legend(fontsize=7);fig.tight_layout();fig.savefig(OUT/'comparison.png',dpi=160);fig.savefig(OUT/'comparison.svg');plt.close(fig)
    print(json.dumps(metadata,indent=2))

if __name__=='__main__':main()
