import importlib.metadata as metadata
from pathlib import Path
import shutil
root=Path(__file__).resolve().parents[1]/'third-party-licenses';root.mkdir(exist_ok=True)
for name in ['PySide6_Essentials','PySide6_Addons','PySide6_WebEngine','shiboken6','numpy','scipy','Pillow','tifffile','pyinstaller']:
 dist=metadata.distribution(name)
 for f in dist.files or []:
  if any(key in str(f).lower() for key in ('license','copying','copyright','notice')) and dist.locate_file(f).is_file():
   dest=root/name/Path(str(f));dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dist.locate_file(f),dest)
print('Collected third-party licence files')
