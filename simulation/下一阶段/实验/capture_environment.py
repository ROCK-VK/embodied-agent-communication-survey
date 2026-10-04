"""Record actual software/image/build-source identity and stopped deployment state."""
import hashlib
import json
import platform
import subprocess
from importlib.metadata import version
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT.parent

def main():
    data_python=PROJECT/'.venv-data/Scripts/python.exe'
    data=json.loads(subprocess.check_output([str(data_python),'-c',
        "import json,platform; from importlib.metadata import version; print(json.dumps({'python':platform.python_version(),'packages':{n:version(n) for n in ['numpy','pandas','scikit-learn','matplotlib']}}))"],text=True,encoding='utf-8'))
    images=json.loads(subprocess.check_output(['docker','image','inspect','embodied-sim-ros1:noetic-local','embodied-phase2-network:noetic-local'],text=True,encoding='utf-8'))
    containers=json.loads(subprocess.check_output(['docker','inspect','embodied-phase2-master','embodied-phase2-sender','embodied-phase2-receiver'],text=True,encoding='utf-8'))
    result={'windows_data':data,'a2a_python':platform.python_version(),'a2a_packages':{n:version(n) for n in ('a2a-sdk','httpx','uvicorn','sqlalchemy','aiosqlite','greenlet')},
        'images':[{'tags':image['RepoTags'],'id':image['Id'],'size_bytes':image['Size']} for image in images],
        'network_dockerfile_sha256':hashlib.sha256((ROOT/'Dockerfile.network').read_bytes()).hexdigest(),
        'runtime':[{'name':c['Name'],'image':c['Image'],'state':c['State']['Status'],'mounts':c['Mounts'],'cap_add':c['HostConfig']['CapAdd']} for c in containers],
        'source_runtime_relation':'scripts read directly from read-only project mount; new Docker image adds only network tools; actual image IDs and build source saved',
        'physical_device_relation':'no firmware/JetPack/model deployment performed; physical device runtime unknown',
        'container_versions':(ROOT/'结果/网络实验/network-version.txt').read_text(encoding='utf-8')}
    (ROOT/'环境/environment-manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    public={k:v for k,v in result.items() if k!='runtime'}
    public['runtime']=[{k:v for k,v in item.items() if k!='mounts'} for item in result['runtime']]
    public['mount_scope']='project read-only; stage results and private logs are separate project-specific writable mounts'
    (ROOT/'环境/environment-public.json').write_text(json.dumps(public,indent=2),encoding='utf-8')
    assert all(not c['State']['Running'] for c in containers)
    assert len({c['Image'] for c in containers})==1 and containers[0]['Image']==images[1]['Id']
    print(json.dumps({'environment_recorded':True,'network_containers_stopped':True}))

if __name__=='__main__':main()
