"""Checks for version endpoint response from the API to determine which module to run"""

import requests as r
from configparser import ConfigParser

CONFIGS = ConfigParser()
CONFIGS.read("config.ini")
print(CONFIGS["ENDPOINTS"]["backend_url"])
BACKEND_URL = CONFIGS["ENDPOINTS"]["backend_url"]
V2_AVAILABILITY_ENDPOINT = BACKEND_URL + "/v2"

resp = r.get(str(V2_AVAILABILITY_ENDPOINT))
match resp.status_code:
    case 200:
        import main_v2
    case _:
        import main_v1
