"""Two real A2A services: delegation, actual experiment evidence, SQLite task persistence."""
import argparse
import asyncio
import csv
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from importlib.metadata import version
from pathlib import Path
import httpx
import uvicorn
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Value
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.applications import Starlette
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes,create_jsonrpc_routes
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCard,AgentCapabilities,AgentInterface,AgentSkill,Part,Task,TaskStatus,TaskState

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT.parent/'日志/下一阶段/a2a'
OUT=ROOT/'结果/A2A整合'
CASES={'tcp-normal','tcp-netem','tcp-reconnect','udp-normal','udp-netem','ros1-normal','ros1-netem'}

def params(request,immediate=False):
    return {'message':{'messageId':str(uuid.uuid4()),'role':'ROLE_USER','parts':[{'text':json.dumps(request),'mediaType':'text/plain'}]},
        'configuration':{'returnImmediately':immediate}}

async def rpc(client,method,parameters):
    result=await client.post('/rpc',json={'jsonrpc':'2.0','id':str(uuid.uuid4()),'method':method,'params':parameters})
    result.raise_for_status();return result.json()

class Analysis(AgentExecutor):
    def __init__(self,directory):
        self.cancelled=set();self.lock=asyncio.Lock();self.db=directory/'business-cache.sqlite'
        with sqlite3.connect(self.db) as db:db.execute('CREATE TABLE IF NOT EXISTS results (key TEXT PRIMARY KEY, result TEXT NOT NULL)')
    async def execute(self,context,queue):
        updater=TaskUpdater(queue,context.task_id,context.context_id)
        await queue.enqueue_event(Task(id=context.task_id,context_id=context.context_id,status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED)))
        await updater.start_work()
        try:
            request=json.loads(context.get_user_input())
            if set(request)-{'case','delay_ms'} or request.get('case') not in CASES:raise ValueError('unknown case or request field')
            delay=int(request.get('delay_ms',100))
            if not 0<=delay<=3000:raise ValueError('delay outside 0..3000')
        except (ValueError,TypeError,json.JSONDecodeError):
            await updater.add_artifact([Part(data=ParseDict({'error':'invalid analysis request'},Value()),media_type='application/json')],name='validation-error')
            await updater.failed();return
        await asyncio.sleep(delay/1000)
        if context.task_id in self.cancelled:return
        case=request['case'];summary_file=ROOT/'结果/网络实验'/case/'receiver.json';training_file=ROOT/'结果/网络实验/receiver-training.csv'
        digest=hashlib.sha256(summary_file.read_bytes()+training_file.read_bytes()).hexdigest()
        cache_key=hashlib.sha256((case+digest+'analysis-v1').encode()).hexdigest()
        async with self.lock:
            if context.task_id in self.cancelled:return
            with sqlite3.connect(self.db) as db:
                previous=db.execute('SELECT result FROM results WHERE key=?',(cache_key,)).fetchone()
                if previous:result=json.loads(previous[0]);cached=True
                else:
                    summary=json.loads(summary_file.read_text(encoding='utf-8'))
                    with training_file.open(encoding='utf-8') as stream:training=next(r for r in csv.DictReader(stream) if r['case']==case)
                    result={'case':case,'accepted_frames':summary['accepted'],'expired_frames':summary['expired'],
                        'macro_f1':float(training['macro_f1']),'baseline_f1':float(training['baseline_f1']),
                        'captured_ethernet_bytes':summary['captured_ethernet_bytes'],'evidence_sha256':digest,
                        'received_sha256':training['received_sha256'],
                        'recommendation':'Keep random/interval baselines; do not use confidence alone as a training-value guarantee',
                        'scope':'actual local simulation results; no robot actuation; no autonomous model retraining'}
                    db.execute('INSERT INTO results VALUES (?,?)',(cache_key,json.dumps(result)));cached=False
        result={**result,'cache_hit':cached,'business_key':cache_key}
        await updater.add_artifact([Part(data=ParseDict(result,Value()),media_type='application/json')],name='experiment-analysis',last_chunk=True)
        await updater.complete()
    async def cancel(self,context,queue):
        self.cancelled.add(context.task_id)
        await TaskUpdater(queue,context.task_id,context.context_id).cancel()

class Coordinator(AgentExecutor):
    def __init__(self,upstream):self.upstream=upstream
    async def execute(self,context,queue):
        updater=TaskUpdater(queue,context.task_id,context.context_id)
        await queue.enqueue_event(Task(id=context.task_id,context_id=context.context_id,status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED)))
        await updater.start_work()
        async with httpx.AsyncClient(base_url=self.upstream,trust_env=False,timeout=15,headers={'A2A-Version':'1.0'}) as client:
            response=await rpc(client,'SendMessage',params(json.loads(context.get_user_input())))
        child=response['result']['task']
        if child['status']['state']!='TASK_STATE_COMPLETED':await updater.failed();return
        data=child['artifacts'][0]['parts'][0]['data']
        await updater.add_artifact([Part(data=ParseDict({'delegated_task_id':child['id'],'analysis':data},Value()),media_type='application/json')],name='delegated-analysis',last_chunk=True)
        await updater.complete()
    async def cancel(self,context,queue):
        await TaskUpdater(queue,context.task_id,context.context_id).cancel()

def app(role,port,directory,upstream):
    directory.mkdir(parents=True,exist_ok=True)
    card=AgentCard(name='Experiment '+role,description='Local simulation '+role,version='1.0',
        supported_interfaces=[AgentInterface(url=f'http://127.0.0.1:{port}/rpc',protocol_binding='JSONRPC',protocol_version='1.0')],
        capabilities=AgentCapabilities(streaming=True),default_input_modes=['text/plain'],default_output_modes=['application/json'],
        skills=[AgentSkill(id=role,name=role,description='Analyze actual recorded simulation evidence',tags=['simulation','perception'])])
    engine=create_async_engine('sqlite+aiosqlite:///'+(directory/(role+'-tasks.sqlite')).as_posix())
    store=DatabaseTaskStore(engine)
    executor=Analysis(directory) if role=='analysis' else Coordinator(upstream)
    handler=DefaultRequestHandler(executor,store,card)
    @asynccontextmanager
    async def lifespan(application):
        await store.initialize()
        yield
        await handler.aclose();await engine.dispose()
    return Starlette(routes=create_agent_card_routes(card)+create_jsonrpc_routes(handler,'/rpc'),lifespan=lifespan)

def port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    directory=PRIVATE/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');directory.mkdir(parents=True,exist_ok=True)
    ports={'analysis':port(),'coordinator':port()};processes={};logs={};transcript=[];checks={}
    async def start(role):
        logs[role]=(directory/(role+'.log')).open('a',encoding='utf-8')
        env=dict(os.environ,PYTHONIOENCODING='utf-8')
        processes[role]=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve','--role',role,'--port',str(ports[role]),
            '--directory',str(directory),'--upstream',f"http://127.0.0.1:{ports['analysis']}"],stdout=logs[role],stderr=subprocess.STDOUT,env=env)
        async with httpx.AsyncClient(trust_env=False,timeout=1) as client:
            for attempt in range(100):
                if processes[role].poll() is not None:raise RuntimeError('server exited: '+role)
                try:
                    response=await client.get(f'http://127.0.0.1:{ports[role]}/.well-known/agent-card.json')
                    if response.status_code==200:return response.json()
                except httpx.HTTPError:pass
                await asyncio.sleep(.05)
        raise TimeoutError('server startup: '+role)
    def stop(role):
        p=processes.get(role)
        if p and p.poll() is None:p.terminate();p.wait(10)
        if role in logs:logs[role].close()
    async def call(role,method,p):
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{ports[role]}',trust_env=False,timeout=15,headers={'A2A-Version':'1.0'}) as client:
            result=await rpc(client,method,p)
        transcript.append({'role':role,'method':method,'request':p,'response':result});return result
    try:
        cards={role:await start(role) for role in ('analysis','coordinator')};checks['two_agent_discovery']=all(c['capabilities']['streaming'] for c in cards.values())
        first=(await call('coordinator','SendMessage',params({'case':'tcp-normal'})))['result']['task']
        assert first['status']['state']=='TASK_STATE_COMPLETED'
        evidence=first['artifacts'][0]['parts'][0]['data'];assert evidence['analysis']['accepted_frames']==120 and not evidence['analysis']['cache_hit']
        checks['real_evidence_delegation']=True
        duplicate=(await call('coordinator','SendMessage',params({'case':'tcp-normal'})))['result']['task']
        assert duplicate['artifacts'][0]['parts'][0]['data']['analysis']['cache_hit'];checks['duplicate_business_result_reused']=True
        # Disconnect an actual SSE consumer after working, then poll the persisted task.
        events=[];task_id=None
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{ports['analysis']}",trust_env=False,timeout=15,headers={'A2A-Version':'1.0'}) as client:
            async with client.stream('POST','/rpc',json={'jsonrpc':'2.0','id':'disconnect-test','method':'SendStreamingMessage','params':params({'case':'udp-normal','delay_ms':500})}) as response:
                assert 'text/event-stream' in response.headers['content-type']
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):continue
                    event=json.loads(line[5:]);events.append(event)
                    result=event.get('result',{})
                    if 'task' in result:task_id=result['task']['id']
                    if 'statusUpdate' in result:
                        task_id=result['statusUpdate']['taskId']
                        if result['statusUpdate']['status']['state']=='TASK_STATE_WORKING':break
        assert task_id
        for attempt in range(80):
            recovered=await call('analysis','GetTask',{'id':task_id})
            if recovered.get('result',{}).get('status',{}).get('state')=='TASK_STATE_COMPLETED':break
            await asyncio.sleep(.05)
        else:raise AssertionError('disconnected task did not finish')
        checks['sse_disconnect_gettask_recovery']=True
        canceled=(await call('analysis','SendMessage',params({'case':'tcp-netem','delay_ms':2500},True)))['result']['task']
        cancellation=await call('analysis','CancelTask',{'id':canceled['id']})
        assert cancellation['result']['status']['state']=='TASK_STATE_CANCELED';checks['cancel']=True
        invalid=(await call('analysis','SendMessage',params({'case':'../../outside'})))['result']['task']
        assert invalid['status']['state']=='TASK_STATE_FAILED';checks['invalid_case_failed']=True
        stop('analysis');await start('analysis')
        # Same official DatabaseTaskStore is reopened in a fresh process.
        restored=await call('analysis','GetTask',{'id':evidence['delegated_task_id']})
        assert restored['result']['status']['state']=='TASK_STATE_COMPLETED'
        assert restored['result']['artifacts'][0]['parts'][0]['data']['evidence_sha256']==evidence['analysis']['evidence_sha256']
        checks['analysis_process_restart_completed_task']=True
        stop('coordinator');await start('coordinator')
        restored=await call('coordinator','GetTask',{'id':first['id']})
        assert restored['result']['status']['state']=='TASK_STATE_COMPLETED';checks['coordinator_process_restart_completed_task']=True
        again=(await call('coordinator','SendMessage',params({'case':'tcp-normal'})))['result']['task']
        assert again['artifacts'][0]['parts'][0]['data']['analysis']['cache_hit'];checks['cache_survives_restart']=True
        unknown=await call('analysis','UnknownMethod',{});assert 'error' in unknown;checks['unknown_method_error']=True
        with sqlite3.connect(directory/'business-cache.sqlite') as db:business_count=db.execute('SELECT COUNT(*) FROM results').fetchone()[0]
        assert business_count==2;checks['only_two_unique_business_computations']=True
        summary={'checks':checks,'sdk':version('a2a-sdk'),'protocol':'1.0','services':'two separate real Windows server processes, HTTP/TCP loopback, JSON-RPC and SSE',
            'task_store':'official DatabaseTaskStore, SQLAlchemy + aiosqlite','business_computations':business_count,
            'evidence_case':'tcp-normal','artifact':evidence,'task_restore_scope':'completed tasks restored after actual process termination/restart; in-flight worker restart not implemented',
            'disconnect_scope':'SSE client disconnect while working; server continued and GetTask returned completed',
            'idempotency_scope':'application-level content-addressed result reuse for sequential duplicate requests, not a universal A2A exactly-once guarantee',
            'private_database_directory':str(directory.relative_to(ROOT.parent)),'llm_required':False,'tls_auth_verified':False,'servers_stopped_after_test':True}
        (OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        (OUT/'agent-cards.json').write_text(json.dumps(cards,indent=2),encoding='utf-8')
        (OUT/'transcript.json').write_text(json.dumps(transcript,indent=2),encoding='utf-8')
        (OUT/'disconnect-events.json').write_text(json.dumps(events,indent=2),encoding='utf-8')
        print(json.dumps(summary,indent=2))
    finally:
        for role in ('coordinator','analysis'):stop(role)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',nargs='?',default='test');parser.add_argument('--role',choices=['analysis','coordinator']);parser.add_argument('--port',type=int);parser.add_argument('--directory',type=Path);parser.add_argument('--upstream');args=parser.parse_args()
    if args.command=='serve':uvicorn.run(app(args.role,args.port,args.directory,args.upstream),host='127.0.0.1',port=args.port,log_level='warning')
    else:asyncio.run(main())
