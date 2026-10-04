"""Exact bounded proxy objective; independent enumeration verifies DP, not learning optimality."""
import itertools
import json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]

def solve(costs,values,budget):
    states={0:(0,())}
    for i,(cost,value) in enumerate(zip(costs,values)):
        for spent,(score,path) in list(states.items()):
            new=spent+cost
            if new<=budget and score+value>states.get(new,(-1,()))[0]:
                states[new]=(score+value,path+(i,))
    spent,(score,path)=max(states.items(),key=lambda pair:(pair[1][0],-pair[0]))
    return spent,score,path

def main():
    records=json.loads((ROOT/'结果/图像实验/network-input.json').read_text(encoding='utf-8'))['stream'][:14]
    costs=[4+len(json.dumps(r,separators=(',',':')).encode())+5 for r in records]
    values=[]
    for r in records:
        p=np.array(r['probabilities']);entropy=-(p*np.log(np.maximum(p,1e-12))).sum()
        values.append(max(1,round(1000*(.2+entropy))))
    result=[]
    for ratio in (.1,.25,.5):
        budget=int(sum(costs)*ratio)
        spent,score,path=solve(costs,values,budget)
        exhaustive=max(sum(values[i] for i in range(len(costs)) if mask>>i&1)
            for mask in range(1<<len(costs)) if sum(costs[i] for i in range(len(costs)) if mask>>i&1)<=budget)
        assert score==exhaustive and spent<=budget and len(path)==len(set(path))
        greedy=[];gspent=0
        for i in sorted(range(len(costs)),key=lambda i:values[i]/costs[i],reverse=True):
            if gspent+costs[i]<=budget:greedy.append(i);gspent+=costs[i]
        gscore=sum(values[i] for i in greedy)
        assert gscore<=score
        result.append({'ratio':ratio,'budget':budget,'optimal_proxy_value':score,'optimal_spent':spent,
            'optimal_indices':list(path),'greedy_proxy_value':gscore,'greedy_gap':score-gscore,'exhaustive_verified':True})
    out={'objective':'sum integerized 0.2 + teacher entropy, no labels/test input',
       'scope':'exact optimum only for this additive 14-item proxy; not optimal training performance; diverse_cost has a different nonadditive proxy',
       'costs':costs,'values':values,'cases':result}
    (ROOT/'结果/代理目标精确解.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps(out,indent=2))

if __name__=='__main__':main()
