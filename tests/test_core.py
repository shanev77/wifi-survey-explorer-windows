import csv,json
from pathlib import Path
import numpy as np
import pytest
from survey_explorer.importing import parse_files,Cancelled
from survey_explorer.storage import Project,group_aps
from survey_explorer.analysis import estimate,surface,project,unproject
from survey_explorer.maps import coverage,Cache,MapServer
from survey_explorer.exporting import raster_export
ROOT=Path(__file__).resolve().parents[1]
def write(tmp_path,rows,name='input.csv',delimiter=','):
 p=tmp_path/name
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter=delimiter);w.writeheader();w.writerows(rows)
 return p
def row(**kw):
 r=dict(latitude='0',longitude='0',bssid='AA-BB-CC-DD-EE-FF',ssid='Café, "家"',rssi_dbm='-65',timestamp_utc='2026-11-12T09:00:00+08:00');r.update(kw);return r
@pytest.mark.parametrize('delimiter',[',',';','\t'])
def test_parse_unicode_optional_zero(tmp_path,delimiter):
 obs,reports=parse_files([write(tmp_path,[row()],delimiter=delimiter)]);assert len(obs)==1;assert obs[0]['latitude']==0;assert obs[0]['ssid']=='Café, "家"';assert obs[0]['timestamp_utc'].endswith('+00:00');assert obs[0]['bssid']=='aa:bb:cc:dd:ee:ff'
def test_identity_duplicates_and_reopen(tmp_path):
 p1=write(tmp_path,[row(),row(bssid='11:22:33:44:55:66')]);p2=write(tmp_path,[row(),row(timestamp_utc='2026-11-12T01:00:01Z')],name='second.csv')
 obs,reports=parse_files([p1,p2]);p=Project();result=p.append(obs,reports);assert result['added']==3;assert result['duplicates']==1;assert len(group_aps(p.observations()))==2;assert p.append(obs,reports)['added']==0
 saved=tmp_path/'test.wifiproject';p.save(saved);p2=Project(saved);assert len(p2.observations())==3;p2.close();p.close()
def test_invalid_and_uncertain(tmp_path):
 obs,report=parse_files([write(tmp_path,[row(latitude='nan'),row(longitude='181'),row(rssi_dbm='bad'),row(timestamp_utc=''),row(timestamp_utc='')])]);assert len(report[0]['invalid'])==2;assert len(obs)==3;assert obs[0]['rssi_dbm'] is None;assert obs[1]['dedup_key']!=obs[2]['dedup_key']
def synthetic(seed=4,noise=0,line=False,offset=0,session='a'):
 rng=np.random.default_rng(seed);xy=rng.uniform(-120,120,(90,2));xy[:,0]+=offset
 if line:xy[:,1]=0
 transmitter=np.array([15+offset,25]);rssi=-35-24*np.log10(np.maximum(np.linalg.norm(xy-transmitter,axis=1),1))+rng.normal(0,noise,len(xy));ll=unproject(xy,[115.63,-33.35])
 return [dict(longitude=float(p[0]),latitude=float(p[1]),rssi_dbm=float(s),gps_accuracy_m=4,session_id=session) for p,s in zip(ll,rssi)],transmitter
@pytest.mark.parametrize('noise',[0,3])
def test_synthetic_estimation(noise):
 obs,truth=synthetic(noise=noise);e=estimate(obs);assert e['method']=='Experimental robust propagation fit';xy,_=project([[e['longitude'],e['latitude']]],[115.63,-33.35]);assert np.linalg.norm(xy[0]-truth)<25;assert e['confidence']!='High'
def test_weak_geometry_sparse_outlier():
 obs,_=synthetic(line=True);e=estimate(obs);assert e['confidence']=='Low';assert 'straight' in ' '.join(e['warnings']);assert surface(obs)['reason'];assert estimate(obs[:1])['method']=='Insufficient data'
 obs,_=synthetic();base=estimate(obs,False);obs[0]['rssi_dbm']=0;changed=estimate(obs,False);delta,_=project([[changed['longitude'],changed['latitude']]],[base['longitude'],base['latitude']]);assert np.linalg.norm(delta)<35
 before=estimate(obs,False);after=estimate(obs+[obs[0]]*500,False);assert before['samples']==after['samples'];assert abs(before['longitude']-after['longitude'])<1e-10
def test_conflicting_sessions():
 a,_=synthetic(session='a');b,_=synthetic(offset=1200,session='b');e=estimate(a+b,False);assert e['confidence']=='Low';assert 'inconsistent' in ' '.join(e['warnings'])
def test_surface_export(tmp_path):
 import tifffile
 obs,_=synthetic();s=surface(obs);assert not s['reason'];assert np.isnan(s['values']).any();path=tmp_path/'surface.tif';raster_export(path,s)
 with tifffile.TiffFile(path) as f:assert f.pages[0].tags[34735].value[-1]==4326
 assert surface(obs[:3])['reason']
def test_cancel_transaction(tmp_path):
 obs,reports=parse_files([write(tmp_path,[row()])]);p=Project()
 with pytest.raises(Cancelled):p.append(obs,reports,lambda:True)
 assert not p.observations()
def test_disjoint_coverage():
 a=[dict(latitude=-33.35,longitude=115.63)];b=[dict(latitude=-33.86,longitude=151.2)];assert len(coverage(a+b))<=len(coverage(a))+len(coverage(b));assert len(coverage(a+b))<250

def test_offline_server(tmp_path,monkeypatch):
 import survey_explorer.maps as maps,urllib.request
 cache=Cache(tmp_path/'cache.sqlite');style=dict(version=8,sources={},layers=[dict(id='bg',type='background',paint={'background-color':'#fff'})])
 with cache.connection() as db:db.execute('INSERT INTO resources VALUES(?,?,?)',(maps.DEFAULT_STYLE,json.dumps(style).encode(),'application/json'))
 monkeypatch.setattr(maps,'fetch',lambda url:pytest.fail('Offline server attempted network'))
 server=MapServer(ROOT/'assets',cache);server.offline=True
 try:
  with urllib.request.urlopen(server.base+'/style') as response:assert json.load(response)['version']==8
  with urllib.request.urlopen(server.base+'/index.html') as response:assert b'maplibre-gl.js' in response.read()
 finally:server.close()
def test_supplied_files():
 paths=sorted(ROOT.glob('wifi-survey*.csv'))
 if not paths:pytest.skip('Private supplied surveys are not distributed with public source')
 obs,reports=parse_files(paths);assert len(obs)==6521;assert not any(r['invalid'] for r in reports);p=Project();result=p.append(obs,reports);assert result['added']==6521;assert p.append(obs,reports)['duplicates']==6521;p.close()
