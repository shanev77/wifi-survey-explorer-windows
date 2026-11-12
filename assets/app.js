let bridge=null,state={},ready=false,styleLoading=false,mapFailed=false,baseMapStarted=false,pendingPaint=false;
new QWebChannel(qt.webChannelTransport,c=>{bridge=c.objects.bridge;bridge.ready()});
const blank={version:8,sources:{},layers:[{id:'background',type:'background',paint:{'background-color':'#e4e9ed'}}]};
const map=new maplibregl.Map({container:'map',style:blank,center:[0,0],zoom:2,preserveDrawingBuffer:true,attributionControl:true});
map.addControl(new maplibregl.NavigationControl(),'top-right');map.addControl(new maplibregl.ScaleControl({unit:'metric'}));

const color=['interpolate',['linear'],['coalesce',['get','rssi_dbm'],-100],-100,'#5a47b4',-85,'#267bc6',-70,'#20b8aa',-55,'#f5ca41',-35,'#ee5845'];
const fc=features=>({type:'FeatureCollection',features});
function source(id,data,options={}){if(map.getSource(id))map.getSource(id).setData(data);else map.addSource(id,{type:'geojson',data,...options})}
function layer(obj){if(!map.getLayer(obj.id))map.addLayer(obj)}
function paint(){
 if(!map.isStyleLoaded()){pendingPaint=true;return;}pendingPaint=false;
 const observations=state.observations||[];source('observations',fc(observations),{cluster:true,clusterMaxZoom:15,clusterRadius:35});
 layer({id:'clusters',type:'circle',source:'observations',filter:['has','point_count'],paint:{'circle-radius':['step',['get','point_count'],14,100,20,1000,27],'circle-color':'#3e617b','circle-stroke-color':'#fff','circle-stroke-width':2}});
 layer({id:'points',type:'circle',source:'observations',filter:['!', ['has','point_count']],paint:{'circle-radius':4,'circle-color':color,'circle-opacity':.65,'circle-stroke-width':.5,'circle-stroke-color':'#fff'}});
 source('selected',fc(state.selected||[]));layer({id:'selected',type:'circle',source:'selected',paint:{'circle-radius':6,'circle-color':color,'circle-stroke-width':1.5,'circle-stroke-color':'#142333'}});
 source('routes',fc(state.routes||[]));layer({id:'routes',type:'line',source:'routes',paint:{'line-color':'#557c90','line-opacity':.4,'line-width':2}});
 source('uncertainty',fc(state.uncertainty||[]));layer({id:'uncertainty-fill',type:'fill',source:'uncertainty',paint:{'fill-color':'#ba53c9','fill-opacity':.09}});layer({id:'uncertainty-line',type:'line',source:'uncertainty',paint:{'line-color':'#a03bb0','line-width':2,'line-dasharray':[3,3]}});
 source('estimates',fc(state.estimates||[]));layer({id:'estimates',type:'circle',source:'estimates',paint:{'circle-color':'#d36cdb','circle-radius':10,'circle-stroke-color':'#42134e','circle-stroke-width':3}});
 source('strongest',fc(state.strongest||[]));layer({id:'strongest',type:'circle',source:'strongest',paint:{'circle-color':'#fff','circle-radius':9,'circle-stroke-color':'#e89319','circle-stroke-width':4}});
 if(map.getLayer('surface'))map.removeLayer('surface');if(map.getSource('surface'))map.removeSource('surface');
 if(state.surface){map.addSource('surface',{type:'image',url:state.surface.url,coordinates:state.surface.corners});map.addLayer({id:'surface',type:'raster',source:'surface',paint:{'raster-opacity':state.opacity??.65,'raster-fade-duration':0}},'selected')}
 source('contours',state.contours||fc([]));layer({id:'contours',type:'line',source:'contours',paint:{'line-color':'#293c4a','line-width':1,'line-opacity':.6}});
 if(state.fit){fit(state.fit==='selected'?(state.selected||[]):observations);state.fit=null;}
}
function fit(features,duration=650){if(!features.length)return;const bounds=new maplibregl.LngLatBounds();const ref=features[0].geometry.coordinates[0];features.forEach(f=>{let [x,y]=f.geometry.coordinates;x=ref+((x-ref+540)%360-180);bounds.extend([x,y])});map.fitBounds(bounds,{padding:65,maxZoom:18,duration})}
async function refresh(){try{state=await(await fetch('/state')).json();if(typeof clearHover==='function')clearHover();document.getElementById('legend').style.display=(state.observations||[]).length?'block':'none';if((state.observations||[]).length && !baseMapStarted){baseMapStarted=true;basemap()}else paint()}catch(e){if(bridge)bridge.status(String(e))}}
async function basemap(){if(!(state.observations||[]).length)return;baseMapStarted=true;if(styleLoading)return;styleLoading=true;mapFailed=false;try{let style=await(await fetch('/style')).json();fit(state.observations||[],0);map.setStyle(style);map.once('style.load',()=>{paint();document.getElementById('notice').style.display='none';if(bridge)bridge.status('Street map ready')})}catch(e){document.getElementById('notice').textContent='Street map unavailable. Open Offline maps to download coverage or select a completed package. Measurements still work.';if(bridge)bridge.status('Map unavailable: '+String(e))}finally{styleLoading=false}}
map.on('load',()=>{ready=true;refresh()});map.on('style.load',paint);map.on('idle',()=>{if(pendingPaint||!map.getSource('observations'))paint();if(baseMapStarted && !mapFailed && document.getElementById('notice').style.display!=='none'){document.getElementById('notice').style.display='none';if(bridge)bridge.status('Street map ready')}});
map.on('error',e=>{console.warn(String(e.error));if(!String(e.error).match(/503|fetch|Failed|AJAX|network/i))return;mapFailed=true;document.getElementById('notice').style.display='block';document.getElementById('notice').textContent='Some map resources are unavailable. Check connectivity or download an offline package for this area.';if(bridge)bridge.status('Map resource unavailable; survey data remains accessible')});
map.on('mousemove',e=>{if(bridge)bridge.cursor(e.lngLat.lat,e.lngLat.lng)});
map.on('contextmenu',e=>{if(bridge)bridge.copyCoordinate(e.lngLat.lat,e.lngLat.lng)});
map.on('click',async e=>{
 const layers=['estimates','strongest','selected','points','clusters'].filter(id=>map.getLayer(id));const found=map.queryRenderedFeatures(e.point,{layers});if(!found.length)return;const f=found[0];
 if(f.properties.cluster_id!==undefined){let z=await map.getSource('observations').getClusterExpansionZoom(f.properties.cluster_id);map.easeTo({center:f.geometry.coordinates,zoom:z});return}
 if(f.layer.id==='estimates'){if(bridge)bridge.estimateClicked(f.properties.bssid);return}
 const matched=(state.observations||[]).filter(o=>{let p=map.project(o.geometry.coordinates);return Math.hypot(p.x-e.point.x,p.y-e.point.y)<10});
 if(bridge)bridge.observationsClicked(JSON.stringify(matched.map(o=>o.properties.id)));
});
window.refresh=refresh;window.basemap=basemap;window.fitAll=()=>fit(state.observations||[]);window.fitSelected=()=>fit(state.selected||[]);
// Build hover content with textContent: network names are untrusted survey data.
const hoverPopup=new maplibregl.Popup({closeButton:false,closeOnClick:false,offset:15,maxWidth:'340px',className:'ap-hover'});
let hoverKey='',hoverToken=0;
function popupContent(entries,extra=''){
 const root=document.createElement('div');root.className='ap-tooltip';
 for(const entry of entries){
  const title=document.createElement('strong');title.textContent=entry.title;root.appendChild(title);
  for(const [label,value] of entry.rows){if(value===null||value===undefined||value==='')continue;const line=document.createElement('div');const key=document.createElement('b');key.textContent=label+': ';line.appendChild(key);line.appendChild(document.createTextNode(String(value)));root.appendChild(line)}
 }
 if(extra){const note=document.createElement('small');note.textContent=extra;root.appendChild(note)}return root;
}
function apEntry(f){
 const p=f.properties||{},ll=f.geometry.coordinates;
 if(p.kind==='estimate')return {title:p.ssid||'(Hidden / unnamed)',rows:[['BSSID',p.bssid],['Position','Estimated transmitter'],['Method',p.method],['Confidence',p.confidence],['Spatial samples',p.samples],['Approx. uncertainty',p.uncertainty_m==null?'':Math.round(p.uncertainty_m)+' m'],['Coordinates',ll[1].toFixed(6)+', '+ll[0].toFixed(6)]]};
 return {title:p.ssid||'(Hidden / unnamed)',rows:[['BSSID',p.bssid],['Signal',p.rssi_dbm==null?'Unavailable':p.rssi_dbm+' dBm'],['Radio',[p.band,p.frequency_mhz?`${p.frequency_mhz} MHz`:'',p.channel?`channel ${p.channel}`:''].filter(Boolean).join(' · ')],['Security',p.security||'Unknown'],['Observations',state.counts?.[p.bssid]],['Recorded',p.timestamp_utc?new Date(p.timestamp_utc).toISOString().slice(0,19).replace('T',' ')+' UTC':''],['GPS accuracy',p.gps_accuracy_m==null?'Unknown':Number(p.gps_accuracy_m).toFixed(1)+' m'],['Source',p.source_file],['Measured position',ll[1].toFixed(6)+', '+ll[0].toFixed(6)]]};
}
async function showHover(e){
 const layers=['estimates','strongest','selected','points','clusters'].filter(id=>map.getLayer(id));
 const hits=map.queryRenderedFeatures([[e.point.x-5,e.point.y-5],[e.point.x+5,e.point.y+5]],{layers});
 if(!hits.length){hoverKey='';hoverToken++;hoverPopup.remove();map.getCanvas().style.cursor='';return}
 const f=hits[0],p=f.properties;map.getCanvas().style.cursor='pointer';
 const key=f.layer.id+':'+(p.cluster_id??p.id??p.bssid);if(key===hoverKey){hoverPopup.setLngLat(e.lngLat);return}hoverKey=key;const token=++hoverToken;
 if(p.cluster_id!==undefined){
  const leaves=await map.getSource('observations').getClusterLeaves(p.cluster_id,100,0);if(token!==hoverToken)return;
  const unique=[...new Map(leaves.map(v=>[v.properties.bssid,v])).values()];
  const entries=unique.slice(0,4).map(v=>({title:v.properties.ssid||'(Hidden / unnamed)',rows:[['BSSID',v.properties.bssid],['Security',v.properties.security]]}));
  hoverPopup.setLngLat(e.lngLat).setDOMContent(popupContent(entries,`${p.point_count} measurements in this cluster. Showing up to 4 APs from the first 100 samples; click to zoom.`)).addTo(map);
 }else{
  const unique=[...new Map(hits.filter(v=>v.properties.cluster_id===undefined).map(v=>[v.properties.bssid,v])).values()];
  hoverPopup.setLngLat(e.lngLat).setDOMContent(popupContent([apEntry(f)],p.kind==='estimate'?'RSSI-based estimate, not a known location.':`${unique.length>1?unique.length+' APs overlap here; showing the foremost point. ':''}Measured reception location, not the known AP position. Click to inspect records.`)).addTo(map);
 }
}
map.on('mousemove',e=>showHover(e).catch(()=>hoverPopup.remove()));
function clearHover(){hoverKey='';hoverToken++;hoverPopup.remove();map.getCanvas().style.cursor=''}
map.getCanvas().addEventListener('mouseleave',clearHover);map.on('dragstart',clearHover);map.on('zoomstart',clearHover);

window.fitBssid=async bssid=>{await refresh();fit((state.observations||[]).filter(f=>f.properties.bssid===bssid))};
