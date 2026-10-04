"""Validate explicitly hypothetical device inventories, not the host or a physical Jetson."""
import ipaddress
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def validate(profile):
    issues=[]
    if profile['arch']!='aarch64':issues.append('not Jetson ARM64')
    expected='20.04' if profile['jetpack'].startswith('5.') else '22.04' if profile['jetpack'].startswith('6.') else None
    if expected is None or profile['ubuntu']!=expected:issues.append('JetPack/Ubuntu profile inconsistent')
    if profile['native_ros']=='noetic' and profile['ubuntu']!='20.04':issues.append('Noetic native Ubuntu profile mismatch')
    network=ipaddress.ip_network('192.168.123.0/24');addresses=[ipaddress.ip_address(profile[k]) for k in ('host_ip','robot_ip','dock_ip')]
    if len(set(addresses))!=3 or any(address not in network or address in (network.network_address,network.broadcast_address) for address in addresses):issues.append('IP subnet or address collision')
    if profile['native_ros']=='noetic' and profile['unitree_protocol']=='DDS':
        bridge='requires a protocol adapter; ROS1/TCPROS cannot directly subscribe Unitree DDS'
    else:bridge='ROS2 needs device-compatible DDS types/RMW; actual version not verified'
    return {'consistent':not issues,'issues':issues,'integration_boundary':bridge}

def main():
    assumed={'name':'hypothesis: Go2 EDU NX dock','arch':'aarch64','memory_gib_assumed':16,
        'jetpack':'5.1.1','ubuntu':'20.04','native_ros':'noetic','unitree_protocol':'DDS',
        'host_ip':'192.168.123.222','robot_ip':'192.168.123.161','dock_ip':'192.168.123.18',
        'status':'mock inventory, NOT physical device output'}
    alternate={**assumed,'name':'alternative generic Orin NX setup','jetpack':'6.2','ubuntu':'22.04','native_ros':'humble','memory_gib_assumed':8}
    inconsistent={**assumed,'name':'negative test: incompatible host and duplicate IP','arch':'x86_64','ubuntu':'22.04','host_ip':'192.168.123.18'}
    results=[{'profile':p,'validation':validate(p)} for p in (assumed,alternate,inconsistent)]
    assert results[0]['validation']['consistent'] and results[1]['validation']['consistent']
    assert not results[2]['validation']['consistent'] and len(results[2]['validation']['issues'])==4
    (ROOT/'结果/设备假设核验.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps({'mock_profiles':len(results),'positive':2,'negative_rejected':1,'actual_hardware_checked':False}))

if __name__=='__main__':main()
