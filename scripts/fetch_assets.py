import urllib.request,pathlib
root=pathlib.Path(__file__).resolve().parents[1]/'assets'
for name in ['maplibre-gl.js','maplibre-gl.css']:
 url='https://unpkg.com/maplibre-gl@5.12.0/dist/'+name
 with urllib.request.urlopen(url,timeout=60) as r: (root/name).write_bytes(r.read())
with urllib.request.urlopen('https://unpkg.com/maplibre-gl@5.12.0/LICENSE.txt') as r:(root/'MAPLIBRE-LICENSE.txt').write_bytes(r.read())
print('Bundled MapLibre GL JS 5.12.0')
