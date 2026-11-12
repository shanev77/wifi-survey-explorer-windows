"""Exports distinguish reception measurements from inferred transmitter locations."""
import csv,json,io,base64,math
import numpy as np
from PIL import Image

def csv_export(path,rows):
 rows=list(rows); keys=list(dict.fromkeys(k for r in rows for k in r))
 with open(path,'w',encoding='utf-8-sig',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
  for row in rows:writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})

def features(obs,estimates):
 result=[]
 for o in obs:result.append(dict(type='Feature',geometry=dict(type='Point',coordinates=[o['longitude'],o['latitude']]),properties=dict(o,kind='measurement')))
 for key,e in estimates.items():
  if 'longitude' in e:result.append(dict(type='Feature',geometry=dict(type='Point',coordinates=[e['longitude'],e['latitude']]),properties=dict(e,bssid=key.split('|')[0],scope=key.split('|')[-1],kind='estimated_transmitter')))
 return dict(type='FeatureCollection',features=result)

def geojson_export(path,obs,estimates):
 with open(path,'w',encoding='utf-8') as f:json.dump(features(obs,estimates),f,ensure_ascii=False)

def rgba(values,opacity=180):
 stops=np.array([-100,-85,-70,-55,-35]); colors=np.array([[90,71,180],[38,123,198],[32,184,170],[245,202,65],[238,88,69]])
 out=np.zeros((*values.shape,4),dtype=np.uint8);v=np.nan_to_num(values,nan=-100)
 for c in range(3):out[:,:,c]=np.interp(v,stops,colors[:,c]).astype(np.uint8)
 out[:,:,3]=np.where(np.isfinite(values),opacity,0).astype(np.uint8);return out

def image_uri(surface):
 buffer=io.BytesIO();Image.fromarray(rgba(surface['values'])).save(buffer,format='PNG');return 'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()

def raster_export(path,surface):
 import tifffile
 values=surface['values'].astype('float32');nw,ne,se,sw=surface['corners'];h,w=values.shape
 # Geographic WGS84, pixel-is-area; extend half a sample beyond centres.
 dx=(ne[0]-nw[0])/(w-1);dy=(nw[1]-sw[1])/(h-1)
 keys=(1,1,0,3,1024,0,1,2,1025,0,1,1,2048,0,1,4326)
 tifffile.imwrite(path,values,metadata=None,description=surface['method']+'; units dBm; NaN = unsupported',extratags=[(33550,'d',3,(dx,dy,0),False),(33922,'d',6,(0,0,0,nw[0]-dx/2,nw[1]+dy/2,0),False),(34735,'H',len(keys),keys,False),(42113,'s',4,'nan',False)])

def contour_features(surface):
 v=surface['values'];h,w=v.shape;nw,ne,se,sw=surface['corners'];lines=[]
 def ll(x,y):return [nw[0]+x/(w-1)*(ne[0]-nw[0]),nw[1]+y/(h-1)*(sw[1]-nw[1])]
 for level in (-90,-80,-70,-60,-50,-40):
  for y in range(h-1):
   for x in range(w-1):
    vals=[v[y,x],v[y,x+1],v[y+1,x+1],v[y+1,x]]
    if not np.all(np.isfinite(vals)):continue
    pts=[(x,y),(x+1,y),(x+1,y+1),(x,y+1)];hits=[]
    for i in range(4):
     j=(i+1)%4
     if (vals[i]<level)<(vals[j]<level) or (vals[j]<level)<(vals[i]<level):
      t=(level-vals[i])/(vals[j]-vals[i]);hits.append(ll(pts[i][0]+t*(pts[j][0]-pts[i][0]),pts[i][1]+t*(pts[j][1]-pts[i][1])))
    if len(hits)==2:lines.append(dict(type='Feature',geometry=dict(type='LineString',coordinates=hits),properties=dict(dbm=level)))
 return dict(type='FeatureCollection',features=lines)
