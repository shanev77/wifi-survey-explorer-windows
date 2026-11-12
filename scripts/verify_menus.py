"""Visual verification of real menu popups in both application themes."""
import sys,os,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));os.environ['WIFI_CACHE_PATH']=str(root/'demo/maps.sqlite')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from survey_explorer.ui import Window
app=QApplication([]);window=Window();window.server.offline=True;window.show();checks=[];cases=iter([(theme,index) for theme in ['Dark','Light'] for index in [0,1]])
def next_case():
 try:theme,index=next(cases)
 except StopIteration:
  (root/'demo/menu-validation.json').write_text(json.dumps(checks,indent=2),encoding='utf-8');print(json.dumps(checks,indent=2),flush=True);window.dirty=False;window.close();app.quit();return
 window.theme=theme;window.apply_theme();action=window.menuBar().actions()[index];menu=action.menu();rect=window.menuBar().actionGeometry(action);menu.popup(window.menuBar().mapToGlobal(rect.bottomLeft()))
 def capture():
  labels=[a.text() for a in menu.actions()];assert all(labels) and labels
  menu.grab().save(str(root/f'demo/menu-{theme.lower()}-{action.text().lower()}.png'));checks.append(dict(theme=theme,menu=action.text(),items=labels));menu.close();QTimer.singleShot(100,next_case)
 QTimer.singleShot(300,capture)
QTimer.singleShot(700,next_case);app.exec()
