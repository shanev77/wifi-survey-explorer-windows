"""Entry point with persistent diagnostics for the windowed Windows build."""
import sys,os,traceback
from pathlib import Path
if getattr(sys,'frozen',False):
 logdir=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'WiFiSurveyExplorer'
 logdir.mkdir(parents=True,exist_ok=True)
 sys.stdout=open(logdir/'application.log','w',encoding='utf-8',buffering=1)
 sys.stderr=sys.stdout
try:
 from survey_explorer.ui import main
 if __name__=='__main__':raise SystemExit(main())
except Exception:
 traceback.print_exc()
 raise
