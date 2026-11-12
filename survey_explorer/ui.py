"""Desktop shell. Background jobs communicate with widgets through signals."""
import sys,os,json,math,threading,statistics,hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from PySide6.QtCore import Qt,QObject,Signal,Slot,QThread,QUrl,QTimer
from PySide6.QtGui import QAction,QIcon,QPixmap
from PySide6.QtWidgets import *
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
class MapPage(QWebEnginePage):
 def javaScriptConsoleMessage(self,level,message,line,source):
  print(f"Map JS {line}: {message}",flush=True)
from . import __version__
from .importing import inspect,parse_files
from .storage import Project,group_aps
from .analysis import estimate,surface
from .filtering import filter_observations
from .maps import Cache,MapServer,coverage,download,DEFAULT_STYLE
from .exporting import csv_export,geojson_export,raster_export,image_uri,contour_features
ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
class Worker(QThread):
 progress=Signal(int,str);result=Signal(object);failed=Signal(str)
 def __init__(self,fn):super().__init__();self.fn=fn;self.cancelled=threading.Event()
 def run(self):
  try:self.result.emit(self.fn(self.progress.emit,self.cancelled.is_set))
  except Exception as e:self.failed.emit(str(e))
class Bridge(QObject):
 def __init__(self,window):super().__init__();self.window=window
 @Slot()
 def ready(self):QTimer.singleShot(200,self.window.publish)
 @Slot(str)
 def status(self,text):self.window.map_status.setText(text)
 @Slot(float,float)
 def cursor(self,lat,lon):self.window.coordinates.setText(f'{lat:.6f}, {lon:.6f} · Right-click to copy')
 @Slot(float,float)
 def copyCoordinate(self,lat,lon):QApplication.clipboard().setText(f'{lat:.7f}, {lon:.7f}');self.window.statusBar().showMessage('Coordinates copied',3000)
 @Slot(str)
 def observationsClicked(self,ids):self.window.inspect_observations(json.loads(ids))
 @Slot(str)
 def estimateClicked(self,bssid):self.window.select_bssid(bssid);self.window.tabs.setCurrentIndex(1)
class MappingDialog(QDialog):
 def __init__(self,name,headers,mapping,parent):
  super().__init__(parent);self.setWindowTitle('Map columns · '+name);layout=QFormLayout(self);self.boxes={}
  layout.addRow(QLabel('Identify required coordinates and BSSID. Signal analysis also needs RSSI.'))
  for key in ('latitude','longitude','bssid','rssi_dbm'):
   box=QComboBox();box.addItems(['(not available)']+headers)
   if mapping.get(key):box.setCurrentText(mapping[key])
   self.boxes[key]=box;layout.addRow(key,box)
  buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addRow(buttons)
 def mapping(self):return {k:(b.currentText() if b.currentIndex()>0 else None) for k,b in self.boxes.items()}
class Window(QMainWindow):
 def __init__(self):
  super().__init__();self.setWindowTitle('Wi-Fi Survey Explorer');self.resize(1540,920);self.setMinimumSize(1000,650);self.setWindowIcon(QIcon(str(ROOT/'assets/icon.ico')));self.setAcceptDrops(True)
  self.project=Project();self.path=None;self.dirty=False;self.obs=[];self.groups={};self.selected=None;self.current_surface=None;self.worker=None;self.generation=0;self.surface_worker=None;self.surface_timer=QTimer(self);self.surface_timer.setSingleShot(True);self.surface_timer.timeout.connect(self.generate_surface)
  cache_path=Path(os.environ.get('WIFI_CACHE_PATH',str(Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'WiFiSurveyExplorer'/'maps.sqlite')))
  if not cache_path.exists() and (ROOT/'demo/maps.sqlite').exists():
   import shutil
   cache_path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/'demo/maps.sqlite',cache_path)
  self.cache=Cache(cache_path);self.server=MapServer(ROOT/'assets',self.cache)
  self.web=QWebEngineView();self.web.setPage(MapPage(self.web));self.channel=QWebChannel();self.bridge=Bridge(self);self.channel.registerObject('bridge',self.bridge);self.web.page().setWebChannel(self.channel);self.setCentralWidget(self.web)
  self.actions={};toolbar=self.addToolBar('Workspace');toolbar.setMovable(False)
  for label,fn in [('Import',self.import_files),('Open Project',self.open_project),('Save Project',self.save_project),('Export',self.export_dialog),('Fit Survey',lambda:self.web.page().runJavaScript('fitAll()')),('Offline maps',self.offline_dialog),('Settings',self.settings),('Load demo',self.demo)]:
   action=QAction(label,self);action.triggered.connect(fn);toolbar.addAction(action);self.actions[label]=action
  self.actions['Load demo'].setEnabled((ROOT/'demo/supplied-surveys.wifiproject').exists() or any(ROOT.glob('wifi-survey*.csv')))
  for label,key in [('Import','Ctrl+I'),('Open Project','Ctrl+O'),('Save Project','Ctrl+S')]:self.actions[label].setShortcut(key)
  self.left=QDockWidget('ACCESS POINTS',self);self.left.setObjectName('APs');self.addDockWidget(Qt.LeftDockWidgetArea,self.left);panel=QWidget();vl=QVBoxLayout(panel);self.left.setWidget(panel)
  self.search=QLineEdit();self.search.setPlaceholderText('Filter names or BSSID (map + list)');self.search.textChanged.connect(self.filters_changed);vl.addWidget(self.search)
  self.sort=QComboBox();self.sort.addItems(['Strongest signal','Name','Observation count']);self.sort.currentIndexChanged.connect(self.refresh_list);vl.addWidget(self.sort)
  filters=QGroupBox('Filters - click to expand');filters.setCheckable(True);filters.setChecked(False);form=QFormLayout(filters)
  self.session=QComboBox();self.source=QComboBox();self.security=QComboBox();self.band=QComboBox();self.frequency=QComboBox();self.channel_filter=QComboBox();self.names=QComboBox();self.names.addItems(['All names','Named only','Hidden / unnamed'])
  for label,box in [('Session',self.session),('Source file',self.source),('Security',self.security),('Band',self.band),('Frequency (MHz)',self.frequency),('Channel',self.channel_filter),('Names',self.names)]:form.addRow(label,box);box.currentIndexChanged.connect(self.filters_changed)
  self.min_signal=QSpinBox();self.min_signal.setRange(-150,10);self.min_signal.setValue(-150);self.max_signal=QSpinBox();self.max_signal.setRange(-150,10);self.max_signal.setValue(10)
  for label,w in [('Minimum dBm',self.min_signal),('Maximum dBm',self.max_signal)]:form.addRow(label,w);w.valueChanged.connect(self.filters_changed)
  self.date_from=QLineEdit();self.date_to=QLineEdit()
  for label,w in [('From date',self.date_from),('Through date',self.date_to)]:w.setPlaceholderText('YYYY-MM-DD (UTC)');form.addRow(label,w);w.editingFinished.connect(self.filters_changed)
  for i in range(form.count()):form.itemAt(i).widget().setVisible(False)
  reset=QPushButton('Reset all filters');reset.clicked.connect(self.reset_filters);form.addRow(reset);reset.setVisible(False)
  filters.toggled.connect(lambda on:[form.itemAt(i).widget().setVisible(on) for i in range(form.count())]);vl.addWidget(filters)
  self.ap_list=QTreeWidget();self.ap_list.setHeaderLabels(['Access point / BSSID','Peak','Count']);self.ap_list.setColumnWidth(0,240);self.ap_list.setColumnWidth(1,50);self.ap_list.setAlternatingRowColors(True);self.ap_list.currentItemChanged.connect(self.ap_changed);self.ap_list.itemDoubleClicked.connect(self.focus_ap);vl.addWidget(self.ap_list)
  self.ap_count=QLabel('Import surveys or load the supplied demo.');vl.addWidget(self.ap_count)
  self.right=QDockWidget('INSPECTOR',self);self.right.setObjectName('Inspector');self.addDockWidget(Qt.RightDockWidgetArea,self.right);detail=QWidget();dv=QVBoxLayout(detail);self.right.setWidget(detail)
  self.title=QLabel('Explore your survey');self.title.setWordWrap(True);self.title.setStyleSheet('font-size:19px;font-weight:600;padding:8px 0');dv.addWidget(self.title)
  self.tabs=QTabWidget();self.details=QTextBrowser();self.evidence=QTextBrowser();self.measurements=QTableWidget();self.measurements.setColumnCount(5);self.measurements.setHorizontalHeaderLabels(['Time (UTC)','dBm','Latitude','Longitude','Source']);self.measurements.setEditTriggers(QAbstractItemView.NoEditTriggers);self.measurements.cellDoubleClicked.connect(self.measurement_detail)
  self.tabs.addTab(self.details,'AP details');self.tabs.addTab(self.evidence,'Estimate');self.tabs.addTab(self.measurements,'Measurements');dv.addWidget(self.tabs)
  self.mode=QComboBox();self.mode.addItems(['Measured signals','Interpolated signal surface']);self.mode.setCurrentIndex(1);self.mode.setToolTip('Automatically creates a signal surface for the selected AP where samples support interpolation. Reception is not the known transmitter location.');self.mode.currentIndexChanged.connect(self.request_surface);dv.addWidget(self.mode)
  buttons=QHBoxLayout();fit=QPushButton('Fit selected');fit.clicked.connect(lambda:self.web.page().runJavaScript('fitSelected()'));buttons.addWidget(fit);self.calculate=QPushButton('Estimate selected');self.calculate.clicked.connect(self.estimate_selected);buttons.addWidget(self.calculate);dv.addLayout(buttons)
  self.all_estimates=QPushButton('Estimate all visible APs');self.all_estimates.clicked.connect(self.estimate_all);dv.addWidget(self.all_estimates)
  self.note=QPlainTextEdit();self.note.setPlaceholderText('Project note for this BSSID');self.note.setMaximumHeight(70);dv.addWidget(self.note);self.bookmark=QCheckBox('Bookmark this AP');dv.addWidget(self.bookmark);save_note=QPushButton('Save note / bookmark');save_note.clicked.connect(self.save_note);dv.addWidget(save_note)
  self.map_status=QLabel('Drop one or more survey CSV files into the window.');self.map_status.setWordWrap(True);dv.addWidget(self.map_status)
  self.opacity=.65;self.contours=False;self.routes=False;self.experimental=True;self.theme='Dark';self.apply_theme()
  self.coordinates=QLabel();self.statusBar().addPermanentWidget(self.coordinates);self.statusBar().showMessage('Ready · recorded surveys only');self.resizeDocks([self.left,self.right],[370,390],Qt.Horizontal)
  menu=self.menuBar().addMenu('View');menu.addAction(self.left.toggleViewAction());menu.addAction(self.right.toggleViewAction());about_menu=self.menuBar().addMenu('About');about_action=about_menu.addAction('About Wi-Fi Survey Explorer');about_action.triggered.connect(self.show_about);self.web.setUrl(QUrl(self.server.base+'/index.html'))
  self.details.setPlainText('Import survey exports to explore measured reception.\n\nEach BSSID remains a separate AP, even when SSIDs match.\n\nTransmitter estimates are RSSI-based heuristics, not precise triangulation.\n\nLoad demo explores the supplied surveys without altering them.')
 def create_about_dialog(self):
  dialog=QDialog(self);dialog.setWindowTitle('About Wi-Fi Survey Explorer');dialog.setMinimumWidth(560)
  outer=QVBoxLayout(dialog);row=QHBoxLayout();outer.addLayout(row)
  photo=QLabel();photo.setObjectName('aboutAuthorPhoto');photo.setAlignment(Qt.AlignTop|Qt.AlignHCenter)
  pixmap=QPixmap(str(ROOT/'assets/about_author.jpg'))
  photo.setPixmap(pixmap.scaled(144,144,Qt.KeepAspectRatio,Qt.SmoothTransformation));photo.setFixedWidth(160);row.addWidget(photo)
  description=QLabel(f'<h2>Wi-Fi Survey Explorer</h2><p>Version {__version__} - Windows desktop</p><p>Explore recorded Wi-Fi surveys on a street map. Import and combine survey files, filter access points, inspect signal strength, generate per-AP reception surfaces and review approximate RSSI-based transmitter estimates.</p><p>This application analyses recordings; it does not scan Wi-Fi networks.</p><p><b>Copyright 2026 S. van Ingen</b><br>Written by S. van Ingen</p>')
  description.setObjectName('aboutDescription');description.setWordWrap(True);description.setMinimumWidth(350);row.addWidget(description,1)
  attribution=QLabel('Maps: OpenFreeMap, OpenMapTiles and OpenStreetMap contributors.<br>Built with Python, PySide6 / Qt, MapLibre, NumPy and SciPy.<br>Third-party libraries and resources retain their respective licences.')
  attribution.setWordWrap(True);outer.addWidget(attribution)
  buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.rejected.connect(dialog.reject);outer.addWidget(buttons)
  return dialog
 def show_about(self):
  self.create_about_dialog().exec()
 def apply_theme(self):
  dark=self.theme=='Dark';bg='#17212e' if dark else '#f4f7fa';fg='#e7eef7' if dark else '#1d2b3b';field='#223144' if dark else '#ffffff';border='#3a4b61' if dark else '#c5d0dc'
  self.setStyleSheet(f'QWidget{{font-family:Segoe UI;font-size:12px;color:{fg};}} QMainWindow,QDialog,QDockWidget,QToolBar{{background:{bg};}} QLineEdit,QComboBox,QSpinBox,QTextBrowser,QPlainTextEdit,QTreeWidget,QTableWidget{{background:{field};border:1px solid {border};border-radius:4px;padding:5px;selection-background-color:#246b88;}} QPushButton,QToolButton{{background:{field};border:1px solid {border};border-radius:5px;padding:8px 12px;}} QPushButton:hover,QToolButton:hover{{background:#38657b;}} QHeaderView::section,QTabBar::tab{{background:{field};padding:7px;}} QGroupBox{{border:1px solid {border};margin-top:12px;padding-top:10px;}} QStatusBar{{background:{bg};}} QMenuBar{{background:{bg};color:{fg};}} QMenuBar::item{{background:transparent;color:{fg};padding:6px 10px;}} QMenuBar::item:selected,QMenuBar::item:pressed{{background:#246b88;color:#ffffff;}} QMenu{{background:{field};color:{fg};border:1px solid {border};padding:5px;}} QMenu::item{{background:transparent;color:{fg};padding:8px 28px 8px 22px;}} QMenu::item:selected{{background:#246b88;color:#ffffff;}} QMenu::item:disabled{{color:#8797a6;}} QMenu::separator{{height:1px;background:{border};margin:5px 8px;}}')
 def job(self,label,fn,done):
  if self.worker and self.worker.isRunning():QMessageBox.information(self,'Processing','Please finish or cancel the current operation.');return False
  self.progress=QProgressDialog(label,'Cancel',0,100,self);self.progress.setWindowTitle('Wi-Fi Survey Explorer');self.progress.setWindowModality(Qt.WindowModal);self.progress.setMinimumDuration(0);self.progress.setAutoClose(False);self.progress.setAutoReset(False);self.progress.setValue(0)
  worker=Worker(fn);self.worker=worker;self.progress.canceled.connect(worker.cancelled.set);worker.progress.connect(lambda value,text:(self.progress.setValue(value),self.progress.setLabelText(text)))
  def success(value):
   was_cancelled=worker.cancelled.is_set();self.progress.canceled.disconnect();self.progress.close()
   if was_cancelled:self.statusBar().showMessage('Cancelled');return
   done(value)
  worker.result.connect(success);worker.failed.connect(lambda error:(self.progress.close(),QMessageBox.warning(self,'Operation stopped',error)));worker.finished.connect(lambda:self.statusBar().showMessage(f'{len(self.obs):,} observations · {len(self.groups):,} APs'));worker.start();return True
 def dragEnterEvent(self,event):
  if event.mimeData().hasUrls():event.acceptProposedAction()
 def dropEvent(self,event):self.import_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
 def import_files(self,paths=None):
  if not paths or isinstance(paths,bool):paths=QFileDialog.getOpenFileNames(self,'Import survey files','','Survey exports (*.csv *.tsv *.txt);;All files (*)')[0]
  if not paths:return
  mappings={}
  try:
   for path in paths:
    _,_,headers,mapping,_,_=inspect(path)
    if any(not mapping.get(k) for k in ('latitude','longitude','bssid','rssi_dbm')):
     dialog=MappingDialog(Path(path).name,headers,mapping,self)
     if dialog.exec()!=QDialog.Accepted:return
     mappings[str(path)]=dialog.mapping()
  except Exception as e:QMessageBox.warning(self,'Cannot read file',str(e));return
  self.job('Reading survey files',lambda p,c:parse_files(paths,mappings,p,c),self.review_import)
 def review_import(self,result):
  obs,reports=result;known={o['dedup_key'] for o in self.obs};unique=set();duplicate=0
  for o in obs:
   if o['dedup_key'] in known or o['dedup_key'] in unique:duplicate+=1
   else:unique.add(o['dedup_key'])
  dates=sorted(o['timestamp_utc'] for o in obs if o['timestamp_utc']);invalid=sum(len(r['invalid']) for r in reports)
  summary=f'Files: {len(reports)}\nRows read: {sum(r["rows"] for r in reports):,}\nValid plotted observations to add: {len(unique):,}\nUnique BSSIDs in input: {len({o["bssid"] for o in obs}):,}\nDuplicates to skip: {duplicate:,}\nInvalid / incomplete rows: {invalid:,}\nRows with warnings: {sum(len(r["warnings"]) for r in reports):,}\nDate range (UTC): {(dates[0]+" to "+dates[-1]) if dates else "unavailable"}'
  box=QMessageBox(self);box.setWindowTitle('Review import');box.setText(summary);box.setInformativeText('Import valid observations into the current project?');box.setDetailedText(json.dumps(reports,ensure_ascii=False,indent=2));box.setStandardButtons(QMessageBox.Yes|QMessageBox.No)
  if box.exec()==QMessageBox.Yes:QTimer.singleShot(50,lambda:self.job('Committing observations',lambda p,c:self.project.append(obs,reports,c),self.import_done))
 def import_done(self,result):self.dirty=True;self.reload();self.publish('all');self.statusBar().showMessage(f'Imported {result["added"]:,}; skipped {result["duplicates"]:,} duplicates; rejected {result["invalid"]:,}')
 def reload(self):
  self.obs=self.project.observations();self.current_surface=None;self.generation+=1
  for box,key in [(self.session,'session_id'),(self.source,'source_file'),(self.security,'security'),(self.band,'band'),(self.frequency,'frequency_mhz'),(self.channel_filter,'channel')]:
   previous=box.currentText();box.blockSignals(True);box.clear();box.addItem('All');box.addItems(sorted({str(o[key]) for o in self.obs if o.get(key)}));box.setCurrentText(previous if previous else 'All');box.blockSignals(False)
  self.refresh_list()
 def visible(self):
  criteria={key:box.currentText() for box,key in [(self.session,'session_id'),(self.source,'source_file'),(self.security,'security'),(self.band,'band'),(self.frequency,'frequency_mhz'),(self.channel_filter,'channel')]}
  return filter_observations(self.obs,criteria,self.search.text(),self.min_signal.value(),self.max_signal.value(),self.date_from.text().strip(),self.date_to.text().strip(),self.names.currentText())
 def reset_filters(self):
  boxes=(self.session,self.source,self.security,self.band,self.frequency,self.channel_filter,self.names)
  widgets=(*boxes,self.search,self.min_signal,self.max_signal,self.date_from,self.date_to)
  for widget in widgets:widget.blockSignals(True)
  for box in boxes:box.setCurrentIndex(0)
  self.search.clear();self.min_signal.setValue(-150);self.max_signal.setValue(10);self.date_from.clear();self.date_to.clear()
  for widget in widgets:widget.blockSignals(False)
  self.filters_changed()
 def focus_ap(self,item,column=0):
  if item:
   bssid=item.data(0,Qt.UserRole);self.select_bssid(bssid);self.web.page().runJavaScript('if(window.fitBssid)fitBssid('+json.dumps(bssid)+')')
 def filters_changed(self,*args):
  for w in (self.date_from,self.date_to):
   if w.text().strip():
    try:datetime.strptime(w.text().strip(),'%Y-%m-%d')
    except ValueError:self.map_status.setText('Date filter must use YYYY-MM-DD.');return
  self.generation+=1;self.current_surface=None;self.refresh_list();self.publish();self.request_surface()
 def refresh_list(self,*args):
  self.groups=group_aps(self.visible());search=self.search.text().casefold();self.ap_list.blockSignals(True);self.ap_list.clear();entries=[]
  for b,rows in self.groups.items():
   names=sorted({o['ssid'] for o in rows if o['ssid']});name=' / '.join(names) or '(Hidden / unnamed)';signals=[o['rssi_dbm'] for o in rows if o['rssi_dbm'] is not None];peak=max(signals) if signals else -999
   if search and search not in (name+' '+b).casefold():continue
   entries.append((name,b,rows,peak))
  entries.sort(key=lambda e:(-e[3] if self.sort.currentIndex()==0 else e[0].casefold() if self.sort.currentIndex()==1 else -len(e[2]),e[1]))
  selected_item=None;estimates=self.project.estimates()
  for name,b,rows,peak in entries:
   e=estimates.get(b+'|'+self.scope(),{});status=e.get('method','Not calculated');security=', '.join(sorted({o['security'] for o in rows if o['security']}))
   item=QTreeWidgetItem([name+'\n'+b+'\n'+security+' · '+e.get('confidence','Not estimated'),('—' if peak==-999 else f'{peak:g}'),str(len(rows))]);item.setData(0,Qt.UserRole,b);item.setToolTip(0,f'{security}\n{status}');self.ap_list.addTopLevelItem(item)
   if b==self.selected:selected_item=item
  self.ap_list.blockSignals(False);self.ap_count.setText(f'{len(entries):,} APs · {sum(len(r) for r in self.groups.values()):,} observations')
  if selected_item:self.ap_list.blockSignals(True);self.ap_list.setCurrentItem(selected_item);self.ap_list.blockSignals(False);self.show_details()
  elif self.selected:self.selected=None;self.show_details()
 def select_bssid(self,bssid):
  for i in range(self.ap_list.topLevelItemCount()):
   item=self.ap_list.topLevelItem(i)
   if item.data(0,Qt.UserRole)==bssid:self.ap_list.setCurrentItem(item);break
 def ap_changed(self,item,old):
  self.selected=item.data(0,Qt.UserRole) if item else None;self.generation+=1;self.current_surface=None;self.show_details();self.publish();self.request_surface()
 def scope(self):
  values=[b.currentText() for b in (self.session,self.source,self.security,self.band,self.frequency,self.channel_filter,self.names)]+[self.min_signal.value(),self.max_signal.value(),self.date_from.text(),self.date_to.text()]
  if values==['All','All','All','All','All','All','All names',-150,10,'','']:return 'all'
  return 'filtered-'+hashlib.sha256(json.dumps(values).encode()).hexdigest()[:16]
 def show_details(self):
  rows=self.groups.get(self.selected,[])
  if not rows:self.title.setText('Select an access point');self.details.clear();self.evidence.clear();self.measurements.setRowCount(0);return
  signals=[o['rssi_dbm'] for o in rows if o['rssi_dbm'] is not None];dates=sorted(o['timestamp_utc'] for o in rows if o['timestamp_utc']);gps=[o['gps_accuracy_m'] for o in rows if o['gps_accuracy_m'] is not None];strong=max((o for o in rows if o['rssi_dbm'] is not None),key=lambda o:o['rssi_dbm'],default=None)
  names=sorted({o['ssid'] or '(Hidden / unnamed)' for o in rows});self.title.setText(' / '.join(names));details={'BSSID':self.selected,'Observed names':names,'Observation count':len(rows),'UTC range':[dates[0],dates[-1]] if dates else [],'RSSI min / median / max dBm':[min(signals),statistics.median(signals),max(signals)] if signals else [],'Files':sorted({o['source_file'] for o in rows}),'Sessions':sorted({o['session_id'] for o in rows}),'Security':sorted({o['security'] for o in rows}),'Bands':sorted({o['band'] for o in rows}),'Frequencies MHz':sorted({o['frequency_mhz'] for o in rows if o['frequency_mhz'] is not None}),'GPS accuracy median / worst m':[statistics.median(gps),max(gps)] if gps else 'Unknown','Strongest measured position (not known AP position)':([strong['latitude'],strong['longitude']] if strong else None),'Advertised capabilities':sorted({o['raw'].get('capabilities','') for o in rows})}
  self.details.setPlainText('\n\n'.join(f'{k}\n{v}' for k,v in details.items()));e=self.project.estimates().get(self.selected+'|'+self.scope());self.evidence.setPlainText(json.dumps(e,indent=2,ensure_ascii=False) if e else 'No estimate for this selection.\n\nRSSI-based location estimation is approximate. Use Estimate selected. Filter a session to obtain a session-specific result.')
  self.display_measurements(rows);note=self.project.db.execute('SELECT note,bookmarked FROM notes WHERE bssid=?',(self.selected,)).fetchone();self.note.setPlainText(note[0] if note else '');self.bookmark.setChecked(bool(note and note[1]))
 def display_measurements(self,rows):
  self.table_rows=sorted(rows,key=lambda o:o.get('timestamp_utc') or '');self.measurements.setRowCount(len(rows))
  for i,o in enumerate(self.table_rows):
   for j,key in enumerate(('timestamp_utc','rssi_dbm','latitude','longitude','source_file')):self.measurements.setItem(i,j,QTableWidgetItem(str(o.get(key) if o.get(key) is not None else '—')))
 def measurement_detail(self,row,column):
  o=self.table_rows[row];box=QMessageBox(self);box.setWindowTitle('Measured observation');box.setText(f'{o["bssid"]}\n{o["latitude"]}, {o["longitude"]}\n{o["rssi_dbm"]} dBm');box.setDetailedText(json.dumps(o,indent=2,ensure_ascii=False));box.exec()
 def inspect_observations(self,ids):
  rows=[o for o in self.visible() if o['id'] in ids]
  if rows:self.display_measurements(rows);self.tabs.setCurrentIndex(2);self.map_status.setText(f'{len(rows)} overlapping measurements. Double-click a row for provenance.')
 def save_note(self):
  if self.selected:
   with self.project.db:self.project.db.execute('INSERT OR REPLACE INTO notes VALUES(?,?,?)',(self.selected,self.note.toPlainText(),int(self.bookmark.isChecked())))
   self.dirty=True
 def estimate_selected(self):
  if self.selected:self.run_estimates({self.selected:self.groups[self.selected]})
 def estimate_all(self):self.run_estimates(dict(self.groups))
 def run_estimates(self,groups):
  scope=self.scope();experimental=self.experimental
  def work(progress,cancel):
   result={}
   for i,(b,rows) in enumerate(groups.items()):result[b]=estimate(rows,experimental,cancel);progress(int(100*(i+1)/max(1,len(groups))),f'Estimating {i+1}/{len(groups)} APs')
   return result
  def done(results):self.project.put_estimates(results,scope);self.dirty=True;self.refresh_list();self.show_details();self.publish();self.tabs.setCurrentIndex(1)
  self.job('RSSI-based location estimation',work,done)
 def request_surface(self,*args):
  self.surface_timer.start(180)
 def generate_surface(self):
  if self.surface_worker and self.surface_worker.isRunning():
   self.surface_worker.cancelled.set();self.surface_timer.start(100);return
  if self.mode.currentIndex()==0 or not self.selected:
   self.current_surface=None;self.publish();return
  rows=list(self.groups.get(self.selected,[]));generation=self.generation
  if not rows:return
  self.map_status.setText('Calculating selected AP signal surface...')
  worker=Worker(lambda p,c:surface(rows,cancel=c));self.surface_worker=worker
  def done(result):
   if generation!=self.generation or self.mode.currentIndex()==0:return
   self.current_surface=None if result.get('reason') else result
   self.map_status.setText(result.get('reason') or result['method']);self.publish()
  worker.result.connect(done)
  worker.failed.connect(lambda error:self.map_status.setText(error) if generation==self.generation else None)
  worker.start()
 def publish(self,fit=None):
  obs=self.visible();selected=self.groups.get(self.selected,[])
  def feature(o,properties=None):return dict(type='Feature',geometry=dict(type='Point',coordinates=[o['longitude'],o['latitude']]),properties=properties or {k:o[k] for k in ('id','bssid','ssid','rssi_dbm','security','frequency_mhz','channel','band','timestamp_utc','gps_accuracy_m','source_file','session_id')})
  counts={b:len(rows) for b,rows in group_aps(obs).items()}
  state=dict(counts=counts,observations=[feature(o) for o in obs],selected=[feature(o) for o in selected],estimates=[],uncertainty=[],strongest=[],routes=[],fit=fit,opacity=self.opacity)
  signals=[o for o in selected if o['rssi_dbm'] is not None]
  if signals:state['strongest']=[feature(max(signals,key=lambda o:o['rssi_dbm']))]
  e=self.project.estimates().get(str(self.selected)+'|'+self.scope())
  if e and 'longitude' in e:
   state['estimates']=[feature(e,dict(bssid=self.selected,ssid=selected[0]['ssid'] if selected else '',method=e['method'],confidence=e['confidence'],uncertainty_m=e.get('uncertainty_m'),samples=e['samples'],kind='estimate'))];ring=[]
   for i in range(65):
    a=i*2*math.pi/64;dy=e['uncertainty_m']/111195;dx=dy/max(.001,math.cos(math.radians(e['latitude'])));ring.append([e['longitude']+dx*math.cos(a),e['latitude']+dy*math.sin(a)])
   state['uncertainty']=[dict(type='Feature',geometry=dict(type='Polygon',coordinates=[ring]),properties={})]
  if self.current_surface:
   state['surface']=dict(url=image_uri(self.current_surface),corners=self.current_surface['corners'])
   if self.contours:state['contours']=contour_features(self.current_surface)
  if self.routes:
   sessions=defaultdict(dict)
   for o in obs:
    if o.get('timestamp_utc') and o.get('session_id'):sessions[(o['source_hash'],o['session_id'])][o['timestamp_utc']]=o
   for samples in sessions.values():
    segment=[];last=None
    for t,o in sorted(samples.items()):
     dt=datetime.fromisoformat(t);coord=[o['longitude'],o['latitude']]
     if last:
      seconds=(dt-last[0]).total_seconds();distance=math.hypot((coord[0]-last[1][0])*111195*math.cos(math.radians(coord[1])),(coord[1]-last[1][1])*111195)
      if seconds>15 or distance>250:
       if len(segment)>1:state['routes'].append(dict(type='Feature',geometry=dict(type='LineString',coordinates=segment),properties={}))
       segment=[]
     segment.append(coord);last=(dt,coord)
    if len(segment)>1:state['routes'].append(dict(type='Feature',geometry=dict(type='LineString',coordinates=segment),properties={}))
  self.server.state=state;self.web.page().runJavaScript('if(window.refresh)refresh()')
 def unsaved(self):
  if not self.dirty:return True
  answer=QMessageBox.question(self,'Unsaved project','Save changes before continuing?',QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel)
  if answer==QMessageBox.Save:return self.save_project()
  return answer==QMessageBox.Discard
 def save_project(self):
  path=self.path or QFileDialog.getSaveFileName(self,'Save project','','Wi-Fi Survey project (*.wifiproject)')[0]
  if not path:return False
  try:
   self.project.set('preferences',dict(theme=self.theme,opacity=self.opacity,contours=self.contours,routes=self.routes,experimental=self.experimental));self.project.set('map_style',self.server.style_url);self.project.set('offline_packages',[p['name'] for p in self.cache.packs() if p['status']=='Complete']);self.project.save(path);self.path=path;self.dirty=False;self.setWindowTitle('Wi-Fi Survey Explorer · '+Path(path).name);return True
  except Exception as e:QMessageBox.warning(self,'Save failed',str(e));return False
 def open_project(self,path=None):
  if not self.unsaved():return
  if not path or isinstance(path,bool):path=QFileDialog.getOpenFileName(self,'Open project','','Wi-Fi Survey project (*.wifiproject *.sqlite)')[0]
  if not path:return
  try:
   import sqlite3
   source=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True);project=Project();source.backup(project.db);source.close()
   if project.get('format_version')!=1:raise ValueError('Unsupported project format')
   project.observations()
   self.project.close();self.project=project;self.path=str(path);self.dirty=False;self.selected=None
   for box in (self.session,self.source,self.security,self.band,self.frequency,self.channel_filter,self.names):box.blockSignals(True);box.setCurrentIndex(0);box.blockSignals(False)
   prefs=project.get('preferences',{})
   for key in ('theme','opacity','contours','routes','experimental'):
    if key in prefs:setattr(self,key,prefs[key])
   self.server.style_url=project.get('map_style',DEFAULT_STYLE);self.apply_theme();self.reload();self.publish('all');self.web.page().runJavaScript('if(window.basemap)basemap()');self.setWindowTitle('Wi-Fi Survey Explorer · '+Path(path).name)
  except Exception as e:QMessageBox.warning(self,'Open failed',str(e))
 def demo(self):
  demo=ROOT/'demo'/'supplied-surveys.wifiproject'
  if demo.exists():self.open_project(str(demo));self.path=None;self.setWindowTitle('Wi-Fi Survey Explorer · Demo (save a copy)')
  else:self.import_files([str(p) for p in ROOT.glob('wifi-survey*.csv')])
 def export_dialog(self):
  choices=['Normalised observations CSV','AP summary and estimates CSV','GeoJSON observations + estimates','Selected signal surface GeoTIFF','Map image PNG','Import reports JSON']
  choice,ok=QInputDialog.getItem(self,'Export','Export current filtered observations; estimates retain their scope.',choices,0,False)
  if not ok:return
  ext=['csv','csv','geojson','tif','png','json'][choices.index(choice)];path=QFileDialog.getSaveFileName(self,'Export','survey.'+ext,f'{ext.upper()} (*.{ext})')[0]
  if not path:return
  try:
   obs=self.visible();estimates=self.project.estimates()
   if choice==choices[0]:csv_export(path,obs)
   elif choice==choices[1]:
    rows=[]
    for b,group in group_aps(obs).items():
     rssi=[o['rssi_dbm'] for o in group if o['rssi_dbm'] is not None];base=dict(bssid=b,ssids=sorted({o['ssid'] for o in group}),count=len(group),strongest_rssi_dbm=max(rssi) if rssi else None)
     ee=[(k,e) for k,e in estimates.items() if k.split('|')[0]==b]
     for key,e in ee or [(b+'|all',{})]:rows.append(dict(base,estimate_scope=key.split('|')[-1],**{'estimated_'+k:v for k,v in e.items()}))
    csv_export(path,rows)
   elif choice==choices[2]:geojson_export(path,obs,{k:e for k,e in estimates.items() if k.split('|')[0] in self.groups})
   elif choice==choices[3]:
    if not self.current_surface:raise ValueError('Select an AP and generate an interpolated signal surface first.')
    raster_export(path,self.current_surface)
   elif choice==choices[4]:
    if not self.web.grab().save(path):raise ValueError('Image could not be saved')
   else:Path(path).write_text(json.dumps([json.loads(r[0]) for r in self.project.db.execute('SELECT report FROM imports')],ensure_ascii=False,indent=2),encoding='utf-8')
   self.statusBar().showMessage('Exported '+path,5000)
  except Exception as e:QMessageBox.warning(self,'Export failed',str(e))
 def settings(self):
  dialog=QDialog(self);dialog.setWindowTitle('Appearance and advanced analysis');form=QFormLayout(dialog);theme=QComboBox();theme.addItems(['Dark','Light']);theme.setCurrentText(self.theme);form.addRow('Theme',theme)
  opacity=QSlider(Qt.Horizontal);opacity.setRange(10,100);opacity.setValue(int(self.opacity*100));form.addRow('Surface opacity',opacity)
  contours=QCheckBox();contours.setChecked(self.contours);form.addRow('Signal contour lines',contours);routes=QCheckBox();routes.setChecked(self.routes);form.addRow('Credible session routes',routes);experimental=QCheckBox();experimental.setChecked(self.experimental);form.addRow('Experimental propagation model',experimental)
  style=QLineEdit(self.server.style_url);form.addRow('MapLibre style URL',style);form.addRow(QLabel('Default: OpenFreeMap Liberty, matching the Android app.\nNo credentials required. Custom providers must permit your use.\nAutomatic offline downloads are available for OpenFreeMap only.'))
  buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
  if dialog.exec()==QDialog.Accepted:
   changed=style.text()!=self.server.style_url;self.theme=theme.currentText();self.opacity=opacity.value()/100;self.contours=contours.isChecked();self.routes=routes.isChecked();self.experimental=experimental.isChecked();self.server.style_url=style.text().strip();self.apply_theme();self.dirty=True;self.publish()
   if changed:self.web.page().runJavaScript('basemap()')
 def offline_dialog(self):
  dialog=QDialog(self);dialog.setWindowTitle('Offline maps · explicit packages');dialog.resize(690,450);layout=QVBoxLayout(dialog);layout.addWidget(QLabel('Packages include street tiles, Liberty style, sprites and label fonts.\nCoverage follows 400 m neighbourhoods around observations, avoiding empty space\nbetween distant clusters. Maximum 2,800 tiles / 48 MB per download.'))
  offline=QCheckBox('Offline mode — prohibit all map network requests');offline.setChecked(self.server.offline);offline.toggled.connect(lambda value:setattr(self.server,'offline',value));layout.addWidget(offline)
  zoom=QSpinBox();zoom.setRange(8,16);zoom.setValue(14);row=QHBoxLayout();row.addWidget(QLabel('Maximum zoom (minimum 8)'));row.addWidget(zoom);layout.addLayout(row);packs=QListWidget();layout.addWidget(packs)
  def reload():
   packs.clear()
   for p in self.cache.packs():
    item=QListWidgetItem(f'{p["name"]} · {p["status"]} · {p["tiles"]} tiles · {p["bytes"]/1e6:.1f} MB');item.setData(Qt.UserRole,p['name']);packs.addItem(item)
  reload();buttons=QHBoxLayout();layout.addLayout(buttons)
  def start():
   if self.server.style_url!=DEFAULT_STYLE:QMessageBox.warning(dialog,'Provider policy','Automatic downloads are enabled only for the verified OpenFreeMap style.');return
   try:tiles=coverage(self.visible(),8,zoom.value())
   except Exception as e:QMessageBox.warning(dialog,'Coverage',str(e));return
   if not tiles:QMessageBox.information(dialog,'Coverage','Import observations first.');return
   if QMessageBox.question(dialog,'Download package',f'{len(tiles)} geographic tiles; roughly {len(tiles)*25/1000:.1f} MB plus fonts and sprites.\nHard limit: 48 MB. Continue?')!=QMessageBox.Yes:return
   name='Survey-z'+str(zoom.value())+'-'+hashlib.sha256(json.dumps(tiles).encode()).hexdigest()[:8];dialog.accept()
   self.job('Downloading offline map package',lambda p,c:download(self.cache,DEFAULT_STYLE,tiles,name,p,c),lambda pack:(self.map_status.setText(f'Offline package {pack["status"]}: {pack["name"]}'),self.web.page().runJavaScript('basemap()')))
  button=QPushButton('Download / retry coverage');button.clicked.connect(start);buttons.addWidget(button)
  def delete():
   item=packs.currentItem()
   if item and QMessageBox.question(dialog,'Delete map package','Delete this package and resources not used by other packages?')==QMessageBox.Yes:self.cache.delete(item.data(Qt.UserRole));reload()
  button=QPushButton('Delete selected');button.clicked.connect(delete);buttons.addWidget(button)
  button=QPushButton('Use cached maps offline');button.clicked.connect(lambda:(setattr(self.server,'offline',True),dialog.accept()));buttons.addWidget(button)
  layout.addWidget(QLabel('Cache: '+str(self.cache.path)+'\nShare this cache separately from survey projects when moving computers.'));dialog.finished.connect(lambda _:self.web.page().runJavaScript('basemap()'));dialog.exec()
 def closeEvent(self,event):
  self.surface_timer.stop()
  if self.surface_worker and self.surface_worker.isRunning():self.surface_worker.cancelled.set();self.surface_worker.wait(3000)
  if self.worker and self.worker.isRunning():self.worker.cancelled.set();QMessageBox.information(self,'Cancelling','The operation is stopping. Close again when it finishes.');event.ignore();return
  if not self.unsaved():event.ignore();return
  self.server.close();self.project.close();event.accept()
def main():
 app=QApplication(sys.argv);app.setApplicationName('Wi-Fi Survey Explorer');app.setOrganizationName('WiFiSurveyExplorer');window=Window();window.show()
 if '--demo' in sys.argv:QTimer.singleShot(800,window.demo)
 if '--smoke-test' in sys.argv:
  window.server.offline=True
  def finish():
   result=dict(window_visible=window.isVisible(),web_url=window.web.url().toString(),observations=len(window.obs),aps=len(window.groups))
   def received(value):
    result['map']=json.loads(value) if value else None;result['resource_errors']=window.server.errors
    target=Path(os.environ.get('WIFI_SMOKE_RESULT',str(ROOT/'smoke-result.json')));target.write_text(json.dumps(result,indent=2),encoding='utf-8');window.grab().save(str(target.with_suffix('.png')));window.dirty=False;window.close();app.quit()
   window.web.page().runJavaScript("JSON.stringify({loaded:map.isStyleLoaded(),tiles:map.areTilesLoaded(),rendered:map.queryRenderedFeatures().length,measurements:map.queryRenderedFeatures({layers:['points','clusters']}).length})",received)
  QTimer.singleShot(12000,finish)
 return app.exec()
