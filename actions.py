import re
import os
from pathlib import Path
from typing import Callable
import requests as r
import configparser
from functools import partial, wraps
from tkinter import Tk, filedialog
from models import (
    ADPCustomer,
    Coils,
    SCACustomer,
    CoilAttrs,
    Coil,
    Coils,
    AHAttrs,
    AH,
    AHs,
    Stage,
    Rating,
    Ratings,
    RatingAttrs,
    RatingRels,
)
from auth import AuthToken

os.chdir(os.path.dirname(os.path.abspath(__file__)))
configs = configparser.ConfigParser()
configs.read("config.ini")


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
    onedrive = home_dir / "OneDrive" / "Desktop"
    non_onedrive = home_dir / "Desktop"
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


BACKEND_URL = configs["ENDPOINTS"]["backend_url"]

ADP_RESOURCE = BACKEND_URL + "/vendors/adp"
AHS = ADP_RESOURCE + "/adp-ah-programs"
COILS = ADP_RESOURCE + "/adp-coil-programs"
RATINGS = ADP_RESOURCE + "/adp-program-ratings"
ADP_CUSTOMERS = ADP_RESOURCE + "/adp-customers"
MODEL_LOOKUP = ADP_RESOURCE + "/model-lookup"
ADP_FILE_DOWNLOAD_LINK = ADP_RESOURCE + "/programs/{customer_id}/download?stage={stage}"


VERIFY = configs.getboolean("SSL", "verify")

if VERIFY:
    if path := configs.get("SSL", "path", fallback=None):
        VERIFY = path


def retry(func: Callable) -> Callable:
    @wraps(func)
    def inner(*args, **kwargs):
        resp: r.Response = func(*args, **kwargs)
        if resp.status_code == 401:
            reset_request_methods()
            resp = func(*args, **kwargs)
            if resp.status_code == 401:
                raise Exception("Unable to authenticate")
        return resp

    return inner


r_get = partial(retry(r.get), headers=AuthToken.header, verify=VERIFY)
r_post = partial(retry(r.post), headers=AuthToken.header, verify=VERIFY)
r_patch = partial(retry(r.patch), headers=AuthToken.header, verify=VERIFY)
r_delete = partial(retry(r.delete), headers=AuthToken.header, verify=VERIFY)


class FileSaveError(Exception):
    def __init__(self, filename: str, *args, **kwargs):
        super().__init__(*args, *kwargs)
        self.filename = filename


class UploadError(Exception):
    """Exception for an error in uploading a file"""


def get_coils(for_customer: ADPCustomer, version: int = 1) -> Coils:
    match version:
        case 1:
            url = ADP_CUSTOMERS + f"/{for_customer.id}/adp-coil-programs"
            resp: r.Response = r_get(url)
            data: dict = resp.json()
            if not data.get("data"):
                raise Exception("No Coils")
            customer_coils = [
                Coil(id=record["id"], attributes=CoilAttrs(**record["attributes"]))
                for record in data["data"]
            ]
            customer_coils.sort(
                key=lambda coil: (
                    coil.attributes.stage,
                    coil.attributes.category,
                    coil.attributes.tonnage,
                    coil.attributes.width,
                )
            )
            return Coils(data=customer_coils)
        case 2:
            product_url = (
                BACKEND_URL + f"/v2/vendors/adp/vendor-customers/{for_customer.id}"
            )
            includes = [
                "vendor-pricing-by-class.vendor-pricing-classes",
                "vendor-pricing-by-class.vendor-products.vendor-product-attrs",
                "vendor-pricing-by-customer.vendor-products.vendor-product-attrs",
            ]
            include = "include=" + "&include=".join(incl for incl in includes)
            resp: r.Response = r_get(f"{product_url}?{include}")
            data: dict = resp.json()
            if not data.get("data"):
                raise Exception("No Coils")
            return data

            # customer_coils = [
            #     Coil(id=record["id"], attributes=CoilAttrs(**record["attributes"]))
            #     for record in data["data"]
            # ]


def get_air_handlers(for_customer: ADPCustomer, version: int = 1) -> AHs:
    match version:
        case 1:
            url = ADP_CUSTOMERS + f"/{for_customer.id}/adp-ah-programs"
            resp: r.Response = r_get(url)
            data: dict = resp.json()
            if not data.get("data"):
                raise Exception("No Air Handlers")
            customer_ahs = [
                AH(id=record["id"], attributes=AHAttrs(**record["attributes"]))
                for record in data["data"]
            ]
            customer_ahs.sort(
                key=lambda ah: (
                    ah.attributes.stage,
                    ah.attributes.category,
                    ah.attributes.tonnage,
                    ah.attributes.width,
                )
            )
        case 2:
            pass
    return AHs(data=customer_ahs)


def get_ratings(for_customer: ADPCustomer, version: int = 1) -> Ratings:
    match version:
        case 1:
            url = ADP_CUSTOMERS + f"/{for_customer.id}/adp-program-ratings"
            resp: r.Response = r_get(url)
            data: dict = resp.json()
            if not data.get("data"):
                raise Exception("No Ratings")
            customer_ratings = [
                Rating(
                    id=record["id"],
                    attributes=RatingAttrs(**record["attributes"]),
                    relationships=RatingRels(
                        adp_customers={
                            "data": {"id": for_customer.id, "type": "adp-customers"}
                        }
                    ),
                )
                for record in data["data"]
            ]
            customer_ratings.sort(
                key=lambda rating: (
                    rating.attributes.outdoor_model,
                    rating.attributes.indoor_model,
                )
            )
        case 2:
            pass
    return Ratings(data=customer_ratings)


def get_sca_customers_w_adp_accounts(version: int = 1) -> list[SCACustomer]:
    match version:
        case 1:
            page_num = "page_number=0"
            include = "include=customers"
            fields = "fields_adp_customers=customers,adp-alias"
            query_params = "&".join((page_num, include, fields))
            full_url = ADP_CUSTOMERS + f"?{query_params}"
            resp: r.Response = r_get(url=full_url)
            payload = resp.json()
            adp_customers = {
                r["id"]: (
                    r["attributes"]["adp-alias"],
                    r["relationships"]["customers"]["data"]["id"],
                )
                for r in payload["data"]
            }
            sca_customers = {
                r["id"]: r["attributes"]["name"] for r in payload["included"]
            }
            result = []
            for sca_id, sca_name in sca_customers.items():
                adp_customers_selected = [
                    ADPCustomer(id=k, adp_alias=v[0])
                    for k, v in adp_customers.items()
                    if v[1] == sca_id
                ]
                result.append(
                    SCACustomer(sca_name=sca_name, adp_objs=adp_customers_selected)
                )
        case 2:
            # v2_adp_resource = "/v2/vendors/adp"
            v2_adp_resource = "/v2/vendors/TEST_VENDOR"
            sub_resource = "/vendor-customers"
            page_num = "page_number=0"
            includes = "include=customer-location-mapping.customer-locations.customers"
            url = f"{BACKEND_URL}{v2_adp_resource}{sub_resource}?{includes}&{page_num}"
            resp: r.Response = r_get(url=url)
            resp_data = resp.json()
            data, included = resp_data["data"], resp_data["included"]
            customers = {
                r["id"]: r["attributes"]["name"]
                for r in included
                if r["type"] == "customers"
            }
            customer_by_location = {
                r["id"]: r["relationships"]["customers"]["data"]["id"]
                for r in included
                if r["type"] == "customer-locations"
            }
            location_by_mapping = {
                r["id"]: r["relationships"]["customer-locations"]["data"]["id"]
                for r in included
                if r["type"] == "customer-location-mapping"
            }
            adp_customers_w_mapping = {
                r["id"]: (
                    r["attributes"]["name"],
                    [
                        mapping["id"]
                        for mapping in r["relationships"]["customer-location-mapping"][
                            "data"
                        ]
                    ],
                )
                for r in data
                if r["relationships"]["customer-location-mapping"]["data"]
            }
            result = []
            for sca_id, sca_name in customers.items():
                locations = [
                    id_
                    for id_, customer_id in customer_by_location.items()
                    if customer_id == sca_id
                ]
                mapping_ids_for_locations = [
                    id_
                    for id_, location_id in location_by_mapping.items()
                    if location_id in locations
                ]
                adp_customers_selected = [
                    ADPCustomer(id=id_, adp_alias=v[0])
                    for id_, v in adp_customers_w_mapping.items()
                    if set(v[1]) <= set(mapping_ids_for_locations)
                ]
                result.append(
                    SCACustomer(sca_name=sca_name, adp_objs=adp_customers_selected)
                )
    return result


def reset_request_methods() -> None:
    AuthToken.get_new_token()
    global r_get, r_post, r_patch, r_delete
    r_get = partial(retry(r.get), headers=AuthToken.header, verify=VERIFY)
    r_post = partial(retry(r.post), headers=AuthToken.header, verify=VERIFY)
    r_patch = partial(retry(r.patch), headers=AuthToken.header, verify=VERIFY)
    r_delete = partial(retry(r.delete), headers=AuthToken.header, verify=VERIFY)


def request_dl_link(customer_id: int, stage: Stage) -> str:
    url = ADP_FILE_DOWNLOAD_LINK.format(customer_id=customer_id, stage=stage.value)
    resp: r.Response = r_post(url=url)
    if not resp.status_code == 200:
        raise Exception(
            "Unable to obtain download link.\n" f"Message: {resp.content.decode()}"
        )
    return resp.json()["downloadLink"]


def download_file(customer_id: str, stage: Stage) -> None:
    rel_link = request_dl_link(customer_id, stage)
    resp: r.Response = r_get(BACKEND_URL + rel_link)
    if resp.status_code != 200:
        raise Exception("unable to download file")
    fn_match: re.Match | None = re.search(
        r'filename="(.*?)"', resp.headers.get("content-disposition")
    )
    filename = fn_match.group(1) if fn_match else None
    save_path = str(get_save_dir() / filename)
    try:
        with open(save_path, "wb") as new_file:
            new_file.write(resp.content)
    except PermissionError:
        raise FileSaveError(filename=filename)
    except Exception:
        raise Exception(rf"unexpected error with file save to {save_path}")


def patch_new_coil_status(
    customer_id: int, coil_id: int, new_status: Stage
) -> r.Response:
    url = COILS + f"/{coil_id}"
    payload = {
        "data": {
            "id": coil_id,
            "type": "adp-coil-programs",
            "attributes": {"stage": new_status.value},
            "relationships": {
                "adp-customers": {"data": {"id": customer_id, "type": "adp-customers"}}
            },
        }
    }
    return r_patch(url=url, json=payload)


def price_check(customer_id: int, model: str, *args, **kwargs) -> r.Response:
    query = f"?model_num={model}&customer_id={customer_id}"
    return r_get(url=MODEL_LOOKUP + query)


def post_new_coil(customer_id: int, model: str) -> r.Response:
    data = {
        "type": "adp-coil-programs",
        "attributes": {"model-number": model},
        "relationships": {
            "adp-customers": {"data": {"id": customer_id, "type": "adp-customers"}}
        },
    }
    payload = dict(data=data)
    return r_post(url=COILS, json=payload)


def patch_new_ah_status(customer_id: int, ah_id: int, new_status: Stage) -> r.Response:
    url = AHS + f"/{ah_id}"
    payload = {
        "data": {
            "id": ah_id,
            "type": "adp-ah-programs",
            "attributes": {"stage": new_status.value},
            "relationships": {
                "adp-customers": {"data": {"id": customer_id, "type": "adp-customers"}}
            },
        }
    }
    return r_patch(url=url, json=payload)


def post_new_ah(customer_id: int, model: str) -> r.Response:
    payload = {
        "data": {
            "type": "adp-ah-programs",
            "attributes": {"model-number": model},
            "relationships": {
                "adp-customers": {"data": {"id": customer_id, "type": "adp-customers"}}
            },
        }
    }
    return r_post(url=AHS, json=payload)


def post_new_ratings(customer_id: int, file: str) -> None:
    if not file:
        raise UploadError("no file selected")
    with open(file, "rb") as fh:
        file_data = fh.read()
    resp: r.Response = r_post(
        url=BACKEND_URL + f"/vendors/adp/adp-program-ratings/{customer_id}",
        files={
            "ratings_file": (
                file,
                file_data,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    if not 299 >= resp.status_code >= 200:
        raise UploadError(
            "Ratings were not able to be uploaded successfully. "
            f"Status code {resp.status_code}. "
            f"Message:\n {resp.content.decode()}"
        )


def delete_rating(rating_id: int, customer_id: int) -> r.Response:
    resp: r.Response = r_delete(
        url=RATINGS + f"/{rating_id}?adp_customer_id={customer_id}"
    )
    if code := resp.status_code != 204:
        raise Exception(
            f"Error with delete operation. "
            f"Status: {code}.\n "
            f"Message = {resp.content.decode()}"
        )
    return resp
