"""Start a private ROS master and verify one local TCPROS message."""
import json
import os
import signal
import subprocess
import threading
import time
import xmlrpc.client

os.environ["ROS_MASTER_URI"] = "http://127.0.0.1:11311"
os.environ["ROS_HOSTNAME"] = "localhost"
master = subprocess.Popen(["roscore"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.STDOUT, start_new_session=True)
try:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if xmlrpc.client.ServerProxy(os.environ["ROS_MASTER_URI"]).getUri("env_check")[0] == 1:
                break
        except (OSError, xmlrpc.client.Error):
            time.sleep(0.2)
    else:
        raise RuntimeError("ROS master did not start")
    import rospy
    from std_msgs.msg import String
    rospy.init_node("environment_check", anonymous=True, disable_signals=True)
    received = []
    event = threading.Event()
    def callback(message):
        received.append(message.data)
        event.set()
    subscriber = rospy.Subscriber("/env_check/message", String, callback, queue_size=1)
    publisher = rospy.Publisher("/env_check/message", String, queue_size=1)
    deadline = time.monotonic() + 10
    while publisher.get_num_connections() == 0 and time.monotonic() < deadline:
        time.sleep(0.1)
    if publisher.get_num_connections() == 0:
        raise RuntimeError("Subscriber connection failed")
    publisher.publish(String(data="embodied-sim-environment-ready"))
    if not event.wait(5):
        raise RuntimeError("No message received")
    assert received[0] == "embodied-sim-environment-ready"
    print(json.dumps({"scope": "single-container ROS1 TCPROS smoke",
                      "received": received, "ros": "noetic"}))
    subscriber.unregister()
    publisher.unregister()
    rospy.signal_shutdown("check complete")
finally:
    os.killpg(master.pid, signal.SIGTERM)
    try:
        master.wait(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(master.pid, signal.SIGKILL)
        master.wait()
