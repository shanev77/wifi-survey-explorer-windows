import os,sys,json,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));os.environ['WIFI_CACHE_PATH']=str(root/'demo/maps.sqlite')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from survey_explorer.ui import Window
from survey_explorer.analysis import surface,samples,geometry
import numpy as np
app=QApplication([]);w=Window();w.server.offline=True;w.show();w.demo();result={};failures=[]
def guard(fn):
 def wrapped(*args):
  try:fn(*args)
  except Exception as e:
   import traceback
   failures.append(traceback.format_exc());print(failures[-1],flush=True);w.dirty=False;w.close();app.quit()
 return wrapped
@guard
def begin():
 w.frequency.setCurrentText('2412.0');assert w.visible() and all(o['frequency_mhz']==2412 for o in w.visible());result['frequency_filtered']=len(w.visible())
 w.security.setCurrentText('WPA2');assert w.visible() and all(o['security']=='WPA2' for o in w.visible());result['combined_filtered']=len(w.visible())
 assert len(w.server.state['observations'])==len(w.visible())
 w.reset_filters();assert len(w.visible())==6521
 w.search.setText('Telstra');assert w.visible() and len(w.visible())<6521;assert len(w.server.state['observations'])==len(w.visible());result['name_filtered']=len(w.visible());w.reset_filters()
 candidates=[]
 for b,rows in w.groups.items():
  if len(rows)<6:continue
  xy,rr,origin,good=samples(rows);ratio,spread=geometry(xy)
  if 30<spread<600 and ratio>.06:
   s=surface(rows)
   if not s.get('reason'):candidates.append((len(rows),b))
 assert candidates
 b=max(candidates)[1];w.select_bssid(b);item=w.ap_list.currentItem();w.ap_list.scrollToItem(item);app.processEvents()
 QTest.mouseClick(w.ap_list.viewport(),Qt.LeftButton,Qt.NoModifier,w.ap_list.visualItemRect(item).center())
 QTest.mouseDClick(w.ap_list.viewport(),Qt.LeftButton,Qt.NoModifier,w.ap_list.visualItemRect(item).center())
 result['selected_bssid']=b;QTimer.singleShot(3000,check_map)
@guard
def check_map():
 print('Surface state',w.selected,result.get('selected_bssid'),w.mode.currentIndex(),w.map_status.text(),flush=True)
 assert w.current_surface is not None;result['surface_cells']=int(np.isfinite(w.current_surface['values']).sum())
 w.web.page().runJavaScript("JSON.stringify({surface:!!map.getLayer('surface'),fit:(state.selected||[]).every(f=>map.getBounds().contains(f.geometry.coordinates)),count:(state.selected||[]).length})",after_map)
@guard
def after_map(value):
 result['map']=json.loads(value);print(result,flush=True);assert result['map']['surface'] and result['map']['fit']
 w.web.page().runJavaScript("(()=>{const f=map.queryRenderedFeatures({layers:['selected']})[0];if(!f)return false;const p=map.project(f.geometry.coordinates);map.fire('mousemove',{point:p,lngLat:map.unproject(p)});return true})()",lambda v:result.update(hover_event=bool(v)))
 QTimer.singleShot(700,capture)
@guard
def capture():
 w.grab().save(str(root/'demo/hover-and-surface.png'))
 w.web.page().runJavaScript("JSON.stringify({text:document.querySelector('.ap-tooltip')?.textContent||'',unsafeElements:document.querySelectorAll('.ap-tooltip script,.ap-tooltip img').length})",finish)
@guard
def finish(value):
 result['hover']=json.loads(value);assert 'BSSID' in result['hover']['text'] and 'Signal' in result['hover']['text'];assert result['hover']['unsafeElements']==0;assert not w.server.errors
 about=w.create_about_dialog();about.show();app.processEvents()
 from PySide6.QtWidgets import QLabel
 assert not about.findChild(QLabel,'aboutAuthorPhoto').pixmap().isNull()
 assert 'Copyright 2026 S. van Ingen' in about.findChild(QLabel,'aboutDescription').text()
 about.grab().save(str(root/'demo/about-dialog.png'));about.close();result['about_verified']=True
 (root/'demo/interaction-validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2),flush=True);w.dirty=False;w.close();app.quit()
QTimer.singleShot(8000,begin);QTimer.singleShot(40000,app.quit);app.exec()
if failures or 'hover' not in result:raise SystemExit(1)
