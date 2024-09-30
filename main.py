"""Checks for version endpoint response from the API to determine which module to run"""

from os.path import dirname, abspath
import requests as r
from pathlib import Path
from configparser import ConfigParser

FILE_DIR = Path(dirname(abspath(__file__)))
CONFIGS = ConfigParser()
CONFIGS.read(str(FILE_DIR / "config.ini"))
BACKEND_URL = CONFIGS["ENDPOINTS"]["backend_url"]
V2_AVAILABILITY_ENDPOINT = BACKEND_URL + "/v2"

resp = r.get(V2_AVAILABILITY_ENDPOINT)
match resp.status_code:
    case 200:
        import main_v2
    case _:
        import main_v1
