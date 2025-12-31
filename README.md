

![Enigma2](https://img.shields.io/badge/Enigma2-OpenATV%207.6%2B-blue?logo=linux)
![Python](https://img.shields.io/badge/Python-2.7%2F3.x-yellow?logo=python)
![License](https://img.shields.io/badge/License-GPLv2%2B-green)

| ![Series Search](https://github.com/ciefp/CiefpOpenSubtitles/blob/main/series.jpg) |
A powerful, lightweight subtitle search and download plugin for Enigma2-based set-top boxes (Vu+, Dreambox, etc.), supporting **OpenSubtitles.com (API)** and **OpenSubtitles.org (login)** — with **excellent series search capability**.

> ✨ **Why choose CiefpOpenSubtitles?**  
> While many plugins handle movies well, **CiefpOpenSubtitles excels at series searches** — delivering more accurate, relevant results for TV shows (e.g. *Stranger Things*, *Fargo*, *Westworld*), as confirmed by real-world comparisons.

---

## 🚀 Features

- 🔍 **Search subtitles for movies & TV series** by title, season, and episode  
- 🌐 **Dual backend support**:
  - `OpenSubtitles.com` — via modern REST API (recommended)
  - `OpenSubtitles.org` — via classic username/password login
- 🗣️ **Multi-language support**: use 2-letter (`sr,hr,en`) or 3-letter (`srp,hrv,eng`) codes
- ⬇️ **One-click download & auto-save** to configurable directory (e.g. `/media/hdd/subtitles/`)
- 🔄 **Multi-language download mode**: fetch subtitles in all configured languages for a single title
- 🤖 **Smart auto-matching**: renames downloaded `.srt` files to match existing video files (e.g. `Movie.sr.srt`)
- 📊 **Result filtering & sorting** by year, download count, rating, FPS, HD, and hearing-impaired flag
- 🛠️ **Full configuration**: delay, path, language priority, auto-download toggle

---

## 📺 Screenshots

| Series Search (✅ accurate) | Movie Search | Configuration |
|-----------------------------|--------------|---------------|
| ![Series Search](https://github.com/ciefp/CiefpOpenSubtitles/blob/main/series.jpg) | ![Movie Search](https://github.com/ciefp/CiefpOpenSubtitles/blob/main/movies.jpg) | ![Config](https://github.com/ciefp/CiefpOpenSubtitles/blob/main/series.jpg) |

> 💡 *Note: Input field display bug (missing search text) is known on OpenATV 7.6 + MetrixHD — functional logic is fully intact.*

---

## 🛠️ Installation

### Option 1: Via OPKG (recommended)

opkg install enigma2-plugin-extensions-ciefpopensubtitles*.ipk


### 📦 Plugin Structure
CiefpOpenSubtitles
- **plugin.py                  Main plugin logic**
- **api/                       OpenSubtitles API wrappers (.com & .org)**
- **background.png             Right-side background image**
- **skin/                      Optional skin overrides**
- **README.md                  This file**

###🧩 Planned Features (v2.0+)
- Feature
Status
- **🎞️ Subtitle preview (with MoviePlayer)** Planned
- **📺 EPG integration (auto-search current program)** Planned
- **📼 Auto-download on recording start** Planned
- **📊 IMDb ID search support** Planned
- **🌐 Multi-source fallback (Addic7ed, etc.)** Under review

## 📜 License
This plugin is licensed under GPLv2+.
See LICENSE for details.

⚠️ This plugin uses the OpenSubtitles API — respect their Terms of Use and rate limits.


## 🛠️ Save API Key, Username and Password
- **In the main menu of the plugin, select API Key / Login (blue/OK).**
For .com (recommended – faster and better):
- **Press GREEN (Edit API Key).**
- **Enter the API key from opensubtitles.com (free account > API tab > Create new key).**
It is saved automatically in the file: /etc/enigma2/ciefpopensubtitles/opensubtitles_apikey.txt
(format: apikey=xxxxxxxxxxxxxxx).

- **For .org (older system):**
Press YELLOW (Edit Login).
Enter username, then password from opensubtitles.org.
It is saved automatically in the file: /etc/enigma2/ciefpopensubtitles/opensubtitles_login.txt
(format:
user=yourusername
pass=yourpassword).


## 🙌 Acknowledgements
Based on opensubtitles-api
Inspired by SubsSupport, but optimized for series accuracy
Uses Enigma2 framework (OpenPLi/OpenATV)
## 🔗 Links
OpenSubtitles.com
Enigma2 GitHub
OpenATV
## **Made with ❤️ for the Enigma2 community.**
## **Happy subtitling! 🎬**
