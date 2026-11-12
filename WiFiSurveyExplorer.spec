# PyInstaller builds; set WIFI_ONEFILE=1 for a standalone self-extracting executable.
from pathlib import Path
import os,sys
os.environ['PATH']=os.pathsep.join([sys.base_prefix,str(Path(sys.base_prefix)/'DLLs'),str(Path(os.environ['SystemRoot'])/'System32'),os.environ['SystemRoot']])
root=Path(SPECPATH)
datas=[(str(root/'assets'),'assets'),(str(root/'third-party-licenses'),'third-party-licenses'),(str(root/'README.md'),'.'),(str(root/'THIRD_PARTY_NOTICES.md'),'.')]
for path in [root/'demo/supplied-surveys.wifiproject',root/'demo/maps.sqlite']:
 if path.exists():datas.append((str(path),'demo'))
a=Analysis([str(root/'main.py')],pathex=[str(root)],binaries=[],datas=datas,hiddenimports=['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtWebChannel','scipy._external.array_api_compat.numpy.fft','scipy._external.array_api_compat.numpy.linalg'],hookspath=[],runtime_hooks=[],excludes=['matplotlib','pandas','IPython','jupyter','tkinter','PyQt5','PyQt6','torch','tensorflow'],noarchive=False)
pyz=PYZ(a.pure)
if os.environ.get('WIFI_ONEFILE') in ('1','both'):
 exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='WiFiSurveyExplorer-Standalone',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,icon=str(root/'assets/icon.ico'))
if os.environ.get('WIFI_ONEFILE')!='1':
 exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='WiFiSurveyExplorer',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,icon=str(root/'assets/icon.ico'))
 coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='WiFiSurveyExplorer')
