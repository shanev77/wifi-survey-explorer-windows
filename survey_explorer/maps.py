"""Explicit offline resource packages; localhost-only map and asset service."""
import json, hashlib, sqlite3, threading, urllib.request, urllib.parse, math, time, mimetypes, gzip
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from .importing import check
DEFAULT_STYLE='https://tiles.openfreemap.org/styles/liberty'
AGENT='WiFiSurveyExplorer/1.0 (Windows desktop offline survey viewer)'
LIMIT_BYTES=48_000_000

def fetch(url):
 if urllib.parse.urlparse(url).scheme not in ('https','http'): raise ValueError('Map resources require HTTP(S) URLs')
 request=urllib.request.Request(url,headers={'User-Agent':AGENT,'Accept-Encoding':'identity'})
 with urllib.request.urlopen(request,timeout=25) as r:
  data=r.read(LIMIT_BYTES+1)
  if len(data)>LIMIT_BYTES: raise ValueError('Resource exceeds package size limit')
  if r.headers.get('Content-Encoding')=='gzip': data=gzip.decompress(data)
  return data,r.headers.get('Content-Type','application/octet-stream')

class Cache:
 def __init__(self,path):
  self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
  with self.connection() as db:
   db.executescript('CREATE TABLE IF NOT EXISTS resources(url TEXT PRIMARY KEY,data BLOB,mime TEXT); CREATE TABLE IF NOT EXISTS packs(name TEXT PRIMARY KEY,manifest TEXT);')
 def connection(self): return sqlite3.connect(self.path,timeout=30)
 def get(self,url,network=True):
  with self.connection() as db: row=db.execute('SELECT data,mime FROM resources WHERE url=?',(url,)).fetchone()
  if row:return row
  if not network: raise FileNotFoundError('Resource absent from offline package; download coverage while online.')
  data,mime=fetch(url)
  with self.connection() as db: db.execute('INSERT OR REPLACE INTO resources VALUES(?,?,?)',(url,data,mime))
  return data,mime
 def packs(self):
  with self.connection() as db:return [json.loads(r[0]) for r in db.execute('SELECT manifest FROM packs')]
 def put_pack(self,manifest):
  with self.connection() as db:db.execute('INSERT OR REPLACE INTO packs VALUES(?,?)',(manifest['name'],json.dumps(manifest)))
 def delete(self,name):
  with self.connection() as db:
   db.execute('DELETE FROM packs WHERE name=?',(name,)); keep=set()
   for (m,) in db.execute('SELECT manifest FROM packs'):keep.update(json.loads(m)['resources'])
   for (url,) in db.execute('SELECT url FROM resources').fetchall():
    if url not in keep:db.execute('DELETE FROM resources WHERE url=?',(url,))
   db.commit(); db.execute('VACUUM')

def tile_xy(lon,lat,z):
 n=2**z; lat=max(-85.0511,min(85.0511,lat))
 return int((lon+180)/360*n)%n, min(n-1,max(0,int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)))

def coverage(obs,zmin=8,zmax=14):
 # Union padded measurement neighbourhoods, never one vast rectangle between distant clusters.
 tiles=set()
 for o in obs:
  lat=o['latitude']; lon=o['longitude']; dy=400/111195; dx=dy/max(.01,math.cos(math.radians(lat)))
  for z in range(zmin,zmax+1):
   cx,cy=tile_xy(lon,lat,z); x0,y0=tile_xy(lon-dx,lat+dy,z); x1,y1=tile_xy(lon+dx,lat-dy,z)
   xs=range(x0,x1+1) if x0<=x1 else list(range(x0,2**z))+list(range(0,x1+1))
   for x in xs:
    for y in range(y0,y1+1):tiles.add((z,x,y))
  if len(tiles)>2800: raise ValueError('Coverage exceeds 2,800 tiles. Filter a session or reduce maximum zoom.')
 # A one-tile viewport halo at each zoom prevents edge gaps while fitting coverage.
 tiles={(z,(x+dx)%2**z,y+dy) for z,x,y in tiles for dx in (-1,0,1) for dy in (-1,0,1) if 0<=y+dy<2**z}
 if len(tiles)>2800:raise ValueError('Padded viewport coverage exceeds 2,800 tiles; select a smaller session or zoom.')
 return sorted(tiles)

def proto_fields(data):
 def var(pos):
  v=0; shift=0
  while pos<len(data):
   b=data[pos]; pos+=1; v|=(b&127)<<shift
   if b<128:return v,pos
   shift+=7
   if shift>63:raise ValueError('Invalid protobuf')
  raise ValueError('Truncated protobuf')
 pos=0
 while pos<len(data):
  tag,pos=var(pos); wire=tag&7; number=tag>>3
  if wire==0:v,pos=var(pos)
  elif wire==2:
   size,pos=var(pos); v=data[pos:pos+size]; pos+=size
  elif wire==1:v=data[pos:pos+8];pos+=8
  elif wire==5:v=data[pos:pos+4];pos+=4
  else:raise ValueError('Invalid protobuf wire type')
  yield number,wire,v

def tile_ranges(data):
 ranges={0}
 for n,w,layer in proto_fields(data):
  if n==3 and w==2:
   for ln,lw,value in proto_fields(layer):
    if ln==4 and lw==2:
     for vn,vw,string in proto_fields(value):
      if vn==1 and vw==2:
       for c in string.decode('utf-8',errors='replace'): ranges.add(ord(c)//256*256)
 return ranges

def normalise_style(style):
 style=json.loads(json.dumps(style)); fonts=set()
 for layer in style.get('layers',[]):
  layout=layer.get('layout',{})
  if 'text-field' in layout:
   stack=layout.get('text-font',['Noto Sans Regular'])
   if not isinstance(stack,list) or not all(isinstance(x,str) for x in stack) or (stack and stack[0] in ('case','match','get','literal','step')): stack=['Noto Sans Regular']
   layout['text-font']=stack; fonts.add(','.join(stack))
 return style,fonts

def download(cache,style_url,tiles,name,progress=None,cancel=None):
 manifest=dict(name=name,style_url=style_url,status='Incomplete',resources=[],tiles=len(tiles),bytes=0,zooms=[min(t[0] for t in tiles),max(t[0] for t in tiles)],attribution='OpenFreeMap · OpenMapTiles · © OpenStreetMap contributors')
 seen=set()
 def get(url):
  check(cancel)
  error=None
  for attempt in range(3):
   try:data,mime=cache.get(url);break
   except Exception as e:error=e;check(cancel)
  else: raise error
  if url not in seen:
   seen.add(url); manifest['bytes']+=len(data); manifest['resources'].append(url)
   if manifest['bytes']>LIMIT_BYTES:raise ValueError('48 MB package cap reached. Reduce zoom or coverage.')
  return data
 try:
  style,fonts=normalise_style(json.loads(get(style_url))); ranges={0}
  requests=[]
  for source in style.get('sources',{}).values():
   source=dict(source)
   if 'url' in source: source.update(json.loads(get(source['url'])))
   templates=source.get('tiles',[])
   if not templates:continue
   for z,x,y in tiles:
    if source.get('minzoom',0)<=z<=source.get('maxzoom',22):
     requests.append((templates[0].replace('{z}',str(z)).replace('{x}',str(x)).replace('{y}',str(2**z-1-y if source.get('scheme')=='tms' else y)),source.get('type','vector')))
  if len(requests)>2800:raise ValueError('Multiple sources exceed 2,800 tile limit')
  for i,(url,kind) in enumerate(requests):
   data=get(url)
   if kind=='vector':ranges.update(tile_ranges(data))
   if progress:progress(int(85*(i+1)/max(1,len(requests))),f'Downloading tiles {i+1}/{len(requests)} · {manifest["bytes"]/1e6:.1f} MB')
  sprites=style.get('sprite',[])
  if isinstance(sprites,str):sprites=[{'url':sprites}]
  for sprite in sprites:
   for suffix in ('.json','.png','@2x.json','@2x.png'):get(sprite['url']+suffix)
  glyphs=style.get('glyphs')
  if glyphs:
   jobs=[(stack,start) for stack in sorted(fonts) for start in sorted(ranges)]
   for i,(stack,start) in enumerate(jobs):
    get(glyphs.replace('{fontstack}',urllib.parse.quote(stack,safe=',')).replace('{range}',f'{start}-{start+255}'))
    if progress:progress(85+int(14*(i+1)/len(jobs)),f'Fonts {i+1}/{len(jobs)} · {manifest["bytes"]/1e6:.1f} MB')
  manifest['status']='Complete';manifest['glyph_ranges']=sorted(ranges);manifest['font_stacks']=sorted(fonts)
 finally:cache.put_pack(manifest)
 return manifest

class MapServer:
 def __init__(self,assets,cache):
  self.assets=Path(assets);self.cache=cache;self.offline=False;self.style_url=DEFAULT_STYLE;self.state={};self.errors=[];self.lock=threading.Lock()
  owner=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    try:
     parsed=urllib.parse.urlparse(self.path)
     if parsed.path=='/state':data=json.dumps(owner.state,ensure_ascii=False).encode();mime='application/json'
     elif parsed.path=='/style':
      style,fonts=normalise_style(json.loads(owner.cache.get(owner.style_url,not owner.offline)[0]))
      for source in style.get('sources',{}).values():
       if 'url' in source:
        source.update(json.loads(owner.cache.get(source.pop('url'),not owner.offline)[0]))
       if 'tiles' in source:
        source['tiles']=[owner.proxy(u) for u in source['tiles']]
        complete=[p for p in owner.cache.packs() if p['status']=='Complete' and p['style_url']==owner.style_url]
        if owner.offline and complete:source['maxzoom']=min(source.get('maxzoom',22),max(p['zooms'][1] for p in complete));source['minzoom']=min(source.get('maxzoom',22),min(p['zooms'][0] for p in complete))
      if style.get('glyphs'):style['glyphs']=owner.proxy(style['glyphs'])
      sprites=style.get('sprite')
      if isinstance(sprites,str):style['sprite']=owner.base+'/sprite?url='+urllib.parse.quote(sprites,safe='')
      elif isinstance(sprites,list):
       for s in sprites:s['url']=owner.base+'/sprite?url='+urllib.parse.quote(s['url'],safe='')
      data=json.dumps(style).encode();mime='application/json'
     elif parsed.path=='/resource' or parsed.path.startswith('/sprite'):
      url=urllib.parse.parse_qs(parsed.query)['url'][0]
      if parsed.path.startswith('/sprite'):url+=parsed.path[len('/sprite'):]
      url=urllib.parse.quote(url,safe=':/?&=%{},@+-._~')
      data,mime=owner.cache.get(url,not owner.offline)
     else:
      path=(owner.assets/parsed.path.lstrip('/')).resolve()
      if not path.is_relative_to(owner.assets.resolve()):raise FileNotFoundError()
      if path.is_dir():path=path/'index.html'
      data=path.read_bytes();mime=mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
     self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    except Exception as e:
     owner.errors.append(dict(path=self.path,error=str(e)))
     self.send_response(503);self.end_headers();self.wfile.write(str(e).encode())
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.base=f'http://127.0.0.1:{self.server.server_port}'
  threading.Thread(target=self.server.serve_forever,daemon=True).start()
 def proxy(self,url):return self.base+'/resource?url='+urllib.parse.quote(url,safe='{},')
 def close(self):self.server.shutdown();self.server.server_close()
