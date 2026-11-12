import os,sys,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));os.environ['WIFI_CACHE_PATH']=str(root/'demo/maps.sqlite')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from survey_explorer.ui import Window
from survey_explorer.analysis import surface
app=QApplication([]);window=Window();window.server.offline=True;window.show();window.demo()
result={};errors=[]
# Fail on every remote-fetch attempt while checking real street maps offline.
import survey_explorer.maps as maps
def deny(url):errors.append(url);raise RuntimeError('Network disabled during offline verification')
maps.fetch=deny

def inspect_map():
 window.web.page().runJavaScript("JSON.stringify({loaded:map.isStyleLoaded(),tiles:map.areTilesLoaded(),sources:Object.keys(map.getStyle().sources),features:map.queryRenderedFeatures().length,measurements:map.queryRenderedFeatures({layers:['points','clusters']}).length,center:map.getCenter(),zoom:map.getZoom(),notice:document.getElementById('notice').textContent})",lambda value:result.update(map=json.loads(value) if value else None))
 # Choose the most sampled BSSID with a supported surface.
 for b,rows in sorted(window.groups.items(),key=lambda x:-len(x[1])):
  s=surface(rows)
  if not s.get('reason'):
   window.select_bssid(b);window.current_surface=s;window.publish('selected');result['selected_bssid']=b;break
 QTimer.singleShot(3000,finish)
def finish():
 result.update(observations=len(window.obs),aps=len(window.groups),network_attempts=errors,resource_errors=window.server.errors)
 window.grab().save(str(root/'demo/verified-interface.png'))
 window.web.page().runJavaScript("JSON.stringify({surface:!!map.getLayer('surface'),selected:map.queryRenderedFeatures({layers:['selected']}).length,streetFeatures:map.queryRenderedFeatures().filter(f=>!['points','clusters','selected','uncertainty-fill','uncertainty-line','strongest','estimates','surface','routes','contours'].includes(f.layer.id)).length})",save)
def save(value):
 result['selected_map']=json.loads(value) if value else None;(root/'demo/ui-validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2),flush=True);assert result['map']['loaded'] and result['map']['measurements']>0
 assert result['selected_map']['surface'] and result['selected_map']['streetFeatures']>0
 assert not errors and not window.server.errors
 window.dirty=False;window.close();app.quit()
QTimer.singleShot(10000,inspect_map);QTimer.singleShot(35000,app.quit);app.exec()
