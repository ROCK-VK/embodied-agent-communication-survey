"""Real loopback A2A 1.0 JSON-RPC + SSE task demo using official SDK 1.2.1."""
import asyncio
import json
import socket
import time
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

import httpx
import uvicorn
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Value
from starlette.applications import Starlette
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCard, AgentCapabilities, AgentInterface, AgentSkill, Part, Task, TaskState, TaskStatus

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "结果" / "A2A"

class SummaryExecutor(AgentExecutor):
    async def execute(self, context, event_queue):
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await event_queue.enqueue_event(Task(id=context.task_id, context_id=context.context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED)))
        await updater.start_work()
        request = json.loads(context.get_user_input())
        records = request["records"]
        if not isinstance(records, list) or not 1 <= len(records) <= 1000:
            raise ValueError("records must have 1..1000 entries")
        delay_ms = int(request.get("delay_ms", 150))
        if not 0 <= delay_ms <= 3000:
            raise ValueError("delay_ms outside 0..3000")
        await asyncio.sleep(delay_ms / 1000)
        summary = {"samples":len(records),"prediction_counts":dict(Counter(str(r["prediction"]) for r in records)),
                   "mean_confidence":sum(float(r["confidence"]) for r in records)/len(records),
                   "recommendation":"Compare random sampling against novelty; do not infer training value from confidence alone",
                   "basis":"Observed sender predictions; not ground-truth class counts"}
        await updater.add_artifact([Part(data=ParseDict(summary, Value()), media_type="application/json")],
                                   name="perception-summary", last_chunk=True)
        await updater.complete()

    async def cancel(self, context, event_queue):
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()

def build_app(base_url):
    card = AgentCard(name="Perception Summary Agent", description="Local rule-based data summary",
        version="0.1.0", supported_interfaces=[AgentInterface(url=base_url+"/rpc",
        protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=True), default_input_modes=["text/plain"],
        default_output_modes=["application/json"], skills=[AgentSkill(id="summary",name="Data summary",
        description="Summarize predictions and confidence, no robot actuation",tags=["perception","analysis"])])
    handler = DefaultRequestHandler(SummaryExecutor(), InMemoryTaskStore(), card)
    @asynccontextmanager
    async def lifespan(app):
        yield
        await handler.aclose()
    app=Starlette(routes=create_agent_card_routes(card)+create_jsonrpc_routes(handler,"/rpc"),lifespan=lifespan)
    return app

def request_params(records, delay_ms=150, immediate=False):
    return {"message":{"messageId":str(uuid.uuid4()),"role":"ROLE_USER",
            "parts":[{"text":json.dumps({"records":records,"delay_ms":delay_ms},separators=(",", ":")),
                      "mediaType":"text/plain"}]},"configuration":{"returnImmediately":immediate}}

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    records=[json.loads(line) for line in (ROOT/"结果/数据实验/redundant-stream.jsonl").read_text(encoding="utf-8").splitlines()[:20]]
    sock=socket.socket()
    sock.bind(("127.0.0.1",0))
    port=sock.getsockname()[1]
    base=f"http://127.0.0.1:{port}"
    server=uvicorn.Server(uvicorn.Config(build_app(base),log_level="warning",lifespan="on"))
    serving=asyncio.create_task(server.serve(sockets=[sock]))
    transcript=[]
    try:
        deadline=time.monotonic()+10
        while not server.started:
            if serving.done():
                await serving
            if time.monotonic()>deadline:
                raise TimeoutError("server startup")
            await asyncio.sleep(.02)
        async with httpx.AsyncClient(base_url=base,trust_env=False,timeout=15,
            headers={"A2A-Version":"1.0"}) as client:
            card=await client.get("/.well-known/agent-card.json")
            card.raise_for_status()
            assert card.json()["capabilities"]["streaming"]
            (OUT/"agent-card.json").write_text(json.dumps(card.json(),indent=2),encoding="utf-8")
            async def rpc(method, params):
                payload={"jsonrpc":"2.0","id":str(uuid.uuid4()),"method":method,"params":params}
                start=time.perf_counter()
                response=await client.post("/rpc",json=payload)
                response.raise_for_status()
                data=response.json()
                transcript.append({"method":method,"request":payload,"response":data,
                    "elapsed_ms":(time.perf_counter()-start)*1000,
                    "http_body_bytes":len(response.content)})
                return data
            result=await rpc("SendMessage",request_params(records))
            assert "error" not in result,result
            task=result["result"]["task"]
            assert task["status"]["state"]=="TASK_STATE_COMPLETED",task
            assert task["artifacts"][0]["parts"][0]["data"]["samples"]==20
            retrieved=await rpc("GetTask",{"id":task["id"]})
            assert retrieved["result"]["status"]["state"]=="TASK_STATE_COMPLETED"
            stream_payload={"jsonrpc":"2.0","id":"stream-check","method":"SendStreamingMessage",
                            "params":request_params(records)}
            events=[]
            async with client.stream("POST","/rpc",json=stream_payload) as response:
                response.raise_for_status()
                assert "text/event-stream" in response.headers["content-type"]
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        events.append(json.loads(line[5:].strip()))
            states=[e["result"]["statusUpdate"]["status"]["state"] for e in events
                    if "statusUpdate" in e.get("result",{})]
            assert "TASK_STATE_WORKING" in states and "TASK_STATE_COMPLETED" in states,events
            assert any("artifactUpdate" in e.get("result",{}) for e in events)
            (OUT/"stream-events.json").write_text(json.dumps(events,indent=2),encoding="utf-8")
            pending=await rpc("SendMessage",request_params(records,delay_ms=2500,immediate=True))
            pending_id=pending["result"]["task"]["id"]
            await asyncio.sleep(.1)
            canceled=await rpc("CancelTask",{"id":pending_id})
            assert canceled["result"]["status"]["state"]=="TASK_STATE_CANCELED",canceled
            bad=await rpc("UnknownMethod",{})
            assert "error" in bad,bad
            missing=await rpc("GetTask",{"id":"nonexistent-task"})
            assert "error" in missing,missing
            # Server body size only, not all IP/TCP/HTTP overhead.
            summary={"sdk":version("a2a-sdk"),"protocol":"1.0","transport":"JSON-RPC over real HTTP/TCP loopback; SSE",
                "bind":"127.0.0.1 ephemeral port","samples":20,"rpc_checks":len(transcript),
                "checks":{"discovery":True,"send_message":True,"get_task":True,"stream_working_completed":True,
                          "artifact":True,"cancel":True,"unknown_method_error":True,"missing_task_error":True},
                "stream_statuses":states,"send_message_latency_ms":transcript[0]["elapsed_ms"],
                "latency_scope":"Single local run with intentional 150ms task delay; not a protocol benchmark",
                "full_wire_bytes_measured":False,"llm_required":False,"server_shutdown_after_test":True}
            (OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
            (OUT/"rpc-transcript.json").write_text(json.dumps(transcript,indent=2),encoding="utf-8")
            print(json.dumps(summary,indent=2))
    finally:
        server.should_exit=True
        await asyncio.wait_for(serving,10)
        sock.close()

if __name__=="__main__":
    asyncio.run(main())
