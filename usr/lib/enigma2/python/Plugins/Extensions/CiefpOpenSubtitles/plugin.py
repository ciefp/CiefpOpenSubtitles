from __future__ import absolute_import
from __future__ import print_function

import os
import sys
import re
import json
import time
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from six.moves.urllib.parse import quote_plus, urlencode

from enigma import eTimer, getDesktop, gFont, eSize, ePoint, eServiceCenter
from Components.MenuList import MenuList
from Components.ActionMap import ActionMap, HelpableActionMap
from Components.Button import Button
from Components.ConfigList import ConfigListScreen
from Components.config import config, ConfigSubsection, ConfigText, \
    ConfigSelection, ConfigYesNo, ConfigInteger, ConfigPassword, getConfigListEntry, ConfigNothing
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.ScrollLabel import ScrollLabel
from Components.ServiceEventTracker import ServiceEventTracker
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.ChoiceBox import ChoiceBox
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Tools.BoundFunction import boundFunction
from Tools.Directories import fileExists, pathExists, createDir, resolveFilename, SCOPE_PLUGINS

# Versija plugina
PLUGIN_VERSION = "1.1"
PLUGIN_PATH = resolveFilename(SCOPE_PLUGINS, "Extensions/CiefpOpenSubtitles/")
CONFIG_DIR = "/etc/enigma2/ciefpopensubtitles/"

# Kreiraj config direktorijum ako ne postoji
if not pathExists(CONFIG_DIR):
    try:
        createDir(CONFIG_DIR)
    except:
        CONFIG_DIR = "/tmp/ciefpopensubtitles/"

# Simple translation function if _ is not defined
try:
    _
except NameError:
    def _(text):
        return text

class OpenSubtitlesConfig:
    """Klasa za čitanje/pisanje konfiguracijskih fajlova"""
    
    def __init__(self):
        self.api_key_file = os.path.join(CONFIG_DIR, "opensubtitles_apikey.txt")
        self.login_file = os.path.join(CONFIG_DIR, "opensubtitles_login.txt")
        self.settings_file = os.path.join(CONFIG_DIR, "settings.json")
        
    def read_api_key(self):
        """Čitanje API ključa iz fajla"""
        if fileExists(self.api_key_file):
            try:
                with open(self.api_key_file, 'r') as f:
                    content = f.read().strip()
                    # Može biti u formatu: apikey=xxxxxxxx ili samo xxxxxxxx
                    if '=' in content:
                        for line in content.split('\n'):
                            if line.startswith('apikey='):
                                return line.split('=', 1)[1].strip()
                    return content
            except:
                pass
        return ""
    
    def write_api_key(self, api_key):
        """Pisanje API ključa u fajl"""
        try:
            with open(self.api_key_file, 'w') as f:
                f.write(f"apikey={api_key}")
            return True
        except:
            return False
    
    def read_login(self):
        """Čitanje login podataka iz fajla"""
        username = ""
        password = ""
        if fileExists(self.login_file):
            try:
                with open(self.login_file, 'r') as f:
                    content = f.read().strip()
                    for line in content.split('\n'):
                        if line.startswith('user='):
                            username = line.split('=', 1)[1].strip()
                        elif line.startswith('pass='):
                            password = line.split('=', 1)[1].strip()
            except:
                pass
        return username, password
    
    def write_login(self, username, password):
        """Pisanje login podataka u fajl"""
        try:
            with open(self.login_file, 'w') as f:
                f.write(f"user={username}\n")
                f.write(f"pass={password}\n")
            return True
        except:
            return False
    
    def read_settings(self):
        """Čitanje postavki iz JSON fajla"""
        defaults = {
            'languages': ['sr', 'hr'],
            'save_path': '/media/hdd/subtitles/',
            'auto_download': False,
            'preferred_site': 'com',
            'search_timeout': 10,
            'download_delay': 20,
            'multi_lang_download': False,
            'priority_language': 'first'
        }
        
        if fileExists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    loaded = json.load(f)
                    # Merge sa podrazumevanim vrednostima
                    for key, value in defaults.items():
                        if key not in loaded:
                            loaded[key] = value
                    return loaded
            except:
                pass
        return defaults
    
    def write_settings(self, settings):
        """Pisanje postavki u JSON fajl"""
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
            return True
        except:
            return False

class OpenSubtitlesAPI:
    """Klasa za komunikaciju sa OpenSubtitles API-jem"""
    
    def __init__(self):
        self.config = OpenSubtitlesConfig()
        self.session = requests.Session()
        
        # Konfiguriši retry mehanizam
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        self.api_key = ""
        self.username = ""
        self.password = ""
        self.auth_token = ""
        self.load_credentials()
        
        # API endpoints
        self.ORG_BASE = "https://www.opensubtitles.org"
        self.COM_BASE = "https://api.opensubtitles.com/api/v1"
        
    def load_credentials(self):
        """Učitavanje kredencijala iz fajlova"""
        self.api_key = self.config.read_api_key()
        self.username, self.password = self.config.read_login()
    
    def search_org(self, query, languages=None):
        """Pretraga na OpenSubtitles.org"""
        if not languages:
            languages = ['srp', 'hrv']
            
        search_url = f"{self.ORG_BASE}/en/search2"
        params = {
            'MovieName': query,
            'action': 'search',
            'SubLanguageID': '|'.join(languages)
        }
        
        try:
            headers = {
                'User-Agent': 'Enigma2 OpenSubtitles Plugin v1.1'
            }
            
            response = self.session.get(search_url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Parsiranje HTML rezultata
            import re
            results = []
            
            # Pronađi sve rezultate prema tipičnoj HTML strukturi OpenSubtitles.org
            content = response.text
            
            # Pattern za pronalaženje naslova i linkova
            title_pattern = r'<a[^>]*class="[^"]*bnone[^"]*"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>'
            title_matches = re.findall(title_pattern, content)
            
            for href, title in title_matches:
                if '/en/subtitles/' in href:
                    # Proveri jezik
                    lang_pattern = r'<span[^>]*class="[^"]*flags[^"]*"[^>]*>([^<]+)</span>'
                    lang_match = re.search(lang_pattern, content)
                    language = lang_match.group(1) if lang_match else 'Unknown'
                    
                    results.append({
                        'title': title.strip(),
                        'url': f"{self.ORG_BASE}{href}",
                        'language': language.strip(),
                        'site': 'org'
                    })
            
            return results[:20]  # Ograniči na 20 rezultata
            
        except Exception as e:
            print(f"Error searching .org: {e}")
            return []

    def search_com(self, query, languages=None):
        print("[CiefpOpenSubtitles] SEARCH_COM STARTED")
        print(f"[CiefpOpenSubtitles] Query: '{query}'")

        if not self.api_key:
            print("[CiefpOpenSubtitles] ERROR: No API Key set!")
            return []

        settings = self.config.read_settings()
        if languages is None:
            languages = settings.get('languages', ['sr', 'hr'])

        print(f"[CiefpOpenSubtitles] Original languages from settings: {languages}")

        # MAPIRANJE .org → .com kodova jezika
        lang_map = {
            'srp': 'sr',
            'scc': 'sr',
            'hrv': 'hr',
            'bos': 'bs',
            'eng': 'en',
            'slv': 'sl',
        }

        converted_languages = []
        for lang in languages:
            lang_lower = lang.lower().strip()
            converted = lang_map.get(lang_lower, lang_lower[:2])
            if len(converted) == 2:
                converted_languages.append(converted)

        converted_languages = list(set(converted_languages))

        print(f"[CiefpOpenSubtitles] Converted for .com API: {converted_languages}")

        if not converted_languages:
            print("[CiefpOpenSubtitles] WARNING: No valid languages!")
            return []

        url = "https://api.opensubtitles.com/api/v1/subtitles"
        params = {
            'query': query,
            'languages': ','.join(converted_languages)
        }

        headers = {
            'Api-Key': self.api_key,
            'User-Agent': 'Enigma2 CiefpOpenSubtitles v1.1',
            'Accept': 'application/json'
        }

        print(f"[CiefpOpenSubtitles] Sending GET request to: {url}")
        print(f"[CiefpOpenSubtitles] Params: {params}")

        try:
            response = self.session.get(url, params=params, headers=headers, timeout=15)
            print(f"[CiefpOpenSubtitles] Response status: {response.status_code}")

            if response.status_code == 401:
                print("[CiefpOpenSubtitles] ERROR: Invalid API Key!")
                return []
            elif response.status_code == 429:
                print("[CiefpOpenSubtitles] ERROR: Rate limit exceeded!")
                return []

            response.raise_for_status()
            data = response.json()

            total_count = data.get('total_count', 0)
            print(f"[CiefpOpenSubtitles] Found {total_count} subtitles total")

            results = []
            for item in data.get('data', []):
                attr = item['attributes']
                files = attr.get('files', [])
                if not files:
                    continue
                
                # Proveri da li je serija
                parent_title = attr.get('feature_details', {}).get('parent_title', '')
                is_series = bool(parent_title)
                
                results.append({
                    'title': attr.get('release_name') or attr.get('feature_details', {}).get('movie_name', 'Unknown'),
                    'language': attr['language'],
                    'downloads': attr.get('download_count', 0),
                    'uploader': attr.get('uploader', {}).get('name', 'Unknown'),
                    'file_id': files[0]['file_id'],
                    'rating': attr.get('ratings', 0.0),
                    'fps': attr.get('fps', 0),
                    'hd': attr.get('hd', False),
                    'hearing_impaired': attr.get('hearing_impaired', False),
                    'is_series': is_series,
                    'series_name': parent_title if is_series else '',
                    'season': attr.get('feature_details', {}).get('season_number'),
                    'episode': attr.get('feature_details', {}).get('episode_number'),
                    'release_info': attr.get('release', ''),
                    'year': attr.get('feature_details', {}).get('year')
                })

            results.sort(key=lambda x: x['downloads'], reverse=True)
            print(f"[CiefpOpenSubtitles] Returning {len(results)} parsed results")
            return results

        except Exception as e:
            print(f"[CiefpOpenSubtitles] Request failed: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def search_series_com(self, query, season=None, episode=None, languages=None):
        """Pretraga titlova za serije"""
        print(f"[CiefpOpenSubtitles] SEARCH_SERIES_COM: {query} S{season}E{episode}")
        
        if not self.api_key:
            return []
        
        settings = self.config.read_settings()
        if languages is None:
            languages = settings.get('languages', ['sr', 'hr'])
        
        # Konvertuj jezike
        lang_map = {
            'srp': 'sr', 'scc': 'sr', 'hrv': 'hr', 
            'bos': 'bs', 'eng': 'en', 'slv': 'sl'
        }
        
        converted_languages = []
        for lang in languages:
            lang_lower = lang.lower().strip()
            converted = lang_map.get(lang_lower, lang_lower[:2])
            if len(converted) == 2:
                converted_languages.append(converted)
        
        converted_languages = list(set(converted_languages))
        
        if not converted_languages:
            return []
        
        # Kreiraj query za seriju
        search_query = query
        if season is not None:
            search_query += f" S{season:02d}"
            if episode is not None:
                search_query += f"E{episode:02d}"
        
        url = "https://api.opensubtitles.com/api/v1/subtitles"
        params = {
            'query': search_query,
            'languages': ','.join(converted_languages),
            'type': 'episode'
        }
        
        headers = {
            'Api-Key': self.api_key,
            'User-Agent': 'Enigma2 CiefpOpenSubtitles v1.1',
            'Accept': 'application/json'
        }
        
        try:
            response = self.session.get(url, params=params, headers=headers, timeout=15)
            print(f"[CiefpOpenSubtitles] Series search status: {response.status_code}")
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            results = []
            
            for item in data.get('data', []):
                attr = item['attributes']
                files = attr.get('files', [])
                if not files:
                    continue
                
                parent_title = attr.get('feature_details', {}).get('parent_title', '')
                parent_imdb_id = attr.get('feature_details', {}).get('parent_imdb_id')
                
                season_num = attr.get('feature_details', {}).get('season_number')
                episode_num = attr.get('feature_details', {}).get('episode_number')
                
                results.append({
                    'title': attr.get('release_name') or attr.get('feature_details', {}).get('movie_name', 'Unknown'),
                    'language': attr['language'],
                    'downloads': attr.get('download_count', 0),
                    'uploader': attr.get('uploader', {}).get('name', 'Unknown'),
                    'file_id': files[0]['file_id'],
                    'rating': attr.get('ratings', 0.0),
                    'fps': attr.get('fps', 0),
                    'hd': attr.get('hd', False),
                    'hearing_impaired': attr.get('hearing_impaired', False),
                    'is_series': bool(parent_title or parent_imdb_id),
                    'series_name': parent_title or query,
                    'season': season_num,
                    'episode': episode_num,
                    'release_info': attr.get('release', ''),
                    'year': attr.get('feature_details', {}).get('year')
                })
            
            results.sort(key=lambda x: x['downloads'], reverse=True)
            print(f"[CiefpOpenSubtitles] Found {len(results)} series results")
            return results
            
        except Exception as e:
            print(f"[CiefpOpenSubtitles] Series search error: {e}")
            return []
    
    def search_multiple_languages(self, query, languages=None):
        """Pretraga za više jezika odjednom"""
        if not languages:
            settings = self.config.read_settings()
            languages = settings.get('languages', ['sr', 'hr'])
        
        all_results = []
        
        # Ako je 'all', pretražujemo sve poznate jezike
        if 'all' in languages:
            languages = ['sr', 'hr', 'bs', 'sl', 'en', 'srp', 'hrv', 'bos', 'slv', 'eng']
        
        print(f"[DEBUG] Multi-language search for: {languages}")
        
        for lang in languages:
            lang_results = self.search_com(query, [lang])
            for result in lang_results:
                result['searched_language'] = lang
            all_results.extend(lang_results)
        
        # Sortiraj po downloads
        all_results.sort(key=lambda x: x.get('downloads', 0), reverse=True)
        
        return all_results

    def download_org(self, url, delay=20):
        """Preuzimanje sa .org (kroz .com redirekciju)"""
        try:
            headers = {'User-Agent': 'Enigma2 CiefpOpenSubtitles Plugin v1.1'}
            response = self.session.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            import re
            
            content = response.text
            
            download_patterns = [
                r'href="(/en/subtitleserve[^"]+)"',
                r'href="(https://www.opensubtitles.com/download/[^"]+)"',
                r'data-url="([^"]+)"',
                r'action="([^"]+download[^"]+)"'
            ]
            
            download_link = None
            for pattern in download_patterns:
                match = re.search(pattern, content)
                if match:
                    download_link = match.group(1)
                    if not download_link.startswith('http'):
                        download_link = f"{self.ORG_BASE}{download_link}"
                    break
            
            if not download_link:
                return None
            
            response = self.session.get(download_link, headers=headers, timeout=30)
            response.raise_for_status()
            
            if delay > 0:
                time.sleep(delay)
            
            content = response.text
            
            srt_patterns = [
                r'href="([^"]+\.srt)"',
                r'<a[^>]*href="([^"]+)"[^>]*>.*Download.*</a>',
                r'download_link.*?href="([^"]+)"'
            ]
            
            final_link = None
            for pattern in srt_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    final_link = match.group(1)
                    if not final_link.startswith('http'):
                        if final_link.startswith('/'):
                            final_link = f"https://www.opensubtitles.com{final_link}"
                        else:
                            final_link = f"https://www.opensubtitles.com/{final_link}"
                    break
            
            if final_link:
                file_response = self.session.get(final_link, headers=headers, timeout=30)
                file_response.raise_for_status()
                
                if file_response.content[:4] == b'1\r\n0' or 'subrip' in str(file_response.content[:100]).lower():
                    return file_response.content
                elif b'WEBVTT' in file_response.content[:100]:
                    return self.convert_vtt_to_srt(file_response.content)
            
            return None
            
        except Exception as e:
            print(f"Error downloading from .org: {e}")
            return None

    def download_com(self, file_id, filename):
        print(f"[DEBUG] Starting download for file_id: {file_id}")
        
        if not self.api_key:
            print("[DEBUG] No API key!")
            return False

        headers = {
            'Api-Key': self.api_key,
            'Content-Type': 'application/json',
            'User-Agent': 'Enigma2 CiefpOpenSubtitles v1.1',
            'Accept': 'application/json'
        }

        data = {
            "file_id": int(file_id),
            "sub_format": "srt"
        }

        try:
            print(f"[DEBUG] POST to {self.COM_BASE}/download")
            response = requests.post(f"{self.COM_BASE}/download", 
                                   headers=headers, 
                                   json=data, 
                                   timeout=15)
            print(f"[DEBUG] Response status: {response.status_code}")
            
            if response.status_code != 200:
                print(f"[DEBUG] Error response: {response.text[:200]}")
                return False
                
            response_data = response.json()
            print(f"[DEBUG] Response keys: {list(response_data.keys())}")
            
            if 'link' in response_data:
                download_link = response_data['link']
                print(f"[DEBUG] Got download link: {download_link[:100]}...")
                
                sub_response = requests.get(download_link, timeout=30)
                sub_response.raise_for_status()
                
                content = sub_response.content
                
                if content[:2] == b'PK':  # ZIP
                    from io import BytesIO
                    from zipfile import ZipFile
                    try:
                        zipfile = ZipFile(BytesIO(content))
                        srt_files = [f for f in zipfile.namelist() if f.lower().endswith('.srt')]
                        if srt_files:
                            srt_data = zipfile.read(srt_files[0])
                            return srt_data, filename
                        else:
                            first_file = zipfile.namelist()[0]
                            srt_data = zipfile.read(first_file)
                            return srt_data, filename
                    except Exception as e:
                        print(f"[DEBUG] ZIP extraction error: {e}")
                        return content, filename
                else:
                    return content, filename
                    
            elif 'file_name' in response_data:
                download_link = response_data.get('download_link') or response_data.get('link')
                if download_link:
                    sub_response = requests.get(download_link, timeout=30)
                    sub_response.raise_for_status()
                    return sub_response.content, filename
                    
            print("[DEBUG] No download link found in response")
            return False
            
        except Exception as e:
            print(f"[DEBUG] Download error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def convert_vtt_to_srt(self, vtt_content):
        """Konvertuje VTT format u SRT format"""
        try:
            lines = vtt_content.decode('utf-8', errors='ignore').split('\n')
            srt_lines = []
            counter = 1
            i = 0
            
            while i < len(lines):
                line = lines[i].strip()
                if line == 'WEBVTT' or line == '' or '-->' not in line:
                    i += 1
                    continue
                
                if '-->' in line:
                    time_parts = line.split(' --> ')
                    if len(time_parts) == 2:
                        start_time = time_parts[0].replace('.', ',')
                        end_time = time_parts[1].split(' ')[0].replace('.', ',')
                        
                        srt_lines.append(str(counter))
                        srt_lines.append(f"{start_time} --> {end_time}")
                        
                        i += 1
                        text_lines = []
                        while i < len(lines) and lines[i].strip() != '' and '-->' not in lines[i]:
                            text_lines.append(lines[i].strip())
                            i += 1
                        
                        if text_lines:
                            srt_lines.append('\n'.join(text_lines))
                            srt_lines.append('')
                            counter += 1
                else:
                    i += 1
            
            return '\n'.join(srt_lines).encode('utf-8')
        except:
            return vtt_content

class OpenSubtitlesConfigScreen(ConfigListScreen, Screen):
    """Ekran za konfiguraciju plugina"""
    
    skin = """
    <screen position="center,center" size="1600,800" title="OpenSubtitles Configuration">
    <widget name="config" position="50,50" size="1100,550" scrollbarMode="showOnDemand" />
    
    <!-- Dugmad - pomereni niže da ne preklapaju listu -->
    <widget source="key_red" render="Label" position="50,750" size="160,50" backgroundColor="#9f1313" foregroundColor="white" font="Regular;28" halign="center" valign="center" />
    <widget source="key_green" render="Label" position="230,750" size="160,50" backgroundColor="#1f771f" foregroundColor="white" font="Regular;28" halign="center" valign="center" />
    <widget source="key_yellow" render="Label" position="410,750" size="160,50" backgroundColor="#a08500" foregroundColor="white" font="Regular;28" halign="center" valign="center" />
    <widget source="key_blue" render="Label" position="590,750" size="160,50" backgroundColor="#18188b" foregroundColor="white" font="Regular;28" halign="center" valign="center" />
    
    <!-- Slika sa desne strane -->
    <widget name="background"
            position="1200,0" size="400,800"
            pixmap="/usr/lib/enigma2/python/Plugins/Extensions/CiefpOpenSubtitles/background.png"
            zPosition="0" />
    </screen>
    """
    
    def __init__(self, session, plugin=None):
        Screen.__init__(self, session)
        self.session = session
        
        if plugin is None:
            from Plugins.Extensions.CiefpOpenSubtitles.plugin import opensubtitles_plugin
            self.plugin = opensubtitles_plugin
        else:
            self.plugin = plugin
        
        self.config_obj = OpenSubtitlesConfig()
        self.settings = self.config_obj.read_settings()
        
        ConfigListScreen.__init__(self, [], session=session)
        self["config"].l.setItemHeight(40)  # ili 35, 45 – zavisi od tvoje želje
        
        self["key_red"] = StaticText("Exit")
        self["key_green"] = StaticText("Save")
        self["key_yellow"] = StaticText("API/Login")
        self["key_blue"] = StaticText("Select")
        self["background"] = Pixmap()
        
        self["actions"] = ActionMap(["SetupActions", "ColorActions"],
        {
            "cancel": self.keyCancel,
            "red": self.keyCancel,
            "green": self.keySave,
            "yellow": self.editCredentials,
            "blue": self.keyOK,
            "ok": self.keyOK,
        }, -2)
        
        self.createSetup()
        self.onLayoutFinish.append(self.layoutFinished)
    
    def layoutFinished(self):
        self.setTitle("OpenSubtitles Configuration v1.1")
    
    def createSetup(self):
        """Kreiraj listu konfiguracija"""
        self.list = []
        
        site_choices = [("com", "OpenSubtitles.com (API Key)"), ("org", "OpenSubtitles.org (Login)")]
        self.site_choice = ConfigSelection(choices=site_choices, default=self.settings.get('preferred_site', 'com'))
        self.list.append(getConfigListEntry("Preferred site:", self.site_choice))
        
        current_languages = self.settings.get('languages', ['sr', 'hr'])
        if isinstance(current_languages, list):
            current_languages_str = ','.join(current_languages)
        else:
            current_languages_str = str(current_languages)
        
        self.languages = ConfigText(default=current_languages_str, fixed_size=False)
        self.list.append(getConfigListEntry("Languages (comma separated):", self.languages))
        
        self.language_help = ConfigNothing()
        self.list.append(getConfigListEntry("Quick select: sr,hr,en or srp,hrv,eng", self.language_help))
        
        self.save_path = ConfigText(default=self.settings.get('save_path', '/media/hdd/subtitles/'), fixed_size=False)
        self.list.append(getConfigListEntry("Save path:", self.save_path))
        
        self.auto_download = ConfigYesNo(default=self.settings.get('auto_download', False))
        self.list.append(getConfigListEntry("Auto download:", self.auto_download))
        
        self.multi_lang_download = ConfigYesNo(default=self.settings.get('multi_lang_download', False))
        self.list.append(getConfigListEntry("Multi-language download:", self.multi_lang_download))
        
        self.download_delay = ConfigInteger(default=self.settings.get('download_delay', 20), limits=(0, 60))
        self.list.append(getConfigListEntry("Download delay (seconds):", self.download_delay))
        
        self.priority_language = ConfigSelection(
            choices=[("first", "Download first found"), ("all", "Try all languages")],
            default=self.settings.get('priority_language', 'first')
        )
        self.list.append(getConfigListEntry("Language priority:", self.priority_language))
        
        self["config"].list = self.list
        self["config"].l.setList(self.list)
    
    def editCredentials(self):
        """Otvaranje ekrana za editovanje kredencijala"""
        self.session.open(OpenSubtitlesCredentialsScreen, self.plugin)
    
    def keyOK(self):
        """Plavo dugme - Select / Edit"""
        current = self["config"].getCurrent()
        if current:
            if current[1] == self.languages:
                self.session.openWithCallback(
                    self.VirtualKeyBoardCallback,
                    VirtualKeyBoard,
                    title="Enter languages (comma separated)\nExamples: sr,hr,en or srp,hrv,eng",
                    text=current[1].value
                )
            elif current[1] == self.save_path:
                self.session.openWithCallback(
                    self.VirtualKeyBoardCallback,
                    VirtualKeyBoard,
                    title="Enter save directory path",
                    text=current[1].value
                )
            elif current[1] == self.language_help:
                help_text = """LANGUAGE CODES HELP:

Common codes:
• sr, hr, bs, sl, en (2-letter codes for OpenSubtitles.com)
• srp, hrv, bos, slv, eng (3-letter codes for OpenSubtitles.org)

Examples:
• Single: sr
• Multiple: sr,hr
• Multiple: srp,hrv,eng
• All: all (will search all available)

Note: Use commas without spaces for best results."""
                self.session.open(MessageBox, help_text, MessageBox.TYPE_INFO)
    
    def VirtualKeyBoardCallback(self, callback=None):
        """Callback iz virtuelne tastature"""
        if callback is not None:
            current = self["config"].getCurrent()
            if current:
                if current[1] == self.languages:
                    self.languages.setValue(callback)
                elif current[1] == self.save_path:
                    self.save_path.setValue(callback)
    
    def keySave(self):
        """Zeleno dugme - Save"""
        languages_input = self.languages.value.strip()
        if languages_input.lower() == 'all':
            languages_list = ['all']
        else:
            languages_list = [lang.strip() for lang in languages_input.split(',') if lang.strip()]
        
        if not languages_list:
            self.session.open(MessageBox, "Please enter at least one language code!", MessageBox.TYPE_ERROR)
            return
        
        self.settings['preferred_site'] = self.site_choice.value
        self.settings['languages'] = languages_list
        self.settings['save_path'] = self.save_path.value
        self.settings['auto_download'] = self.auto_download.value
        self.settings['multi_lang_download'] = self.multi_lang_download.value
        self.settings['download_delay'] = self.download_delay.value
        self.settings['priority_language'] = self.priority_language.value
        
        if self.save_path.value and not pathExists(self.save_path.value):
            try:
                createDir(self.save_path.value)
            except:
                self.session.open(MessageBox, 
                                "Cannot create save directory!", 
                                MessageBox.TYPE_ERROR)
        
        if self.config_obj.write_settings(self.settings):
            self.plugin.api.config = self.config_obj
            self.close(True)
        else:
            self.session.open(MessageBox, 
                            "Error saving configuration!", 
                            MessageBox.TYPE_ERROR)
    
    def keyCancel(self):
        """Crveno dugme - Exit"""
        self.close(False)

class OpenSubtitlesCredentialsScreen(Screen):
    """Ekran za editovanje API ključa i login podataka"""
    
    skin = """
    <screen position="center,center" size="800,600" title="OpenSubtitles Credentials">
        <widget name="info" position="10,10" size="780,50" font="Regular;24" halign="center" valign="center" />
        <widget source="key_red" render="Label" position="50,80" size="160,50" backgroundColor="#9f1313" foregroundColor="white" font="Regular;24" halign="center" valign="center" />
        <widget source="key_green" render="Label" position="230,80" size="160,50" backgroundColor="#1f771f" foregroundColor="white" font="Regular;24" halign="center" valign="center" />
        <widget source="key_yellow" render="Label" position="410,80" size="160,50" backgroundColor="#a08500" foregroundColor="white" font="Regular;24" halign="center" valign="center" />
        <widget source="key_blue" render="Label" position="590,80" size="160,50" backgroundColor="#18188b" foregroundColor="white" font="Regular;24" halign="center" valign="center" />
        <widget name="status" position="50,150" size="700,400" font="Regular;22" valign="center" />
    </screen>
    """
    
    def __init__(self, session, plugin):
        Screen.__init__(self, session)
        self.session = session
        self.plugin = plugin
        
        self["key_red"] = StaticText("Exit")
        self["key_green"] = StaticText("API Key")
        self["key_yellow"] = StaticText("Login")
        self["key_blue"] = StaticText("Back")
        self["info"] = Label("Edit API Key or Login credentials")
        self["status"] = Label("")
        
        self["actions"] = ActionMap(["ColorActions", "SetupActions"],
        {
            "red": self.close,
            "green": self.editApiKey,
            "yellow": self.editLogin,
            "blue": self.close,
            "cancel": self.close,
        }, -2)
        
        self.config_obj = OpenSubtitlesConfig()
        
        self.onLayoutFinish.append(self.updateStatus)
    
    def updateStatus(self):
        """Ažuriraj statusnu poruku"""
        api_key = self.config_obj.read_api_key()
        username, password = self.config_obj.read_login()
        
        status_text = "Current settings:\n\n"
        
        if api_key:
            masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else api_key
            status_text += f"API Key: {masked_key}\n"
        else:
            status_text += "API Key: Not set\n"
        
        status_text += "\n"
        
        if username:
            status_text += f"Username: {username}\n"
            status_text += "Password: ********"
        else:
            status_text += "Username: Not set\n"
            status_text += "Password: Not set"
        
        status_text += "\n\n"
        status_text += "Instructions:\n"
        status_text += "• GREEN: Edit API Key\n"
        status_text += "• YELLOW: Edit Login\n"
        status_text += "• RED/BLUE: Exit"
        
        self["status"].setText(status_text)
    
    def editApiKey(self):
        """Editovanje API ključa"""
        current_key = self.config_obj.read_api_key()
        self.session.openWithCallback(
            self.apiKeyCallback,
            VirtualKeyBoard,
            title="Enter OpenSubtitles.com API Key",
            text=current_key
        )
    
    def apiKeyCallback(self, callback=None):
        """Callback za API ključ"""
        if callback is not None and callback.strip():
            if self.config_obj.write_api_key(callback.strip()):
                self.plugin.api.api_key = callback.strip()
                self.updateStatus()
                self["status"].setText("API Key saved successfully!")
                self.status_timer = eTimer()
                self.status_timer.callback.append(self.restoreStatus)
                self.status_timer.start(3000, True)
            else:
                self["status"].setText("Error saving API Key!")
    
    def restoreStatus(self):
        """Vrati originalni status tekst"""
        self.updateStatus()
    
    def editLogin(self):
        """Editovanje login podataka"""
        username, password = self.config_obj.read_login()
        
        self.session.openWithCallback(
            lambda username_cb: self.usernameCallback(username_cb, password),
            VirtualKeyBoard,
            title="Enter OpenSubtitles.org Username",
            text=username
        )
    
    def usernameCallback(self, username_callback=None, current_password=""):
        """Callback za username"""
        if username_callback is not None:
            self.session.openWithCallback(
                lambda password_cb: self.passwordCallback(username_callback, password_cb),
                VirtualKeyBoard,
                title="Enter OpenSubtitles.org Password",
                text=current_password
            )
    
    def passwordCallback(self, username, password_callback=None):
        """Callback za password"""
        if password_callback is not None:
            if self.config_obj.write_login(username.strip(), password_callback.strip()):
                self.plugin.api.username = username.strip()
                self.plugin.api.password = password_callback.strip()
                self.updateStatus()
                self["status"].setText("Login credentials saved successfully!")
                self.status_timer = eTimer()
                self.status_timer.callback.append(self.restoreStatus)
                self.status_timer.start(3000, True)
            else:
                self["status"].setText("Error saving login credentials!")

class OpenSubtitlesSearchScreen(Screen):
    """Ekran za pretragu titlova filmova"""

    skin = """
    <screen position="center,center" size="1600,800" title="Search Movie Subtitles" backgroundColor="#000000">
        <eLabel position="0,0" size="1600,800" backgroundColor="#000000" zPosition="-10" />

        <widget name="input_label" position="50,30" size="200,40" font="Regular;28" foregroundColor="#ffffff" valign="center" />

        <eLabel position="260,30" size="700,40" backgroundColor="#222222" />

        <!-- Input field - DIRECT Label (no source/render!) -->
        <widget name="input" position="270,35" size="680,30"
            font="Regular;28"
            foregroundColor="#ffff00"
            backgroundColor="#222222"
            transparent="0"
            halign="left" />

        <widget name="results" position="50,100" size="1100,550" enableWrapAround="1" scrollbarMode="showOnDemand" 
                transparent="0" backgroundColor="#111111" foregroundColor="#ffffff" 
                itemHeight="50" font="Regular;24" />

        <eLabel position="50,670" size="700,30" backgroundColor="#333333" />
        <widget name="status" position="60,675" size="680,20" 
            font="Regular;22" 
            foregroundColor="#ffff00"
            backgroundColor="transparent" 
            transparent="1" />

        <eLabel text="Exit" position="50,720" size="150,50" font="Regular;26" foregroundColor="#ffffff" backgroundColor="#9f1313" halign="center" valign="center" />
        <eLabel text="Search" position="230,720" size="150,50" font="Regular;26" foregroundColor="#ffffff" backgroundColor="#1f771f" halign="center" valign="center" />
        <eLabel text="Keyboard" position="410,720" size="150,50" font="Regular;26" foregroundColor="#ffffff" backgroundColor="#a08500" halign="center" valign="center" />
        <eLabel text="Download" position="590,720" size="150,50" font="Regular;26" foregroundColor="#ffffff" backgroundColor="#18188b" halign="center" valign="center" />

        <widget name="background" position="1200,0" size="400,800" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/CiefpOpenSubtitles/background.png" />

        <!-- OVO SU SADA NEPOTREBNI - uklonjeni su -->
        <widget source="key_red" render="Label" position="0,0" size="0,0" />
        <widget source="key_green" render="Label" position="0,0" size="0,0" />
        <widget source="key_yellow" render="Label" position="0,0" size="0,0" />
        <widget source="key_blue" render="Label" position="0,0" size="0,0" />
    </screen>
    """

    def __init__(self, session, plugin, initial_query=""):
        Screen.__init__(self, session)
        self.session = session
        self.plugin = plugin
        self.initial_query = initial_query

        # ✅ KORISTIMO Label UMESTO StaticText
        self["input_label"] = Label("Search:")
        self["input"] = Label(initial_query or "")  # Direktno Label
        self["status"] = Label("Enter movie title and press GREEN to search")
        self["background"] = Pixmap()

        self["key_red"] = Label("Exit")      # Može biti i StaticText, ali Label je jednostavniji
        self["key_green"] = Label("Search")
        self["key_yellow"] = Label("Keyboard")
        self["key_blue"] = Label("Download")

        self["results"] = MenuList([])
        self.results_list = []

        self["actions"] = ActionMap(["ColorActions", "SetupActions", "MovieSelectionActions"],
                                    {
                                        "red": self.close,
                                        "green": self.doSearch,
                                        "yellow": self.openKeyboard,
                                        "blue": self.downloadSelected,
                                        "cancel": self.close,
                                        "ok": self.downloadSelected,
                                        "up": self.up,
                                        "down": self.down,
                                        "left": self.left,
                                        "right": self.right,
                                    }, -2)

        if initial_query:
            self.doSearch()

        self.onLayoutFinish.append(self.updateDisplay)

    def updateDisplay(self):
        search_text = self["input"].getText()
        print(f"[DEBUG] Input text: '{search_text}'")
        if not search_text or not search_text.strip():
            self["status"].setText("Enter movie title and press GREEN to search")
        else:
            self["status"].setText(f"Ready to search: {search_text[:30]}...")

    def openKeyboard(self):
        current_text = self["input"].getText()
        self.session.openWithCallback(
            self.keyboardCallback,
            VirtualKeyBoard,
            title="Search for movie subtitles",
            text=current_text
        )

    def keyboardCallback(self, callback=None):
        if callback is not None:
            cleaned_text = callback.strip()
            self["input"].setText(cleaned_text)  # ✅ Tekst se osvežava odmah
            self.updateDisplay()
            if cleaned_text:
                self.doSearch()

    def doSearch(self):
        query = self["input"].getText().strip()
        if not query:
            self["status"].setText("Please enter search term")
            return

        self["status"].setText("Searching...")

        settings = self.plugin.api.config.read_settings()
        languages = settings.get('languages', ['sr', 'hr'])
        site = settings.get('preferred_site', 'com')
        multi_lang = settings.get('multi_lang_download', False)

        print(f"[DEBUG] Searching for: '{query}' on {site}")
        print(f"[DEBUG] Languages: {languages}")
        print(f"[DEBUG] Multi-language: {multi_lang}")

        if site == 'org':
            results = self.plugin.api.search_org(query, languages)
        else:
            if multi_lang and len(languages) > 1:
                results = self.plugin.api.search_multiple_languages(query, languages)
            else:
                results = self.plugin.api.search_com(query, languages)

        print(f"[DEBUG] Got {len(results) if results else 0} results")

        self.results_list = results or []

        # Sortiranje rezultata
        self.results_list.sort(key=lambda x: (
            -int(x.get('year', 0) or 0) if str(x.get('year', '0')).isdigit() else 0,
            -x.get('downloads', 0)
        ))

        list_items = []

        if self.results_list:
            for idx, result in enumerate(self.results_list, 1):
                title = result.get('title', 'Unknown Title')
                language = result.get('language', 'Unknown').upper()

                lang_indicator = ""
                if multi_lang and len(languages) > 1:
                    searched_lang = result.get('searched_language', language.lower())
                    lang_indicator = f"[{searched_lang.upper()}] "

                year = result.get('year', '')
                year_prefix = f"{year} - " if year and str(year).isdigit() else ""

                display_text = f"{idx}. {lang_indicator}{year_prefix}{title[:45]}"
                if len(title) > 45:
                    display_text += "..."

                info_parts = [f"Lang: {language}"]

                fps = result.get('fps')
                if fps and fps > 0:
                    fps_text = f"{fps:.2f}" if isinstance(fps, float) else str(fps)
                    info_parts.append(f"FPS: {fps_text}")

                if result.get('downloads'):
                    info_parts.append(f"↓{result['downloads']}")

                if result.get('rating'):
                    rating = result['rating']
                    if rating > 0:
                        info_parts.append(f"⭐{rating:.1f}")

                if result.get('hd'):
                    info_parts.append("HD")

                if result.get('hearing_impaired'):
                    info_parts.append("HI")

                display_text += f" ({' | '.join(info_parts)})"

                if len(display_text) > 120:
                    display_text = display_text[:117] + "..."

                list_items.append(display_text)
        else:
            list_items = ["No results found"]

        print(f"[DEBUG] Setting list with {len(list_items)} items")
        self["results"].setList(list_items)

        if self.results_list:
            # Prikaži statistiku rezultata
            year_counts = {}
            for result in self.results_list:
                year = result.get('year', 'Unknown')
                year_counts[year] = year_counts.get(year, 0) + 1

            # Sortiraj godine od najnovije
            sorted_years = sorted([(y, c) for y, c in year_counts.items()
                                   if str(y).isdigit()],
                                  key=lambda x: int(x[0]), reverse=True)
            year_summary = ", ".join([f"{year}:{count}" for year, count in sorted_years[:3]])

            languages_found = set(r.get('language', '').upper() for r in self.results_list)
            self["status"].setText(
                f"Found {len(self.results_list)} results in {len(languages_found)} languages. Years: {year_summary}")
        else:
            self["status"].setText("No results found. Try different search term.")

    def downloadSelected(self):
        selected_idx = self["results"].getSelectedIndex()

        if not self.results_list or selected_idx >= len(self.results_list):
            self["status"].setText("No item selected!")
            return

        result = self.results_list[selected_idx]
        self["status"].setText(f"Downloading: {result.get('title', 'Unknown')[:30]}...")

        settings = self.plugin.api.config.read_settings()
        multi_lang = settings.get('multi_lang_download', False)
        priority_language = settings.get('priority_language', 'first')

        if multi_lang and priority_language == 'all':
            self.downloadAllLanguages(result)
        else:
            self.downloadSingleSubtitle(result)

    def downloadSingleSubtitle(self, result):
        print(f"[DEBUG] Downloading single subtitle")

        content = None
        if result.get('site') == 'org':
            content = self.plugin.api.download_org(result.get('url'), delay=5)
        else:
            if result.get('file_id'):
                download_result = self.plugin.api.download_com(result.get('file_id'), result.get('title', 'subtitle'))
                if download_result:
                    content, _ = download_result

        if content:
            self.saveSubtitle(content, result)
        else:
            self.showDownloadError()

    def downloadAllLanguages(self, result):
        print(f"[DEBUG] Downloading all languages")

        title = result.get('title', 'Unknown')
        self["status"].setText(f"Searching all languages for: {title[:30]}...")

        settings = self.plugin.api.config.read_settings()
        languages = settings.get('languages', ['sr', 'hr'])

        if 'all' in languages:
            languages = ['sr', 'hr', 'bs', 'sl', 'en']

        downloaded_count = 0

        for lang in languages:
            search_results = self.plugin.api.search_com(title, [lang])

            if search_results:
                for sub_result in search_results:
                    if sub_result.get('file_id'):
                        download_result = self.plugin.api.download_com(
                            sub_result.get('file_id'),
                            sub_result.get('title', 'subtitle')
                        )

                        if download_result:
                            content, _ = download_result
                            if content:
                                self.saveSubtitle(content, sub_result)
                                downloaded_count += 1
                                break

        if downloaded_count > 0:
            self["status"].setText(f"Downloaded {downloaded_count} language(s)")
            self.session.open(MessageBox,
                              f"Successfully downloaded {downloaded_count} subtitle(s)\nin different languages!",
                              MessageBox.TYPE_INFO,
                              timeout=5)
        else:
            self.showDownloadError()

    def saveSubtitle(self, content, result):
        settings = self.plugin.api.config.read_settings()
        save_path = settings.get('save_path', '/media/hdd/subtitles/')

        title = result.get('title', 'subtitle').replace(' ', '_')
        title = re.sub(r'[^\w\-_]', '', title)
        language = result.get('language', 'unknown').lower()
        timestamp = int(time.time())
        filename = f"{title}_{language}_{timestamp}.srt"
        full_path = os.path.join(save_path, filename)

        try:
            if not pathExists(save_path):
                createDir(save_path)

            if isinstance(content, str):
                content = content.encode('utf-8')

            with open(full_path, 'wb') as f:
                f.write(content)

            self["status"].setText(f"Downloaded: {filename}")
            self.session.open(MessageBox,
                              f"Subtitle downloaded successfully!\n\nSaved to: {full_path}",
                              MessageBox.TYPE_INFO,
                              timeout=5)

            self.autoMapSubtitle(full_path, title)

        except Exception as e:
            print(f"[DEBUG] Error saving subtitle: {e}")
            self["status"].setText(f"Error saving: {str(e)}")
            self.session.open(MessageBox,
                              f"Error saving subtitle: {str(e)}",
                              MessageBox.TYPE_ERROR)

    def autoMapSubtitle(self, subtitle_path, base_name):
        try:
            video_extensions = ['.mkv', '.mp4', '.avi', '.ts', '.mov', '.m2ts']
            sub_dir = os.path.dirname(subtitle_path)

            if os.path.exists(sub_dir):
                for file in os.listdir(sub_dir):
                    if any(file.lower().endswith(ext) for ext in video_extensions):
                        video_name = os.path.splitext(file)[0]
                        if base_name.lower() in video_name.lower() or video_name.lower() in base_name.lower():
                            settings = self.plugin.api.config.read_settings()
                            languages = settings.get('languages', ['srp'])
                            lang_code = languages[0] if languages else 'srp'

                            new_name = f"{video_name}.{lang_code}.srt"
                            new_path = os.path.join(sub_dir, new_name)

                            if not os.path.exists(new_path):
                                os.rename(subtitle_path, new_path)
                                print(f"[DEBUG] Auto-mapped subtitle to: {new_name}")
                                return True
            return False
        except Exception as e:
            print(f"[DEBUG] Auto-map error: {e}")
            return False

    def showDownloadError(self):
        self["status"].setText("Download failed!")
        self.session.open(MessageBox,
                          "Download failed!\n\nCheck:\n1. API Key\n2. Internet connection\n3. File availability",
                          MessageBox.TYPE_ERROR)

    def up(self):
        if self["results"].getList():
            self["results"].up()

    def down(self):
        if self["results"].getList():
            self["results"].down()

    def left(self):
        if self["results"].getList():
            self["results"].pageUp()

    def right(self):
        if self["results"].getList():
            self["results"].pageDown()

class OpenSubtitlesSeriesSearchScreen(Screen):
    skin = """<screen position="center,center" size="1600,800"
        title="Search Series Subtitles"
        backgroundColor="#000000">

        <!-- Background -->
        <eLabel position="0,0" size="1600,800" backgroundColor="#000000" zPosition="-10" />

        <!-- Header -->
        <widget name="header" position="50,15" size="1100,40"
            font="Regular;32"
            foregroundColor="#ffff00"
            halign="center"
            valign="center"
            transparent="1"
            zPosition="1" />

        <!-- SERIES -->
        <widget name="series_label" position="55,75" size="140,30"
            font="Regular;28"
            foregroundColor="#ff5555"
            transparent="1" />

        <widget name="series_input" position="215,75" size="390,30"
            font="Regular;28"
            foregroundColor="#ffffff"
            transparent="1" />

        <!-- SEASON -->
        <widget name="season_label" position="55,125" size="140,30"
            font="Regular;28"
            foregroundColor="#ff5555"
            transparent="1" />

        <widget name="season_input" position="215,125" size="140,30"
            font="Regular;28"
            foregroundColor="#ffffff"
            transparent="1" />

        <!-- EPISODE -->
        <widget name="episode_label" position="385,125" size="140,30"
            font="Regular;28"
            foregroundColor="#ff5555"
            transparent="1" />

        <widget name="episode_input" position="545,125" size="140,30"
            font="Regular;28"
            foregroundColor="#ffffff"
            transparent="1" />

        <!-- Instructions -->
        <widget name="instructions" position="50,175" size="1100,30"
            font="Regular;24"
            foregroundColor="#ffff00"
            transparent="1" />

        <!-- Results -->
        <widget name="results"
            position="50,215" size="1100,470"
            enableWrapAround="1"
            scrollbarMode="showOnDemand"
            backgroundColor="#111111"
            foregroundColor="#ffffff"
            itemHeight="47"
            font="Regular;22"
            zPosition="1" />

        <!-- Status -->
        <eLabel position="50,700" size="700,30" backgroundColor="#333333" />
        <widget name="status" position="60,705" size="680,20"
            font="Regular;22"
            foregroundColor="#ffff00"
            transparent="1" />

        <!-- Buttons -->
        <eLabel text="Exit" position="50,745" size="150,45"
                font="Regular;26"
                foregroundColor="#ffffff"
                backgroundColor="#9f1313"
                halign="center" valign="center"
                zPosition="1" />

        <eLabel text="Search" position="230,745" size="150,45"
                font="Regular;26"
                foregroundColor="#ffffff"
                backgroundColor="#1f771f"
                halign="center" valign="center"
                zPosition="1" />

        <eLabel text="Keyboard" position="410,745" size="150,45"
                font="Regular;26"
                foregroundColor="#ffffff"
                backgroundColor="#a08500"
                halign="center" valign="center"
                zPosition="1" />

        <eLabel text="Download" position="590,745" size="150,45"
                font="Regular;26"
                foregroundColor="#ffffff"
                backgroundColor="#18188b"
                halign="center" valign="center"
                zPosition="1" />

        <!-- Right image -->
        <widget name="background"
                position="1200,0" size="400,800"
                pixmap="/usr/lib/enigma2/python/Plugins/Extensions/CiefpOpenSubtitles/background.png"
                zPosition="0" />
    </screen>"""

    def __init__(self, session, plugin):
        Screen.__init__(self, session)
        self.session = session
        self.plugin = plugin

        # Kreiramo widget-e - koristimo Label za sve
        self["header"] = Label("SERIES SUBTITLES SEARCH")
        self["series_label"] = Label("Series:")
        self["series_input"] = Label("")
        self["season_label"] = Label("Season:")
        self["season_input"] = Label("")
        self["episode_label"] = Label("Episode:")
        self["episode_input"] = Label("")
        self["instructions"] = Label("Press YELLOW for keyboard, GREEN to search")
        self["background"] = Pixmap()
        self["status"] = Label("Ready")

        self["results"] = MenuList([])
        self.results_list = []

        # Aktuelno polje za unos
        self.current_field = "series"

        # Hidden za ActionMap
        self["key_red"] = StaticText("")
        self["key_green"] = StaticText("")
        self["key_yellow"] = StaticText("")
        self["key_blue"] = StaticText("")

        # Action map
        self["actions"] = ActionMap(["ColorActions", "SetupActions", "MovieSelectionActions"],
                                    {
                                        "red": self.close,
                                        "green": self.doSearch,
                                        "yellow": self.openKeyboard,
                                        "blue": self.downloadSelected,
                                        "cancel": self.close,
                                        "ok": self.downloadSelected,
                                        "up": self.up,
                                        "down": self.down,
                                        "left": self.left,
                                        "right": self.right,
                                    }, -2)

        self.onLayoutFinish.append(self.updateDisplay)

    def updateDisplay(self):
        """Ažurira prikaz polja"""
        # Provjeri koje polje je prazno i postavi current_field
        series_text = self["series_input"].getText()
        season_text = self["season_input"].getText()
        episode_text = self["episode_input"].getText()

        if not series_text or not series_text.strip():
            self.current_field = "series"
            self["instructions"].setText("Press YELLOW to enter SERIES name")
        elif series_text.strip() and (not season_text or not season_text.strip()):
            self.current_field = "season"
            self["instructions"].setText("Press YELLOW to enter SEASON number")
        elif series_text.strip() and season_text.strip() and (not episode_text or not episode_text.strip()):
            self.current_field = "episode"
            self["instructions"].setText("Press YELLOW to enter EPISODE number")
        else:
            self["instructions"].setText("All fields filled. Press GREEN to search!")

    def openKeyboard(self):
        """Otvara virtuelnu tastaturu za trenutno polje"""
        if self.current_field == "series":
            self.editSeries()
        elif self.current_field == "season":
            self.editSeason()
        elif self.current_field == "episode":
            self.editEpisode()

    def editSeries(self):
        """Editovanje naziva serije"""
        current_text = self["series_input"].getText()
        self.session.openWithCallback(
            self.seriesCallback,
            VirtualKeyBoard,
            title="Enter series name",
            text=current_text
        )

    def seriesCallback(self, callback=None):
        """Callback za seriju"""
        if callback is not None:
            self["series_input"].setText(callback)
            self.updateDisplay()

    def editSeason(self):
        """Editovanje sezone"""
        current_text = self["season_input"].getText()
        self.session.openWithCallback(
            self.seasonCallback,
            VirtualKeyBoard,
            title="Enter season number",
            text=current_text
        )

    def seasonCallback(self, callback=None):
        """Callback za sezonu"""
        if callback is not None:
            self["season_input"].setText(callback)
            self.updateDisplay()

    def editEpisode(self):
        """Editovanje epizode"""
        current_text = self["episode_input"].getText()
        self.session.openWithCallback(
            self.episodeCallback,
            VirtualKeyBoard,
            title="Enter episode number",
            text=current_text
        )

    def episodeCallback(self, callback=None):
        """Callback za epizodu"""
        if callback is not None:
            self["episode_input"].setText(callback)
            self.updateDisplay()

    def doSearch(self):
        """Pretraga serije"""
        series_name = self["series_input"].getText()
        if not series_name or not series_name.strip():
            self["status"].setText("ERROR: Please enter series name!")
            return

        series_name = series_name.strip()

        season_str = self["season_input"].getText()
        episode_str = self["episode_input"].getText()

        season = None
        episode = None

        if season_str and season_str.strip():
            try:
                season = int(season_str.strip())
            except:
                self["status"].setText("ERROR: Invalid season number!")
                return

        if episode_str and episode_str.strip():
            try:
                episode = int(episode_str.strip())
            except:
                self["status"].setText("ERROR: Invalid episode number!")
                return

        # Kreiraj prikazni tekst za status
        search_display = f"'{series_name}'"
        if season is not None:
            search_display += f" S{season}"
            if episode is not None:
                search_display += f"E{episode}"

        self["status"].setText(f"Searching {search_display}...")

        # Izvrši pretragu
        results = self.plugin.api.search_series_com(series_name, season, episode)

        self.results_list = results or []
        list_items = []

        if self.results_list:
            for idx, result in enumerate(self.results_list, 1):
                title = result.get('title', 'Unknown')

                display_text = f"{idx}. {title[:50]}"
                if len(title) > 50:
                    display_text += "..."

                info_parts = []

                language = result.get('language', 'Unknown').upper()
                info_parts.append(f"Lang: {language}")

                season_num = result.get('season')
                episode_num = result.get('episode')
                if season_num and episode_num:
                    info_parts.append(f"S{season_num:02d}E{episode_num:02d}")
                elif season_num:
                    info_parts.append(f"S{season_num:02d}")

                fps = result.get('fps')
                if fps and fps > 0:
                    fps_text = f"{fps:.2f}" if isinstance(fps, float) else str(fps)
                    info_parts.append(f"FPS: {fps_text}")

                downloads = result.get('downloads', 0)
                if downloads > 0:
                    try:
                        downloads_str = f"{downloads:,}".replace(",", ".")
                        info_parts.append(f"↓{downloads_str}")
                    except:
                        info_parts.append(f"↓{downloads}")

                if result.get('hd'):
                    info_parts.append("HD")

                if result.get('hearing_impaired'):
                    info_parts.append("HI")

                if info_parts:
                    display_text += f" ({' | '.join(info_parts)})"

                list_items.append(display_text)
        else:
            list_items = ["No results found"]

        self["results"].setList(list_items)

        if self.results_list:
            # Prikazi kratak rezime
            lang_counts = {}
            for result in self.results_list:
                lang = result.get('language', 'Unknown').upper()
                lang_counts[lang] = lang_counts.get(lang, 0) + 1

            lang_summary = ", ".join([f"{lang}:{count}" for lang, count in lang_counts.items()])
            self["status"].setText(f"Found {len(self.results_list)} results [{lang_summary}]")
        else:
            self["status"].setText("No results found. Try different search.")

    def downloadSelected(self):
        """Download izabranog titla"""
        selected_idx = self["results"].getSelectedIndex()

        if not self.results_list or selected_idx >= len(self.results_list):
            self["status"].setText("No item selected!")
            return

        result = self.results_list[selected_idx]
        title = result.get('title', 'subtitle')
        self["status"].setText(f"Downloading: {title[:30]}...")

        if result.get('file_id'):
            download_result = self.plugin.api.download_com(result.get('file_id'), result.get('title', 'subtitle'))
            if download_result:
                content, filename = download_result

                settings = self.plugin.api.config.read_settings()
                save_path = settings.get('save_path', '/media/hdd/subtitles/')

                # Kreiraj naziv fajla
                title = result.get('title', 'subtitle').replace(' ', '_')
                title = re.sub(r'[^\w\-_]', '', title)
                language = result.get('language', 'unknown').lower()
                season = result.get('season')
                episode = result.get('episode')
                timestamp = int(time.time())

                if season and episode:
                    filename = f"{title}_S{season:02d}E{episode:02d}_{language}_{timestamp}.srt"
                elif season:
                    filename = f"{title}_S{season:02d}_{language}_{timestamp}.srt"
                else:
                    filename = f"{title}_{language}_{timestamp}.srt"

                full_path = os.path.join(save_path, filename)

                try:
                    if not pathExists(save_path):
                        createDir(save_path)

                    if isinstance(content, str):
                        content = content.encode('utf-8')

                    with open(full_path, 'wb') as f:
                        f.write(content)

                    self["status"].setText(f"Downloaded: {filename}")
                    self.session.open(MessageBox,
                                      f"Subtitle downloaded successfully!\n\nSaved to: {full_path}",
                                      MessageBox.TYPE_INFO,
                                      timeout=5)

                except Exception as e:
                    self["status"].setText(f"Error: {str(e)}")
                    self.session.open(MessageBox,
                                      f"Error saving subtitle: {str(e)}",
                                      MessageBox.TYPE_ERROR)
            else:
                self["status"].setText("Download failed!")
                self.session.open(MessageBox,
                                  "Download failed! Check API key or internet connection.",
                                  MessageBox.TYPE_ERROR)
        else:
            self["status"].setText("No file ID found!")

    def up(self):
        """Navigacija gore"""
        if self.current_field == "season":
            self.current_field = "series"
            self.updateDisplay()
        elif self.current_field == "episode":
            self.current_field = "season"
            self.updateDisplay()
        elif self["results"].getList():
            self["results"].up()

    def down(self):
        """Navigacija dole"""
        if self.current_field == "series":
            self.current_field = "season"
            self.updateDisplay()
        elif self.current_field == "season":
            self.current_field = "episode"
            self.updateDisplay()
        elif self["results"].getList():
            self["results"].down()

    def left(self):
        """Navigacija levo (page up)"""
        if self["results"].getList():
            self["results"].pageUp()

    def right(self):
        """Navigacija desno (page down)"""
        if self["results"].getList():
            self["results"].pageDown()

class OpenSubtitlesMainScreen(Screen):
    skin = """
    <screen name="CiefpOpenSubtitlesMain" position="center,center" size="1600,800" title="Ciefp OpenSubtitles v1.1" backgroundColor="#000000">
        <eLabel position="0,0" size="1920,1080" backgroundColor="#000000" zPosition="-15" />
        <eLabel position="center,center" size="1200,800" backgroundColor="#101010" zPosition="-10" />
        
        <widget name="background" position="1200,10" size="400,800" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/CiefpOpenSubtitles/background.png" />
        <widget name="title" position="0,40" size="1200,80" font="Regular;42" foregroundColor="#ffffff" backgroundColor="transparent" halign="center" valign="center" transparent="1" zPosition="1" />

        <widget name="menu" position="100,140" size="1000,450" itemHeight="60" font="Regular;34" foregroundColor="#ffffff" backgroundColor="transparent" scrollbarMode="showOnDemand" enableWrapAround="1" transparent="1" zPosition="1" />

        <eLabel text="Exit" position="100,e-100" size="250,60" font="Regular;30" foregroundColor="#ffffff" backgroundColor="#9f1313" halign="center" valign="center" zPosition="1" />
        <eLabel text="Help" position="380,e-100" size="250,60" font="Regular;30" foregroundColor="#ffffff" backgroundColor="#1f771f" halign="center" valign="center" zPosition="1" />
        <eLabel text="Refresh" position="660,e-100" size="250,60" font="Regular;30" foregroundColor="#ffffff" backgroundColor="#a08500" halign="center" valign="center" zPosition="1" />
        <eLabel text="Select" position="940,e-100" size="250,60" font="Regular;30" foregroundColor="#ffffff" backgroundColor="#18188b" halign="center" valign="center" zPosition="1" />

        <widget source="key_red" render="Label" position="0,0" size="0,0" />
        <widget source="key_green" render="Label" position="0,0" size="0,0" />
        <widget source="key_yellow" render="Label" position="0,0" size="0,0" />
        <widget source="key_blue" render="Label" position="0,0" size="0,0" />
    </screen>
    """

    def __init__(self, session, plugin):
        Screen.__init__(self, session)
        self.session = session
        self.plugin = plugin
        
        self.menu_items = [
            ("Search movie subtitles", "search_movie"),
            ("Search series subtitles", "search_series"),
            ("Configuration", "config"),
            ("API Key / Login", "credentials"),
            ("About", "about"),
            ("Exit", "exit")
        ]
        self["menu"] = MenuList([])
        self["background"] = Pixmap()
        
        list_items = []
        for idx, item in enumerate(self.menu_items):
            list_items.append((f"{idx+1}. {item[0]}", item[1]))
        
        self["menu"].list = list_items
        self["menu"].setList(list_items)
        
        self["key_red"] = StaticText("Exit")
        self["key_green"] = StaticText("Help")
        self["key_yellow"] = StaticText("Refresh")
        self["key_blue"] = StaticText("Select")
        
        self["title"] = Label("Ciefp OpenSubtitles v1.1")
        
        self["actions"] = ActionMap(["ColorActions", "SetupActions"],
        {
            "red": self.close,
            "green": self.keyGreen,
            "yellow": self.keyYellow,
            "blue": self.selectItem,
            "cancel": self.close,
            "ok": self.selectItem,
        }, -2)
    
    def keyGreen(self):
        """Zeleno dugme - Help"""
        help_text = """Ciefp OpenSubtitles v1.1 - 
        HELPCONTROLS: 
        - Up/Down: Navigation 
        - BLUE/OK: Choose 
        - RED: Exit 
        - GREEN: This help 
        - YELLOW: Refresh the list 
        NEW: 
        - Multi-language search (sr, hr, en) 
        - Series with seasons/episodes 
        - FPS display 
        - Download multiple languages 
        - Language priority 
        FIRST STEPS: 
        1. Go to Configuration 
        2. Enter API Key or Login 
        3. Get the API key from opensubtitles.com 
        4. Set languages ​​(sr, hr, en) 
        5. Use Search for subtitles 
        6. Download and enjoy!"""
        self.session.open(MessageBox, help_text, MessageBox.TYPE_INFO)
    
    def keyYellow(self):
        """Žuto dugme - Refresh"""
        list_items = []
        for idx, item in enumerate(self.menu_items):
            list_items.append((f"{idx+1}. {item[0]}", item[1]))
        self["menu"].setList(list_items)
    
    def selectItem(self):
        """Plavo dugme - Select"""
        selected = self["menu"].getCurrent()
        if selected:
            action = selected[1]
            
            if action == "search_movie":
                self.session.open(OpenSubtitlesSearchScreen, self.plugin)
            elif action == "search_series":
                self.session.open(OpenSubtitlesSeriesSearchScreen, self.plugin)
            elif action == "config":
                self.session.open(OpenSubtitlesConfigScreen, self.plugin)
            elif action == "credentials":
                self.session.open(OpenSubtitlesCredentialsScreen, self.plugin)
            elif action == "about":
                about_text = """Ciefp OpenSubtitles Plugin
Version: 1.1

Author: Ciefp
Description: Search and download subtitles
Supports: OpenSubtitles.com & .org

Features:
• Movie subtitles search
• Series subtitles search
• Multiple language support
• FPS information display
• Auto-mapping to videos

Enjoy!"""
                self.session.open(MessageBox, about_text, MessageBox.TYPE_INFO)
            elif action == "exit":
                self.close()

class OpenSubtitlesPlugin:
    """Glavna klasa plugina"""
    
    def __init__(self):
        self.api = OpenSubtitlesAPI()
    
    def main(self, session, **kwargs):
        """Glavna funkcija plugina"""
        session.open(OpenSubtitlesMainScreen, self)
    
    def autoSearch(self, session, event, movie_title):
        """Automatska pretraga za trenutni video"""
        session.open(OpenSubtitlesSearchScreen, self, movie_title)
    
    def config(self, session, **kwargs):
        """Konfiguracija"""
        session.open(OpenSubtitlesConfigScreen, self)
    
    def credits(self):
        """Informacije o pluginu"""
        return [
            ("Ciefp OpenSubtitles", "v" + PLUGIN_VERSION),
            ("Author", "Ciefp"),
            ("Description", "Download subtitles from OpenSubtitles"),
            ("Features", "Multi-language, Series search, FPS display")
        ]

# Kreiranje instance plugina
opensubtitles_plugin = OpenSubtitlesPlugin()

# Funkcije za Enigma2
def main(session, **kwargs):
    opensubtitles_plugin.main(session, **kwargs)

def config(session, **kwargs):
    opensubtitles_plugin.config(session, **kwargs)

def Plugins(**kwargs):
    """Registracija plugina u Enigma2"""
    from Plugins.Plugin import PluginDescriptor
    
    icon_path = os.path.join(PLUGIN_PATH, "icon.png")
    if not fileExists(icon_path):
        icon_path = None
    
    return [
        PluginDescriptor(
            name="CiefpOpenSubtitles v1.1",
            description="Search and download subtitles (multi-language)",
            where=PluginDescriptor.WHERE_PLUGINMENU,
            icon=icon_path,
            fnc=main
        ),
        PluginDescriptor(
            name="CiefpOpenSubtitles Config",
            description="Configure OpenSubtitles plugin",
            where=PluginDescriptor.WHERE_PLUGINMENU,
            icon=icon_path,
            fnc=config
        ),
        PluginDescriptor(
            name="CiefpOpenSubtitles",
            description="Search subtitles for current video",
            where=PluginDescriptor.WHERE_MOVIELIST,
            fnc=opensubtitles_plugin.autoSearch
        )
    ]