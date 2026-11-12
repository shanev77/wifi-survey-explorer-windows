import sys,os,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));os.environ['WIFI_CACHE_PATH']=str(root/'demo/maps.sqlite')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from survey_explorer.ui import Window
from survey_explorer.importing import parse_files
app=QApplication([]);w=Window();w.server.offline=True;w.show();results={}
def start():w.job('Import verification',lambda p,c:parse_files(sorted(root.glob('wifi-survey*.csv')),progress=p,cancel=c),parsed)
def parsed(data):
 results['parsed']=len(data[0]);QTimer.singleShot(100,lambda:w.job('Commit verification',lambda p,c:w.project.append(*data,cancel=c),committed))
def committed(value):
 results['import']=value;w.reload();assert len(w.obs)==6521
 b=max(w.groups,key=lambda b:len(w.groups[b]));w.select_bssid(b);results['bssid']=b
 QTimer.singleShot(100,estimate_selected)
def estimate_selected():
 from survey_explorer.analysis import estimate
 w.job('Estimate verification',lambda p,c:estimate(w.groups[w.selected],cancel=c),estimated)
def estimated(value):
 results['estimate']=value['method'];w.project.put_estimates({w.selected:value});w.show_details();w.publish();QTimer.singleShot(100,surface_selected)
def surface_selected():
 from survey_explorer.analysis import surface
 w.job('Surface verification',lambda p,c:surface(w.groups[w.selected],cancel=c),finish)
def finish(value):
 results['surface_available']=not bool(value.get('reason'));(root/'demo/worker-validation.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results),flush=True);w.dirty=False;QTimer.singleShot(200,w.close);QTimer.singleShot(400,app.quit)
QTimer.singleShot(500,start);QTimer.singleShot(60000,app.quit);app.exec()
