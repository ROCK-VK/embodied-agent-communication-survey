"""ROS2 Humble same JSON contract, byte selection, and real QoS compatibility."""
import json
import time
from pathlib import Path

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy
from rclpy.qos_event import SubscriptionEventCallbacks
from rclpy.serialization import serialize_message
from rclpy.utilities import get_rmw_implementation_identifier
from std_msgs.msg import String

OUT=Path("/workspaces/ros2/results")

def qos(reliable):
    return QoSProfile(depth=200,reliability=ReliabilityPolicy.RELIABLE if reliable else ReliabilityPolicy.BEST_EFFORT,
                      durability=DurabilityPolicy.VOLATILE)

def spin_until(executor,condition,seconds):
    deadline=time.monotonic()+seconds
    while not condition() and time.monotonic()<deadline:executor.spin_once(timeout_sec=.02)

def pipeline():
    source=Node("comparison_source");selector=Node("comparison_selector");receiver=Node("comparison_receiver")
    executor=SingleThreadedExecutor()
    for node in (source,selector,receiver):executor.add_node(node)
    records=[json.loads(line) for line in Path("/project/结果/数据实验/redundant-stream.jsonl").read_text().splitlines()[:90]]
    received=[];block=[];windows=[];cdr_bytes=[]
    outgoing=selector.create_publisher(String,"/comparison/selected",qos(True))
    receiver.create_subscription(String,"/comparison/selected",lambda msg:received.append(json.loads(msg.data)),qos(True))
    def choose(msg):
        block.append(json.loads(msg.data))
        if len(block)<15:return
        # Same application serialization accounting as ROS1 comparison; CDR counted separately.
        encoded=lambda r:json.dumps(r,separators=(",",":"))
        budget=int(sum(len(encoded(r).encode())+4 for r in block)*.5)
        chosen=[];used=0
        for record in sorted(block,key=lambda r:r["confidence"]):
            cost=len(encoded(record).encode())+4
            if used+cost<=budget:chosen.append(record);used+=cost
        for record in sorted(chosen,key=lambda r:r["seq"]):
            message=String(data=encoded(record));cdr_bytes.append(len(serialize_message(message)));outgoing.publish(message)
        windows.append(dict(budget=budget,selected_bytes=used,count=len(chosen)))
        block.clear()
    selector.create_subscription(String,"/comparison/perception",choose,qos(True))
    incoming=source.create_publisher(String,"/comparison/perception",qos(True))
    spin_until(executor,lambda:incoming.get_subscription_count()==1 and outgoing.get_subscription_count()==1,6)
    assert incoming.get_subscription_count()==1 and outgoing.get_subscription_count()==1
    for record in records:
        incoming.publish(String(data=json.dumps(record,separators=(",",":"))))
        executor.spin_once(timeout_sec=.02)
        time.sleep(1/60)
    target=sum(w["count"] for w in windows)
    spin_until(executor,lambda:len(windows)==6 and len(received)==sum(w["count"] for w in windows),5)
    assert len(windows)==6 and len(received)==sum(w["count"] for w in windows)>0
    assert all(w["selected_bytes"]<=w["budget"] for w in windows)
    result=dict(candidate_count=90,selected_count=sum(w["count"] for w in windows),received_count=len(received),
        windows=windows,budget_violations=0,selected_cdr_bytes=sum(cdr_bytes),
        accounting="Budget = 4+UTF8 JSON bytes as ROS1; ROS2 actual CDR bytes separately measured, not full network bytes",
        seqs=[r["seq"] for r in received],clock="Original synthetic timestamps, not used for ROS2 latency/TTL")
    for node in (source,selector,receiver):executor.remove_node(node);node.destroy_node()
    executor.shutdown()
    return result

def reliability_case(name,pub_reliable,sub_reliable):
    source=Node("qos_source_"+name);receiver=Node("qos_receiver_"+name)
    executor=SingleThreadedExecutor();executor.add_node(source);executor.add_node(receiver)
    received=[];incompatible=[]
    receiver.create_subscription(String,"/qos/"+name,lambda msg:received.append(msg.data),qos(sub_reliable),
        event_callbacks=SubscriptionEventCallbacks(incompatible_qos=lambda event:incompatible.append(event.total_count)))
    pub=source.create_publisher(String,"/qos/"+name,qos(pub_reliable))
    start=time.monotonic()
    while time.monotonic()-start<2.5:
        pub.publish(String(data="qos-check"));executor.spin_once(timeout_sec=.05)
        time.sleep(.03)
    result=dict(case=name,publisher="reliable" if pub_reliable else "best_effort",
        subscriber="reliable" if sub_reliable else "best_effort",received=len(received),
        incompatible_events=incompatible)
    if not pub_reliable and sub_reliable:assert not received and incompatible
    else:assert received
    for node in (source,receiver):executor.remove_node(node);node.destroy_node()
    executor.shutdown()
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rclpy.init()
    try:
        result={"ros":"humble","middleware":get_rmw_implementation_identifier(),
            "scope":"Real DDS within one container; application contract comparison, no throughput ranking",
            "pipeline":pipeline(),"qos":[reliability_case("reliable_pair",True,True),
                reliability_case("best_effort_pair",False,False),reliability_case("incompatible",False,True)]}
        (OUT/"summary.json").write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:rclpy.shutdown()

if __name__=="__main__":main()
