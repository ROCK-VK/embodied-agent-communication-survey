"""Read only publicly returned official documentation URLs; private local source snapshots."""
import hashlib
import json
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PRIVATE=ROOT/'日志/下一阶段'
PUBLIC=ROOT/'扩展调研与模拟/结果'
SELECT={'module_update','Quick_start','network service','DDS Application','Architecture Description','Obtain SDK','Creating_customer_applications'}

class Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
        if tag in ('p','div','br','h1','h2','h3','li','tr'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)

def walk(items):
    for item in items:
        yield item
        yield from walk(item.get('children',[]))

def fetch(item):
    with urllib.request.urlopen(item['url'],timeout=25) as response:body=response.read()
    name=item['path'].replace(' ','_')
    (PRIVATE/(name+'.html')).write_bytes(body)
    text=body.decode('utf-8')
    parser=Text();parser.feed(text)
    readable='\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())
    (PRIVATE/(name+'.txt')).write_text(readable,encoding='utf-8')
    return {'name':item['name'],'path':item['path'],'public_page':'https://support.unitree.com/home/zh/developer/'+urllib.parse.quote(item['path']),
        'official_cdn':item['url'],'page_update_time':item['updateTime'],'access_date':'2026-10-04',
        'sha256':hashlib.sha256(body).hexdigest(),'local_snapshot':'日志/下一阶段/'+name+'.html','text_characters':len(readable)}

def main():
    PRIVATE.mkdir(parents=True,exist_ok=True)
    entry=PRIVATE/'unitree-developer.json'
    if not entry.exists():
        with urllib.request.urlopen('https://robot-api.unitree.com/doc?space=developer&locale=zh',timeout=25) as response:
            entry.write_bytes(response.read())
    data=json.loads(entry.read_text(encoding='utf-8'))
    selected=[item for item in walk(data['data']['directory']) if item['path'] in SELECT]
    with ThreadPoolExecutor(max_workers=4) as pool:entries=list(pool.map(fetch,selected))
    assert len(entries)==7 and all(e['text_characters']>100 for e in entries)
    (PUBLIC/'宇树官方资料核验.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
    for entry in entries:print(json.dumps(entry,ensure_ascii=False))

if __name__=='__main__':main()
