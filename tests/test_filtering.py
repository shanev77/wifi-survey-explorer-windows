from survey_explorer.filtering import filter_observations

def rows():
 return [dict(bssid='aa',ssid='Office',frequency_mhz=2412.0,channel=1.0,security='WPA2',rssi_dbm=-60,timestamp_utc='2026-11-12T01:00:00+00:00'),dict(bssid='aa',ssid='Renamed',frequency_mhz=5180.0,channel=36.0,security='WPA3',rssi_dbm=-80,timestamp_utc='2026-11-12T02:00:00+00:00'),dict(bssid='bb',ssid='',frequency_mhz=2412.0,channel=1.0,security='Open',rssi_dbm=None,timestamp_utc=None)]
def test_radio_and_security_filters_combine():
 assert len(filter_observations(rows(),{'frequency_mhz':'2412.0','security':'WPA2'}))==1
 assert len(filter_observations(rows(),{'channel':'36.0'}))==1
 assert not filter_observations(rows(),{'frequency_mhz':'2412.0','security':'WPA3'})
def test_name_search_keeps_ap_history_and_hidden_filter():
 assert len(filter_observations(rows(),search='office'))==2
 assert len(filter_observations(rows(),names='Hidden / unnamed'))==1
 assert len(filter_observations(rows(),names='Named only'))==2
 assert len(filter_observations(rows(),search='bb'))==1
 assert not filter_observations(rows(),search='unknown')
def test_signal_and_date_filter_missing_values():
 assert len(filter_observations(rows(),minimum=-70))==1
 assert len(filter_observations(rows(),date_from='2026-11-12',date_to='2026-11-12'))==2
 assert len(filter_observations(rows()))==3
