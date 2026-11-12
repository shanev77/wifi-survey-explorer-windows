"""Metric reception analysis. No known transmit power or exact RSSI ranges assumed."""
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import cKDTree, Delaunay, QhullError
from .importing import check
R=6371008.8
ALGORITHM='rssi-explorer-1.0'

def project(coords,origin=None):
 coords=np.asarray(coords,float); origin=np.asarray(origin if origin is not None else np.median(coords,axis=0))
 delta=coords-origin; delta[:,0]=(delta[:,0]+180)%360-180
 return np.column_stack((np.radians(delta[:,0])*R*max(.001,np.cos(np.radians(origin[1]))),np.radians(delta[:,1])*R)),origin

def unproject(xy,origin):
 xy=np.asarray(xy); return np.column_stack((((origin[0]+np.degrees(xy[:,0]/(R*max(.001,np.cos(np.radians(origin[1]))))))+180)%360-180,origin[1]+np.degrees(xy[:,1]/R)))

def samples(obs,cell=8,gps_limit=50):
 good=[o for o in obs if o['rssi_dbm'] is not None and (o.get('gps_accuracy_m') is None or o['gps_accuracy_m']<=gps_limit)]
 if not good: return np.empty((0,2)),np.array([]),np.array([0.,0.]),[]
 unique={(o['longitude'],o['latitude'],o['rssi_dbm']):o for o in good}
 good=list(unique.values())
 xy,origin=project([[o['longitude'],o['latitude']] for o in good]); buckets={}
 for i,p in enumerate(xy): buckets.setdefault(tuple(np.floor(p/cell).astype(int)),[]).append(i)
 points=[]; signals=[]
 for ids in buckets.values(): points.append(np.median(xy[ids],axis=0)); signals.append(np.median([good[i]['rssi_dbm'] for i in ids]))
 return np.asarray(points),np.asarray(signals),origin,good

def geometry(xy):
 if len(xy)<3:return 0.,0.
 eig=np.linalg.eigvalsh(np.cov(xy.T)); return float(eig[0]/max(eig[-1],1)),float(np.linalg.norm(np.ptp(xy,axis=0)))

def centroid(xy,rssi):
 # Cap at 12 dB over median: no isolated strong reading can dominate.
 r=np.clip(rssi,np.median(rssi)-25,np.median(rssi)+12)
 weights=np.power(10,(r-r.max())/20); weights=np.maximum(weights,.03)
 return np.average(xy,axis=0,weights=weights)

def estimate(obs,experimental=True,cancel=None):
 xy,rssi,origin,good=samples(obs); n=len(xy); ratio,spread=geometry(xy)
 result=dict(algorithm=ALGORITHM,settings=dict(cell_m=8,gps_limit_m=50,weighting='10^((clipped RSSI - max)/20), floor .03',path_loss_bounds=[1,5],reference_dbm_bounds=[-90,-10]),samples=n,confidence='Low',method='Insufficient data',warnings=[],diagnostics=dict(geometry_ratio=ratio,spread_m=spread),uncertainty_description='Approximate sensitivity/spread radius, not a calibrated confidence interval')
 if n<2: return result
 check(cancel); center=centroid(xy,rssi); method='Robust signal-weighted centroid'
 if n<5: result['warnings'].append('Sparse spatial samples')
 if ratio<.06: result['warnings'].append('Nearly straight route: either side of the road may be plausible')
 if spread>20000: result['warnings'].append('Distant observations: local model is unreliable; inspect individual sessions')
 distances=np.linalg.norm(xy-center,axis=1); accuracy=float(np.median([o.get('gps_accuracy_m') or 15 for o in good]))
 uncertainty=max(25.,accuracy,float(np.percentile(distances,75)))
 # Spatial-cell deletion measures sensitivity without treating stationary repeats as independent.
 centers=[]
 for ids in np.array_split(np.arange(n),min(12,n)):
  check(cancel); keep=np.ones(n,bool); keep[ids]=False
  if keep.sum()>=2: centers.append(centroid(xy[keep],rssi[keep]))
 sensitivity=float(max((np.linalg.norm(c-center) for c in centers),default=0)); uncertainty=max(uncertainty,sensitivity*2)
 result['diagnostics']['centroid_sensitivity_m']=sensitivity
 if n>=8 and ratio>=.06 and spread>=30 and spread<20000 and experimental:
  pad=max(100.,spread); lo=xy.min(axis=0)-pad; hi=xy.max(axis=0)+pad
  def residual(p,xx=xy,rr=rssi): return p[2]-10*p[3]*np.log10(np.maximum(np.linalg.norm(xx-p[:2],axis=1),1))-rr
  starts=[center,np.mean(xy,axis=0),xy[np.argmax(rssi)],center+[spread/2,0],center+[-spread/2,0],center+[0,spread/2],center+[0,-spread/2]]
  fits=[]
  for start in starts:
   check(cancel)
   p=np.r_[np.clip(start,lo+1,hi-1),-40.,2.5]
   fit=least_squares(residual,p,bounds=(np.r_[lo,-90.,1.],np.r_[hi,-10.,5.]),loss='soft_l1',f_scale=4,max_nfev=500)
   fits.append(fit)
  best=min(fits,key=lambda f:f.cost); p=best.x
  near=[f for f in fits if f.cost<=best.cost*1.1+1]
  stability=float(max(np.linalg.norm(f.x[:2]-p[:2]) for f in near))
  rmse=float(np.sqrt(np.mean(residual(p)**2))); boundary=bool(np.any((p-np.r_[lo,-90,1])<.02*(np.r_[hi,-10,5]-np.r_[lo,-90,1])) or np.any((np.r_[hi,-10,5]-p)<.02*(np.r_[hi,-10,5]-np.r_[lo,-90,1])))
  condition=float(np.linalg.cond(best.jac)); deletion=[]
  for ids in np.array_split(np.arange(n),min(8,n)):
   check(cancel); keep=np.ones(n,bool); keep[ids]=False
   f=least_squares(lambda q:residual(q,xy[keep],rssi[keep]),p,bounds=(np.r_[lo,-90,1],np.r_[hi,-10,5]),loss='soft_l1',f_scale=4,max_nfev=250)
   deletion.append(float(np.linalg.norm(f.x[:2]-p[:2])))
  fit_sensitivity=max(deletion)
  result['diagnostics'].update(residual_rmse_db=rmse,initialisation_spread_m=stability,fit_sensitivity_m=fit_sensitivity,jacobian_condition=condition,boundary_limited=boundary,reference_dbm=float(p[2]),path_loss_exponent=float(p[3]))
  if not boundary and stability<max(30,spread*.3) and fit_sensitivity<max(50,spread*.5) and condition<1e5 and rmse<12:
   center=p[:2]; method='Experimental robust propagation fit'; uncertainty=max(25.,accuracy*2,stability,fit_sensitivity*2,rmse*5); result['confidence']='Moderate'
  else: result['warnings'].append('Propagation model unstable, poorly identified or boundary-limited; baseline retained')
 result['method']=method
 # Session-specific centroids expose mobile/inconsistent BSSIDs.
 sessions={o.get('session_id') for o in good if o.get('session_id')}; session_centers=[]
 for session in sessions:
  subset=[o for o in good if o.get('session_id')==session]; sx,sr,so,_=samples(subset)
  if len(sx)>=3:
   sc=unproject([centroid(sx,sr)],so); local,_=project(sc,origin); session_centers.append(local[0])
 if len(session_centers)>1:
  disagreement=max(np.linalg.norm(a-b) for a in session_centers for b in session_centers)
  result['diagnostics']['session_disagreement_m']=float(disagreement)
  if disagreement>max(100.,uncertainty*1.5): result['warnings'].append('Possibly mobile or inconsistent across sessions; use session-specific estimates'); result['confidence']='Low'; uncertainty=max(uncertainty,float(disagreement))
 if ratio<.06 or n<5: result['confidence']='Low'
 ll=unproject([center],origin)[0]; result.update(longitude=float(ll[0]),latitude=float(ll[1]),uncertainty_m=float(uncertainty))
 direction=np.linalg.svd(xy-xy.mean(axis=0),full_matrices=False)[2][0]; offset=center-xy.mean(axis=0)
 result['diagnostics']['route_side_offset_m']=float(abs(direction[0]*offset[1]-direction[1]*offset[0]))
 return result

def surface(obs,resolution=90,radius=65,cancel=None):
 xy,rssi,origin,good=samples(obs); ratio,spread=geometry(xy)
 if len(xy)<4 or ratio<.025 or spread<15: return dict(reason='Surface unavailable: at least four spatial samples with two-dimensional spread are required.')
 if spread>20000: return dict(reason='Surface unavailable across distant clusters. Select a session or smaller area.')
 # Conservative local IDW: three samples within radius AND sample hull support.
 xs=np.linspace(xy[:,0].min(),xy[:,0].max(),resolution); ys=np.linspace(xy[:,1].max(),xy[:,1].min(),resolution)
 xx,yy=np.meshgrid(xs,ys); grid=np.column_stack((xx.ravel(),yy.ravel())); tree=cKDTree(xy)
 dist,idx=tree.query(grid,k=min(8,len(xy))); inside=Delaunay(xy).find_simplex(grid)>=0
 valid=inside & ((dist<=radius).sum(axis=1)>=3); weights=1/np.maximum(dist,2)**2; weights[dist>radius]=0
 values=np.full(len(grid),np.nan); values[valid]=(weights[valid]*rssi[idx[valid]]).sum(axis=1)/weights[valid].sum(axis=1)
 check(cancel)
 if not valid.any(): return dict(reason='Surface unavailable: no cells have three nearby supporting samples within 65 m.')
 corners=unproject([[xs[0],ys[0]],[xs[-1],ys[0]],[xs[-1],ys[-1]],[xs[0],ys[-1]]],origin)
 return dict(values=values.reshape((resolution,resolution)),corners=corners.tolist(),method='Median 8 m cells; IDW p=2, 65 m support radius; minimum 3 neighbours; convex-hull mask',reason='')
