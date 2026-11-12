import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from survey_explorer.maps import Cache,coverage,download,DEFAULT_STYLE
from survey_explorer.storage import Project
root=Path(__file__).resolve().parents[1];p=Project(root/'demo/supplied-surveys.wifiproject');tiles=coverage(p.observations());p.close();print('Tile count',len(tiles),flush=True)
cache=Cache(root/'demo/maps.sqlite');pack=download(cache,DEFAULT_STYLE,tiles,'Supplied survey - zoom 8-14',lambda n,t:print(t,flush=True));print(json.dumps(pack,indent=2))
