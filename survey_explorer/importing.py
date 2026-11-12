"""Loss-aware survey parsing. Original rows are retained verbatim as field values."""
import csv, io, re, hashlib, json, math, uuid
from pathlib import Path
from datetime import datetime, timezone

ALIASES = {
 'latitude':['latitude','lat','gps_latitude'], 'longitude':['longitude','lon','lng','gps_longitude'],
 'bssid':['bssid','mac','mac_address','ap_mac'], 'rssi_dbm':['rssi_dbm','rssi','signal','signal_dbm'],
 'ssid':['ssid','network_name'], 'timestamp_utc':['timestamp_utc','timestamp','time','datetime'],
 'session_id':['session_id','session'], 'gps_accuracy_m':['gps_accuracy_m','accuracy','accuracy_m'],
 'frequency_mhz':['frequency_mhz','frequency','freq'], 'channel':['channel'], 'security':['security'],
 'band':['band'], 'observation_id':['observation_id','measurement_id'],
}
class Cancelled(Exception): pass

def check(cancel):
 if cancel and cancel(): raise Cancelled('Operation cancelled; no partial observations committed.')

def inspect(path):
 raw=Path(path).read_bytes()
 encoding='utf-16' if raw[:2] in (b'\xff\xfe',b'\xfe\xff') else 'utf-8-sig'
 text=raw.decode(encoding)
 try: delimiter=csv.Sniffer().sniff(text[:65536], delimiters=',;\t').delimiter
 except csv.Error: delimiter=max(',;\t',key=lambda d:text.splitlines()[0].count(d))
 reader=csv.DictReader(io.StringIO(text),delimiter=delimiter)
 headers=reader.fieldnames or []
 norm={re.sub(r'[^a-z0-9]','',h.lower()):h for h in headers}
 mapping={k:next((norm[re.sub(r'[^a-z0-9]','',a)] for a in names if re.sub(r'[^a-z0-9]','',a) in norm),None) for k,names in ALIASES.items()}
 return text,delimiter,headers,mapping,hashlib.sha256(raw).hexdigest(),encoding

def parse_files(paths, mappings=None, progress=None, cancel=None):
 batch=str(uuid.uuid4()); observations=[]; reports=[]
 for file_index,path in enumerate(paths):
  check(cancel)
  text,delimiter,headers,mapping,digest,encoding=inspect(path)
  mapping.update((mappings or {}).get(str(path),{}))
  missing=[k for k in ('latitude','longitude','bssid') if not mapping.get(k)]
  if missing: raise ValueError(f'{Path(path).name}: map required columns: {", ".join(missing)}')
  report=dict(filename=Path(path).name,sha256=digest,encoding=encoding,delimiter=delimiter,rows=0,invalid=[],warnings=[],batch=batch)
  reader=csv.DictReader(io.StringIO(text),delimiter=delimiter)
  for raw in reader:
   check(cancel); report['rows']+=1; rownum=reader.line_num
   def field(k): return (raw.get(mapping.get(k)) or '').strip()
   try:
    if None in raw: raise ValueError('More values than column headers')
    lat=float(field('latitude')); lon=float(field('longitude'))
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180: raise ValueError('Invalid coordinate range')
    if str(raw.get('valid_map_position','true')).lower() in ('false','0','no'): raise ValueError('Source marks map position invalid')
    mac=re.sub('[:. -]','',field('bssid')).lower()
    if not re.fullmatch('[0-9a-f]{12}',mac): raise ValueError('Invalid BSSID')
    bssid=':'.join(mac[i:i+2] for i in range(0,12,2))
    o={k:field(k) for k in ALIASES}; o.update(latitude=lat,longitude=lon,bssid=bssid,bssid_original=field('bssid'),source_file=Path(path).name,source_hash=digest,row_number=rownum,import_batch=batch,raw=raw)
    warnings=[]
    for k,lo,hi in [('rssi_dbm',-150,10),('gps_accuracy_m',0,100000),('frequency_mhz',0,100000),('channel',0,1000)]:
     v=field(k); o[k]=None
     if v:
      try:
       value=float(v)
       if not math.isfinite(value) or not lo<=value<=hi: raise ValueError()
       o[k]=value
      except ValueError: warnings.append(f'{k}: invalid numeric value retained in raw data')
    original_time=field('timestamp_utc'); o['timestamp_original']=original_time; o['timestamp_utc']=None
    if original_time:
     try:
      dt=datetime.fromisoformat(original_time.replace('Z','+00:00'))
      if dt.tzinfo is None: warnings.append('Timestamp lacks offset; not used for deduplication or routes')
      else: o['timestamp_utc']=dt.astimezone(timezone.utc).isoformat()
     except ValueError: warnings.append('Unrecognised timestamp retained in raw data')
    identity=field('observation_id')
    if identity: key=['id',o['session_id'],bssid,identity]
    elif o['timestamp_utc']: key=['composite',o['timestamp_utc'],bssid,lat,lon,o['rssi_dbm'],o['frequency_mhz'],o['channel'],o['session_id'],o['ssid'],raw.get('capabilities','')]
    else:
     key=['source-row',digest,rownum]
     warnings.append('No reliable time/ID: only identical-file rows deduplicated')
    o['dedup_key']=hashlib.sha256(json.dumps(key,ensure_ascii=False).encode()).hexdigest()
    observations.append(o)
    if warnings: report['warnings'].append(dict(row=rownum,reasons=warnings))
   except (ValueError,TypeError) as e: report['invalid'].append(dict(row=rownum,reason=str(e),raw=raw))
   if progress and report['rows']%250==0: progress(int(100*file_index/len(paths)),f'Reading {Path(path).name}: {report["rows"]:,} rows')
  reports.append(report)
 return observations,reports
