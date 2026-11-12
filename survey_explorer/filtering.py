"""Shared observation filtering used by the map, list, exports and analysis."""
def filter_observations(observations, criteria=None, search='', minimum=-150, maximum=10, date_from='', date_to='', names='All names'):
 criteria=criteria or {};tokens=search.casefold().split()
 matching={o['bssid'] for o in observations if all(t in (str(o.get('ssid',''))+' '+o['bssid']).casefold() for t in tokens)} if tokens else None
 result=[]
 for o in observations:
  if matching is not None and o['bssid'] not in matching:continue
  if any(value not in ('','All',None) and str(o.get(key,''))!=value for key,value in criteria.items()):continue
  if names=='Named only' and not o.get('ssid'):continue
  if names=='Hidden / unnamed' and o.get('ssid'):continue
  signal=o.get('rssi_dbm')
  if signal is None and (minimum>-150 or maximum<10):continue
  if signal is not None and not minimum<=signal<=maximum:continue
  date=(o.get('timestamp_utc') or '')[:10]
  if (date_from and (not date or date<date_from)) or (date_to and (not date or date>date_to)):continue
  result.append(o)
 return result
