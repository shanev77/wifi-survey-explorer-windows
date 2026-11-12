"""SQLite project format 1; transactional import and atomic snapshot save."""
import sqlite3, json, os, uuid
from pathlib import Path
from collections import defaultdict
from .importing import check
VERSION=1
class Project:
 def __init__(self,path=':memory:'):
  self.db=sqlite3.connect(str(path),check_same_thread=False); self.db.execute('PRAGMA foreign_keys=ON')
  self.db.executescript('''CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,dedup_key TEXT UNIQUE NOT NULL,bssid TEXT NOT NULL,data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS by_bssid ON observations(bssid);
CREATE TABLE IF NOT EXISTS access_points(bssid TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY,batch TEXT,report TEXT);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS estimates(bssid TEXT,scope TEXT,data TEXT,PRIMARY KEY(bssid,scope));
CREATE TABLE IF NOT EXISTS notes(bssid TEXT PRIMARY KEY,note TEXT,bookmarked INTEGER DEFAULT 0);''')
  v=self.get('format_version',VERSION)
  if v!=VERSION: raise ValueError(f'Unsupported project version {v}')
  self.set('format_version',VERSION)
 def set(self,key,value):
  with self.db: self.db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(key,json.dumps(value)))
 def get(self,key,default=None):
  row=self.db.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone(); return json.loads(row[0]) if row else default
 def append(self,obs,reports,cancel=None):
  added=0; duplicates=0
  with self.db:
   for o in obs:
    check(cancel)
    cur=self.db.execute('INSERT OR IGNORE INTO observations(dedup_key,bssid,data) VALUES(?,?,?)',(o['dedup_key'],o['bssid'],json.dumps(o,ensure_ascii=False)))
    if cur.rowcount:
     added+=1; self.db.execute('INSERT OR IGNORE INTO access_points VALUES(?)',(o['bssid'],)); self.db.execute('INSERT OR IGNORE INTO sessions VALUES(?)',(o['session_id'],))
     self.db.execute('DELETE FROM estimates WHERE bssid=?',(o['bssid'],))
    else: duplicates+=1
   for r in reports: self.db.execute('INSERT INTO imports(batch,report) VALUES(?,?)',(r['batch'],json.dumps(r,ensure_ascii=False)))
  return dict(added=added,duplicates=duplicates,files=len(reports),rows=sum(r['rows'] for r in reports),invalid=sum(len(r['invalid']) for r in reports))
 def observations(self):
  return [dict(json.loads(data),id=id) for id,data in self.db.execute('SELECT id,data FROM observations')]
 def estimates(self): return {f'{b}|{s}':json.loads(d) for b,s,d in self.db.execute('SELECT * FROM estimates')}
 def put_estimates(self,estimates,scope='all'):
  with self.db:
   for b,e in estimates.items(): self.db.execute('INSERT OR REPLACE INTO estimates VALUES(?,?,?)',(b,scope,json.dumps(e)))
 def save(self,path):
  path=Path(path); temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
  try:
   target=sqlite3.connect(temp); self.db.backup(target); target.close(); os.replace(temp,path)
  finally:
   if temp.exists(): temp.unlink()
 def close(self): self.db.close()

def group_aps(obs):
 groups=defaultdict(list)
 for o in obs: groups[o['bssid']].append(o)
 return dict(groups)

