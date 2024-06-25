import re
import os
from pathlib import Path
import requests as r
import configparser
from functools import partial
from tkinter import Tk, filedialog
from models import (
    ADPCustomer, Coils, SCACustomer,
    CoilAttrs, Coil, Coils, AHAttrs,
    AH, AHs, Stage, Rating, Ratings,
    RatingAttrs
)
from auth import AuthToken

os.chdir(os.path.dirname(os.path.abspath(__file__)))
configs = configparser.ConfigParser()
configs.read('config.ini')

def select_file() -> str:
    root = Tk()
    root.withdraw()
    try:
        file_path = filedialog.askopenfilename()
    except Exception as e:
        pass
    finally:
        root.destroy()
    return file_path

def get_save_dir() -> Path:
    home_dir = Path.home()
    onedrive = home_dir / 'OneDrive' / 'Desktop'
    non_onedrive = home_dir / 'Desktop'
    if Path.exists(onedrive):
        return onedrive
    elif Path.exists(non_onedrive):
        return non_onedrive
    else:
        root = Tk()
        root.withdraw()
        try:
            dir_path = filedialog.askdirectory()
        finally:
            root.destroy()
        return Path(dir_path)
        

BACKEND_URL = configs['ENDPOINTS']['backend_url']

ADP_RESOURCE = BACKEND_URL + '/vendors/adp'
AHS = ADP_RESOURCE + '/adp-ah-programs'
COILS = ADP_RESOURCE + '/adp-coil-programs'
RATINGS = ADP_RESOURCE + '/adp-program-ratings'
ADP_CUSTOMERS = ADP_RESOURCE + '/adp-customers'
ADP_FILE_DOWNLOAD_LINK = (
    ADP_RESOURCE
    + '/programs/{customer_id}/download?stage={stage}'
)


VERIFY = configs.getboolean('SSL','verify')

if VERIFY:
    if path := configs.get('SSL', 'path', fallback=None):
        VERIFY = path

r_get = partial(r.get, headers=AuthToken.header, verify=VERIFY)
r_post = partial(r.post, headers=AuthToken.header, verify=VERIFY)
r_patch = partial(r.patch, headers=AuthToken.header, verify=VERIFY)
r_delete = partial(r.delete, headers=AuthToken.header, verify=VERIFY)


class FileSaveError(Exception):
    def __init__(self,filename: str, *args, **kwargs):
        super().__init__(*args, *kwargs)
        self.filename = filename

class UploadError(Exception):
    """Exception for an error in uploading a file"""

def get_coils(for_customer: ADPCustomer) -> Coils:
    resp = r_get(url=ADP_CUSTOMERS + f'/{for_customer.id}/adp-coil-programs')
    data: dict = resp.json()
    if not data.get('data'):
        raise Exception("No Coils")
    customer_coils = [
        Coil(id=record['id'], attributes=CoilAttrs(**record['attributes']))
        for record in data['data'] 
    ]
    customer_coils.sort(
        key=lambda coil: (
            coil.attributes.stage,
            coil.attributes.category,
            coil.attributes.tonnage,
            coil.attributes.width
        )
    )
    return Coils(data=customer_coils)

def get_air_handlers(for_customer: ADPCustomer) -> AHs:
    resp = r_get(url=ADP_CUSTOMERS + f'/{for_customer.id}/adp-ah-programs')
    data: dict = resp.json()
    if not data.get('data'):
        raise Exception("No Air Handlers")
    customer_ahs = [
        AH(id=record['id'], attributes=AHAttrs(**record['attributes']))
        for record in data['data'] 
    ]
    customer_ahs.sort(
        key=lambda ah: (
            ah.attributes.stage,
            ah.attributes.category,
            ah.attributes.tonnage,
            ah.attributes.width
        )
    )
    return AHs(data=customer_ahs)

def get_ratings(for_customer: ADPCustomer) -> Ratings:
    resp = r_get(url=ADP_CUSTOMERS + f'/{for_customer.id}/adp-program-ratings')
    data: dict = resp.json()
    if not data.get('data'):
        raise Exception("No Ratings")
    customer_ratings = [
        Rating(id=record['id'], attributes=RatingAttrs(**record['attributes']))
        for record in data['data'] 
    ]
    customer_ratings.sort(
        key=lambda rating: (
            rating.attributes.outdoor_model,
            rating.attributes.indoor_model
        )
    )
    return Ratings(data=customer_ratings)

def get_sca_customers_w_adp_accounts() -> list[SCACustomer]:
    # NOTE the API expects JSON:API-like query params
    page_num = 'page_number=0'
    include = 'include=customers'
    fields = 'fields_adp_customers=customers,adp-alias'
    query_params = '&'.join((page_num, include, fields))
    full_url = ADP_CUSTOMERS + f'?{query_params}'
    resp = r_get(url=full_url)
    if resp.status_code == 401:
        reset_request_methods()
        resp = r_get(url=full_url)
        if resp.status_code == 401:
            raise Exception('Unable to authenticate')
    payload = resp.json()
    adp_customers = {
        r['id']: (
            r['attributes']['adp-alias'],
            r['relationships']['customers']['data']['id']
        )
        for r in payload['data']
    }
    sca_customers = {
       r['id']: r['attributes']['name']
       for r in payload['included']
    }
    result = []
    for sca_id, sca_name in sca_customers.items():
        adp_customers_selected = [
            ADPCustomer(id=k, adp_alias=v[0])
            for k,v in adp_customers.items()
            if v[1] == sca_id
        ]
        result.append(SCACustomer(sca_name=sca_name,
                                  adp_objs=adp_customers_selected))
    return result

def reset_request_methods() -> None:
    AuthToken.get_new_token()
    global r_get, r_post, r_patch, r_delete
    r_get = partial(r.get, headers=AuthToken.header, verify=VERIFY)
    r_post = partial(r.post, headers=AuthToken.header, verify=VERIFY)
    r_patch = partial(r.patch, headers=AuthToken.header, verify=VERIFY)
    r_delete = partial(r.delete, headers=AuthToken.header, verify=VERIFY)

def request_dl_link(customer_id: int, stage: Stage) -> str:
    url = ADP_FILE_DOWNLOAD_LINK.format(customer_id=customer_id,
                                        stage=stage.value)
    resp = r_post(url=url)
    if resp.status_code == 401:
        try:
            reset_request_methods()
        except Exception as e:
            print('unable to authenticate with the server')
            raise e
        else:
            resp = r_get(url=url)
        
    elif not resp.status_code == 200:
        raise Exception('Unable to obtain download link.\n'
                        f'Message: {resp.content.decode()}')
    return resp.json()['downloadLink']


def download_file(customer_id: str, stage: Stage) -> None:
    rel_link = request_dl_link(customer_id, stage)
    resp = r_get(BACKEND_URL + rel_link)
    if resp.status_code != 200:
        raise Exception('unable to download file')
    fn_match: re.Match | None = re.search(
            r'filename="(.*?)"',
            resp.headers.get('content-disposition')
        )
    filename = fn_match.group(1) if fn_match else None
    save_path = str(get_save_dir() / filename)
    try:
        with open(save_path, 'wb') as new_file:
            new_file.write(resp.content)
    except PermissionError:
        raise FileSaveError(filename=filename)
    except Exception:
        raise Exception(rf"unexpected error with file save to {save_path}")

def patch_new_coil_status(customer_id: int, coil_id: int, 
                          new_status: Stage) -> r.Response:
    url = COILS + f'/{coil_id}'
    payload = {
        "data": {
            "id": coil_id,
            "type": "adp-coil-programs",
            "attributes": {
                "stage": new_status.value
            },
            "relationships": {
                "adp-customers": {
                    'data': {
                        'id': customer_id,
                        'type': 'adp-customers'
                    }
                }
            }
        }
    }
    return r_patch(url=url, json=payload)

def post_new_coil(customer_id: int, model: str) -> r.Response:
    data = {
        "type": "adp-coil-programs",
        "attributes": {
            "model-number": model
        },
        "relationships": {
            "adp-customers": {
                'data': {
                    'id': customer_id,
                    'type': 'adp-customers'
                }
            }
        }
    }
    payload = dict(data=data)
    return r_post(url=COILS, json=payload)

def patch_new_ah_status(customer_id: int, ah_id: int,
                        new_status: Stage) -> r.Response:
    url = AHS + f'/{ah_id}'
    payload = {
        "data": {
            "id": ah_id,
            "type": "adp-ah-programs",
            "attributes": {
                "stage": new_status.value
            },
        "relationships": {
            "adp-customers": {
                'data': {
                    'id': customer_id,
                    'type': 'adp-customers'
                    }
                }
            }
        }
    }
    return r_patch(url=url, json=payload)

def post_new_ah(customer_id: int, model: str) -> r.Response:
    payload = {
        "data": {
            "type": "adp-ah-programs",
            "attributes": {
                "model-number": model
            },
            "relationships": {
                "adp-customers": {
                    'data': {
                        'id': customer_id,
                        'type': 'adp-customers'
                    }
                }
            }
        }
    }
    return r_post(url=AHS, json=payload)
    
def post_new_ratings(customer_id: int, file: str) -> None:
    if not file:
        raise UploadError('no file selected')
    with open(file, 'rb') as fh:
        file_data = fh.read()
    resp = r_post(
        url=BACKEND_URL + f'/vendors/adp/adp-program-ratings/{customer_id}',
        files={
            'ratings_file': (
                file,
                file_data,
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
        },
    )
    if not 299 >= resp.status_code >= 200:
        raise UploadError('Ratings were not able to be uploaded successfully. '
                          f'Status code {resp.status_code}. '
                          f'Message:\n {resp.content.decode()}')

def delete_rating(rating_id: int) -> r.Response:
    resp = r_delete(url=RATINGS + f'/{rating_id}')
    if code := resp.status_code != 204:
        raise Exception(f'Error with delete operation. '
                        f'Status: {code}.\n '
                        f'Message = {resp.content.decode()}')
    return resp