import os
import sys
import json

# Determine base application directory
if getattr(sys, 'frozen', False):
    _EXE_DIR = os.path.dirname(sys.executable)
    if os.path.basename(_EXE_DIR).lower() == 'dist':
        _APP_DIR = os.path.dirname(_EXE_DIR)
    else:
        _APP_DIR = _EXE_DIR
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Internal bundled locales directory (PyInstaller temporary directory)
_INTERNAL_LOCALES_DIR = ""
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    _INTERNAL_LOCALES_DIR = os.path.join(sys._MEIPASS, 'locales')

# External locales directory (next to the executable or script)
_EXTERNAL_LOCALES_DIR = os.path.join(_APP_DIR, 'locales')

# Language data storage
_locales = {}               # lang_code -> dict (translation keys)
_available_languages = {}   # lang_code -> display name (e.g. "日本語")
_current_language = "zh_tw" # Default active language

def scan_and_load_locales():
    """Scans bundled and external locales folders to load and merge language JSON files."""
    global _locales, _available_languages
    _locales.clear()
    _available_languages.clear()

    dirs_to_scan = []
    # Scan internal bundled locales first, so external ones can overwrite/supplement them
    if _INTERNAL_LOCALES_DIR and os.path.isdir(_INTERNAL_LOCALES_DIR):
        dirs_to_scan.append(_INTERNAL_LOCALES_DIR)
    if os.path.isdir(_EXTERNAL_LOCALES_DIR):
        dirs_to_scan.append(_EXTERNAL_LOCALES_DIR)

    for d in dirs_to_scan:
        try:
            for filename in os.listdir(d):
                if filename.lower().endswith('.json'):
                    path = os.path.join(d, filename)
                    lang_code = os.path.splitext(filename)[0].lower()
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        if isinstance(data, dict):
                            if lang_code not in _locales:
                                _locales[lang_code] = {}
                            # Update dictionary (overriding keys from internal with external if any)
                            _locales[lang_code].update(data)
                            
                            # Cache the display name
                            lang_name = data.get('lang_name', lang_code)
                            _available_languages[lang_code] = lang_name
                    except Exception as e:
                        print(f"[i18n] Error loading translation file {path}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[i18n] Error scanning directory {d}: {e}", file=sys.stderr)

    # Ensure a basic safety fallback is available
    if not _locales:
        _locales['zh_tw'] = {}
        _available_languages['zh_tw'] = '繁體中文'

def set_language(lang_code: str):
    """Sets the active language. If the requested language isn't loaded, falls back gracefully."""
    global _current_language
    lang_code = lang_code.lower() if lang_code else "zh_tw"
    if lang_code in _locales:
        _current_language = lang_code
    else:
        # Graceful fallback hierarchy
        if 'zh_tw' in _locales:
            _current_language = 'zh_tw'
        elif 'en_us' in _locales:
            _current_language = 'en_us'
        elif _locales:
            _current_language = list(_locales.keys())[0]

def get_current_language() -> str:
    """Returns the current active language code."""
    return _current_language

def get_available_languages() -> dict:
    """Returns a dictionary of all loaded language codes and their display names."""
    return _available_languages

def _tr(key: str, fallback_val: str = None, **kwargs) -> str:
    """
    Translates a key into the active language, with a series of graceful fallbacks:
    1. Active language translation
    2. English ('en_us') translation
    3. Traditional Chinese ('zh_tw') translation
    4. fallback_val parameter
    5. The key itself
    Supports string formatting if keyword arguments are supplied.
    """
    # 1. Try current language
    lang_dict = _locales.get(_current_language, {})
    val = lang_dict.get(key)
    
    # 2. Try English
    if val is None and _current_language != 'en_us':
        val = _locales.get('en_us', {}).get(key)
        
    # 3. Try Traditional Chinese
    if val is None and _current_language != 'zh_tw':
        val = _locales.get('zh_tw', {}).get(key)
        
    # 4. Try manual fallback value
    if val is None:
        val = fallback_val
        
    # 5. Fallback to key
    if val is None:
        val = key

    # Apply formatting
    if kwargs:
        try:
            return val.format(**kwargs)
        except Exception:
            pass
    return val

# Run scan on module import
scan_and_load_locales()
# Set default language
set_language('zh_tw')
