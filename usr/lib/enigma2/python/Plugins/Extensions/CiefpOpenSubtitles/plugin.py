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
PLUGIN_VERSION = "1.2"  # TRI PRETRAGE: Standard, Smart, Advanced
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

class SubDLAPI:
    """Klasa za komunikaciju sa zvaničnim SubDL API-jem - POBOLJŠANO"""
    
    def __init__(self):
        self.base_url = "https://api.subdl.com/api/v1/subtitles"
        self.download_base = "https://dl.subdl.com"
        self.session = requests.Session()
        self.api_key = ""
        
        # Retry mehanizam
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        self.headers = {
            'User-Agent': 'Enigma2 SubDL Plugin/1.2',
            'Accept': 'application/json'
        }
    
    def set_api_key(self, api_key):
        """Postavljanje API ključa"""
        self.api_key = api_key
    
    def smart_search(self, query, languages=None, season=None, episode=None):
        """
        PAMETNA pretraga koja proba SVA TRI načina po tvom redosledu:
        1. IMDB ID (ako postoji u query-u)
        2. File Name
        3. Film Name
        
        Vraća listu sa dodatnim poljem 'search_method'
        """
        print(f"[SubDL SMART] Smart search for: '{query}'")
        all_results = []
        
        # 1. PRVO: Probaj IMDB ID (najbolje po tvom testu)
        imdb_id = self.extract_imdb_id(query)
        if imdb_id:
            print(f"[SubDL SMART] Trying IMDB ID: {imdb_id}")
            imdb_results = self.search(
                query="",  # Prazan query jer koristimo imdb_id
                languages=languages,
                imdb_id=imdb_id,
                season=season,
                episode=episode
            )
            if imdb_results:
                print(f"[SubDL SMART] IMDB search found: {len(imdb_results)} results")
                for result in imdb_results:
                    result['search_method'] = 'imdb'
                all_results.extend(imdb_results)
        
        # 2. DRUGO: Probaj File Name
        if not all_results:  # Ako IMDB nije dao rezultate
            print(f"[SubDL SMART] Trying File Name search")
            file_results = self.search(
                query="",  # Prazan query jer koristimo file_name
                languages=languages,
                file_name=query,
                season=season,
                episode=episode
            )
            if file_results:
                print(f"[SubDL SMART] File Name search found: {len(file_results)} results")
                for result in file_results:
                    result['search_method'] = 'file_name'
                all_results.extend(file_results)
        
        # 3. TREĆE: Probaj Film Name (najslabije)
        if not all_results:  # Ako ni file_name nije dao rezultate
            print(f"[SubDL SMART] Trying Film Name search (last resort)")
            film_results = self.search(
                query=query,
                languages=languages,
                season=season,
                episode=episode
            )
            if film_results:
                print(f"[SubDL SMART] Film Name search found: {len(film_results)} results")
                for result in film_results:
                    result['search_method'] = 'film_name'
                all_results.extend(film_results)
        
        print(f"[SubDL SMART] Total results from smart search: {len(all_results)}")
        
        # Ukloni duplikate (po file_id)
        unique_results = []
        seen_ids = set()
        
        for result in all_results:
            file_id = result.get('file_id')
            if file_id and file_id not in seen_ids:
                seen_ids.add(file_id)
                unique_results.append(result)
            elif not file_id:
                # Ako nema file_id, koristi kombinaciju title+language
                key = f"{result.get('title', '')}_{result.get('language', '')}"
                if key not in seen_ids:
                    seen_ids.add(key)
                    unique_results.append(result)
        
        return unique_results
    
    def extract_imdb_id(self, query):
        """Pokušaj da ekstraktuješ IMDB ID iz query-a"""
        # Podržani formati: tt1375666, imdb:tt1375666, imdb=tt1375666
        import re
        
        # Ukloni razmake i specijalne karaktere
        clean_query = query.strip()
        
        # Pattern za IMDB ID: tt + 7-8 cifara
        imdb_pattern = r'(?:imdb[:=]?\s*)?(tt\d{7,8})'
        match = re.search(imdb_pattern, clean_query, re.IGNORECASE)
        
        if match:
            imdb_id = match.group(1).lower()  # tt1375666
            print(f"[SubDL SMART] Extracted IMDB ID: {imdb_id}")
            return imdb_id
        
        # Ako query SAMO sadrži IMDB ID (nema drugog teksta)
        if re.match(r'^tt\d{7,8}$', clean_query, re.IGNORECASE):
            print(f"[SubDL SMART] Query is pure IMDB ID: {clean_query}")
            return clean_query.lower()
        
        return None
    
    def search(self, query, languages=None, season=None, episode=None, 
               imdb_id=None, file_name=None, year=None, include_comments=False,
               include_releases=False, full_season=False):
        """ISPRAVLJENO: Pretraga titlova na SubDL koristeći zvanični API"""
        
        if not self.api_key:
            print("[SubDL] No API key configured!")
            return []
        
        print(f"[SubDL] API search: '{query}'")
        
        # Mapiranje jezika za SubDL API (velika slova kao u dokumentaciji)
        lang_map = {
            'sr': 'SR', 'srp': 'SR', 'scc': 'SR', 'srb': 'SR',
            'hr': 'HR', 'hrv': 'HR',
            'bs': 'BS', 'bos': 'BS',
            'sl': 'SL', 'slv': 'SL',
            'sk': 'SK', 'slk': 'SK',
            'cs': 'CS', 'cze': 'CS', 'ces': 'CS',  # Dodaj ces za kompatibilnost
            'en': 'EN', 'eng': 'EN',
            'mk': 'MK', 'mkd': 'MK',
            'bg': 'BG', 'bul': 'BG',
            'ro': 'RO', 'rum': 'RO',
            'pl': 'PL', 'pol': 'PL',
            'ar': 'AR', 'ara': 'AR',
            'fr': 'FR', 'fra': 'FR',
            'de': 'DE', 'deu': 'DE',
            'es': 'ES', 'spa': 'ES',
            'it': 'IT', 'ita': 'IT',
            'ru': 'RU', 'rus': 'RU'
        }
        
        # Konvertuj jezike u VELIKA SLOVA
        subdl_langs = []
        for lang in languages or ['SR']:  # Podrazumevano SR
            lang_lower = lang.lower().strip()
            if lang_lower == 'all':
                subdl_langs = ['SR', 'HR', 'BS', 'SL', 'SK', 'CS', 'EN', 'MK', 'BG', 'RO', 'PL', 'AR', 'FR', 'DE', 'ES', 'IT', 'RU']
                break
            else:
                converted = lang_map.get(lang_lower, lang_lower[:2].upper())
                if converted and converted not in subdl_langs:
                    subdl_langs.append(converted)
        
        if not subdl_langs:
            subdl_langs = ['SR']  # Veliko SR
        
        # Odredi tip (movie ili tv) - ISPRAVLJENO
        content_type = "tv" if season is not None or episode is not None else "movie"
        
        # Kreiraj parametre PREMA DOKUMENTACIJI
        params = {
            "api_key": self.api_key,
            "subs_per_page": 30  # Maksimum je 30 po strani
        }
        
        # Dodaj parametre pretrage PREMA PRIORITETU IZ DOKUMENTACIJE
        if imdb_id:
            params["imdb_id"] = imdb_id
        elif file_name:
            params["file_name"] = file_name
        else:
            params["film_name"] = query
        
        # Dodaj sezonu/epizodu ako je serija
        if season is not None:
            params["season_number"] = season
        if episode is not None:
            params["episode_number"] = episode
        
        # Dodaj ostale parametre
        params["type"] = content_type
        params["languages"] = ','.join(subdl_langs)
        
        if year:
            params["year"] = year
        
        # Dodaj opcione parametre iz dokumentacije
        if include_comments:
            params["comment"] = "1"
        if include_releases:
            params["releases"] = "1"
        if full_season:
            params["full_season"] = "1"
        
        # Uvek dodaj hi=1 da dobijemo informacije o titlovima za nagluve
        params["hi"] = "1"
        
        print(f"[SubDL] API params: {params}")
        
        try:
            response = self.session.get(self.base_url, params=params, headers=self.headers, timeout=15)
            print(f"[SubDL] Response status: {response.status_code}")
            
            if response.status_code != 200:
                print(f"[SubDL] API error: {response.status_code}")
                print(f"[SubDL] Response text: {response.text[:200]}")
                return []
            
            data = response.json()
            print(f"[SubDL] API response status: {data.get('status')}")
            
            if not data.get("status"):
                error_msg = data.get('error', 'Unknown error')
                print(f"[SubDL] API returned error: {error_msg}")
                return []
            
            # ISPRAVLJENO: API vraća DVE liste: results i subtitles
            results_list = data.get("results", [])
            subtitles_list = data.get("subtitles", [])
            
            print(f"[SubDL] Found {len(results_list)} results, {len(subtitles_list)} subtitles")
            
            return self.parse_api_response(results_list, subtitles_list, query, season, episode)
            
        except Exception as e:
            print(f"[SubDL] API search error: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def parse_api_response(self, results_list, subtitles_list, original_query, season=None, episode=None):
        """ISPRAVLJENO: Parsiranje odgovora od SubDL API-ja prema dokumentaciji"""
        parsed_results = []
        
        if not subtitles_list:
            return parsed_results
        
        # Uzmi informacije o filmu/seriji iz prvog rezultata
        movie_info = results_list[0] if results_list else {}
        
        for sub in subtitles_list:
            # Osnovne informacije
            release_name = sub.get("release", "")
            file_name = sub.get("file_name", "")
            language = sub.get("language", "Unknown")
            language_name = sub.get("language_name", language)
            
            # KRITIČNO ISPRAVLJENO: Ekstraktuj PRAVI file_id iz download URL-a
            download_url = sub.get("url", "")
            file_id = ""
            
            if download_url:
                # URL je u formatu: /subtitle/3197651-3213944/download
                # Ili: /subtitle/3197651-3213944.zip
                # Treba nam: 3197651-3213944
                import re
                # Pokušaj prvo sa .zip formatom
                match = re.search(r'/subtitle/(\d+-\d+)\.zip', download_url)
                if not match:
                    # Pokušaj sa /download formatom
                    match = re.search(r'/subtitle/(\d+-\d+)/download', download_url)
                if not match:
                    # Pokušaj sa bilo kojim formatom
                    match = re.search(r'/subtitle/(\d+-\d+)', download_url)
                
                if match:
                    file_id = match.group(1)
                else:
                    # Ako ne može da ekstraktuje, koristi ceo URL bez prvog dela
                    file_id = download_url.split('/')[-1].replace('.zip', '')
            
            # Kreiraj naslov
            title = movie_info.get("name", original_query)
            if release_name:
                title = f"{title} - {release_name}"
            
            # Dodaj dodatne informacije ako su dostupne
            comment = sub.get("comment", "")
            if comment and len(comment) < 50:
                title += f" ({comment[:50]})"
            
            # Proveri da li je HD
            release_lower = str(release_name).lower()
            is_hd = any(res in release_lower for res in ['1080p', '720p', 'hd', 'bluray', 'web-dl', 'webdl'])
            
            # Kreiraj rezultat SA ISPRAVLJENIM POLJIMA
            result = {
                'title': title,
                'release_name': release_name,
                'movie_name': movie_info.get("name", original_query),
                'language': language_name,
                'language_code': language,
                'downloads': sub.get("download_count", 0),
                'rating': float(sub.get("rating", 0.0)),
                'release_info': release_name,
                'year': movie_info.get("year", ""),
                'file_id': file_id,  # OVO JE SADA ISPRAVLJENO
                'download_url': download_url,
                'imdb_id': movie_info.get("imdb_id", ""),
                'tmdb_id': movie_info.get("tmdb_id", ""),
                'sd_id': movie_info.get("sd_id", ""),
                'fps': 0,  # SubDL ne daje FPS
                'hd': is_hd,
                'hearing_impaired': sub.get("hearing_impaired", False),
                'comment': comment,
                'is_series': season is not None or episode is not None,
                'season': season,
                'episode': episode,
                'site': 'subdl',
                'search_query': original_query
            }
            
            # Dodaj releases informacije ako postoje
            if "releases" in sub:
                result['releases'] = sub.get("releases", [])
            
            parsed_results.append(result)
        
        return parsed_results
    
    def download(self, file_id, title=""):
        """ISPRAVLJENO: Preuzimanje titla sa SubDL"""
        print(f"[SubDL] Downloading file_id: {file_id}")
        
        if not file_id:
            print("[SubDL] Error: No file ID provided")
            return None
        
        # ISPRAVLJENO: Format iz dokumentacije: https://dl.subdl.com/subtitle/3197651-3213944.zip
        download_url = f"{self.download_base}/subtitle/{file_id}.zip"
        
        print(f"[SubDL] Downloading from: {download_url}")
        
        try:
            headers = {
                'User-Agent': 'Enigma2 SubDL Plugin/1.2',
                'Accept': '*/*',
                'Referer': 'https://subdl.com/'
            }
            
            response = requests.get(download_url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                print(f"[SubDL] Download failed: {response.status_code}")
                print(f"[SubDL] Response: {response.text[:200]}")
                
                # Probaj alternativni format ako prvi ne radi
                alt_url = f"{self.download_base}/{file_id}/download"
                print(f"[SubDL] Trying alternative URL: {alt_url}")
                response = requests.get(alt_url, headers=headers, timeout=30)
                
                if response.status_code != 200:
                    print(f"[SubDL] Alternative also failed: {response.status_code}")
                    return None
            
            content = response.content
            
            # Procesiraj ZIP
            if content.startswith(b'PK'):
                from io import BytesIO
                from zipfile import ZipFile, BadZipFile
                try:
                    zipfile = ZipFile(BytesIO(content))
                    
                    # Pronađi SRT fajl (prioritet)
                    srt_files = [f for f in zipfile.namelist() if f.lower().endswith('.srt')]
                    if srt_files:
                        return zipfile.read(srt_files[0])
                    
                    # Pronađi bilo koji tekstualni fajl
                    text_extensions = ['.sub', '.txt', '.ass', '.ssa', '.vtt']
                    for file_name in zipfile.namelist():
                        if any(file_name.lower().endswith(ext) for ext in text_extensions):
                            return zipfile.read(file_name)
                    
                    # Uzmi prvi fajl ako nije pronađen tekstualni
                    if zipfile.namelist():
                        return zipfile.read(zipfile.namelist()[0])
                    else:
                        return content
                        
                except BadZipFile:
                    print(f"[SubDL] Invalid ZIP file, returning raw content")
                    return content
                except Exception as e:
                    print(f"[SubDL] ZIP extraction error: {e}")
                    return content
            else:
                # Direktno SRT ili drugi tekstualni format
                return content
                    
        except Exception as e:
            print(f"[SubDL] Download error: {e}")
            import traceback
            traceback.print_exc()
            return None

class OpenSubtitlesConfig:
    """Klasa za čitanje/pisanje konfiguracijskih fajlova"""
    
    def __init__(self):
        self.opensubtitles_apikey_file = os.path.join(CONFIG_DIR, "opensubtitles_apikey.txt")
        self.subdl_apikey_file = os.path.join(CONFIG_DIR, "subdl_apikey.txt")
        self.settings_file = os.path.join(CONFIG_DIR, "settings.json")
        
    def read_opensubtitles_api_key(self):
        """Čitanje OpenSubtitles API ključa iz fajla"""
        if fileExists(self.opensubtitles_apikey_file):
            try:
                with open(self.opensubtitles_apikey_file, 'r') as f:
                    content = f.read().strip()
                    if '=' in content:
                        for line in content.split('\n'):
                            if line.startswith('apikey='):
                                return line.split('=', 1)[1].strip()
                    return content
            except:
                pass
        return ""
    
    def write_opensubtitles_api_key(self, api_key):
        """Pisanje OpenSubtitles API ključa u fajl"""
        try:
            with open(self.opensubtitles_apikey_file, 'w') as f:
                f.write(f"apikey={api_key}")
            return True
        except:
            return False
    
    def read_subdl_api_key(self):
        """Čitanje SubDL API ključa iz fajla"""
        if fileExists(self.subdl_apikey_file):
            try:
                with open(self.subdl_apikey_file, 'r') as f:
                    content = f.read().strip()
                    if '=' in content:
                        for line in content.split('\n'):
                            if line.startswith('apikey='):
                                return line.split('=', 1)[1].strip()
                    return content
            except:
                pass
        return ""
    
    def write_subdl_api_key(self, api_key):
        """Pisanje SubDL API ključa u fajl"""
        try:
            with open(self.subdl_apikey_file, 'w') as f:
                f.write(f"apikey={api_key}")
            return True
        except:
            return False
    
    def read_settings(self):
        """Čitanje postavki iz JSON fajla"""
        defaults = {
            'languages': ['sr', 'hr'],
            'save_path': '/media/hdd/subtitles/',
            'auto_download': False,
            'preferred_service': 'both',  # both, opensubtitles, subdl
            'search_timeout': 15,
            'download_delay': 2,
            'multi_lang_download': False,
            'priority_language': 'first',
            'use_opensubtitles': True,
            'use_subdl': True,
            'max_results': 50,
            'subdl_include_comments': False,
            'subdl_include_releases': True,
            'subdl_full_season': False
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

class SubtitlesAPI:
    """Glavna API klasa koja upravlja svim servisima - DODATA SMART SEARCH"""
    
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
        
        # Učitaj API ključeve
        self.opensubtitles_api_key = self.config.read_opensubtitles_api_key()
        self.subdl_api_key = self.config.read_subdl_api_key()
        
        # Inicijalizuj servise
        self.subdl_api = SubDLAPI()
        self.subdl_api.set_api_key(self.subdl_api_key)
        
        # OpenSubtitles.com endpoints
        self.opensubtitles_base = "https://api.opensubtitles.com/api/v1"
    
    def update_api_keys(self):
        """Ažuriraj API ključeve nakon promene u konfiguraciji"""
        self.opensubtitles_api_key = self.config.read_opensubtitles_api_key()
        self.subdl_api_key = self.config.read_subdl_api_key()
        self.subdl_api.set_api_key(self.subdl_api_key)
    
    def search_all_smart(self, query, languages=None, season=None, episode=None):
        """
        PAMETNA pretraga na svim servisima sa optimizacijom za SubDL
        Koristi smart_search za SubDL, standard za OpenSubtitles
        """
        print(f"[API SMART] Smart search for: '{query}'")
        
        settings = self.config.read_settings()
        if languages is None:
            languages = settings.get('languages', ['sr', 'hr'])
        
        use_opensubtitles = settings.get('use_opensubtitles', True) and self.opensubtitles_api_key
        use_subdl = settings.get('use_subdl', True) and self.subdl_api_key
        preferred_service = settings.get('preferred_service', 'both')
        
        all_results = []
        
        # SUBDL SMART SEARCH (nova metoda)
        if use_subdl and preferred_service in ['both', 'subdl']:
            print(f"[API SMART] Starting SubDL SMART search...")
            subdl_results = self.subdl_api.smart_search(
                query, 
                languages, 
                season, 
                episode
            )
            
            # Označi rezultate
            for result in subdl_results:
                result['site'] = 'subdl'
                # Dodaj search method u naslov ako već nije dodat
                method = result.get('search_method', 'unknown')
                title = result.get('title', '')
                if method and method != 'unknown' and not title.startswith('['):
                    result['title'] = f"[{method.upper()}] {title}"
            
            all_results.extend(subdl_results)
            print(f"[API SMART] SubDL smart search found: {len(subdl_results)} results")
        
        # OpenSubtitles (standardna pretraga - opciono)
        if use_opensubtitles and preferred_service in ['both', 'opensubtitles']:
            print(f"[API SMART] Searching OpenSubtitles.com...")
            opensub_results = self.search_opensubtitles(query, languages, season, episode)
            for result in opensub_results:
                result['site'] = 'opensubtitles'
                result['search_method'] = 'standard'
            
            all_results.extend(opensub_results)
            print(f"[API SMART] OpenSubtitles found: {len(opensub_results)} results")
        
        # Ukloni duplikate
        unique_results = []
        seen = set()
        
        for result in all_results:
            file_id = result.get('file_id', '')
            title = result.get('title', '').lower()[:50]
            lang = result.get('language', '').lower()
            site = result.get('site', '').lower()
            
            # Ako ima file_id, koristi ga za jedinstvenost
            if file_id:
                key = f"{site}_{file_id}"
            else:
                key = f"{site}_{title}_{lang}"
            
            if key not in seen:
                seen.add(key)
                unique_results.append(result)
        
        # Sortiraj po kvalitetu pretrage
        def sort_key(x):
            site = x.get('site', '').lower()
            method = x.get('search_method', '').lower()
            
            # Prioriteti:
            # 1. SubDL IMDB
            # 2. SubDL File Name  
            # 3. SubDL Film Name
            # 4. OpenSubtitles
            # 5. Ostalo
            
            if site == 'subdl':
                if method == 'imdb':
                    return 0
                elif method == 'file_name':
                    return 1
                elif method == 'film_name':
                    return 2
                else:
                    return 3
            elif site == 'opensubtitles':
                return 4
            else:
                return 5
        
        unique_results.sort(key=sort_key)
        
        # Ograniči broj rezultata
        max_results = settings.get('max_results', 50)
        final_results = unique_results[:max_results]
        
        print(f"[API SMART] Total unique results: {len(final_results)}")
        return final_results
    
    def search_all(self, query, languages=None, season=None, episode=None):
        """ISPRAVLJENO: Pretraga na svim dostupnim servisima"""
        print(f"[API] Searching all services for: '{query}'")
        
        settings = self.config.read_settings()
        if languages is None:
            languages = settings.get('languages', ['sr', 'hr'])
        
        use_opensubtitles = settings.get('use_opensubtitles', True) and self.opensubtitles_api_key
        use_subdl = settings.get('use_subdl', True) and self.subdl_api_key
        preferred_service = settings.get('preferred_service', 'both')
        
        all_results = []
        
        # Prvo probaj SubDL ako je podešen kao preferirani ili oba
        if use_subdl and preferred_service in ['both', 'subdl']:
            print(f"[API] Searching SubDL...")
            subdl_results = self.subdl_api.search(
                query, 
                languages, 
                season, 
                episode,
                include_comments=settings.get('subdl_include_comments', False),
                include_releases=settings.get('subdl_include_releases', True),
                full_season=settings.get('subdl_full_season', False)
            )
            for result in subdl_results:
                result['site'] = 'subdl'
            all_results.extend(subdl_results)
            print(f"[API] SubDL found: {len(subdl_results)} results")
        
        # Onda probaj OpenSubtitles
        if use_opensubtitles and preferred_service in ['both', 'opensubtitles']:
            print(f"[API] Searching OpenSubtitles.com...")
            opensub_results = self.search_opensubtitles(query, languages, season, episode)
            for result in opensub_results:
                result['site'] = 'opensubtitles'
            all_results.extend(opensub_results)
            print(f"[API] OpenSubtitles found: {len(opensub_results)} results")
        
        # Ukloni duplikate
        unique_results = []
        seen = set()
        
        for result in all_results:
            # Kreiraj jedinstveni ključ
            title = result.get('title', '').lower()[:50]
            lang = result.get('language', '').lower()
            release = result.get('release_info', '').lower()[:20]
            site = result.get('site', '').lower()
            
            key = f"{title}_{lang}_{release}_{site}"
            
            if key not in seen:
                seen.add(key)
                unique_results.append(result)
        
        # Sortiraj - SubDL prvi (ima unlimited download), onda po downloads
        def sort_key(x):
            site_priority = {'subdl': 0, 'opensubtitles': 1}.get(x.get('site', '').lower(), 2)
            downloads = x.get('downloads', 0)
            rating = x.get('rating', 0)
            return (site_priority, -downloads, -rating)
        
        unique_results.sort(key=sort_key)
        
        # Ograniči broj rezultata
        max_results = settings.get('max_results', 50)
        final_results = unique_results[:max_results]
        
        print(f"[API] Total unique results: {len(final_results)}")
        return final_results
    
    # DODATE NOVE FUNKCIJE ZA SUBDL PRETRAGU
    def search_subdl_by_imdb(self, imdb_id, languages=None):
        """Pretraga SubDL po IMDB ID-u"""
        if not self.subdl_api_key:
            return []
        
        print(f"[API] Searching SubDL by IMDB ID: {imdb_id}")
        
        settings = self.config.read_settings()
        if languages is None:
            languages = settings.get('languages', ['sr', 'hr'])
        
        results = self.subdl_api.search(
            query="",  # Prazan query jer koristimo imdb_id
            languages=languages,
            imdb_id=imdb_id,
            include_comments=settings.get('subdl_include_comments', False),
            include_releases=settings.get('subdl_include_releases', True)
        )
        
        for result in results:
            result['site'] = 'subdl'
        
        return results
    
    def search_subdl_by_filename(self, filename, languages=None):
        """Pretraga SubDL po nazivu fajla"""
        if not self.subdl_api_key:
            return []
        
        print(f"[API] Searching SubDL by filename: {filename}")
        
        settings = self.config.read_settings()
        if languages is None:
            languages = settings.get('languages', ['sr', 'hr'])
        
        results = self.subdl_api.search(
            query="",  # Prazan query jer koristimo file_name
            languages=languages,
            file_name=filename,
            include_comments=settings.get('subdl_include_comments', False),
            include_releases=settings.get('subdl_include_releases', True)
        )
        
        for result in results:
            result['site'] = 'subdl'
        
        return results
    
    def search_opensubtitles(self, query, languages=None, season=None, episode=None):
        """Pretraga na OpenSubtitles.com"""
        if not self.opensubtitles_api_key:
            print("[OpenSubtitles] No API key!")
            return []
        
        if not languages:
            languages = ['sr', 'hr']
        
        # Konvertuj jezike za OpenSubtitles
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
        
        # Kreiraj query
        search_query = query
        if season is not None:
            search_query += f" S{season:02d}"
            if episode is not None:
                search_query += f"E{episode:02d}"
        
        url = f"{self.opensubtitles_base}/subtitles"
        params = {
            'query': search_query,
            'languages': ','.join(converted_languages)
        }
        
        if season is not None or episode is not None:
            params['type'] = 'episode'
        
        headers = {
            'Api-Key': self.opensubtitles_api_key,
            'User-Agent': 'Enigma2 CiefpSubtitles v1.2',
            'Accept': 'application/json'
        }
        
        try:
            response = self.session.get(url, params=params, headers=headers, timeout=15)
            
            if response.status_code != 200:
                print(f"[OpenSubtitles] Search failed: {response.status_code}")
                return []
            
            data = response.json()
            results = []
            
            for item in data.get('data', []):
                attr = item['attributes']
                files = attr.get('files', [])
                if not files:
                    continue
                
                # Proveri da li je serija
                feature_details = attr.get('feature_details', {})
                parent_title = feature_details.get('parent_title', '')
                
                results.append({
                    'title': attr.get('release_name') or feature_details.get('movie_name', 'Unknown'),
                    'language': attr.get('language', 'Unknown'),
                    'downloads': attr.get('download_count', 0),
                    'file_id': files[0]['file_id'],
                    'rating': attr.get('ratings', 0.0),
                    'fps': attr.get('fps', 0),
                    'hd': attr.get('hd', False),
                    'hearing_impaired': attr.get('hearing_impaired', False),
                    'is_series': bool(parent_title) or season is not None,
                    'season': season or feature_details.get('season_number'),
                    'episode': episode or feature_details.get('episode_number'),
                    'release_info': attr.get('release', ''),
                    'year': feature_details.get('year'),
                    'site': 'opensubtitles'
                })
            
            return results
            
        except Exception as e:
            print(f"[OpenSubtitles] Search error: {e}")
            return []
    
    def download(self, result):
        """ISPRAVLJENO: Preuzimanje titla sa odgovarajućeg servisa"""
        site = result.get('site', 'subdl').lower()
        
        print(f"[API] Downloading from {site}: {result.get('title', 'Unknown')[:50]}")
        
        if site == 'subdl':
            file_id = result.get('file_id')
            print(f"[API] SubDL file_id: {file_id}")
            if file_id:
                content = self.subdl_api.download(file_id, result.get('title', ''))
                if content:
                    print(f"[API] SubDL download successful, size: {len(content)} bytes")
                    return content
                else:
                    print(f"[API] SubDL download failed for file_id: {file_id}")
        
        elif site == 'opensubtitles':
            file_id = result.get('file_id')
            if file_id and self.opensubtitles_api_key:
                content = self.download_opensubtitles(file_id)
                if content:
                    print(f"[API] OpenSubtitles download successful, size: {len(content)} bytes")
                    return content
        
        print(f"[API] Download failed for {site}")
        return None
    
    def download_opensubtitles(self, file_id):
        """Preuzimanje sa OpenSubtitles.com"""
        if not self.opensubtitles_api_key:
            return None
        
        headers = {
            'Api-Key': self.opensubtitles_api_key,
            'Content-Type': 'application/json',
            'User-Agent': 'Enigma2 CiefpSubtitles v1.2',
            'Accept': 'application/json'
        }
        
        data = {
            "file_id": int(file_id),
            "sub_format": "srt"
        }
        
        try:
            response = requests.post(
                f"{self.opensubtitles_base}/download",
                headers=headers,
                json=data,
                timeout=15
            )
            
            if response.status_code != 200:
                print(f"[OpenSubtitles] Download failed: {response.status_code}")
                return None
            
            response_data = response.json()
            
            if 'link' in response_data:
                download_link = response_data['link']
                sub_response = requests.get(download_link, timeout=30)
                sub_response.raise_for_status()
                
                content = sub_response.content
                
                if content.startswith(b'PK'):
                    from io import BytesIO
                    from zipfile import ZipFile
                    try:
                        zipfile = ZipFile(BytesIO(content))
                        srt_files = [f for f in zipfile.namelist() if f.lower().endswith('.srt')]
                        if srt_files:
                            return zipfile.read(srt_files[0])
                        else:
                            first_file = zipfile.namelist()[0]
                            return zipfile.read(first_file)
                    except:
                        return content
                else:
                    return content
            
            return None
            
        except Exception as e:
            print(f"[OpenSubtitles] Download error: {e}")
            return None

class OpenSubtitlesConfigScreen(ConfigListScreen, Screen):
    """Ekran za konfiguraciju plugina - DODATE SUBDL OPCIJE"""
    
    skin = """
    <screen position="center,center" size="1600,800" title="Subtitles Configuration v1.2">
    <widget name="config" position="50,50" size="1100,550" scrollbarMode="showOnDemand" />
    
    <!-- Dugmad -->
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
        self["config"].l.setItemHeight(40)
        
        self["key_red"] = StaticText("Exit")
        self["key_green"] = StaticText("Save")
        self["key_yellow"] = StaticText("API Keys")
        self["key_blue"] = StaticText("Select")
        self["background"] = Pixmap()
        
        self["actions"] = ActionMap(["SetupActions", "ColorActions"],
        {
            "cancel": self.keyCancel,
            "red": self.keyCancel,
            "green": self.keySave,
            "yellow": self.editApiKeys,
            "blue": self.keyOK,
            "ok": self.keyOK,
        }, -2)
        
        self.createSetup()
        self.onLayoutFinish.append(self.layoutFinished)
    
    def layoutFinished(self):
        self.setTitle("Subtitles Configuration v1.2")
    
    def createSetup(self):
        """Kreiraj listu konfiguracija - DODATE SUBDL OPCIJE"""
        self.list = []
        
        # API ključevi
        self.api_keys_info = ConfigNothing()
        self.list.append(getConfigListEntry("API Keys Setup:", self.api_keys_info))
        
        # Servisi
        service_choices = [
            ("both", "Both services (Recommended)"),
            ("subdl", "SubDL only (Unlimited)"),
            ("opensubtitles", "OpenSubtitles only")
        ]
        self.service_choice = ConfigSelection(choices=service_choices, 
                                            default=self.settings.get('preferred_service', 'both'))
        self.list.append(getConfigListEntry("Search on:", self.service_choice))
        
        # Jezici - OBJAŠNJENJE VELIKIH SLOVA
        current_languages = self.settings.get('languages', ['sr', 'hr'])
        if isinstance(current_languages, list):
            current_languages_str = ','.join(current_languages)
        else:
            current_languages_str = str(current_languages)
        
        self.languages = ConfigText(default=current_languages_str, fixed_size=False)
        self.list.append(getConfigListEntry("Languages:", self.languages))
        
        self.lang_examples = ConfigNothing()
        self.list.append(getConfigListEntry("Examples: sr,hr or EN,DE,FR", self.lang_examples))
        
        # Putanja za čuvanje
        self.save_path = ConfigText(default=self.settings.get('save_path', '/media/hdd/subtitles/'), fixed_size=False)
        self.list.append(getConfigListEntry("Save path:", self.save_path))
        
        # SUBDL SPECIFIČNE OPCIJE
        self.subdl_options = ConfigNothing()
        self.list.append(getConfigListEntry("--- SubDL Options ---", self.subdl_options))
        
        self.subdl_include_releases = ConfigYesNo(default=self.settings.get('subdl_include_releases', True))
        self.list.append(getConfigListEntry("SubDL: Include releases:", self.subdl_include_releases))
        
        self.subdl_include_comments = ConfigYesNo(default=self.settings.get('subdl_include_comments', False))
        self.list.append(getConfigListEntry("SubDL: Include comments:", self.subdl_include_comments))
        
        self.subdl_full_season = ConfigYesNo(default=self.settings.get('subdl_full_season', False))
        self.list.append(getConfigListEntry("SubDL: Full season search:", self.subdl_full_season))
        
        # Ostale opcije
        self.auto_download = ConfigYesNo(default=self.settings.get('auto_download', False))
        self.list.append(getConfigListEntry("Auto download:", self.auto_download))
        
        self.multi_lang_download = ConfigYesNo(default=self.settings.get('multi_lang_download', False))
        self.list.append(getConfigListEntry("Multi-language download:", self.multi_lang_download))
        
        max_results_choices = [("20", "20"), ("30", "30"), ("50", "50"), ("100", "100")]
        self.max_results = ConfigSelection(choices=max_results_choices, 
                                         default=str(self.settings.get('max_results', 50)))
        self.list.append(getConfigListEntry("Max results:", self.max_results))
        
        self.download_info = ConfigNothing()
        self.list.append(getConfigListEntry("SubDL: Unlimited, OpenSubtitles: 5/day", self.download_info))
        
        self["config"].list = self.list
        self["config"].l.setList(self.list)
    
    def editApiKeys(self):
        """Otvaranje ekrana za editovanje API ključeva"""
        self.session.open(OpenSubtitlesApiKeysScreen, self.plugin)
    
    def keyOK(self):
        """Plavo dugme - Select / Edit"""
        current = self["config"].getCurrent()
        if current:
            if current[1] == self.languages:
                self.session.openWithCallback(
                    self.VirtualKeyBoardCallback,
                    VirtualKeyBoard,
                    title="Enter languages (comma separated)\nExamples: sr,hr,en or EN,DE,FR\nNote: SubDL uses UPPERCASE codes",
                    text=current[1].value
                )
            elif current[1] == self.save_path:
                self.session.openWithCallback(
                    self.VirtualKeyBoardCallback,
                    VirtualKeyBoard,
                    title="Enter save directory path",
                    text=current[1].value
                )
            elif current[1] == self.api_keys_info:
                help_text = """API KEYS CONFIGURATION:

1. OpenSubtitles.com API Key:
   • Get from: https://www.opensubtitles.com
   • Free account: 5 downloads/24h
   • VIP account: 1000 downloads/day

2. SubDL API Key:
   • Get from: https://subdl.com
   • Registered account needed
   • Unlimited downloads!

Press YELLOW to edit API keys."""
                self.session.open(MessageBox, help_text, MessageBox.TYPE_INFO)
            elif current[1] == self.lang_examples:
                help_text = """LANGUAGE CODES:

IMPORTANT: SubDL uses UPPERCASE codes!

2-letter codes (UPPERCASE for SubDL):
• SR (Serbian), HR (Croatian), BS (Bosnian)
• SL (Slovenian), EN (English), DE (German)
• FR (French), ES (Spanish), IT (Italian)
• RU (Russian), AR (Arabic), MK (Macedonian)

Plugin automatically converts lowercase to uppercase for SubDL.

Examples:
• sr,hr,en (will be converted to SR,HR,EN for SubDL)
• EN,DE,FR (use uppercase for clarity)"""
                self.session.open(MessageBox, help_text, MessageBox.TYPE_INFO)
            elif current[1] == self.download_info:
                help_text = """DOWNLOAD LIMITS:

SubDL:
• UNLIMITED downloads
• No daily restrictions
• Best choice for heavy use
• Requires API key from subdl.com

OpenSubtitles.com:
• Free: 5 downloads every 24 hours
• VIP: 1000 downloads/day
• Resets based on account time

NEW in v1.2:
• THREE search methods
• SMART search (auto-tries all)
• Shows which method worked
• Better debugging

RECOMMENDATION:
Use SMART search for best results!"""
                self.session.open(MessageBox, help_text, MessageBox.TYPE_INFO)
            elif current[1] == self.subdl_options:
                help_text = """SUBDL OPTIONS:

Include releases: Show release info (DVDrip, HDTV, etc.)
Include comments: Show uploader comments
Full season search: Search for all episodes in season

These options require SubDL API key to work."""
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
        
        self.settings['preferred_service'] = self.service_choice.value
        self.settings['languages'] = languages_list
        self.settings['save_path'] = self.save_path.value
        self.settings['auto_download'] = self.auto_download.value
        self.settings['multi_lang_download'] = self.multi_lang_download.value
        self.settings['max_results'] = int(self.max_results.value)
        
        # SubDL specifične opcije
        self.settings['subdl_include_releases'] = self.subdl_include_releases.value
        self.settings['subdl_include_comments'] = self.subdl_include_comments.value
        self.settings['subdl_full_season'] = self.subdl_full_season.value
        
        # Ako je save path prazan, koristi podrazumevani
        if not self.save_path.value.strip():
            self.settings['save_path'] = '/media/hdd/subtitles/'
        
        if self.save_path.value and not pathExists(self.save_path.value):
            try:
                createDir(self.save_path.value)
            except:
                self.session.open(MessageBox, 
                                "Cannot create save directory!", 
                                MessageBox.TYPE_ERROR)
        
        if self.config_obj.write_settings(self.settings):
            self.plugin.api.config = self.config_obj
            self.plugin.api.update_api_keys()
            self.close(True)
        else:
            self.session.open(MessageBox, 
                            "Error saving configuration!", 
                            MessageBox.TYPE_ERROR)
    
    def keyCancel(self):
        """Crveno dugme - Exit"""
        self.close(False)

class OpenSubtitlesApiKeysScreen(Screen):
    """Ekran za editovanje API ključeva"""
    
    skin = """
    <screen position="center,center" size="800,800" title="API Keys Configuration">
        <widget name="info" position="10,10" size="780,50" font="Regular;28" halign="center" valign="center" />
        <widget source="key_red" render="Label" position="50,80" size="160,50" backgroundColor="#9f1313" foregroundColor="white" font="Regular;24" halign="center" valign="center" />
        <widget source="key_green" render="Label" position="230,80" size="160,50" backgroundColor="#1f771f" foregroundColor="white" font="Regular;24" halign="center" valign="center" />
        <widget source="key_yellow" render="Label" position="410,80" size="160,50" backgroundColor="#a08500" foregroundColor="white" font="Regular;24" halign="center" valign="center" />
        <widget source="key_blue" render="Label" position="590,80" size="160,50" backgroundColor="#18188b" foregroundColor="white" font="Regular;24" halign="center" valign="center" />
        <widget name="status" position="50,150" size="700,700" font="Regular;26" valign="center" />
    </screen>
    """
    
    def __init__(self, session, plugin):
        Screen.__init__(self, session)
        self.session = session
        self.plugin = plugin
        
        self["key_red"] = StaticText("Exit")
        self["key_green"] = StaticText("SubDL Key")
        self["key_yellow"] = StaticText("OpenSubtitles")
        self["key_blue"] = StaticText("Test Keys")
        self["info"] = Label("Edit API Keys for subtitle services")
        self["status"] = Label("")
        
        self["actions"] = ActionMap(["ColorActions", "SetupActions"],
        {
            "red": self.close,
            "green": self.editSubDLKey,
            "yellow": self.editOpenSubtitlesKey,
            "blue": self.testApiKeys,
            "cancel": self.close,
        }, -2)
        
        self.config_obj = OpenSubtitlesConfig()
        
        self.onLayoutFinish.append(self.updateStatus)
    
    def updateStatus(self):
        """Ažuriraj statusnu poruku"""
        subdl_key = self.config_obj.read_subdl_api_key()
        opensub_key = self.config_obj.read_opensubtitles_api_key()
        
        status_text = "API Keys Status:\n\n"
        # SubDL
        if subdl_key:
            masked_key = subdl_key[:8] + "..." + subdl_key[-4:] if len(subdl_key) > 12 else subdl_key
            status_text += "✓ SubDL: API Key configured\n"
            status_text += f"  Key: {masked_key}\n"
        else:
            status_text += "✗ SubDL: No API key\n"
            status_text += "  Get from: https://subdl.com\n"
        
        status_text += "  Downloads: UNLIMITED\n"
        status_text += "  Code format: UPPERCASE (EN, SR, HR)\n\n"
        
        # OpenSubtitles
        if opensub_key:
            masked_key = opensub_key[:8] + "..." + opensub_key[-4:] if len(opensub_key) > 12 else opensub_key
            status_text += "✓ OpenSubtitles: API Key configured\n"
            status_text += f"  Key: {masked_key}\n"
        else:
            status_text += "✗ OpenSubtitles: No API key\n"
            status_text += "  Get from: https://opensubtitles.com\n"
        
        status_text += "  Downloads: 5/24h (free), 1000/day (VIP)\n"
        status_text += "  Code format: lowercase (en, sr, hr)\n\n"
        
        status_text += "Instructions:\n"
        status_text += "• GREEN: Edit SubDL API Key\n"
        status_text += "• YELLOW: Edit OpenSubtitles API Key\n"
        status_text += "• BLUE: Test API Keys\n"
        status_text += "• RED: Exit"
        
        self["status"].setText(status_text)
    
    def editSubDLKey(self):
        """Editovanje SubDL API ključa"""
        current_key = self.config_obj.read_subdl_api_key()
        self.session.openWithCallback(
            self.subdlKeyCallback,
            VirtualKeyBoard,
            title="Enter SubDL API Key\nGet from: https://subdl.com\n\nIMPORTANT: SubDL uses UPPERCASE language codes (EN, SR, HR)",
            text=current_key
        )
    
    def subdlKeyCallback(self, callback=None):
        """Callback za SubDL ključ"""
        if callback is not None and callback.strip():
            if self.config_obj.write_subdl_api_key(callback.strip()):
                self.plugin.api.subdl_api_key = callback.strip()
                self.plugin.api.subdl_api.set_api_key(callback.strip())
                self.updateStatus()
                self["status"].setText("SubDL API Key saved successfully!\n\nMake sure to use UPPERCASE language codes (EN, SR, HR) for SubDL.")
                self.status_timer = eTimer()
                self.status_timer.callback.append(self.restoreStatus)
                self.status_timer.start(3000, True)
            else:
                self["status"].setText("Error saving SubDL API Key!")
    
    def editOpenSubtitlesKey(self):
        """Editovanje OpenSubtitles API ključa"""
        current_key = self.config_obj.read_opensubtitles_api_key()
        self.session.openWithCallback(
            self.opensubKeyCallback,
            VirtualKeyBoard,
            title="Enter OpenSubtitles.com API Key\nGet from: https://opensubtitles.com",
            text=current_key
        )
    
    def opensubKeyCallback(self, callback=None):
        """Callback za OpenSubtitles ključ"""
        if callback is not None and callback.strip():
            if self.config_obj.write_opensubtitles_api_key(callback.strip()):
                self.plugin.api.opensubtitles_api_key = callback.strip()
                self.updateStatus()
                self["status"].setText("OpenSubtitles API Key saved successfully!")
                self.status_timer = eTimer()
                self.status_timer.callback.append(self.restoreStatus)
                self.status_timer.start(3000, True)
            else:
                self["status"].setText("Error saving OpenSubtitles API Key!")
    
    def testApiKeys(self):
        """Testiranje API ključeva - POBOLJŠANO"""
        subdl_key = self.config_obj.read_subdl_api_key()
        opensub_key = self.config_obj.read_opensubtitles_api_key()
        
        test_results = []
        
        # Test SubDL - POBOLJŠANO SA ISPRAVNIM PARAMETRIMA
        if subdl_key:
            test_results.append("Testing SubDL API Key...")
            try:
                test_api = SubDLAPI()
                test_api.set_api_key(subdl_key)
                # Test search sa jednostavnim upitom i VELIKIM SLOVIMA
                results = test_api.search("test", ["EN"], include_releases=True)
                if results:
                    test_results.append("✓ SubDL: API Key VALID")
                    test_results.append(f"  Found {len(results)} test results")
                    test_results.append(f"  First result: {results[0].get('title', 'Unknown')[:40]}")
                    
                    # Proveri file_id format
                    file_id = results[0].get('file_id', '')
                    if file_id and '-' in file_id:
                        test_results.append(f"  File ID format: OK ({file_id[:20]}...)")
                    else:
                        test_results.append(f"  ⚠ File ID format may be incorrect")
                else:
                    test_results.append("✗ SubDL: No results found (may be API key issue)")
                    test_results.append("  Check if API key is valid and language codes are UPPERCASE")
            except Exception as e:
                test_results.append(f"✗ SubDL: Error testing API - {str(e)[:100]}")
        else:
            test_results.append("✗ SubDL: No API key configured")
        
        # Test OpenSubtitles
        if opensub_key:
            test_results.append("\nTesting OpenSubtitles API Key...")
            try:
                headers = {
                    'Api-Key': opensub_key,
                    'User-Agent': 'Enigma2 Test'
                }
                response = requests.get("https://api.opensubtitles.com/api/v1/info", 
                                       headers=headers, timeout=10)
                if response.status_code == 200:
                    test_results.append("✓ OpenSubtitles: API Key VALID")
                    data = response.json()
                    user = data.get('user', {})
                    if user:
                        test_results.append(f"  User: {user.get('username', 'Unknown')}")
                        remaining = user.get('remaining_downloads', 0)
                        test_results.append(f"  Remaining downloads: {remaining}")
                else:
                    test_results.append(f"✗ OpenSubtitles: API Key invalid (Status: {response.status_code})")
            except Exception as e:
                test_results.append(f"✗ OpenSubtitles: Error testing API - {str(e)}")
        else:
            test_results.append("\n✗ OpenSubtitles: No API key configured")
        
        test_text = "\n".join(test_results)
        self.session.open(MessageBox, test_text, MessageBox.TYPE_INFO)
    
    def restoreStatus(self):
        """Vrati originalni status tekst"""
        self.updateStatus()

class OpenSubtitlesSearchScreen(Screen):
    """Ekran za STANDARD pretragu titlova filmova"""

    skin = """
    <screen position="center,center" size="1600,800" title="Standard Search v1.2" backgroundColor="#000000">
        <eLabel position="0,0" size="1600,800" backgroundColor="#000000" zPosition="-10" />

        <widget name="input_label" position="50,30" size="200,40" font="Regular;28" foregroundColor="#ffffff" valign="center" />

        <eLabel position="260,30" size="700,40" backgroundColor="#222222" />

        <!-- Input field -->
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
    </screen>
    """

    def __init__(self, session, plugin, initial_query=""):
        Screen.__init__(self, session)
        self.session = session
        self.plugin = plugin
        self.initial_query = initial_query

        self["input_label"] = Label("Search:")
        self["input"] = Label(initial_query or "")
        self["status"] = Label("STANDARD Search - Uses Film Name only")
        self["background"] = Pixmap()

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
        if not search_text or not search_text.strip():
            self["status"].setText("STANDARD Search - Uses Film Name only")
        else:
            self["status"].setText(f"STANDARD search: {search_text[:30]}...")

    def openKeyboard(self):
        current_text = self["input"].getText()
        self.session.openWithCallback(
            self.keyboardCallback,
            VirtualKeyBoard,
            title="STANDARD Search - Film Name only",
            text=current_text
        )

    def keyboardCallback(self, callback=None):
        if callback is not None:
            cleaned_text = callback.strip()
            self["input"].setText(cleaned_text)
            self.updateDisplay()
            if cleaned_text:
                self.doSearch()

    def doSearch(self):
        query = self["input"].getText().strip()
        if not query:
            self["status"].setText("Please enter search term")
            return

        self["status"].setText(f"STANDARD searching: '{query}'...")

        settings = self.plugin.api.config.read_settings()
        languages = settings.get('languages', ['sr', 'hr'])
        service = settings.get('preferred_service', 'both')

        print(f"[STANDARD SEARCH] Searching for: '{query}'")
        print(f"[STANDARD SEARCH] Languages: {languages}")
        print(f"[STANDARD SEARCH] Service: {service}")

        # Koristimo STANDARD API (film_name samo)
        results = self.plugin.api.search_all(query, languages)

        print(f"[STANDARD SEARCH] Got {len(results)} results")

        self.results_list = results or []
        
        if not self.results_list:
            list_items = ["No results found with STANDARD search"]
            self["results"].setList(list_items)
            self["status"].setText("STANDARD search: No subtitles found.")
            return

        list_items = []
        
        for idx, result in enumerate(self.results_list, 1):
            title = result.get('title', 'Unknown Title')
            language = result.get('language', 'Unknown').upper()
            site = result.get('site', '').upper()
            
            # Oznaka servisa
            if site == 'SUBDL':
                site_indicator = "[SubDL] "
                service_color = " (Unlimited)"
            elif site == 'OPENSUBTITLES':
                site_indicator = "[OS] "
                service_color = " (5/day)"
            else:
                site_indicator = ""
                service_color = ""
            
            year = result.get('year', '')
            year_prefix = f"{year} - " if year and str(year).isdigit() else ""

            # Skrati naslov
            display_title = title[:40]
            if len(title) > 40:
                display_title = title[:37] + "..."

            display_text = f"{idx}. {site_indicator}{year_prefix}{display_title}"
            
            # Info delovi
            info_parts = []
            
            # Dodaj jezik
            info_parts.append(f"Lang: {language}")
            
            # Dodaj FPS samo za OpenSubtitles
            if site == 'OPENSUBTITLES':
                fps = result.get('fps')
                if fps and fps > 0:
                    info_parts.append(f"FPS: {fps}")
            
            # Dodaj broj download-a
            downloads = result.get('downloads', 0)
            if downloads > 0:
                # Formatiraj broj
                if downloads >= 1000000:
                    dl_str = f"{downloads/1000000:.1f}M"
                elif downloads >= 1000:
                    dl_str = f"{downloads/1000:.1f}K"
                else:
                    dl_str = str(downloads)
                info_parts.append(f"↓{dl_str}")
            
            # Dodaj rating
            rating = result.get('rating', 0)
            if rating and rating > 0:
                info_parts.append(f"⭐{rating:.1f}")
            
            # Dodaj HD oznaku
            if result.get('hd'):
                info_parts.append("HD")
            
            # Dodaj HI oznaku
            if result.get('hearing_impaired'):
                info_parts.append("HI")
            
            # Dodaj service info
            if service_color:
                info_parts.append(service_color)
            
            # Dodaj release info
            release = result.get('release_info', '')
            if release and len(release) < 20:
                display_text += f" - {release}"
            
            # Dodaj info delove
            if info_parts:
                display_text += f" ({' | '.join(info_parts)})"
            
            list_items.append(display_text)

        self["results"].setList(list_items)

        # Prikaži statistiku
        site_counts = {}
        for result in self.results_list:
            site = result.get('site', 'Unknown')
            site_counts[site] = site_counts.get(site, 0) + 1
        
        total_results = len(self.results_list)
        
        # Ako ima SubDL rezultata, istakni ih
        subdl_count = site_counts.get('subdl', 0)
        opensub_count = site_counts.get('opensubtitles', 0)
        
        if subdl_count > 0 and opensub_count > 0:
            self["status"].setText(f"STANDARD: {total_results} results ({subdl_count} SubDL, {opensub_count} OpenSubtitles)")
        elif subdl_count > 0:
            self["status"].setText(f"STANDARD: {total_results} results (All from SubDL)")
        elif opensub_count > 0:
            self["status"].setText(f"STANDARD: {total_results} results (All from OpenSubtitles)")
        else:
            self["status"].setText(f"STANDARD: {total_results} results")

    def downloadSelected(self):
        selected_idx = self["results"].getSelectedIndex()

        if not self.results_list or selected_idx >= len(self.results_list):
            self["status"].setText("No item selected!")
            return

        result = self.results_list[selected_idx]
        site = result.get('site', 'Unknown')
        title = result.get('title', 'Unknown')
        
        file_id = result.get('file_id', 'N/A')
        print(f"[STANDARD SEARCH] Downloading from {site}: {title}, file_id: {file_id}")
        
        self["status"].setText(f"Downloading from {site}: {title[:30]}...")

        settings = self.plugin.api.config.read_settings()
        multi_lang = settings.get('multi_lang_download', False)
        priority_language = settings.get('priority_language', 'first')

        if multi_lang and priority_language == 'all':
            self.downloadAllLanguages(result)
        else:
            self.downloadSingleSubtitle(result)

    def downloadSingleSubtitle(self, result):
        print(f"[STANDARD SEARCH] Downloading from {result.get('site', 'unknown')}")
        print(f"[STANDARD SEARCH] File ID: {result.get('file_id', 'N/A')}")

        content = self.plugin.api.download(result)
        
        if content:
            self.saveSubtitle(content, result)
        else:
            self.showDownloadError(result.get('site', 'Unknown'), result.get('file_id', 'N/A'))

    def downloadAllLanguages(self, result):
        print(f"[STANDARD SEARCH] Downloading all languages")

        title = result.get('title', 'Unknown')
        self["status"].setText(f"Searching all languages for: {title[:30]}...")

        settings = self.plugin.api.config.read_settings()
        languages = settings.get('languages', ['sr', 'hr'])

        if 'all' in languages:
            languages = ['sr', 'hr', 'bs', 'sl', 'en']

        downloaded_count = 0

        for lang in languages:
            # Pretraži za svaki jezik
            search_results = self.plugin.api.search_all(title, [lang])
            
            if search_results:
                # Preuzmi prvi rezultat za ovaj jezik
                for sub_result in search_results:
                    if sub_result.get('language', '').lower().startswith(lang[:2]):
                        content = self.plugin.api.download(sub_result)
                        if content:
                            self.saveSubtitle(content, sub_result)
                            downloaded_count += 1
                            break

        if downloaded_count > 0:
            self["status"].setText(f"Downloaded {downloaded_count} language(s)")
            self.session.open(MessageBox,
                              f"Successfully downloaded {downloaded_count} subtitle(s)!",
                              MessageBox.TYPE_INFO,
                              timeout=5)
        else:
            self.showDownloadError("all", "")

    def saveSubtitle(self, content, result):
        settings = self.plugin.api.config.read_settings()
        save_path = settings.get('save_path', '/media/hdd/subtitles/')

        # Kreiraj naziv fajla
        title = result.get('title', 'subtitle').replace(' ', '_')
        title = re.sub(r'[^\w\-_]', '', title)
        language = result.get('language', 'unknown').lower()
        site = result.get('site', 'unknown')
        timestamp = int(time.time())
        
        # Ekstenzija
        ext = '.srt'
        if isinstance(content, bytes):
            if content.startswith(b'WEBVTT'):
                ext = '.vtt'
            elif content.startswith(b'1\r\n0'):
                ext = '.sub'
            elif b'[Script Info]' in content[:100]:
                ext = '.ass'
        
        filename = f"{title}_{site}_{language}_{timestamp}{ext}"
        full_path = os.path.join(save_path, filename)

        try:
            if not pathExists(save_path):
                createDir(save_path)

            if isinstance(content, str):
                content = content.encode('utf-8')

            with open(full_path, 'wb') as f:
                f.write(content)

            self["status"].setText(f"Downloaded: {filename}")
            
            # Auto-map
            self.autoMapSubtitle(full_path, title)
            
            self.session.open(MessageBox,
                              f"Subtitle downloaded successfully!\n\nSaved to: {full_path}",
                              MessageBox.TYPE_INFO,
                              timeout=5)

        except Exception as e:
            print(f"[STANDARD SEARCH] Error saving subtitle: {e}")
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
                                print(f"[STANDARD SEARCH] Auto-mapped subtitle to: {new_name}")
                                return True
            return False
        except Exception as e:
            print(f"[STANDARD SEARCH] Auto-map error: {e}")
            return False

    def showDownloadError(self, site, file_id=""):
        if site.lower() == 'subdl':
            error_msg = f"""SubDL download failed!

Possible reasons:
1. Invalid or expired API key
2. Subtitle removed from SubDL
3. Network error or timeout
4. Incorrect file_id format: {file_id}

Solutions:
• Check your SubDL API key in configuration
• Try a different subtitle result
• Ensure language codes are UPPERCASE (EN, SR, HR)
• Try SMART search instead"""
        elif site.lower() == 'opensubtitles':
            error_msg = """OpenSubtitles download failed!

Possible reasons:
1. Daily limit reached (5 downloads for free)
2. Invalid API key
3. Subtitle removed

Try again tomorrow or use SubDL for unlimited downloads."""
        else:
            error_msg = """Download failed!

Check:
1. API keys in configuration (both services)
2. Internet connection
3. Try different result
4. Try SMART search"""
        
        self["status"].setText("Download failed!")
        self.session.open(MessageBox, error_msg, MessageBox.TYPE_ERROR)

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

class OpenSubtitlesSmartSearchScreen(Screen):
    """Ekran za SMART pretragu titlova - NOVO U v1.2"""

    skin = """
    <screen position="center,center" size="1600,800" title="Smart Search v1.2" backgroundColor="#000000">
        <eLabel position="0,0" size="1200,800" backgroundColor="#000000" zPosition="-10" />

        <widget name="header" position="50,20" size="1200,50" font="Regular;30" 
                foregroundColor="#ffff00" halign="center" valign="center" />

        <widget name="input_label" position="50,80" size="200,40" font="Regular;28" 
                foregroundColor="#ffffff" valign="center" />

        <eLabel position="260,80" size="700,40" backgroundColor="#222222" />
        <widget name="input" position="270,85" size="680,30"
                font="Regular;28" foregroundColor="#ffff00" backgroundColor="#222222" />

        <widget name="results" position="50,150" size="1100,500" enableWrapAround="1" 
                scrollbarMode="showOnDemand" backgroundColor="#111111" foregroundColor="#ffffff" 
                itemHeight="48" font="Regular;24" />

        <eLabel position="50,670" size="700,30" backgroundColor="#333333" />
        <widget name="status" position="60,675" size="680,20" 
                font="Regular;22" foregroundColor="#ffff00" transparent="1" />

        <!-- Dugmad -->
        <eLabel text="Exit" position="50,720" size="150,50" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#9f1313" halign="center" valign="center" />
        <eLabel text="Search" position="230,720" size="150,50" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#1f771f" halign="center" valign="center" />
        <eLabel text="Keyboard" position="410,720" size="150,50" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#a08500" halign="center" valign="center" />
        <eLabel text="Download" position="590,720" size="150,50" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#18188b" halign="center" valign="center" />

        <!-- Desna strana sa informacijama -->
      
        <!-- TEKST direktno preko slike (bez pozadine) -->
        <widget name="info" position="1210,60" size="330,680" font="Regular;22" 
                foregroundColor="#ffffff" transparent="1" />
        
        <widget name="background" position="1200,0" size="400,800" 
                pixmap="/usr/lib/enigma2/python/Plugins/Extensions/CiefpOpenSubtitles/background.png" />
    </screen>
    """
    
    def __init__(self, session, plugin, initial_query=""):
        Screen.__init__(self, session)
        self.session = session
        self.plugin = plugin
        self.initial_query = initial_query

        self["header"] = Label("SMART SEARCH - Tries IMDB → File Name → Film Name")
        self["input_label"] = Label("Search:")
        self["input"] = Label(initial_query or "")
        self["status"] = Label("Enter search term - SMART search will try all methods")
        self["info"] = Label(self.get_info_text())
        self["background"] = Pixmap()

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
    
    def get_info_text(self):
        """Vraća tekst sa informacijama za smart search"""
        return """SMART SEARCH v1.2

Search Order:
1. IMDB ID (best)
   Format: tt1375666
   Or: imdb:tt1375666

2. File Name (good)
   Format: Movie.Name.2023.1080p
   Clean filename without special chars

3. Film Name (ok)
   Regular movie title

Examples:
• tt1375666 (Inception)
• Home.Alone.2.1992
• The Matrix

TIP: For TV series:
• Series.Name.S01E02
• tt0944947 (Game of Thrones)

Logs show which method found each result!"""
    
    def updateDisplay(self):
        search_text = self["input"].getText()
        if not search_text or not search_text.strip():
            self["status"].setText("Enter search term for SMART search")
        else:
            self["status"].setText(f"Ready for SMART search: {search_text[:30]}...")
    
    def openKeyboard(self):
        current_text = self["input"].getText()
        self.session.openWithCallback(
            self.keyboardCallback,
            VirtualKeyBoard,
            title="Enter search term for SMART search",
            text=current_text
        )
    
    def keyboardCallback(self, callback=None):
        if callback is not None:
            cleaned_text = callback.strip()
            self["input"].setText(cleaned_text)
            self.updateDisplay()
            if cleaned_text:
                self.doSearch()
    
    def doSearch(self):
        query = self["input"].getText().strip()
        if not query:
            self["status"].setText("Please enter search term")
            return

        self["status"].setText(f"SMART searching: '{query}'...")

        settings = self.plugin.api.config.read_settings()
        languages = settings.get('languages', ['sr', 'hr'])

        print(f"[SMART SEARCH] Starting smart search for: '{query}'")
        
        # KORISTI NOVU SMART SEARCH METODU
        results = self.plugin.api.search_all_smart(query, languages)

        print(f"[SMART SEARCH] Got {len(results)} results from smart search")

        self.results_list = results or []
        
        if not self.results_list:
            list_items = ["No results found with SMART search"]
            self["results"].setList(list_items)
            self["status"].setText("SMART search: No subtitles found.")
            return

        list_items = []
        
        for idx, result in enumerate(self.results_list, 1):
            title = result.get('title', 'Unknown Title')
            language = result.get('language', 'Unknown').upper()
            site = result.get('site', '').upper()
            method = result.get('search_method', '').upper()
            
            # Oznaka kvaliteta
            quality_indicator = ""
            if site == 'SUBDL':
                if method == 'IMDB':
                    quality_indicator = "⭐ "  # Najbolje
                elif method == 'FILE_NAME':
                    quality_indicator = "✓ "   # Dobro
                elif method == 'FILM_NAME':
                    quality_indicator = "~ "   # OK
            
            display_text = f"{idx}. {quality_indicator}{title[:45]}"
            if len(title) > 45:
                display_text = display_text[:42] + "..."
            
            # Info delovi
            info_parts = [f"Lang: {language}"]
            
            # Dodaj metod ako nije u naslovu
            if method and method != 'STANDARD':
                info_parts.append(f"Via: {method}")
            
            # Downloads
            downloads = result.get('downloads', 0)
            if downloads > 0:
                if downloads >= 1000000:
                    dl_str = f"{downloads/1000000:.1f}M"
                elif downloads >= 1000:
                    dl_str = f"{downloads/1000:.1f}K"
                else:
                    dl_str = str(downloads)
                info_parts.append(f"↓{dl_str}")
            
            # HD/HI
            if result.get('hd'):
                info_parts.append("HD")
            if result.get('hearing_impaired'):
                info_parts.append("HI")
            
            # Release info
            release = result.get('release_info', '')
            if release and len(release) < 20:
                display_text += f" - {release}"
            
            if info_parts:
                display_text += f" ({' | '.join(info_parts)})"
            
            list_items.append(display_text)

        self["results"].setList(list_items)

        # Prikaži statistiku
        method_counts = {'imdb': 0, 'file_name': 0, 'film_name': 0, 'opensubtitles': 0}
        for result in self.results_list:
            method = result.get('search_method', '').lower()
            site = result.get('site', '').lower()
            
            if site == 'opensubtitles':
                method_counts['opensubtitles'] += 1
            elif method in method_counts:
                method_counts[method] += 1
        
        stats_parts = []
        if method_counts['imdb'] > 0:
            stats_parts.append(f"⭐IMDB: {method_counts['imdb']}")
        if method_counts['file_name'] > 0:
            stats_parts.append(f"✓File: {method_counts['file_name']}")
        if method_counts['film_name'] > 0:
            stats_parts.append(f"~Film: {method_counts['film_name']}")
        if method_counts['opensubtitles'] > 0:
            stats_parts.append(f"OS: {method_counts['opensubtitles']}")
        
        total = len(self.results_list)
        stats_text = " + ".join(stats_parts) if stats_parts else "No results"
        self["status"].setText(f"SMART: {total} results ({stats_text})")
    
    def downloadSelected(self):
        """Ista download logika kao u originalu"""
        selected_idx = self["results"].getSelectedIndex()

        if not self.results_list or selected_idx >= len(self.results_list):
            self["status"].setText("No item selected!")
            return

        result = self.results_list[selected_idx]
        site = result.get('site', 'Unknown')
        title = result.get('title', 'Unknown')
        
        # Ukloni quality indicator iz naslova ako postoji
        clean_title = title
        if title.startswith(('⭐ ', '✓ ', '~ ')):
            clean_title = title[2:]
        
        file_id = result.get('file_id', 'N/A')
        method = result.get('search_method', 'unknown')
        
        print(f"[SMART SEARCH] Downloading from {site} ({method}): {clean_title[:30]}")
        self["status"].setText(f"Downloading {method} result: {clean_title[:30]}...")

        content = self.plugin.api.download(result)
        
        if content:
            self.saveSubtitle(content, result)
        else:
            self.showDownloadError(site, method, file_id)
    
    def saveSubtitle(self, content, result):
        """Ista save logika kao u originalu"""
        settings = self.plugin.api.config.read_settings()
        save_path = settings.get('save_path', '/media/hdd/subtitles/')

        # Kreiraj naziv fajla
        title = result.get('title', 'subtitle').replace(' ', '_')
        title = re.sub(r'[^\w\-_]', '', title)
        language = result.get('language', 'unknown').lower()
        site = result.get('site', 'unknown')
        method = result.get('search_method', 'unknown')
        timestamp = int(time.time())
        
        # Ekstenzija
        ext = '.srt'
        if isinstance(content, bytes):
            if content.startswith(b'WEBVTT'):
                ext = '.vtt'
            elif content.startswith(b'1\r\n0'):
                ext = '.sub'
            elif b'[Script Info]' in content[:100]:
                ext = '.ass'
        
        filename = f"{title}_{site}_{method}_{language}_{timestamp}{ext}"
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
                              f"Subtitle downloaded successfully!\n\nMethod: {method.upper()}\nSaved to: {full_path}",
                              MessageBox.TYPE_INFO,
                              timeout=5)

        except Exception as e:
            print(f"[SMART SEARCH] Error saving subtitle: {e}")
            self["status"].setText(f"Error saving: {str(e)}")
            self.session.open(MessageBox,
                              f"Error saving subtitle: {str(e)}",
                              MessageBox.TYPE_ERROR)
    
    def showDownloadError(self, site, method, file_id=""):
        """Poboljšana error poruka za SMART search"""
        if site.lower() == 'subdl':
            error_msg = f"""SubDL download failed!

Search Method: {method.upper()}
File ID: {file_id}

Possible reasons:
1. API key issue
2. Subtitle removed
3. Network error
4. Try different search method

Recommendation:
• Try IMDB search (tt1375666 format)
• Or try File Name search"""
        else:
            error_msg = f"""Download failed!

Search Method: {method.upper()}
Service: {site}

Try SMART search again or use different method."""
        
        self["status"].setText(f"{method.upper()} download failed!")
        self.session.open(MessageBox, error_msg, MessageBox.TYPE_ERROR)
    
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

class OpenSubtitlesAdvancedSearchScreen(Screen):
    """Ekran za naprednu pretragu - ADVANCED SEARCH"""
    
    skin = """
    <screen position="center,center" size="1600,800" title="Advanced Search v1.2">
        <eLabel position="0,0" size="1600,800" backgroundColor="#000000" zPosition="-10" />
        
        <widget name="header" position="50,30" size="1200,50" font="Regular;32" 
                foregroundColor="#ffff00" halign="center" valign="center" />
        
        <widget name="search_type_label" position="50,100" size="200,40" 
                font="Regular;28" foregroundColor="#ffffff" valign="center" />
        <widget name="search_type" position="260,100" size="400,40" 
                font="Regular;28" foregroundColor="#ffff00" />
                
        <widget name="query_label" position="50,160" size="200,40" 
                font="Regular;28" foregroundColor="#ffffff" valign="center" />
        <eLabel position="260,160" size="700,40" backgroundColor="#222222" />
        <widget name="query" position="270,165" size="680,30"
                font="Regular;28" foregroundColor="#ffff00" backgroundColor="#222222" />
        
        <widget name="results" position="50,230" size="1100,450" enableWrapAround="1" 
                scrollbarMode="showOnDemand" backgroundColor="#111111" foregroundColor="#ffffff" 
                itemHeight="50" font="Regular;24" />
        
        <eLabel position="50,700" size="700,30" backgroundColor="#333333" />
        <widget name="status" position="60,705" size="680,20" 
                font="Regular;22" foregroundColor="#ffff00" transparent="1" />
        
        <eLabel text="Exit" position="50,745" size="150,45" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#9f1313" halign="center" valign="center" />
        <eLabel text="Search" position="230,745" size="150,45" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#1f771f" halign="center" valign="center" />
        <eLabel text="Keyboard" position="410,745" size="150,45" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#a08500" halign="center" valign="center" />
        <eLabel text="Download" position="590,745" size="150,45" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#18188b" halign="center" valign="center" />
        
        <widget name="background" position="1200,0" size="400,800" 
                pixmap="/usr/lib/enigma2/python/Plugins/Extensions/CiefpOpenSubtitles/background.png" />
    </screen>
    """
    
    def __init__(self, session, plugin):
        Screen.__init__(self, session)
        self.session = session
        self.plugin = plugin
        
        self["header"] = Label("ADVANCED SEARCH - Manual choice use ↑↓ arrows")
        self["search_type_label"] = Label("Search by:")
        self["search_type"] = Label("Film Name")
        self["query_label"] = Label("Search term:")
        self["query"] = Label("")
        self["status"] = Label("Select search type and enter term")
        self["background"] = Pixmap()
        
        self["results"] = MenuList([])
        self.results_list = []
        
        self.search_types = ["↑ Film Name ↓", "↑ IMDB ID ↓", "↑ File Name ↓"]
        self.current_search_type = 0
        
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
        search_type = self.search_types[self.current_search_type]
        self["search_type"].setText(search_type)
        
        query = self["query"].getText()
        if query:
            self["status"].setText(f"Ready: {search_type} = {query[:30]}")
        else:
            self["status"].setText(f"Enter {search_type.lower()} and press GREEN to search")
    
    def openKeyboard(self):
        """Otvaranje tastature za unos pretrage"""
        search_type = self.search_types[self.current_search_type]
        current_text = self["query"].getText()
        
        title = f"Enter {search_type}"
        if search_type == "IMDB ID":
            title += " (e.g., tt1375666 for Inception)"
        elif search_type == "File Name":
            title += " (exact filename to match)"
        
        self.session.openWithCallback(
            self.keyboardCallback,
            VirtualKeyBoard,
            title=title,
            text=current_text
        )
    
    def keyboardCallback(self, callback=None):
        if callback is not None:
            self["query"].setText(callback.strip())
            self.updateDisplay()
    
    def doSearch(self):
        query = self["query"].getText().strip()
        if not query:
            self["status"].setText("Please enter search term!")
            return
        
        search_type = self.search_types[self.current_search_type]
        self["status"].setText(f"ADVANCED searching by {search_type}...")
        
        settings = self.plugin.api.config.read_settings()
        languages = settings.get('languages', ['sr', 'hr'])
        
        results = []
        
        if search_type == "IMDB ID":
            # IMDB ID pretraga (samo SubDL)
            if query.startswith('tt'):
                results = self.plugin.api.search_subdl_by_imdb(query, languages)
            else:
                self["status"].setText("IMDB ID must start with 'tt'")
                return
        elif search_type == "File Name":
            # File name pretraga (samo SubDL)
            results = self.plugin.api.search_subdl_by_filename(query, languages)
        else:
            # Standard film name pretraga (oba servisa)
            results = self.plugin.api.search_all(query, languages)
        
        self.results_list = results or []
        
        if not self.results_list:
            list_items = ["No results found"]
            self["results"].setList(list_items)
            self["status"].setText("No subtitles found. Try different search.")
            return
        
        list_items = []
        for idx, result in enumerate(self.results_list, 1):
            title = result.get('title', 'Unknown')
            site = result.get('site', '').upper()
            site_indicator = f"[{site}] " if site else ""
            language = result.get('language', 'Unknown').upper()
            
            display_text = f"{idx}. {site_indicator}{title[:45]}"
            if len(title) > 45:
                display_text += "..."
            
            info_parts = [f"Lang: {language}"]
            
            downloads = result.get('downloads', 0)
            if downloads > 0:
                dl_str = f"{downloads:,}".replace(",", ".")
                info_parts.append(f"↓{dl_str}")
            
            if result.get('hd'):
                info_parts.append("HD")
            
            if info_parts:
                display_text += f" ({' | '.join(info_parts)})"
            
            list_items.append(display_text)
        
        self["results"].setList(list_items)
        
        site_counts = {}
        for result in self.results_list:
            site = result.get('site', 'Unknown')
            site_counts[site] = site_counts.get(site, 0) + 1
        
        sites_summary = ", ".join([f"{s}:{c}" for s, c in site_counts.items()])
        self["status"].setText(f"ADVANCED: {len(self.results_list)} results ({sites_summary})")
    
    def downloadSelected(self):
        """Identican download kao u OpenSubtitlesSearchScreen"""
        selected_idx = self["results"].getSelectedIndex()

        if not self.results_list or selected_idx >= len(self.results_list):
            self["status"].setText("No item selected!")
            return

        result = self.results_list[selected_idx]
        site = result.get('site', 'Unknown')
        title = result.get('title', 'Unknown')
        file_id = result.get('file_id', 'N/A')
        
        print(f"[ADVANCED SEARCH] Downloading from {site}: {title}, file_id: {file_id}")
        self["status"].setText(f"Downloading from {site}: {title[:30]}...")

        content = self.plugin.api.download(result)
        
        if content:
            self.saveSubtitle(content, result)
        else:
            self.showDownloadError(site, file_id)
    
    def saveSubtitle(self, content, result):
        """Identican save kao u OpenSubtitlesSearchScreen"""
        settings = self.plugin.api.config.read_settings()
        save_path = settings.get('save_path', '/media/hdd/subtitles/')

        title = result.get('title', 'subtitle').replace(' ', '_')
        title = re.sub(r'[^\w\-_]', '', title)
        language = result.get('language', 'unknown').lower()
        site = result.get('site', 'unknown')
        timestamp = int(time.time())
        
        ext = '.srt'
        if isinstance(content, bytes):
            if content.startswith(b'WEBVTT'):
                ext = '.vtt'
            elif content.startswith(b'1\r\n0'):
                ext = '.sub'
        
        filename = f"{title}_{site}_{language}_{timestamp}{ext}"
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
    
    def showDownloadError(self, site, file_id=""):
        """Identican error kao u OpenSubtitlesSearchScreen"""
        if site.lower() == 'subdl':
            error_msg = f"""SubDL download failed!

File ID: {file_id}

Check:
1. SubDL API key is valid
2. Language codes are UPPERCASE (EN, SR, HR)
3. Try different result
4. Try SMART search instead"""
        else:
            error_msg = "Download failed! Check API keys and connection."
        
        self["status"].setText("Download failed!")
        self.session.open(MessageBox, error_msg, MessageBox.TYPE_ERROR)
    
    def up(self):
        if self["results"].getList():
            self["results"].up()
        else:
            # Ciklus kroz search type-ove
            self.current_search_type = (self.current_search_type - 1) % len(self.search_types)
            self.updateDisplay()
    
    def down(self):
        if self["results"].getList():
            self["results"].down()
        else:
            # Ciklus kroz search type-ove
            self.current_search_type = (self.current_search_type + 1) % len(self.search_types)
            self.updateDisplay()
    
    def left(self):
        if self["results"].getList():
            self["results"].pageUp()
    
    def right(self):
        if self["results"].getList():
            self["results"].pageDown()

class OpenSubtitlesSeriesSearchScreen(Screen):
    skin = """<screen position="center,center" size="1600,800"
        title="Search Series Subtitles v1.2"
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

        self["header"] = Label("SERIES SUBTITLES SEARCH v1.2")
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

        self.current_field = "series"

        self["key_red"] = StaticText("")
        self["key_green"] = StaticText("")
        self["key_yellow"] = StaticText("")
        self["key_blue"] = StaticText("")

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
        if self.current_field == "series":
            self.editSeries()
        elif self.current_field == "season":
            self.editSeason()
        elif self.current_field == "episode":
            self.editEpisode()

    def editSeries(self):
        current_text = self["series_input"].getText()
        self.session.openWithCallback(
            self.seriesCallback,
            VirtualKeyBoard,
            title="Enter series name",
            text=current_text
        )

    def seriesCallback(self, callback=None):
        if callback is not None:
            self["series_input"].setText(callback)
            self.updateDisplay()

    def editSeason(self):
        current_text = self["season_input"].getText()
        self.session.openWithCallback(
            self.seasonCallback,
            VirtualKeyBoard,
            title="Enter season number",
            text=current_text
        )

    def seasonCallback(self, callback=None):
        if callback is not None:
            self["season_input"].setText(callback)
            self.updateDisplay()

    def editEpisode(self):
        current_text = self["episode_input"].getText()
        self.session.openWithCallback(
            self.episodeCallback,
            VirtualKeyBoard,
            title="Enter episode number",
            text=current_text
        )

    def episodeCallback(self, callback=None):
        if callback is not None:
            self["episode_input"].setText(callback)
            self.updateDisplay()

    def doSearch(self):
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

        search_display = f"'{series_name}'"
        if season is not None:
            search_display += f" S{season}"
            if episode is not None:
                search_display += f"E{episode}"

        self["status"].setText(f"Searching {search_display}...")

        # Koristimo glavni API za pretragu
        results = self.plugin.api.search_all(series_name, season=season, episode=episode)

        self.results_list = results or []
        list_items = []

        if self.results_list:
            for idx, result in enumerate(self.results_list, 1):
                title = result.get('title', 'Unknown')
                site = result.get('site', '').upper()
                site_indicator = f"[{site}] " if site else ""

                display_text = f"{idx}. {site_indicator}{title[:45]}"
                if len(title) > 45:
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
            site_counts = {}
            for result in self.results_list:
                site = result.get('site', 'Unknown')
                site_counts[site] = site_counts.get(site, 0) + 1
            
            site_summary = ", ".join([f"{s}:{c}" for s, c in site_counts.items()])
            self["status"].setText(f"Found {len(self.results_list)} results from {len(site_counts)} services [{site_summary}]")
        else:
            self["status"].setText("No results found. Try different search.")

    def downloadSelected(self):
        selected_idx = self["results"].getSelectedIndex()

        if not self.results_list or selected_idx >= len(self.results_list):
            self["status"].setText("No item selected!")
            return

        result = self.results_list[selected_idx]
        title = result.get('title', 'subtitle')
        self["status"].setText(f"Downloading: {title[:30]}...")

        content = self.plugin.api.download(result)
        
        if content:
            self.saveSubtitle(content, result)
        else:
            self["status"].setText("Download failed!")
            self.session.open(MessageBox,
                              "Download failed! Check API keys or internet connection.",
                              MessageBox.TYPE_ERROR)

    def saveSubtitle(self, content, result):
        settings = self.plugin.api.config.read_settings()
        save_path = settings.get('save_path', '/media/hdd/subtitles/')

        title = result.get('title', 'subtitle').replace(' ', '_')
        title = re.sub(r'[^\w\-_]', '', title)
        language = result.get('language', 'unknown').lower()
        site = result.get('site', 'unknown')
        season = result.get('season')
        episode = result.get('episode')
        timestamp = int(time.time())

        if season and episode:
            filename = f"{title}_S{season:02d}E{episode:02d}_{site}_{language}_{timestamp}.srt"
        elif season:
            filename = f"{title}_S{season:02d}_{site}_{language}_{timestamp}.srt"
        else:
            filename = f"{title}_{site}_{language}_{timestamp}.srt"

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

    def up(self):
        if self.current_field == "season":
            self.current_field = "series"
            self.updateDisplay()
        elif self.current_field == "episode":
            self.current_field = "season"
            self.updateDisplay()
        elif self["results"].getList():
            self["results"].up()

    def down(self):
        if self.current_field == "series":
            self.current_field = "season"
            self.updateDisplay()
        elif self.current_field == "season":
            self.current_field = "episode"
            self.updateDisplay()
        elif self["results"].getList():
            self["results"].down()

    def left(self):
        if self["results"].getList():
            self["results"].pageUp()

    def right(self):
        if self["results"].getList():
            self["results"].pageDown()

class OpenSubtitlesMainScreen(Screen):
    skin = """
    <screen name="CiefpOpenSubtitlesMain" position="center,center" size="1600,800" title="Ciefp Subtitles v1.2" backgroundColor="#000000">
        <eLabel position="0,0" size="1920,1080" backgroundColor="#000000" zPosition="-15" />
        <eLabel position="center,center" size="1200,800" backgroundColor="#101010" zPosition="-10" />
        
        <widget name="background" position="1200,10" size="400,800" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/CiefpOpenSubtitles/background.png" />
        <widget name="title" position="0,40" size="1200,80" font="Regular;42" foregroundColor="#ffffff" backgroundColor="transparent" halign="center" valign="center" transparent="1" zPosition="1" />

        <widget name="menu" position="100,140" size="1000,550" itemHeight="60" font="Regular;34" foregroundColor="#ffffff" backgroundColor="transparent" scrollbarMode="showOnDemand" enableWrapAround="1" transparent="1" zPosition="1" />

        <eLabel text="Exit" position="100,e-100" size="250,60" font="Regular;30" foregroundColor="#ffffff" backgroundColor="#9f1313" halign="center" valign="center" zPosition="1" />
        <eLabel text="Help" position="380,e-100" size="250,60" font="Regular;30" foregroundColor="#ffffff" backgroundColor="#1f771f" halign="center" valign="center" zPosition="1" />
        <eLabel text="Refresh" position="660,e-100" size="250,60" font="Regular;30" foregroundColor="#ffffff" backgroundColor="#a08500" halign="center" valign="center" zPosition="1" />
        <eLabel text="Select" position="940,e-100" size="250,60" font="Regular;30" foregroundColor="#ffffff" backgroundColor="#18188b" halign="center" valign="center" zPosition="1" />
    </screen>
    """

    def __init__(self, session, plugin):
        Screen.__init__(self, session)
        self.session = session
        self.plugin = plugin
        
        # TRI PRETRAGE ZA TESTIRANJE
        self.menu_items = [
            ("Standard Search (Film Name)", "search_standard"),
            ("Smart Search (All methods)", "search_smart"),
            ("Advanced Search (SubDL)", "search_advanced"),
            ("Search Series", "search_series"),
            ("Configuration", "config"),
            ("API Keys Setup", "api_keys"),
            ("About v1.2", "about"),
            ("Exit", "exit")
        ]
        
        self["menu"] = MenuList([])
        self["background"] = Pixmap()
        
        list_items = []
        for idx, item in enumerate(self.menu_items):
            # Dodaj ikonice za različite pretrage
            icon = ""
            if "Standard" in item[0]:
                icon = "📝 "
            elif "Smart" in item[0]:
                icon = "🚀 "
            elif "Advanced" in item[0]:
                icon = "🔍 "
            elif "Series" in item[0]:
                icon = "📺 "
            elif "Configuration" in item[0]:
                icon = "⚙️ "
            elif "API" in item[0]:
                icon = "🔑 "
            elif "About" in item[0]:
                icon = "ℹ️ "
            elif "Exit" in item[0]:
                icon = "🚪 "
            
            list_items.append((f"{idx+1}. {icon}{item[0]}", item[1]))
        
        self["menu"].list = list_items
        self["menu"].setList(list_items)
        
        self["key_red"] = StaticText("Exit")
        self["key_green"] = StaticText("Help")
        self["key_yellow"] = StaticText("Refresh")
        self["key_blue"] = StaticText("Select")
        
        self["title"] = Label("Ciefp Subtitles v1.2")
        
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
        """Zeleno dugme - Help za sve tri pretrage"""
        help_text = f"""Ciefp Subtitles v1.2
1.STANDARD SEARCH:
   • Uses Film Name only
   • Good for simple searches

2.SMART SEARCH (NEW):
   • Tries ALL methods in order:
     1. IMDB ID (best) - tt1375666
     2. File Name (good) - Movie.Name.2023
     3. Film Name (ok)
   • Shows which method found each result
   • Recommended for best results

3.ADVANCED SEARCH:
   • Manual choice: IMDB/File/Film
   • Use the up and down arrows to change

    IMPORTANT for SubDL:
   • IMDB ID search: BEST results
   • File Name: GOOD results  
   • Film Name: OK results
    Logs show detailed info for debugging!"""
        self.session.open(MessageBox, help_text, MessageBox.TYPE_INFO)
    
    def keyYellow(self):
        """Žuto dugme - Refresh"""
        list_items = []
        for idx, item in enumerate(self.menu_items):
            icon = ""
            if "Standard" in item[0]:
                icon = "📝 "
            elif "Smart" in item[0]:
                icon = "🚀 "
            elif "Advanced" in item[0]:
                icon = "🔍 "
            elif "Series" in item[0]:
                icon = "📺 "
            elif "Configuration" in item[0]:
                icon = "⚙️ "
            elif "API" in item[0]:
                icon = "🔑 "
            elif "About" in item[0]:
                icon = "ℹ️ "
            elif "Exit" in item[0]:
                icon = "🚪 "
            
            list_items.append((f"{idx+1}. {icon}{item[0]}", item[1]))
        self["menu"].setList(list_items)
    
    def selectItem(self):
        """Plavo dugme - Select sa SVIM opcijama"""
        selected = self["menu"].getCurrent()
        if selected:
            action = selected[1]
            
            if action == "search_standard":
                self.session.open(OpenSubtitlesSearchScreen, self.plugin)
            elif action == "search_smart":
                self.session.open(OpenSubtitlesSmartSearchScreen, self.plugin)
            elif action == "search_advanced":
                self.session.open(OpenSubtitlesAdvancedSearchScreen, self.plugin)
            elif action == "search_series":
                self.session.open(OpenSubtitlesSeriesSearchScreen, self.plugin)
            elif action == "config":
                self.session.open(OpenSubtitlesConfigScreen, self.plugin)
            elif action == "api_keys":
                self.session.open(OpenSubtitlesApiKeysScreen, self.plugin)
            elif action == "about":
                about_text = f"""Ciefp Subtitles Plugin
Version: 1.2
THREE SEARCH METHODS:
1.Standard (Film Name only)
2.Smart (IMDB → File → Film) 
3.Advanced (Manual:Film Name,File Name,IMDB ID)
• Use the up and down arrows to change

Based on testing:
✅ IMDB ID = BEST results
✅ File Name = GOOD results  
✅ Film Name = OK results
SMART Search automatically tries all three!

CHANGES in v1.2:
• Added SMART search (auto-tries all methods)
• Shows which method found each result
• Better logging for debugging

RECOMMENDATION:
Use 🚀 SMART SEARCH for best results!"""
                self.session.open(MessageBox, about_text, MessageBox.TYPE_INFO)
            elif action == "exit":
                self.close()

class OpenSubtitlesPlugin:
    """Glavna klasa plugina"""
    
    def __init__(self):
        self.api = SubtitlesAPI()
    
    def main(self, session, **kwargs):
        """Glavna funkcija plugina"""
        session.open(OpenSubtitlesMainScreen, self)
    
    def autoSearch(self, session, event, movie_title):
        """Automatska pretraga - koristi SMART search"""
        session.open(OpenSubtitlesSmartSearchScreen, self, movie_title)
    
    def autoSearchStandard(self, session, event, movie_title):
        """Automatska STANDARD pretraga (za backward compatibility)"""
        session.open(OpenSubtitlesSearchScreen, self, movie_title)
    
    def config(self, session, **kwargs):
        """Konfiguracija"""
        session.open(OpenSubtitlesConfigScreen, self)
    
    def credits(self):
        """Informacije o pluginu"""
        return [
            ("Ciefp Subtitles", f"v{PLUGIN_VERSION}"),
            ("Search Methods", "Standard, Smart, Advanced"),
            ("Smart Search", "IMDB → File → Film (auto)"),
            ("Best Results", "Use IMDB ID (tt1375666)")
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
            name=f"CiefpSubtitles v{PLUGIN_VERSION}",
            description="Search and download subtitles (3 search methods)",
            where=PluginDescriptor.WHERE_PLUGINMENU,
            icon=icon_path,
            fnc=main
        ),
        PluginDescriptor(
            name="CiefpSubtitles",
            description="Search subtitles for current video",
            where=PluginDescriptor.WHERE_MOVIELIST,
            fnc=opensubtitles_plugin.autoSearch
        )
    ]