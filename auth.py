import os
import requests as r
from functools import partial
import configparser
import platform
import warnings; warnings.simplefilter('ignore')

os.chdir(os.path.dirname(os.path.abspath(__file__)))
configs = configparser.ConfigParser()
configs.read('config.ini')

VERIFY = configs.getboolean('SSL','verify')
if VERIFY:
    if path := configs.get('SSL', 'path', fallback=None):
        r_post = partial(r.post, verify=path)
    else:
        r_post = r.post
else:
    r_post = partial(r.post, verify=False)


TOKEN_FILENAME = 'token.txt' 
system = platform.system()
if system == 'Windows':
    TOKEN_PATH = os.path.join(os.environ.get('LOCALAPPDATA'), TOKEN_FILENAME)
elif system == 'Linux':
    home_dir = os.path.expanduser('~')
    token_dir = os.path.join(home_dir, '.local',
                             'share', 'shupe-carboni-backend-tui')
    os.makedirs(token_dir, exist_ok=True)
    TOKEN_PATH = os.path.join(token_dir, TOKEN_FILENAME)
else:
    TOKEN_PATH = os.path.join('./', TOKEN_FILENAME)

class AuthToken:
    header: dict[str,str]

    @classmethod
    def set_header(cls, new_bearer):
        cls.header = {'Authorization': new_bearer}

    @staticmethod
    def build_header(http_resp: r.Response) -> dict[str,str]:
        return {
            'Authorization': f"{http_resp.json()['token_type']} "
                            f"{http_resp.json()['access_token']}"
        }

    @classmethod
    def get_new_token(cls):
        OAUTH_URL = configs.get('AUTH', 'oauth_url')

        payload = {
            'client_id': configs.get('AUTH', 'client_id'),
            'client_secret': configs.get('AUTH', 'client_secret'),
            'audience': configs.get('AUTH', 'audience'),
            'grant_type': configs.get('AUTH', 'grant_type')
        }
        resp = r_post(OAUTH_URL, json=payload)

        if resp.status_code != 200:
            raise Exception('Authentication failed')
        else:
            auth_token_header = cls.build_header(resp)
            cls.header = auth_token_header
            try:
                with open(TOKEN_PATH, 'w') as token_file:
                    token_file.write(auth_token_header['Authorization'])
            except Exception as e:
                import traceback as tb
                print('unable to save token')
                print(e)
                print(tb.format_exc())


def set_up_token() -> None:
    try:
        with open(TOKEN_PATH, 'r') as token_file:
            AuthToken.set_header(token_file.read())
    except:
        AuthToken.get_new_token()