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
PLUGIN_VERSION = "1.3"  # TRI PRETRAGE: Standard, Smart, Advanced
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
            'User-Agent': 'Enigma2 SubDL Plugin/1.3',
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

        # DEBUG ISPIS
        print(f"[SubDL DEBUG] ========== SEARCH CALLED ==========")
        print(f"[SubDL DEBUG] Query: '{query}'")
        print(f"[SubDL DEBUG] IMDB ID: '{imdb_id}'")
        print(f"[SubDL DEBUG] File Name: '{file_name}'")
        print(f"[SubDL DEBUG] Season: {season}, Episode: {episode}")
        print(f"[SubDL DEBUG] Languages: {languages}")
        print(f"[SubDL DEBUG] ==================================")

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

    def search_by_imdb_only(self, imdb_id, languages=None, season=None, episode=None):
        """DIRECT search by IMDB ID only (without trying other methods)"""
        print(f"[SubDL IMDB ONLY] Direct IMDB search: {imdb_id}")

        return self.search(
            query="",  # Prazan query
            languages=languages,
            imdb_id=imdb_id,  # OVO JE KLJUČNO
            season=season,
            episode=episode
        )
    
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
                'User-Agent': 'Enigma2 SubDL Plugin/1.3',
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

class TitloviAPI:
    """Klasa za Titlovi.com - NOVI WORKFLOW (podržava naziv i IMDB ID)"""

    def __init__(self):
        self.base_url = "https://rs.titlovi.com"
        self.search_url = "https://rs.titlovi.com/prevodi/"
        self.session = requests.Session()

        # Realni browser headers
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'sr-RS,sr,en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Referer': 'https://rs.titlovi.com/',
            'Cache-Control': 'max-age=0'
        }

        # Retry mehanizam
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # Cookie jar
        self.session.cookies.clear()

    def search(self, query, languages=None, season=None, episode=None):
        """
        Pretraga na Titlovi.com

        Podržava:
        - Naziv filma: 'moonfall'
        - IMDB ID: 'tt5834426'
        - Naziv serije: 'stranger things'
        """
        print(f"[TitloviAPI] Searching for: '{query}' (supports both name and IMDB ID)")

        # Titlovi.com podržava sve balkanske jezike
        supported_langs = ['sr', 'hr', 'bs', 'sl', 'mk', 'bg', 'me']

        # Filtriranje jezika - samo balkanski
        filtered_langs = []
        if languages:
            for lang in languages:
                lang_lower = lang.lower().strip()
                if lang_lower == 'all':
                    filtered_langs = supported_langs
                    break
                elif lang_lower in ['srp', 'scc', 'srb', 'sr']:
                    filtered_langs.append('sr')
                elif lang_lower in ['hrv', 'hr']:
                    filtered_langs.append('hr')
                elif lang_lower in ['bos', 'bs']:
                    filtered_langs.append('bs')
                elif lang_lower in ['slv', 'sl']:
                    filtered_langs.append('sl')
                elif lang_lower in ['mkd', 'mk']:
                    filtered_langs.append('mk')
                elif lang_lower in ['bul', 'bg']:
                    filtered_langs.append('bg')
                elif lang_lower in ['cnr', 'me']:
                    filtered_langs.append('me')

        if not filtered_langs:
            filtered_langs = ['sr']  # podrazumevano srpski

        print(f"[TitloviAPI] Languages: {filtered_langs}")

        # KREIRAJ SEARCH PARAMS
        params = {'prevod': query.strip()}

        # Dodaj jezike ako postoje (Titlovi možda podržava jezik filter)
        # Čuvaćemo languages za kasnije filtriranje
        self.last_languages = filtered_langs

        # Dodaj sezonu/epizodu ako je serija
        if season is not None:
            params['s'] = season
        if episode is not None:
            params['e'] = episode

        print(f"[TitloviAPI] Search params: {params}")

        try:
            # KORAK 1: Dobij listu svih prevoda
            response = self.session.get(
                self.search_url,
                params=params,
                headers=self.headers,
                timeout=15
            )

            print(f"[TitloviAPI] Search URL: {response.url}")
            print(f"[TitloviAPI] Status: {response.status_code}")

            if response.status_code != 200:
                print(f"[TitloviAPI] Search failed with status {response.status_code}")
                return []

            # DEBUG: Sačuvaj HTML
            self.save_debug_html(response.text, f"search_{query}")

            # KORAK 2: Parsiraj listu prevoda
            results = self.parse_prevodi_list(response.text, query, response.url)

            # KORAK 3: Filtriraj po jeziku
            filtered_results = self.filter_by_language(results, filtered_langs)

            print(f"[TitloviAPI] Total results: {len(results)}, Filtered by language: {len(filtered_results)}")
            return filtered_results

        except Exception as e:
            print(f"[TitloviAPI] Search error: {e}")
            import traceback
            traceback.print_exc()
            return []

    def advanced_search(self, query, params=None):
        """
        NAPREDNA pretraga koristeći Titlovi.com advanced search parametre
        params mora sadržati sve parametre kao u URL-u sa t=2
        """
        print(f"[TitloviAPI] Advanced search for: '{query}'")
        print(f"[TitloviAPI] Advanced params: {params}")

        if not params:
            params = {}

        # Uvek dodaj t=2 za advanced search
        params['t'] = '2'

        # Bazni URL za advanced search
        search_url = "https://rs.titlovi.com/prevodi/"

        try:
            # Napravite zahtev sa svim parametrima
            response = self.session.get(
                search_url,
                params=params,
                headers=self.headers,
                timeout=15
            )

            print(f"[TitloviAPI] Advanced search URL: {response.url}")
            print(f"[TitloviAPI] Status: {response.status_code}")

            if response.status_code != 200:
                print(f"[TitloviAPI] Advanced search failed: {response.status_code}")
                return []

            # Sačuvaj za debug
            self.save_debug_html(response.text, f"advanced_{query}")

            # Parsiraj rezultate (možemo koristiti postojeću metodu)
            return self.parse_prevodi_list(response.text, query, response.url)

        except Exception as e:
            print(f"[TitloviAPI] Advanced search error: {e}")
            import traceback
            traceback.print_exc()
            return []

    def save_debug_html(self, html, name):
        """Sačuvaj HTML za debug"""
        try:
            import time
            timestamp = int(time.time())
            safe_name = name.replace('/', '_').replace('?', '_')[:50]
            debug_path = f"/tmp/titlovi_{safe_name}_{timestamp}.html"

            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)

            print(f"[TitloviAPI] Saved debug HTML: {debug_path}")
        except:
            pass

    def parse_prevodi_list(self, html, query, search_url):
        """Parsiraj listu prevoda sa /prevodi/?prevod=... stranice"""
        print(f"[TitloviAPI] Parsing prevodi list...")

        try:
            import re
            import urllib.parse
            results = []

            # DEBUG: Ispiši sample HTML
            print(f"[TitloviAPI] HTML length: {len(html)} chars")

            # Pronađi sve linkove ka specifičnim prevodima
            # Pattern: /prevodi/naziv-ID/ ili /prevodi/naziv-ID
            prevod_patterns = [
                r'href=["\'](/prevodi/([^"\']+?-(\d+))/?)["\']',
                r'href=["\'][^"\']*?/prevodi/[^"\']*?-(\d+)/?["\']',
                r'data-href=["\']/prevodi/([^"\']+?-(\d+))/["\']'
            ]

            all_matches = []
            for pattern in prevod_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                if matches:
                    print(f"[TitloviAPI] Pattern found {len(matches)} matches")
                    all_matches.extend(matches)
                    break  # Koristi prvi pattern koji nađe nešto

            if not all_matches:
                print(f"[TitloviAPI] No prevod links found, trying alternative parsing...")
                # Fallback: traži bilo koje linkove sa brojevima
                alt_pattern = r'href=["\'][^"\']*?/(\d+)/["\']'
                alt_matches = re.findall(alt_pattern, html)
                if alt_matches:
                    print(f"[TitloviAPI] Found {len(alt_matches)} numeric links")
                    # Pretpostavi da su ovo prevod ID-jevi
                    for match in alt_matches:
                        if match.isdigit() and len(match) >= 4:
                            all_matches.append(('', f"film-{match}", match))

            print(f"[TitloviAPI] Total prevod links found: {len(all_matches)}")

            # Grupiši po ID-u da ukloniš duplikate
            unique_prevods = {}

            for match in all_matches:
                if len(match) >= 3:
                    full_match, full_path, prevod_id = match[:3]
                elif len(match) == 1:
                    # Samo ID
                    prevod_id = match[0]
                    full_path = f"film-{prevod_id}"
                else:
                    continue

                if prevod_id.isdigit() and prevod_id not in unique_prevods:
                    # Ekstraktuj naziv iz path-a
                    name_match = re.match(r'([^-]+)-', full_path)
                    name = name_match.group(1) if name_match else "film"

                    unique_prevods[prevod_id] = {
                        'id': prevod_id,
                        'path': full_path,
                        'name': name,
                        'url': f"https://rs.titlovi.com/prevodi/{full_path}/"
                    }

            print(f"[TitloviAPI] Unique prevods: {len(unique_prevods)}")

            # Ako nema prevoda, možda je direktno jedna prevod stranica
            if not unique_prevods:
                print(f"[TitloviAPI] No prevod links, checking if direct prevod page...")
                # Proveri da li je ovo direktna prevod stranica
                if '/prevodi/' in search_url and re.search(r'/prevodi/[^/?]+-\d+/', search_url):
                    print(f"[TitloviAPI] This is a direct prevod page")
                    # Ekstraktuj ID iz URL-a
                    id_match = re.search(r'/prevodi/[^/]+-(\d+)/', search_url)
                    if id_match:
                        prevod_id = id_match.group(1)
                        # Kreiraj jednostavan rezultat
                        simple_result = self.create_simple_result(prevod_id, query, search_url)
                        if simple_result:
                            return [simple_result]

            # Parsiraj detalje za svaki prevod (maks 10 za brzinu)
            prevod_ids = list(unique_prevods.keys())
            for i, prevod_id in enumerate(prevod_ids[:10]):
                try:
                    prevod_info = unique_prevods[prevod_id]

                    print(f"[TitloviAPI] Processing prevod {i + 1}/{min(len(prevod_ids), 10)}: {prevod_id}")

                    # KORAK 3: Poseti specifičnu prevod stranicu za detalje
                    prevod_details = self.fetch_prevod_details(
                        prevod_info['url'],
                        prevod_id,
                        query,
                        fetch_details=(i < 5)  # Detalje samo za prvih 5 za brzinu
                    )

                    if prevod_details:
                        results.append(prevod_details)
                        print(f"[TitloviAPI] ✓ Added prevod {prevod_id}")
                    else:
                        # Kreiraj jednostavan rezultat ako ne možemo dobiti detalje
                        simple_result = self.create_simple_result(prevod_id, query, prevod_info['url'])
                        if simple_result:
                            results.append(simple_result)
                            print(f"[TitloviAPI] Added simple result for {prevod_id}")

                except Exception as e:
                    print(f"[TitloviAPI] Error processing prevod {prevod_id}: {str(e)[:50]}")
                    continue

            print(f"[TitloviAPI] Parsing completed: {len(results)} results")
            return results

        except Exception as e:
            print(f"[TitloviAPI] Parse prevodi list error: {e}")
            import traceback
            traceback.print_exc()
            return []

    def fetch_prevod_details(self, prevod_url, prevod_id, query, fetch_details=True):
        """Poseti specifičnu prevod stranicu i ekstraktuj detalje"""
        if not fetch_details:
            # Ako ne trebaju detalji, kreiraj jednostavan rezultat
            return self.create_simple_result(prevod_id, query, prevod_url)

        try:
            print(f"[TitloviAPI] Fetching details: {prevod_url}")

            response = self.session.get(prevod_url, headers=self.headers, timeout=10)

            if response.status_code != 200:
                print(f"[TitloviAPI] Prevod page failed: {response.status_code}")
                return self.create_simple_result(prevod_id, query, prevod_url)

            html = response.text

            # Ekstraktuj detalje sa prevod stranice
            import re

            # Naslov filma
            title = "Unknown Title"
            title_patterns = [
                r'<h1[^>]*>([^<]+)</h1>',
                r'<title>([^<]+)</title>',
                r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"',
                r'<div[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</div>'
            ]

            for pattern in title_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    title = match.group(1).strip()
                    # Očisti title
                    title = title.replace(' - Titlovi.com', '').replace('Titlovi.com', '').strip()
                    if title:
                        break

            # Godina
            year = ""
            year_patterns = [
                r'Godina.*?[:>]\s*(\d{4})',
                r'Year.*?[:>]\s*(\d{4})',
                r'\((\d{4})\)',
                r'<span[^>]*class="[^"]*year[^"]*"[^>]*>(\d{4})</span>'
            ]

            for pattern in year_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    year = match.group(1)
                    break

            # Jezik
            language = "srpski"
            lang_patterns = [
                r'Jezik.*?[:>]\s*([^<]+)',
                r'Language.*?[:>]\s*([^<]+)',
                r'<td[^>]*>Jezik</td>\s*<td[^>]*>([^<]+)</td>',
                r'<span[^>]*class="[^"]*language[^"]*"[^>]*>([^<]+)</span>'
            ]

            for pattern in lang_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    language = match.group(1).strip()
                    break

            # Download broj
            downloads = 0
            dl_patterns = [
                r'Preuzimanja.*?[:>]\s*(\d+)',
                r'Downloads.*?[:>]\s*(\d+)',
                r'<td[^>]*>Preuzimanja</td>\s*<td[^>]*>(\d+)</td>',
                r'<span[^>]*class="[^"]*downloads[^"]*"[^>]*>(\d+)</span>'
            ]

            for pattern in dl_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    try:
                        downloads = int(match.group(1))
                    except:
                        pass
                    break

            # Kreiraj rezultat
            result = {
                'title': title[:200],
                'year': year,
                'language': language[:50],
                'language_code': self.get_lang_code(language),
                'downloads': downloads,
                'rating': 0,
                'release_info': self.extract_release_info(html),
                'fps': 0,
                'prevod_id': str(prevod_id),
                'film_id': str(prevod_id),  # Za backward compatibility
                'media_id': str(prevod_id),  # Za backward compatibility
                'prevod_url': prevod_url,
                'prevod_path': prevod_url.replace('https://rs.titlovi.com/prevodi/', '').rstrip('/'),
                'season_info': "",
                'is_series': False,
                'season': None,
                'episode': None,
                'site': 'titlovi',
                'search_query': query,
                'search_method': 'prevod_page'
            }

            # Proveri da li je serija
            series_keywords = ['sezona', 'epizoda', 'season', 'episode', 's0', 'e0']
            html_lower = html.lower()
            for keyword in series_keywords:
                if keyword in html_lower:
                    result['is_series'] = True

                    # Pokušaj ekstraktovati sezonu/epizodu
                    s_match = re.search(r'sezona.*?(\d+)', html_lower, re.IGNORECASE)
                    e_match = re.search(r'epizoda.*?(\d+)', html_lower, re.IGNORECASE)

                    if s_match:
                        try:
                            result['season'] = int(s_match.group(1))
                        except:
                            pass
                    if e_match:
                        try:
                            result['episode'] = int(e_match.group(1))
                        except:
                            pass

                    if result['season'] and result['episode']:
                        result['season_info'] = f"S{result['season']:02d}E{result['episode']:02d}"

                    break

            return result

        except Exception as e:
            print(f"[TitloviAPI] Fetch prevod details error: {e}")
            # Vrati jednostavan rezultat kao fallback
            return self.create_simple_result(prevod_id, query, prevod_url)

    def create_simple_result(self, prevod_id, query, prevod_url):
        """Kreiraj jednostavan rezultat"""
        return {
            'title': f"{query} - {prevod_id}",
            'year': "",
            'language': "srpski",
            'language_code': "srp",
            'downloads': 0,
            'rating': 0,
            'release_info': "",
            'fps': 0,
            'prevod_id': str(prevod_id),
            'film_id': str(prevod_id),
            'media_id': str(prevod_id),
            'prevod_url': prevod_url,
            'prevod_path': prevod_url.replace('https://rs.titlovi.com/prevodi/', '').rstrip('/'),
            'season_info': "",
            'is_series': False,
            'season': None,
            'episode': None,
            'site': 'titlovi',
            'search_query': query,
            'search_method': 'simple'
        }

    def extract_release_info(self, html):
        """Ekstraktuj release info iz HTML-a"""
        import re

        patterns = [
            r'Kvalitet.*?[:>]\s*([^<]+)',
            r'Quality.*?[:>]\s*([^<]+)',
            r'Release.*?[:>]\s*([^<]+)',
            r'<td[^>]*>Kvalitet</td>\s*<td[^>]*>([^<]+)</td>',
            r'<span[^>]*class="[^"]*quality[^"]*"[^>]*>([^<]+)</span>'
        ]

        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return match.group(1).strip()[:100]

        return ""

    def filter_by_language(self, results, languages):
        """Filtriraj rezultate po jeziku"""
        if not languages or 'all' in [l.lower() for l in languages]:
            return results

        filtered = []
        for result in results:
            result_lang = result.get('language', '').lower()
            result_lang_code = result.get('language_code', '').lower()

            # Proveri da li se podudara sa traženim jezicima
            match = False
            for lang in languages:
                lang_lower = lang.lower()
                if (lang_lower in result_lang or
                        result_lang_code.startswith(lang_lower) or
                        lang_lower.startswith(result_lang_code)):
                    match = True
                    break

            if match:
                filtered.append(result)

        return filtered

    def get_lang_code(self, language):
        """Konvertuj naziv jezika u kod"""
        lang_map = {
            'srpski': 'srp', 'српски': 'srp', 'serbian': 'srp',
            'hrvatski': 'hrv', 'croatian': 'hrv',
            'bosanski': 'bos', 'bosnian': 'bos',
            'slovenački': 'slv', 'slovenian': 'slv',
            'slovenski': 'slv',
            'makedonski': 'mkd', 'macedonian': 'mkd',
            'bugarski': 'bul', 'bulgarian': 'bul',
            'crnogorski': 'cnr', 'montenegrin': 'cnr',
            'engleski': 'eng', 'english': 'eng'
        }

        lang_lower = language.lower()
        for key, code in lang_map.items():
            if key in lang_lower:
                return code

        return 'srp'  # podrazumevano

    def download(self, media_id, title=""):
        """
        Preuzimanje titla sa Titlovi.com

        Podržava:
        - result dict (sa prevod_url)
        - string prevod_id
        """
        print(f"[TitloviAPI] Download called with: {type(media_id)}")

        # Ako je result dict (sa prevod_url), koristi ga
        if isinstance(media_id, dict):
            result = media_id
            prevod_url = result.get('prevod_url', '')
            prevod_id = result.get('prevod_id') or result.get('film_id') or result.get('media_id')
            download_title = result.get('title', title)

            if not prevod_url and prevod_id:
                # Konstruiši URL ako ga nema
                prevod_path = result.get('prevod_path', f"film-{prevod_id}")
                prevod_url = f"https://rs.titlovi.com/prevodi/{prevod_path}/"

            print(f"[TitloviAPI] Downloading from result, prevod_url: {prevod_url}")
            return self.download_from_prevod_url(prevod_url, prevod_id, download_title)

        # Ako je samo string ID
        if isinstance(media_id, str) and media_id.isdigit():
            print(f"[TitloviAPI] Downloading with prevod_id: {media_id}")
            # Konstruiši URL
            prevod_url = f"https://rs.titlovi.com/prevodi/film-{media_id}/"
            return self.download_from_prevod_url(prevod_url, media_id, title)

        print(f"[TitloviAPI] Invalid media_id type: {type(media_id)}")
        return None

    def download_from_prevod_url(self, prevod_url, prevod_id, title=""):
        """Download sa specifične prevod stranice - GLAVNA METODA"""
        print(f"[TitloviAPI] Download from prevod URL: {prevod_url}")

        try:
            # KORAK 1: Poseti prevod stranicu
            response = self.session.get(prevod_url, headers=self.headers, timeout=15)

            if response.status_code != 200:
                print(f"[TitloviAPI] Prevod page failed: {response.status_code}")
                return None

            html = response.text

            # Sačuvaj za debug
            self.save_debug_html(html, f"prevod_{prevod_id}")

            # KORAK 2: Pronađi download link
            download_url = self.find_download_link(html, prevod_id, prevod_url)

            if not download_url:
                print(f"[TitloviAPI] No download link found, trying direct download...")
                # Pokušaj direktno sa ?download=1
                direct_url = f"{prevod_url}?download=1"
                print(f"[TitloviAPI] Trying direct: {direct_url}")

                response2 = self.session.get(direct_url, headers=self.headers, timeout=15)
                if response2.status_code == 200 and len(response2.content) > 100:
                    return self.process_download_content(response2.content, f"direct_{prevod_id}")

                return None

            print(f"[TitloviAPI] Found download URL: {download_url}")

            # KORAK 3: Preuzmi sa download URL-a
            response3 = self.session.get(download_url, headers=self.headers, timeout=30)

            if response3.status_code == 200 and len(response3.content) > 100:
                return self.process_download_content(response3.content, f"download_{prevod_id}")
            else:
                print(f"[TitloviAPI] Download failed: {response3.status_code}, size: {len(response3.content)}")

                # Pokušaj POST metodom
                print(f"[TitloviAPI] Trying POST method...")

                post_url = "https://rs.titlovi.com/download/"
                post_data = {
                    'id': prevod_id,
                    'type': '1'
                }

                # Dodaj referer header
                post_headers = self.headers.copy()
                post_headers['Referer'] = prevod_url
                post_headers['Content-Type'] = 'application/x-www-form-urlencoded'

                response4 = self.session.post(post_url, data=post_data, headers=post_headers, timeout=30)
                if response4.status_code == 200 and len(response4.content) > 100:
                    return self.process_download_content(response4.content, f"post_{prevod_id}")

            return None

        except Exception as e:
            print(f"[TitloviAPI] Download error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def find_download_link(self, html, prevod_id, prevod_url):
        """Pronađi download link na prevod stranici"""
        import re

        # Pattern 1: Form action
        form_patterns = [
            r'<form[^>]*action=["\']([^"\']*download[^"\']*)["\'][^>]*>',
            r'<form[^>]*id="downloadForm"[^>]*action=["\']([^"\']+)["\']'
        ]

        for pattern in form_patterns:
            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if match:
                action = match.group(1)
                if not action.startswith('http'):
                    action = 'https://rs.titlovi.com' + action
                print(f"[TitloviAPI] Found form action: {action}")
                return action

        # Pattern 2: Download link/button
        link_patterns = [
            r'href=["\']([^"\']*download[^"\']*id=' + re.escape(prevod_id) + r'[^"\']*)["\']',
            r'href=["\']([^"\']*download\.php\?[^"\']*)["\']',
            r'href=["\']([^"\']*/download/\?[^"\']*)["\']',
            r'<a[^>]*class="[^"]*download[^"]*"[^>]*href=["\']([^"\']+)["\']',
            r'<button[^>]*onclick=["\']window\.location=\'([^\']+)\'["\']'
        ]

        for pattern in link_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for match in matches:
                if match:
                    url = match
                    if not url.startswith('http'):
                        url = 'https://rs.titlovi.com' + url
                    print(f"[TitloviAPI] Found download link: {url}")
                    return url

        # Pattern 3: Meta refresh (redirect)
        meta_pattern = r'<meta[^>]*http-equiv="refresh"[^>]*content="[^"]*url=([^"]+)"'
        meta_match = re.search(meta_pattern, html, re.IGNORECASE)
        if meta_match:
            url = meta_match.group(1)
            if not url.startswith('http'):
                url = 'https://rs.titlovi.com' + url
            print(f"[TitloviAPI] Found meta refresh to: {url}")
            return url

        return None

    def process_download_content(self, content, source_name):
        """Procesiraj download content (ZIP ili direktan SRT)"""
        print(f"[TitloviAPI] Processing download content from {source_name}, size: {len(content)} bytes")

        # Proveri da li je ZIP
        if content[:2] == b'PK':
            print(f"[TitloviAPI] ZIP file detected")
            return self.extract_from_zip(content)

        # Proveri da li je direktan SRT/WebVTT
        if self.is_subtitle_content(content):
            print(f"[TitloviAPI] Direct subtitle file detected")
            return content

        # Ako nije ništa od navedenog, možda je HTML sa error-om
        try:
            text = content[:1000].decode('utf-8', errors='ignore')
            if '<html' in text.lower() or '<!doctype' in text.lower():
                print(f"[TitloviAPI] HTML response instead of subtitle")
                # Sačuvaj za debug
                debug_path = f"/tmp/titlovi_error_{source_name}.html"
                with open(debug_path, 'wb') as f:
                    f.write(content)
                print(f"[TitloviAPI] Saved error HTML to {debug_path}")
        except:
            pass

        return content  # Vrati šta god da je

    def extract_from_zip(self, zip_content):
        """Ekstraktuj SRT iz ZIP fajla"""
        try:
            from io import BytesIO
            from zipfile import ZipFile, BadZipFile

            print(f"[TitloviAPI] Extracting ZIP, size: {len(zip_content)} bytes")

            zipfile = ZipFile(BytesIO(zip_content))
            file_list = zipfile.namelist()
            print(f"[TitloviAPI] ZIP contains {len(file_list)} files: {file_list}")

            # Prioriteta: SRT > SUB > TXT > ASS > SSA > prvi fajl
            extensions_order = ['.srt', '.sub', '.txt', '.ass', '.ssa', '.vtt']

            for ext in extensions_order:
                for filename in file_list:
                    if filename.lower().endswith(ext):
                        print(f"[TitloviAPI] Extracting {filename}")
                        content = zipfile.read(filename)
                        print(f"[TitloviAPI] Extracted {len(content)} bytes from {filename}")

                        # Proveri da nije prazan
                        if len(content) > 10:
                            return content
                        else:
                            print(f"[TitloviAPI] Warning: {filename} is too small ({len(content)} bytes)")

            # Ako nema tekstualnih fajlova, vrati prvi
            if file_list:
                filename = file_list[0]
                print(f"[TitloviAPI] No text files, extracting first file: {filename}")
                return zipfile.read(filename)

            print(f"[TitloviAPI] ZIP is empty")
            return zip_content

        except BadZipFile:
            print(f"[TitloviAPI] Not a valid ZIP file")
            return zip_content
        except Exception as e:
            print(f"[TitloviAPI] ZIP extraction error: {e}")
            return zip_content

    def is_subtitle_content(self, content):
        """Proveri da li je content subtitle fajl"""
        if not content or len(content) < 10:
            return False

        try:
            text = content[:1000].decode('utf-8', errors='ignore')

            # SRT format
            if re.search(r'\d+\s*\r?\n\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}', text):
                return True

            # WebVTT format
            if text.strip().startswith('WEBVTT'):
                return True

            # SUB/IDX format
            if text.startswith('{') and '}' in text:
                return True

            # ASS/SSA format
            if '[Script Info]' in text:
                return True

        except:
            pass

        return False

    # TEST METODE
    def test_search(self, query):
        """Test pretrage"""
        print(f"\n{'=' * 60}")
        print(f"TITLOVI SEARCH TEST: {query}")
        print(f"{'=' * 60}")

        results = self.search(query, ['sr', 'hr'])

        if results:
            print(f"\n✓ Found {len(results)} results")
            for i, result in enumerate(results[:3]):
                print(f"\nResult {i + 1}:")
                print(f"  Title: {result.get('title')}")
                print(f"  Year: {result.get('year')}")
                print(f"  Language: {result.get('language')}")
                print(f"  Prevod ID: {result.get('prevod_id')}")
                print(f"  URL: {result.get('prevod_url')}")
        else:
            print(f"\n✗ No results found")

        return results

    def test_download(self, prevod_id):
        """Test download-a"""
        print(f"\n{'=' * 60}")
        print(f"TITLOVI DOWNLOAD TEST: {prevod_id}")
        print(f"{'=' * 60}")

        # Kreiraj test result
        test_result = {
            'prevod_id': str(prevod_id),
            'prevod_url': f"https://rs.titlovi.com/prevodi/film-{prevod_id}/",
            'title': f"Test {prevod_id}"
        }

        content = self.download(test_result)

        if content:
            print(f"\n✓ Download successful: {len(content)} bytes")

            # Proveri tip
            if content[:2] == b'PK':
                print(f"  Type: ZIP archive")
            elif self.is_subtitle_content(content):
                print(f"  Type: Direct subtitle")
                try:
                    text = content[:200].decode('utf-8', errors='ignore')
                    print(f"  Preview: {text[:100]}...")
                except:
                    print(f"  Binary content")
            else:
                print(f"  Type: Unknown")
        else:
            print(f"\n✗ Download failed")

        return content

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
    """Glavna API klasa koja upravlja svim servisima - DODATA TITLOVI.COM"""

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

        # NEMA potrebe za API ključem za Titlovi.com - JAVAN SERVIS
        self.titlovi_api = TitloviAPI()  # DODATO

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

    def search_titlovi_only(self, query, languages=None, season=None, episode=None):
        """SAMO Titlovi.com pretraga"""
        print(f"[TITLOVI ONLY] Searching: '{query}'")
        return self.titlovi_api.search(query, languages, season, episode)

    def download_titlovi(self, result):
        """Download sa Titlovi.com"""
        return self.titlovi_api.download(result)

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

    def search_subdl_by_imdb(self, imdb_id, languages=None, season=None, episode=None):
        """Pretraga SubDL po IMDB ID-u"""
        if not self.subdl_api_key:
            return []

        print(f"[API] Searching SubDL by IMDB ID: {imdb_id}")

        settings = self.config.read_settings()
        if languages is None:
            languages = settings.get('languages', ['sr', 'hr'])

        # OVO JE KLJUČNO: Prosledi imdb_id parametar!
        results = self.subdl_api.search(
            query="",  # Prazan query jer koristimo imdb_id
            languages=languages,
            imdb_id=imdb_id,  # OVO TREBA DA BUDE POSTAVLJENO!
            season=season,
            episode=episode,
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
            'User-Agent': 'Enigma2 CiefpSubtitles v1.3',
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
            'User-Agent': 'Enigma2 CiefpSubtitles v1.3',
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
    <screen position="center,center" size="1600,800" title="Subtitles Configuration v1.3">
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
        self.setTitle("Subtitles Configuration v1.3")
    
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

NEW in v1.3:
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
    <screen position="center,center" size="1600,800" title="Standard Search v1.3" backgroundColor="#000000">
        <eLabel position="0,0" size="1600,800" backgroundColor="#000000" zPosition="-10" />

        <widget name="input_label" position="50,30" size="200,40" font="Regular;28" foregroundColor="#ffffff" valign="center" />

        <eLabel position="260,30" size="700,40" backgroundColor="#222222" />

        <!-- Input field -->
        <widget name="input" position="270,35" size="680,30"
            font="Regular;28"
            foregroundColor="#ffff00"
            backgroundColor="#222222"
            transparent="0"
            halign="left" zPosition="2" />

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
    """Ekran za SMART pretragu titlova - NOVO U v1.3"""

    skin = """
    <screen position="center,center" size="1600,800" title="Smart Search v1.3" backgroundColor="#000000">
        <eLabel position="0,0" size="1200,800" backgroundColor="#000000" zPosition="-10" />

        <widget name="header" position="50,20" size="1200,50" font="Regular;30" 
                foregroundColor="#ffff00" halign="center" valign="center" />

        <widget name="input_label" position="50,80" size="200,40" font="Regular;28" 
                foregroundColor="#ffffff" valign="center" />

        <eLabel position="260,80" size="700,40" backgroundColor="#222222" />
        <widget name="input" position="270,85" size="680,30"
                font="Regular;28" foregroundColor="#ffff00" backgroundColor="#222222" zPosition="2" />

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
        return """SMART SEARCH v1.3

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
    <screen position="center,center" size="1600,800" title="Advanced Search v1.3">
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
                font="Regular;28" foregroundColor="#ffff00" backgroundColor="#222222" zPosition="2" />
        
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
        languages = settings.get('languages', ['srp', 'hrv'])

        print(f"[ADVANCED SEARCH] Type: {search_type}, Query: '{query}'")
        print(f"[ADVANCED SEARCH] Languages: {languages}")

        results = []

        if "IMDB ID" in search_type:  # OVO JE KLJUČNA PROMENA!
            # IMDB ID pretraga (samo SubDL)
            if query.startswith('tt'):
                self["status"].setText(f"Searching IMDB: {query}...")
                print(f"[ADVANCED] Calling search_subdl_by_imdb for: {query}")

                # KORISTI PRAVU FUNKCIJU ZA IMDB!
                results = self.plugin.api.search_subdl_by_imdb(query, languages)
                print(f"[ADVANCED] IMDB search returned {len(results)} results")

                # Ako nema rezultata, probaj smart search kao fallback
                if not results:
                    print(f"[ADVANCED] No direct IMDB results, trying smart search...")
                    self["status"].setText(f"Trying smart search: {query}...")

                    smart_results = self.plugin.api.search_all_smart(query, languages)

                    # Filtrirati samo IMDB rezultate
                    imdb_results = []
                    for result in smart_results:
                        method = result.get('search_method', '').lower()
                        if method == 'imdb':
                            imdb_results.append(result)

                    results = imdb_results if imdb_results else smart_results

                if not results:
                    self["status"].setText(f"No results for IMDB ID: {query}")
                    list_items = [f"No subtitles found for IMDB ID: {query}"]
                    self.results_list = []
                    self["results"].setList(list_items)
                    return

            else:
                self["status"].setText("IMDB ID must start with 'tt'")
                return

        elif "File Name" in search_type:
            # File name pretraga (samo SubDL)
            self["status"].setText(f"Searching filename: {query[:30]}...")
            print(f"[ADVANCED] Calling search_subdl_by_filename for: {query}")
            results = self.plugin.api.search_subdl_by_filename(query, languages)

            if not results:
                # Probaj smart search kao fallback
                smart_results = self.plugin.api.search_all_smart(query, languages)
                file_results = []
                for result in smart_results:
                    method = result.get('search_method', '').lower()
                    if method == 'file_name':
                        file_results.append(result)

                results = file_results if file_results else smart_results

        else:
            # Standard film name pretraga (oba servisa)
            self["status"].setText(f"Searching: {query[:30]}...")
            print(f"[ADVANCED] Calling search_all for: {query}")
            results = self.plugin.api.search_all(query, languages)

        # Procesiraj rezultate
        self.results_list = results or []

        if not self.results_list:
            list_items = ["No results found"]
            self["results"].setList(list_items)

            if "IMDB ID" in search_type:
                self["status"].setText(f"No subtitles found for IMDB ID: {query}")
            else:
                self["status"].setText("No subtitles found. Try different search.")
            return

        # Prikaži rezultate (isti kod kao prethodno)
        list_items = []
        for idx, result in enumerate(self.results_list, 1):
            title = result.get('title', 'Unknown')
            site = result.get('site', '').upper()
            method = result.get('search_method', '').upper()

            method_icon = ""
            if method == 'IMDB' or method == 'IMDB_DIRECT':
                method_icon = "⭐ "
            elif method == 'FILE_NAME':
                method_icon = "📁 "
            elif method == 'FILM_NAME':
                method_icon = "🎬 "

            site_indicator = f"[{site}] " if site else ""

            display_title = title[:45]
            if len(title) > 45:
                display_title = title[:42] + "..."

            display_text = f"{idx}. {method_icon}{site_indicator}{display_title}"

            info_parts = []
            language = result.get('language', 'Unknown').upper()
            info_parts.append(f"Lang: {language}")

            if method and method != 'STANDARD':
                method_display = method.replace('_', ' ').title()
                info_parts.append(f"Via: {method_display}")

            downloads = result.get('downloads', 0)
            if downloads > 0:
                if downloads >= 1000000:
                    dl_str = f"{downloads / 1000000:.1f}M"
                elif downloads >= 1000:
                    dl_str = f"{downloads / 1000:.1f}K"
                else:
                    dl_str = str(downloads)
                info_parts.append(f"↓{dl_str}")

            if result.get('hd'):
                info_parts.append("HD")
            if result.get('hearing_impaired'):
                info_parts.append("HI")

            season_num = result.get('season')
            episode_num = result.get('episode')
            if season_num and episode_num:
                info_parts.append(f"S{season_num:02d}E{episode_num:02d}")
            elif season_num:
                info_parts.append(f"S{season_num:02d}")

            release = result.get('release_info', '')
            if release and len(release) < 20:
                display_text += f" - {release}"

            if info_parts:
                display_text += f" ({' | '.join(info_parts)})"

            list_items.append(display_text)

        self["results"].setList(list_items)

        # Statistika
        site_counts = {}
        method_counts = {}

        for result in self.results_list:
            site = result.get('site', 'Unknown')
            method = result.get('search_method', 'unknown')
            site_counts[site] = site_counts.get(site, 0) + 1
            method_counts[method] = method_counts.get(method, 0) + 1

        total_results = len(self.results_list)

        if "IMDB ID" in search_type:
            method_summary = []
            for method, count in method_counts.items():
                if method and method != 'unknown':
                    method_display = method.replace('_', ' ').title()
                    method_summary.append(f"{method_display}: {count}")

            if method_summary:
                methods_text = ", ".join(method_summary)
                self["status"].setText(f"ADVANCED IMDB: {total_results} results ({methods_text})")
            else:
                self["status"].setText(f"ADVANCED IMDB: {total_results} results")

        elif "File Name" in search_type:
            sites_text = ", ".join([f"{s}:{c}" for s, c in site_counts.items()])
            self["status"].setText(f"ADVANCED File: {total_results} results ({sites_text})")

        else:
            sites_text = ", ".join([f"{s}:{c}" for s, c in site_counts.items()])
            self["status"].setText(f"ADVANCED: {total_results} results ({sites_text})")

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
        title="Search Series Subtitles v1.3"
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

        self["header"] = Label("SERIES SUBTITLES SEARCH v1.3")
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

class TitloviSearchScreen(Screen):
    """Ekran za pretragu Titlovi.com - NOVO!"""

    skin = """
    <screen position="center,center" size="1600,800" title="Titlovi.com Search" backgroundColor="#000000">
        <eLabel position="0,0" size="1600,800" backgroundColor="#000000" zPosition="-10" />

        <widget name="header" position="50,30" size="1100,50" font="Regular;32" 
                foregroundColor="#ffff00" halign="center" valign="center" />

        <widget name="input_label" position="50,100" size="200,40" 
                font="Regular;28" foregroundColor="#ffffff" valign="center" />
        <eLabel position="260,100" size="700,40" backgroundColor="#222222" />
        <widget name="input" position="270,105" size="680,30"
                font="Regular;28" foregroundColor="#ffff00" backgroundColor="#222222" zPosition="2" />

        <widget name="results" position="50,170" size="1100,500" enableWrapAround="1" 
                scrollbarMode="showOnDemand" backgroundColor="#111111" foregroundColor="#ffffff" 
                itemHeight="50" font="Regular;24" />

        <eLabel position="50,690" size="700,30" backgroundColor="#333333" />
        <widget name="status" position="60,695" size="680,20" 
                font="Regular;22" foregroundColor="#ffff00" transparent="1" />

        <!-- Dugmad -->
        <eLabel text="Exit" position="50,735" size="150,45" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#9f1313" halign="center" valign="center" />
        <eLabel text="Search" position="230,735" size="150,45" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#1f771f" halign="center" valign="center" />
        <eLabel text="Keyboard" position="410,735" size="150,45" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#a08500" halign="center" valign="center" />
        <eLabel text="Download" position="590,735" size="150,45" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#18188b" halign="center" valign="center" />

        <widget name="background" position="1200,0" size="400,800" 
                pixmap="/usr/lib/enigma2/python/Plugins/Extensions/CiefpOpenSubtitles/background.png" />
    </screen>
    """

    def __init__(self, session, plugin, initial_query=""):
        Screen.__init__(self, session)
        self.session = session
        self.plugin = plugin
        self.initial_query = initial_query

        self["header"] = Label("TITLOVI.COM - IMDB ID or Movie title")
        self["input_label"] = Label("Search:")
        self["input"] = Label(initial_query or "")
        self["status"] = Label("ENTER")
        self["background"] = Pixmap()

        self["results"] = MenuList([])
        self.results_list = []

        self["actions"] = ActionMap(["ColorActions", "SetupActions", "MovieSelectionActions"],
                                    {
                                        "red": self.close,
                                        "green": self.doSearch,
                                        "yellow": self.openKeyboard,
                                        "blue": self.downloadSelected,  # OVO TREBA METODA!
                                        "cancel": self.close,
                                        "ok": self.downloadSelected,  # OVO TREBA METODA!
                                        "up": self.up,
                                        "down": self.down,
                                        "left": self.left,
                                        "right": self.right,
                                    }, -2)

        if initial_query:
            self.doSearch()

        self.onLayoutFinish.append(self.updateDisplay)

    # DODAJ OVE METODE ↓

    def updateDisplay(self):
        """Ažuriraj status display"""
        search_text = self["input"].getText()
        if not search_text or not search_text.strip():
            self["status"].setText("Enter")
        else:
            self["status"].setText(f"Ready to search Titlovi.com: {search_text[:30]}...")

    def openKeyboard(self):
        """Otvori virtuelnu tastaturu"""
        current_text = self["input"].getText()
        self.session.openWithCallback(
            self.keyboardCallback,
            VirtualKeyBoard,
            title="Search Titlovi.com ",
            text=current_text
        )

    def keyboardCallback(self, callback=None):
        """Callback nakon unosa sa tastature"""
        if callback is not None:
            cleaned_text = callback.strip()
            self["input"].setText(cleaned_text)
            self.updateDisplay()
            if cleaned_text:
                self.doSearch()

    def doSearch(self):
        """Izvrši pretragu na Titlovi.com"""
        query = self["input"].getText().strip()
        if not query:
            self["status"].setText("Please enter search term!")
            return

        self["status"].setText(f"Searching Titlovi.com for: '{query}'...")

        # Pozovi Titlovi.com API
        results = self.plugin.api.search_titlovi_only(query)

        print(f"[TITLOVI SEARCH] Got {len(results)} results")

        self.results_list = results or []

        if not self.results_list:
            list_items = ["No results found on Titlovi.com"]
            self["results"].setList(list_items)
            self["status"].setText(f"No results for '{query}' on Titlovi.com")
            return

        # Prikaži rezultate
        list_items = []
        for idx, result in enumerate(self.results_list, 1):
            title = result.get('title', 'Unknown')
            year = result.get('year', '')
            language = result.get('language', 'Unknown')
            downloads = result.get('downloads', 0)

            # Formatiraj prikaz
            display_text = f"{idx}. {title}"
            if year:
                display_text += f" ({year})"

            # Skrati ako je predugo
            if len(display_text) > 45:
                display_text = display_text[:42] + "..."

            # Dodaj informacije u zagradi
            info_parts = []

            # Jezik
            lang_short = language[:3] if language else '???'
            info_parts.append(f"Lang: {lang_short}")

            # Download broj
            if downloads > 0:
                if downloads >= 1000:
                    dl_str = f"{downloads / 1000:.1f}K"
                else:
                    dl_str = str(downloads)
                info_parts.append(f"↓{dl_str}")

            if info_parts:
                display_text += f" ({' | '.join(info_parts)})"

            list_items.append(display_text)

        self["results"].setList(list_items)

        # Prikaži statistiku
        total = len(self.results_list)
        self["status"].setText(f"Titlovi.com: {total} results found")

    def downloadSelected(self):
        """Preuzmi selektovani titl - OVO JE METODA KOJA NEDOSTAJE!"""
        selected_idx = self["results"].getSelectedIndex()

        if not self.results_list or selected_idx >= len(self.results_list):
            self["status"].setText("No item selected!")
            return

        result = self.results_list[selected_idx]
        title = result.get('title', 'Unknown')
        media_id = result.get('media_id', '')

        print(f"[TITLOVI SEARCH] Downloading: {title}, media_id: {media_id}")
        self["status"].setText(f"Downloading from Titlovi.com: {title[:30]}...")

        if not media_id:
            self["status"].setText("Error: No media ID!")
            self.session.open(MessageBox,
                              "Error: Cannot download this subtitle (no media ID found)",
                              MessageBox.TYPE_ERROR)
            return

        # Preuzmi sa Titlovi.com
        content = self.plugin.api.download_titlovi(result)

        if content:
            print(f"[TITLOVI SEARCH] Download successful, size: {len(content)} bytes")
            self.saveSubtitle(content, result)
        else:
            print(f"[TITLOVI SEARCH] Download failed")
            self["status"].setText("Download failed!")

            error_msg = f"""Titlovi.com download failed!

Media ID: {media_id}
Title: {title}

Try:
1. Different subtitle result
2. Check internet connection
3. Try again later"""

            self.session.open(MessageBox, error_msg, MessageBox.TYPE_ERROR)

    def saveSubtitle(self, content, result):
        """Sačuvaj preuzeti titl"""
        settings = self.plugin.api.config.read_settings()
        save_path = settings.get('save_path', '/media/hdd/subtitles/')

        # Kreiraj naziv fajla
        title = result.get('title', 'subtitle').replace(' ', '_')
        title = re.sub(r'[^\w\-_]', '', title)
        language = result.get('language_code', 'srp')
        timestamp = int(time.time())

        # Odredi ekstenziju
        ext = '.srt'
        if isinstance(content, bytes):
            if content.startswith(b'PK'):
                ext = '.zip'
            elif content.startswith(b'WEBVTT'):
                ext = '.vtt'

        filename = f"Titlovi_{title}_{language}_{timestamp}{ext}"
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
                              f"Subtitle downloaded from Titlovi.com!\nSaved to: {full_path}",
                              MessageBox.TYPE_INFO,
                              timeout=5)

        except Exception as e:
            print(f"[TITLOVI SEARCH] Error saving subtitle: {e}")
            self["status"].setText(f"Error: {str(e)}")
            self.session.open(MessageBox,
                              f"Error saving subtitle: {str(e)}",
                              MessageBox.TYPE_ERROR)

    # DODAJ I OVE NAVIGACIJSKE METODE ↓

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


class TitloviAdvancedSearchScreen(Screen):
    """Ekran za NAPREDNU pretragu na Titlovi.com - Direktna integracija sa titlovi.com naprednom pretragom"""

    skin = """
    <screen position="center,center" size="1600,900" title="Titlovi.com Advanced Search" backgroundColor="#000000">
        <eLabel position="0,0" size="1600,900" backgroundColor="#000000" zPosition="-10" />

        <widget name="header" position="50,30" size="1100,50" font="Regular;32" 
                foregroundColor="#ffff00" halign="center" valign="center" />

        <!-- NASLOV -->
        <widget name="title_label" position="50,100" size="250,40" 
                font="Regular;28" foregroundColor="#ffffff" valign="center" />
        <eLabel position="320,100" size="630,40" backgroundColor="#222222" />
        <widget name="title_input" position="330,105" size="610,30"
                font="Regular;28" foregroundColor="#ffff00" backgroundColor="#222222" zPosition="2" />

        <!-- IMDB ID -->
        <widget name="imdb_label" position="50,160" size="250,40" 
                font="Regular;28" foregroundColor="#ffffff" valign="center" />
        <eLabel position="320,160" size="630,40" backgroundColor="#222222" />
        <widget name="imdb_input" position="330,165" size="610,30"
                font="Regular;28" foregroundColor="#ffff00" backgroundColor="#222222" zPosition="2" />

        <!-- JEZIK -->
        <widget name="language_label" position="50,220" size="250,40" 
                font="Regular;28" foregroundColor="#ffffff" valign="center" />
        <widget name="language" position="320,220" size="300,40" 
                font="Regular;28" foregroundColor="#ffff00" />

        <!-- TIP -->
        <widget name="type_label" position="50,280" size="250,40" 
                font="Regular;28" foregroundColor="#ffffff" valign="center" />
        <widget name="type" position="320,280" size="300,40" 
                font="Regular;28" foregroundColor="#ffff00" />

        <!-- SEZONA -->
        <widget name="season_label" position="50,340" size="250,40" 
                font="Regular;28" foregroundColor="#ffffff" valign="center" />
        <eLabel position="320,340" size="200,40" backgroundColor="#222222" />
        <widget name="season_input" position="330,345" size="180,30"
                font="Regular;28" foregroundColor="#ffff00" backgroundColor="#222222" zPosition="2" />

        <!-- EPIZODA -->
        <widget name="episode_label" position="550,340" size="250,40" 
                font="Regular;28" foregroundColor="#ffffff" valign="center" />
        <eLabel position="820,340" size="200,40" backgroundColor="#222222" />
        <widget name="episode_input" position="830,345" size="180,30"
                font="Regular;28" foregroundColor="#ffff00" backgroundColor="#222222" zPosition="2" />

        <!-- GODINA -->
        <widget name="year_label" position="50,400" size="250,40" 
                font="Regular;28" foregroundColor="#ffffff" valign="center" />
        <eLabel position="320,400" size="200,40" backgroundColor="#222222" />
        <widget name="year_input" position="330,405" size="180,30"
                font="Regular;28" foregroundColor="#ffff00" backgroundColor="#222222" zPosition="2" />

        <!-- SORTIRANJE -->
        <widget name="sort_label" position="550,400" size="250,40" 
                font="Regular;28" foregroundColor="#ffffff" valign="center" />
        <widget name="sort" position="820,400" size="300,40" 
                font="Regular;28" foregroundColor="#ffff00" />

        <!-- REZULTATI -->
        <widget name="results" position="50,470" size="1100,330" enableWrapAround="1" 
                scrollbarMode="showOnDemand" backgroundColor="#111111" foregroundColor="#ffffff" 
                itemHeight="45" font="Regular;22" />

        <!-- STATUS -->
        <eLabel position="50,820" size="1100,30" backgroundColor="#333333" />
        <widget name="status" position="60,825" size="1080,20" 
                font="Regular;22" foregroundColor="#ffff00" transparent="1" />

        <!-- DUGMAD -->
        <eLabel text="Exit" position="50,865" size="200,45" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#9f1313" halign="center" valign="center" />
        <eLabel text="Search" position="280,865" size="200,45" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#1f771f" halign="center" valign="center" />
        <eLabel text="Keyboard" position="510,865" size="200,45" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#a08500" halign="center" valign="center" />
        <eLabel text="Download" position="740,865" size="200,45" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#18188b" halign="center" valign="center" />
        <eLabel text="Reset" position="970,865" size="200,45" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#a52a8a" halign="center" valign="center" />

        <widget name="background" position="1200,0" size="400,900" 
                pixmap="/usr/lib/enigma2/python/Plugins/Extensions/CiefpOpenSubtitles/background.png" />
    </screen>
    """

    def __init__(self, session, plugin):
        Screen.__init__(self, session)
        self.session = session
        self.plugin = plugin

        # Naslov
        self["header"] = Label("TITLOVI.COM ADVANCED SEARCH")

        # Polja za unos
        self["title_label"] = Label("Naslov:")
        self["title_input"] = Label("")
        self["imdb_label"] = Label("IMDB ID:")
        self["imdb_input"] = Label("")
        self["language_label"] = Label("Jezik:")
        self["language"] = Label("Svi jezici")
        self["type_label"] = Label("Tip pretrage:")
        self["type"] = Label("TV Serija")
        self["season_label"] = Label("Sezona:")
        self["season_input"] = Label("")
        self["episode_label"] = Label("Epizoda:")
        self["episode_input"] = Label("")
        self["year_label"] = Label("Godina:")
        self["year_input"] = Label("")
        self["sort_label"] = Label("Sortiraj po:")
        self["sort"] = Label("Datum postavljanja")

        self["status"] = Label("Popunite željena polja i pritisnite SEARCH")
        self["background"] = Pixmap()

        self["results"] = MenuList([])
        self.results_list = []

        # Opcije za selektore (isti kao na Titlovi.com)
        self.language_options = ["Svi jezici", "Srpski", "Hrvatski", "Bosanski", "Slovenački",
                                 "Makedonski", "Bugarski", "Crnogorski", "Engleski"]
        self.type_options = ["TV Serija", "Film", "Svi"]
        self.sort_options = ["Datum postavljanja", "Naziv", "IMDb ocena", "Broj preuzimanja"]

        self.current_language_idx = 0
        self.current_type_idx = 0
        self.current_sort_idx = 0

        # Trenutno selektovano polje za unos
        self.current_field = "title"

        self["actions"] = ActionMap(["ColorActions", "SetupActions", "MovieSelectionActions"],
                                    {
                                        "red": self.close,
                                        "green": self.doAdvancedSearch,
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
        if not self["title_input"].getText().strip():
            self.current_field = "title"
        elif not self["imdb_input"].getText().strip():
            self.current_field = "imdb"
        elif not self["season_input"].getText().strip():
            self.current_field = "season"
        elif not self["episode_input"].getText().strip():
            self.current_field = "episode"
        elif not self["year_input"].getText().strip():
            self.current_field = "year"

    def openKeyboard(self):
        """Otvori virtuelnu tastaturu za trenutno selektovano polje"""
        if self.current_field == "title":
            current_text = self["title_input"].getText()
            self.session.openWithCallback(
                lambda text: self.fieldCallback(text, "title"),
                VirtualKeyBoard,
                title="Unesi naslov filma/serije",
                text=current_text
            )
        elif self.current_field == "imdb":
            current_text = self["imdb_input"].getText()
            self.session.openWithCallback(
                lambda text: self.fieldCallback(text, "imdb"),
                VirtualKeyBoard,
                title="Unesi IMDB ID (npr: tt0944947)",
                text=current_text
            )
        elif self.current_field == "season":
            current_text = self["season_input"].getText()
            self.session.openWithCallback(
                lambda text: self.fieldCallback(text, "season"),
                VirtualKeyBoard,
                title="Unesi broj sezone",
                text=current_text
            )
        elif self.current_field == "episode":
            current_text = self["episode_input"].getText()
            self.session.openWithCallback(
                lambda text: self.fieldCallback(text, "episode"),
                VirtualKeyBoard,
                title="Unesi broj epizode",
                text=current_text
            )
        elif self.current_field == "year":
            current_text = self["year_input"].getText()
            self.session.openWithCallback(
                lambda text: self.fieldCallback(text, "year"),
                VirtualKeyBoard,
                title="Unesi godinu",
                text=current_text
            )

    def fieldCallback(self, text, field):
        if text is not None:
            text = text.strip()

            if field == "title":
                self["title_input"].setText(text)
                self.current_field = "imdb"

            elif field == "imdb":
                self["imdb_input"].setText(text)
                self.current_field = "season"

            elif field == "season":
                self["season_input"].setText(text)
                self.current_field = "episode"

            elif field == "episode":
                self["episode_input"].setText(text)
                self.current_field = "year"

            elif field == "year":
                self["year_input"].setText(text)

            self.updateDisplay()
            self.highlightCurrentField()

    def doAdvancedSearch(self):
        """Izvrši NAPREDNU pretragu koristeći Titlovi.com advanced search parametre"""
        # Prikupi sve parametre
        title = self["title_input"].getText().strip()
        imdb = self["imdb_input"].getText().strip()
        season = self["season_input"].getText().strip()
        episode = self["episode_input"].getText().strip()
        year = self["year_input"].getText().strip()

        # Proveri da li je nešto uneto
        if not title and not imdb:
            self["status"].setText("Unesite bar NASLOV ili IMDB ID!")
            return

        self["status"].setText("Pretražujem Titlovi.com naprednom pretragom...")

        try:
            # Kreiraj URL za naprednu pretragu - KORISTI PRAVI FORMAT SA t=2
            params = {}

            # Glavni parametar pretrage
            if imdb and imdb.startswith('tt'):
                params['prevod'] = imdb
            elif title:
                params['prevod'] = title

            # Oznaka za naprednu pretragu (t=2 kao na sajtu)
            params['t'] = '2'

            # Dodaj ostale parametre ako postoje
            if season:
                params['s'] = season
            if episode:
                params['e'] = episode
            if year and year.isdigit():
                params['y'] = year

            # Tip pretrage (film/serija)
            type_option = self.type_options[self.current_type_idx]
            if type_option == "TV Serija":
                params['type'] = 'tv'
            elif type_option == "Film":
                params['type'] = 'movie'

            # Sortiranje
            sort_option = self.sort_options[self.current_sort_idx]
            if sort_option == "Datum postavljanja":
                params['sort'] = '4'  # sort=4 na sajtu
            elif sort_option == "Naziv":
                params['sort'] = '1'
            elif sort_option == "IMDb ocena":
                params['sort'] = '2'
            elif sort_option == "Broj preuzimanja":
                params['sort'] = '3'

            print(f"[TITLOVI ADVANCED] Advanced search params: {params}")

            # JEZIČKI PARAMETAR - Bitno za Titlovi.com
            # Na osnovu jezika izabranog u meniju
            language_option = self.language_options[self.current_language_idx]
            jezik_param = None

            if language_option == "Srpski":
                jezik_param = 'sr'
            elif language_option == "Hrvatski":
                jezik_param = 'hr'
            elif language_option == "Bosanski":
                jezik_param = 'bs'
            elif language_option == "Slovenački":
                jezik_param = 'sl'
            elif language_option == "Makedonski":
                jezik_param = 'mk'
            elif language_option == "Bugarski":
                jezik_param = 'bg'
            elif language_option == "Crnogorski":
                jezik_param = 'me'
            elif language_option == "Engleski":
                jezik_param = 'en'

            if jezik_param:
                params['l'] = jezik_param

            # Koristimo postojeći TitloviAPI ali sa naprednim parametrima
            # MODIFIKUJEMO search metodu da prihvati sve parametre
            search_query = title if title else imdb

            results = self.plugin.api.titlovi_api.advanced_search(
                query=search_query,
                params=params
            )

            if results:
                print(f"[TITLOVI ADVANCED] Found {len(results)} results")
                self.processResults(results)
            else:
                # Pokušaj standardnom pretragom kao fallback
                print(f"[TITLOVI ADVANCED] Trying fallback search...")
                fallback_results = self.plugin.api.titlovi_api.search(
                    query=search_query,
                    season=int(season) if season and season.isdigit() else None,
                    episode=int(episode) if episode and episode.isdigit() else None
                )

                if fallback_results:
                    self.processResults(fallback_results)
                else:
                    self["results"].setList(["Nema rezultata za vašu pretragu"])
                    self["status"].setText("Nema rezultata - probajte druge parametre")

        except Exception as e:
            print(f"[TITLOVI ADVANCED] Error: {e}")
            import traceback
            traceback.print_exc()
            self["status"].setText(f"Greška: {str(e)[:50]}")
            self["results"].setList(["Došlo je do greške prilikom pretrage"])

    def processResults(self, results):
        """Procesiraj i prikaži rezultate"""
        self.results_list = results

        if not self.results_list:
            self["results"].setList(["Nema rezultata"])
            self["status"].setText("Nema pronađenih titlova")
            return

        list_items = []
        for idx, result in enumerate(self.results_list, 1):
            title = result.get('title', 'Bez naslova')
            year = result.get('year', '')
            language = result.get('language', '')
            downloads = result.get('downloads', 0)

            # Proveri da li je serija
            is_series = result.get('is_series', False)
            season = result.get('season')
            episode = result.get('episode')

            # Formatiraj prikaz
            display_text = f"{idx}. {title}"

            # Dodaj godinu ako postoji
            if year:
                display_text += f" ({year})"

            # Dodaj informacije o seriji
            if is_series and season and episode:
                display_text += f" [S{season:02d}E{episode:02d}]"
            elif is_series and season:
                display_text += f" [S{season:02d}]"

            # Skrati ako je predugo
            if len(display_text) > 50:
                display_text = display_text[:47] + "..."

            # Dodaj detalje u zagradama
            info_parts = []

            # Jezik
            if language:
                lang_code = self.get_lang_code(language)
                info_parts.append(lang_code)

            # Preuzimanja
            if downloads > 0:
                if downloads >= 1000:
                    dl_str = f"↓{downloads / 1000:.1f}K"
                else:
                    dl_str = f"↓{downloads}"
                info_parts.append(dl_str)

            # IMDB ocena ako postoji
            rating = result.get('imdb_rating')
            if rating:
                info_parts.append(f"⭐{rating}")

            if info_parts:
                display_text += f" ({' | '.join(info_parts)})"

            list_items.append(display_text)

        self["results"].setList(list_items)
        self["status"].setText(f"Pronađeno {len(self.results_list)} titlova")

    def get_lang_code(self, language):
        """Vrati skraćenicu za jezik"""
        lang_map = {
            'srpski': 'SRP', 'српски': 'SRP',
            'hrvatski': 'HRV', 'croatian': 'HRV',
            'bosanski': 'BOS', 'bosnian': 'BOS',
            'slovenački': 'SLV', 'slovenian': 'SLV',
            'makedonski': 'MKD', 'macedonian': 'MKD',
            'bugarski': 'BUL', 'bulgarian': 'BUL',
            'crnogorski': 'MNE', 'montenegrin': 'MNE',
            'engleski': 'ENG', 'english': 'ENG'
        }

        lang_lower = language.lower()
        for key, code in lang_map.items():
            if key in lang_lower:
                return code

        return language[:3].upper()

    def downloadSelected(self):
        """Preuzmi selektovani titl"""
        selected_idx = self["results"].getSelectedIndex()

        if not self.results_list or selected_idx >= len(self.results_list):
            self["status"].setText("Nije selektovan titl!")
            return

        result = self.results_list[selected_idx]
        title = result.get('title', 'Nepoznato')
        media_id = result.get('media_id') or result.get('prevod_id')

        print(f"[TITLOVI ADVANCED] Downloading: {title}, ID: {media_id}")
        self["status"].setText(f"Preuzimam: {title[:30]}...")

        if not media_id:
            self["status"].setText("Greška: Nedostaje ID titla")
            self.session.open(MessageBox,
                              "Ne mogu da preuzmem ovaj titl (nedostaje ID)",
                              MessageBox.TYPE_ERROR)
            return

        # Koristimo postojeću download metodu
        content = self.plugin.api.titlovi_api.download(media_id, title)

        if content:
            print(f"[TITLOVI ADVANCED] Download successful: {len(content)} bytes")
            self.saveSubtitle(content, result)
        else:
            print(f"[TITLOVI ADVANCED] Download failed")
            self["status"].setText("Greška pri preuzimanju")

            error_msg = f"""Preuzimanje sa Titlovi.com nije uspelo!

Naslov: {title}
ID: {media_id}

Mogući razlozi:
1. Titl je uklonjen sa sajta
2. Problemi sa konekcijom
3. Privremeni problem sa serverom

Pokušajte:
• Drugi rezultat
• Kasnije ponovo
• Proverite internet konekciju"""

            self.session.open(MessageBox, error_msg, MessageBox.TYPE_ERROR)

    def saveSubtitle(self, content, result):
        """Sačuvaj preuzeti titl"""
        settings = self.plugin.api.config.read_settings()
        save_path = settings.get('save_path', '/media/hdd/subtitles/')

        # Kreiraj ime fajla
        title = result.get('title', 'titl').replace(' ', '_')
        title = re.sub(r'[^\w\-_]', '', title)
        language = result.get('language_code', 'srp')
        timestamp = int(time.time())

        # Dodaj sezonu/epizodu za serije
        season = result.get('season')
        episode = result.get('episode')

        # Odredi ekstenziju
        if isinstance(content, bytes):
            if content.startswith(b'PK'):
                ext = '.zip'
            elif b'WEBVTT' in content[:100]:
                ext = '.vtt'
            elif b'[Script Info]' in content[:100]:
                ext = '.ass'
            elif b'{' in content[:50] and b'}' in content[:50]:
                ext = '.sub'
            else:
                ext = '.srt'
        else:
            ext = '.srt'

        # Formiraj ime fajla
        if season and episode:
            filename = f"Titlovi_{title}_S{season:02d}E{episode:02d}_{language}_{timestamp}{ext}"
        elif season:
            filename = f"Titlovi_{title}_S{season:02d}_{language}_{timestamp}{ext}"
        else:
            filename = f"Titlovi_{title}_{language}_{timestamp}{ext}"

        full_path = os.path.join(save_path, filename)

        try:
            if not pathExists(save_path):
                createDir(save_path)

            if isinstance(content, str):
                content = content.encode('utf-8')

            with open(full_path, 'wb') as f:
                f.write(content)

            self["status"].setText(f"Sačuvano: {filename}")

            # Auto-map na video fajl
            self.autoMapSubtitle(full_path, title)

            self.session.open(MessageBox,
                              f"Titl uspešno preuzet!\n\nSačuvano u: {full_path}",
                              MessageBox.TYPE_INFO,
                              timeout=5)

        except Exception as e:
            print(f"[TITLOVI ADVANCED] Save error: {e}")
            self["status"].setText(f"Greška: {str(e)[:30]}")
            self.session.open(MessageBox,
                              f"Greška pri čuvanju titla: {str(e)}",
                              MessageBox.TYPE_ERROR)

    def autoMapSubtitle(self, subtitle_path, base_name):
        """Pokušaj automatski mapirati titl na video fajl"""
        try:
            video_extensions = ['.mkv', '.mp4', '.avi', '.ts', '.mov', '.m2ts']
            sub_dir = os.path.dirname(subtitle_path)

            if os.path.exists(sub_dir):
                for file in os.listdir(sub_dir):
                    if any(file.lower().endswith(ext) for ext in video_extensions):
                        video_name = os.path.splitext(file)[0]

                        # Proveri sličnost imena
                        if (base_name.lower() in video_name.lower() or
                                video_name.lower() in base_name.lower() or
                                self.is_similar(base_name, video_name)):

                            # Koristi jezik iz konfiguracije
                            settings = self.plugin.api.config.read_settings()
                            languages = settings.get('languages', ['srp'])
                            lang_code = languages[0] if languages else 'srp'

                            new_name = f"{video_name}.{lang_code}.srt"
                            new_path = os.path.join(sub_dir, new_name)

                            if not os.path.exists(new_path):
                                os.rename(subtitle_path, new_path)
                                print(f"[TITLOVI ADVANCED] Auto-mapped to: {new_name}")
                                return True
            return False
        except Exception as e:
            print(f"[TITLOVI ADVANCED] Auto-map error: {e}")
            return False

    def is_similar(self, str1, str2):
        """Proveri da li su stringovi slični"""
        import difflib
        str1_clean = re.sub(r'[^\w]', '', str1.lower())
        str2_clean = re.sub(r'[^\w]', '', str2.lower())

        similarity = difflib.SequenceMatcher(None, str1_clean, str2_clean).ratio()
        return similarity > 0.7

    def up(self):
        """Gore strelica - navigacija kroz polja"""
        field_order = ["title", "imdb", "season", "episode", "year"]

        if self["results"].getList():
            self["results"].up()
        else:
            # Menjanje polja
            if self.current_field in field_order:
                idx = field_order.index(self.current_field)
                self.current_field = field_order[(idx - 1) % len(field_order)]
            else:
                self.current_field = "title"

            self.updateDisplay()
            self.highlightCurrentField()

    def down(self):
        """Dole strelica - navigacija kroz polja"""
        field_order = ["title", "imdb", "season", "episode", "year"]

        if self["results"].getList():
            self["results"].down()
        else:
            # Menjanje polja
            if self.current_field in field_order:
                idx = field_order.index(self.current_field)
                self.current_field = field_order[(idx + 1) % len(field_order)]
            else:
                self.current_field = "title"

            self.updateDisplay()
            self.highlightCurrentField()

    def left(self):
        """Levo strelica - menjanje opcija ili page up"""
        if self["results"].getList():
            self["results"].pageUp()
        else:
            # Menjanje jezika, tipa ili sortiranja
            if self.current_field == "language":
                self.current_language_idx = (self.current_language_idx - 1) % len(self.language_options)
                self["language"].setText(self.language_options[self.current_language_idx])
            elif self.current_field == "type":
                self.current_type_idx = (self.current_type_idx - 1) % len(self.type_options)
                self["type"].setText(self.type_options[self.current_type_idx])
            elif self.current_field == "sort":
                self.current_sort_idx = (self.current_sort_idx - 1) % len(self.sort_options)
                self["sort"].setText(self.sort_options[self.current_sort_idx])

            self.updateDisplay()

    def right(self):
        """Desno strelica - menjanje opcija ili page down"""
        if self["results"].getList():
            self["results"].pageDown()
        else:
            # Menjanje jezika, tipa ili sortiranja
            if self.current_field == "language":
                self.current_language_idx = (self.current_language_idx + 1) % len(self.language_options)
                self["language"].setText(self.language_options[self.current_language_idx])
            elif self.current_field == "type":
                self.current_type_idx = (self.current_type_idx + 1) % len(self.type_options)
                self["type"].setText(self.type_options[self.current_type_idx])
            elif self.current_field == "sort":
                self.current_sort_idx = (self.current_sort_idx + 1) % len(self.sort_options)
                self["sort"].setText(self.sort_options[self.current_sort_idx])

            self.updateDisplay()

    def highlightCurrentField(self):
        """Istakni trenutno selektovano polje (može se implementirati promenom boje)"""
        # Ova metoda može da menja boju polja koje je trenutno selektovano
        # Za sada ćemo samo ispisati u statusu
        field_names = {
            "title": "Naslov",
            "imdb": "IMDB ID",
            "season": "Sezona",
            "episode": "Epizoda",
            "year": "Godina"
        }

        if self.current_field in field_names:
            current_value = ""
            if self.current_field == "title":
                current_value = self["title_input"].getText()
            elif self.current_field == "imdb":
                current_value = self["imdb_input"].getText()
            elif self.current_field == "season":
                current_value = self["season_input"].getText()
            elif self.current_field == "episode":
                current_value = self["episode_input"].getText()
            elif self.current_field == "year":
                current_value = self["year_input"].getText()

            if current_value:
                self["status"].setText(f"Selektovano: {field_names[self.current_field]} = '{current_value}'")
            else:
                self["status"].setText(f"Selektovano: {field_names[self.current_field]} (prazno)")

class SubtitleFileExplorer(Screen):
    """File Explorer za pregled skinutih titlova"""

    skin = """
    <screen position="center,center" size="1600,800" title="Subtitle File Explorer" backgroundColor="#000000">
        <eLabel position="0,0" size="1600,800" backgroundColor="#000000" zPosition="-10" />

        <widget name="header" position="50,30" size="1100,50" font="Regular;32" 
                foregroundColor="#ffff00" halign="center" valign="center" />

        <widget name="path_label" position="50,90" size="150,40" 
                font="Regular;28" foregroundColor="#ffffff" valign="center" />
        <widget name="path" position="210,90" size="900,40" 
                font="Regular;28" foregroundColor="#ffff00" />

        <widget name="files" position="50,150" size="1100,500" enableWrapAround="1" 
                scrollbarMode="showOnDemand" backgroundColor="#111111" foregroundColor="#ffffff" 
                itemHeight="45" font="Regular;24" />

        <eLabel position="50,670" size="1100,30" backgroundColor="#333333" />
        <widget name="status" position="60,675" size="1080,20" 
                font="Regular;22" foregroundColor="#ffff00" transparent="1" />

        <!-- Dugmad -->
        <eLabel text="Exit" position="50,720" size="200,50" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#9f1313" halign="center" valign="center" />
        <eLabel text="Select" position="280,720" size="200,50" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#1f771f" halign="center" valign="center" />
        <eLabel text="Delete" position="510,720" size="200,50" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#a08500" halign="center" valign="center" />
        <eLabel text="Refresh" position="740,720" size="200,50" font="Regular;26" 
                foregroundColor="#ffffff" backgroundColor="#18188b" halign="center" valign="center" />

        <widget name="background" position="1200,0" size="400,800" 
                pixmap="/usr/lib/enigma2/python/Plugins/Extensions/CiefpOpenSubtitles/background.png" />
    </screen>
    """

    def __init__(self, session, plugin):
        Screen.__init__(self, session)
        self.session = session
        self.plugin = plugin

        self["header"] = Label("SUBTITLE FILE EXPLORER")
        self["path_label"] = Label("Path:")
        self["path"] = Label("")
        self["status"] = Label("Loading files...")
        self["background"] = Pixmap()

        self["files"] = MenuList([])
        self.file_list = []  # Lista fajlova sa punim putevima
        self.current_dir = ""

        self["actions"] = ActionMap(["ColorActions", "SetupActions", "MovieSelectionActions"],
                                    {
                                        "red": self.close,
                                        "green": self.selectFile,
                                        "yellow": self.deleteFile,
                                        "blue": self.refreshFiles,
                                        "cancel": self.close,
                                        "ok": self.selectFile,
                                        "up": self.up,
                                        "down": self.down,
                                        "left": self.left,
                                        "right": self.right,
                                    }, -2)

        self.onLayoutFinish.append(self.loadFiles)

    def loadFiles(self):
        """Učitaj fajlove iz config foldera"""
        settings = self.plugin.api.config.read_settings()
        save_path = settings.get('save_path', '/media/hdd/subtitles/')

        self.current_dir = save_path

        # Proveri da li folder postoji
        if not pathExists(save_path):
            self["status"].setText("Folder does not exist!")
            self["path"].setText(save_path)
            return

        self["path"].setText(save_path)
        self["status"].setText("Loading...")

        try:
            import os
            import time
            from datetime import datetime

            # Pronađi sve subtitle fajlove
            subtitle_extensions = ['.srt', '.sub', '.ass', '.ssa', '.vtt', '.txt']

            files = []
            self.file_list = []

            for filename in sorted(os.listdir(save_path), key=lambda x: os.path.getmtime(os.path.join(save_path, x)),
                                   reverse=True):
                full_path = os.path.join(save_path, filename)

                # Proveri da li je fajl (ne folder) i da li je subtitle
                if os.path.isfile(full_path):
                    if any(filename.lower().endswith(ext) for ext in subtitle_extensions):
                        # Dobij informacije o fajlu
                        file_size = os.path.getsize(full_path)
                        mod_time = os.path.getmtime(full_path)
                        mod_date = datetime.fromtimestamp(mod_time).strftime('%d.%m.%Y %H:%M')

                        # Formatiraj veličinu
                        if file_size < 1024:
                            size_str = f"{file_size} B"
                        elif file_size < 1024 * 1024:
                            size_str = f"{file_size / 1024:.1f} KB"
                        else:
                            size_str = f"{file_size / (1024 * 1024):.1f} MB"

                        # Skrati naziv ako je predug
                        display_name = filename
                        if len(filename) > 40:
                            name, ext = os.path.splitext(filename)
                            display_name = name[:37] + "..." + ext

                        # Kreiraj prikaz
                        display_text = f"{display_name}"
                        display_text += f" ({size_str}, {mod_date})"

                        files.append(display_text)
                        self.file_list.append({
                            'path': full_path,
                            'name': filename,
                            'size': file_size,
                            'date': mod_date
                        })

            if files:
                self["files"].setList(files)
                self["status"].setText(f"Found {len(files)} subtitle files")
            else:
                self["files"].setList(["No subtitle files found"])
                self["status"].setText("No subtitle files in folder")

        except Exception as e:
            print(f"[FILE EXPLORER] Error loading files: {e}")
            self["status"].setText(f"Error: {str(e)[:50]}")
            self["files"].setList(["Error loading files"])

    def selectFile(self):
        """Selektuj fajl za dodatne opcije"""
        selected_idx = self["files"].getSelectedIndex()

        if not self.file_list or selected_idx >= len(self.file_list):
            self["status"].setText("No file selected!")
            return

        file_info = self.file_list[selected_idx]
        filename = file_info['name']

        # Prikaži opcije za fajl
        options = [
            (f"Delete '{filename}'", "delete"),
            (f"Rename file", "rename"),
            (f"View file info", "info"),
            ("Cancel", "cancel")
        ]

        self.session.openWithCallback(
            self.fileActionCallback,
            ChoiceBox,
            title=f"File: {filename}",
            list=options
        )

    def fileActionCallback(self, result):
        """Callback za akcije nad fajlom"""
        if result is None:
            return

        action, action_type = result

        if action_type == "delete":
            self.deleteFile()
        elif action_type == "rename":
            self.renameFile()
        elif action_type == "info":
            self.showFileInfo()

    def deleteFile(self):
        """Obriši selektovani fajl"""
        selected_idx = self["files"].getSelectedIndex()

        if not self.file_list or selected_idx >= len(self.file_list):
            self["status"].setText("No file selected!")
            return

        file_info = self.file_list[selected_idx]
        filename = file_info['name']
        filepath = file_info['path']

        # Potvrda brisanja
        self.session.openWithCallback(
            lambda confirm: self.confirmDelete(confirm, filepath, filename, selected_idx),
            MessageBox,
            f"Delete file '{filename}'?\n\nSize: {self.format_size(file_info['size'])}\nDate: {file_info['date']}",
            MessageBox.TYPE_YESNO
        )

    def confirmDelete(self, confirmed, filepath, filename, index):
        """Potvrdi brisanje fajla"""
        if not confirmed:
            self["status"].setText("Delete cancelled")
            return

        try:
            import os
            os.remove(filepath)

            # Ukloni iz liste
            if index < len(self.file_list):
                del self.file_list[index]

            # Refresh prikaz
            self.refreshFiles()

            self["status"].setText(f"Deleted: {filename}")
            self.session.open(
                MessageBox,
                f"File '{filename}' deleted successfully!",
                MessageBox.TYPE_INFO,
                timeout=3
            )

        except Exception as e:
            print(f"[FILE EXPLORER] Delete error: {e}")
            self["status"].setText(f"Delete failed: {str(e)[:50]}")
            self.session.open(
                MessageBox,
                f"Error deleting file: {str(e)}",
                MessageBox.TYPE_ERROR
            )

    def renameFile(self):
        """Preimenuj fajl"""
        selected_idx = self["files"].getSelectedIndex()

        if not self.file_list or selected_idx >= len(self.file_list):
            self["status"].setText("No file selected!")
            return

        file_info = self.file_list[selected_idx]
        old_name = file_info['name']

        # Otvori virtualnu tastaturu za novi naziv
        self.session.openWithCallback(
            lambda new_name: self.doRename(new_name, file_info, selected_idx),
            VirtualKeyBoard,
            title=f"Rename file\nCurrent: {old_name}",
            text=os.path.splitext(old_name)[0]  # Bez ekstenzije
        )

    def doRename(self, new_name, file_info, index):
        """Izvrši preimenovanje"""
        if not new_name:
            return

        import os

        old_path = file_info['path']
        old_dir = os.path.dirname(old_path)
        old_ext = os.path.splitext(file_info['name'])[1]

        # Dodaj ekstenziju ako je korisnik izostavio
        if not new_name.lower().endswith(old_ext.lower()):
            new_name += old_ext

        new_path = os.path.join(old_dir, new_name)

        # Proveri da li novi fajl već postoji
        if os.path.exists(new_path):
            self.session.open(
                MessageBox,
                f"File '{new_name}' already exists!",
                MessageBox.TYPE_ERROR
            )
            return

        try:
            os.rename(old_path, new_path)

            # Ažuriraj listu
            self.refreshFiles()

            self["status"].setText(f"Renamed to: {new_name}")
            self.session.open(
                MessageBox,
                f"File renamed successfully!\n\n{file_info['name']} → {new_name}",
                MessageBox.TYPE_INFO,
                timeout=3
            )

        except Exception as e:
            print(f"[FILE EXPLORER] Rename error: {e}")
            self["status"].setText(f"Rename failed")
            self.session.open(
                MessageBox,
                f"Error renaming file: {str(e)}",
                MessageBox.TYPE_ERROR
            )

    def showFileInfo(self):
        """Prikaži informacije o fajlu"""
        selected_idx = self["files"].getSelectedIndex()

        if not self.file_list or selected_idx >= len(self.file_list):
            self["status"].setText("No file selected!")
            return

        file_info = self.file_list[selected_idx]

        # Pročitaj prvih nekoliko linija fajla
        preview_lines = []
        try:
            with open(file_info['path'], 'r', encoding='utf-8', errors='ignore') as f:
                for i in range(10):  # Prvih 10 linija
                    line = f.readline()
                    if not line:
                        break
                    preview_lines.append(line.strip()[:80])  # Skrati duge linije
        except:
            preview_lines = ["Could not read file content"]

        # Kreiraj info tekst
        info_text = f"""FILE INFORMATION:

Name: {file_info['name']}
Path: {file_info['path']}
Size: {self.format_size(file_info['size'])}
Date: {file_info['date']}
Type: {self.get_file_type(file_info['name'])}

PREVIEW:
"""
        for i, line in enumerate(preview_lines[:5]):
            info_text += f"{i + 1}. {line}\n"

        if len(preview_lines) > 5:
            info_text += "...\n"

        info_text += "\nPress OK to close"

        self.session.open(
            MessageBox,
            info_text,
            MessageBox.TYPE_INFO
        )

    def format_size(self, size_bytes):
        """Formatiraj veličinu fajla"""
        if size_bytes < 1024:
            return f"{size_bytes} bytes"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def get_file_type(self, filename):
        """Odredi tip fajla"""
        import os
        ext = os.path.splitext(filename)[1].lower()

        ext_types = {
            '.srt': 'SubRip Subtitle',
            '.sub': 'MicroDVD Subtitle',
            '.ass': 'ASS/SSA Subtitle',
            '.ssa': 'SSA Subtitle',
            '.vtt': 'WebVTT Subtitle',
            '.txt': 'Text File',
            '.zip': 'ZIP Archive'
        }

        return ext_types.get(ext, 'Unknown')

    def refreshFiles(self):
        """Osveži listu fajlova"""
        self["status"].setText("Refreshing...")
        self.loadFiles()

    def up(self):
        if self["files"].getList():
            self["files"].up()

    def down(self):
        if self["files"].getList():
            self["files"].down()

    def left(self):
        if self["files"].getList():
            self["files"].pageUp()

    def right(self):
        if self["files"].getList():
            self["files"].pageDown()

class OpenSubtitlesMainScreen(Screen):
    skin = """
    <screen name="CiefpOpenSubtitlesMain" position="center,center" size="1600,800" title="Ciefp Subtitles v1.3" backgroundColor="#000000">
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

        # AŽURIRAJ OVAJ LIST items ↓
        self.menu_items = [
            ("Standard Search (Film Name)", "search_standard"),
            ("Smart Search (All methods)", "search_smart"),
            ("Advanced Search (SubDL)", "search_advanced"),
            ("Titlovi.com Basic", "search_titlovi"),
            ("Titlovi.com Advanced", "search_titlovi_advanced"),  # DODATO
            ("Search Series", "search_series"),
            ("File Explorer", "file_explorer"),
            ("Configuration", "config"),
            ("API Keys Setup", "api_keys"),
            ("About v1.3", "about"),
            ("Exit", "exit")
        ]
        self["menu"] = MenuList([])
        self["background"] = Pixmap()

        list_items = []
        for idx, item in enumerate(self.menu_items):
            # DODAJ OVU IKONICU ZA TITLOVI.COM ↓
            icon = ""
            if "Standard" in item[0]:
                icon = "📝 "
            elif "Smart" in item[0]:
                icon = "🚀 "
            elif "Advanced" in item[0]:
                icon = "🔍 "
            elif "Titlovi.com" in item[0]:  # DODATO
                icon = "🇷🇸 "  # Balkan ikonica
            elif "Series" in item[0]:
                icon = "📺 "
            elif "File Explorer" in item[0]:
                icon = "📁 "
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
        
        self["title"] = Label("Ciefp Subtitles v1.3")
        
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
        
        help_text = f"""Ciefp Subtitles v1.3
1.STANDARD SEARCH:
   • Uses Film Name only

2.SMART SEARCH (NEW):
   • Tries ALL methods in order:
     1. IMDB ID (best) - tt1375666
     2. File Name (good) - Movie.Name.2023
     3. Film Name (ok)

3.ADVANCED SEARCH:
   • Manual choice: IMDB/File/Film
   • Use the up and down arrows to change

4. TITLOVI.COM SEARCH: (NEW - COMPLETELY SEPARATE!)
   • Balkan languages ONLY (srp/hrv/bos/slv/mkd)
   • NO API key required
   • HTML scraping (no API)
   • Perfect for Balkan users

..:: CiefpSettings ::.."""
        self.session.open(MessageBox, help_text, MessageBox.TYPE_INFO)
    
    def keyYellow(self):
        """Žuto dugme - Refresh"""
        list_items = []
        for idx, item in enumerate(self.menu_items):
            # DODAJ OVU IKONICU ZA TITLOVI.COM ↓
            icon = ""
            if "Standard" in item[0]:
                icon = "📝 "
            elif "Smart" in item[0]:
                icon = "🚀 "
            elif "Advanced" in item[0]:
                icon = "🔍 "
            elif "Titlovi.com" in item[0]:  # DODATO
                icon = "🇷🇸 "  # Balkan ikonica
            elif "Series" in item[0]:
                icon = "📺 "
            elif "File Explorer" in item[0]:
                icon = "📁 "
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
            elif action == "search_titlovi":  # DODATO
                self.session.open(TitloviSearchScreen, self.plugin)  # KORISTI TitloviSearchScreen
            elif action == "search_titlovi_advanced":  # DODATO
                self.session.open(TitloviAdvancedSearchScreen, self.plugin)  # NOVO!
            elif action == "search_series":
                self.session.open(OpenSubtitlesSeriesSearchScreen, self.plugin)
            elif action == "file_explorer":
                self.session.open(SubtitleFileExplorer, self.plugin)
            elif action == "config":
                self.session.open(OpenSubtitlesConfigScreen, self.plugin)
            elif action == "api_keys":
                self.session.open(OpenSubtitlesApiKeysScreen, self.plugin)
            elif action == "about":
                about_text = f"""Ciefp Subtitles Plugin
1. Standard Search (Film Name)
   Simple and fast

2. Smart Search (RECOMMENDED!)
   Auto-tries: IMDB > File > Film
   Shows which method worked

3. Advanced Search (Film Name,File Name,IMDB ID)
   Manual choice with arrows ↑ ↓

4. Titlovi.com (NEW!)
   Balkan languages ONLY
   NO API key needed
   Separate from other services

SERVICES:
• SubDL: Unlimited (API key)
• OpenSubtitles: 5/day free
• Titlovi.com: Free, Balkan only
..:: CiefpSettings ::.."""
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