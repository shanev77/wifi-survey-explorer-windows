import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from survey_explorer.importing import parse_files
from survey_explorer.storage import Project,group_aps
from survey_explorer.analysis import estimate
root=Path(__file__).resolve().parents[1];paths=sorted(root.glob('wifi-survey*.csv'))
if not paths:
 print('No private survey files present; building without bundled demo data.');raise SystemExit(0)
(root/'demo').mkdir(exist_ok=True)
obs,reports=parse_files(paths);p=Project();summary=p.append(obs,reports);groups=group_aps(p.observations());summary['unique_bssids']=len(groups);summary['sessions']=len({o['session_id'] for o in obs});summary['date_range']=[min(o['timestamp_utc'] for o in obs),max(o['timestamp_utc'] for o in obs)];summary['source_hashes']={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in paths};summary['reimport']=p.append(obs,[]) ;summary['overlapping_bssids']=sum(len({o['source_file'] for o in rows})>1 for rows in groups.values())
# Precompute transparent baseline results for the demo; experimental fits remain user-triggered.
p.put_estimates({b:estimate(rows,False) for b,rows in groups.items()});p.save(root/'demo/supplied-surveys.wifiproject');p.close();(root/'demo/import-validation.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
