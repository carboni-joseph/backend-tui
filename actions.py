import json
import re
import os
from pathlib import Path
from typing import Callable
from collections import defaultdict
import requests as r
import configparser
from enum import StrEnum
from functools import partial, wraps
from tkinter import Tk, filedialog
from models import (
    ADPCustomer,
    Coils,
    SCACustomer,
    CoilAttrs,
    CoilAttrsV2,
    Coil,
    Coils,
    CoilV2,
    CoilsV2,
    AHAttrs,
    AH,
    AHs,
    AHAttrsV2,
    AHV2,
    AHsV2,
    Stage,
    Rating,
    Ratings,
    RatingAttrs,
    RatingRels,
)
from auth import AuthToken

# VENDOR = "TEST_VENDOR"
VENDOR = "adp"

os.chdir(os.path.dirname(os.path.abspath(__file__)))
configs = configparser.ConfigParser()
configs.read("config.ini")


def reset_request_methods() -> None:
    AuthToken.get_new_token()
    global r_get, r_post, r_patch, r_delete
    r_get = partial(retry(r.get), verify=VERIFY)
    r_post = partial(retry(r.post), verify=VERIFY)
    r_patch = partial(retry(r.patch), verify=VERIFY)
    r_delete = partial(retry(r.delete), verify=VERIFY)


class ADPPricingClasses(StrEnum):
    ZERO_DISCOUNT = "ZERO_DISCOUNT"
    STRATEGY_PRICING = "STRATEGY_PRICING"


class ADPProductClasses(StrEnum):
    COILS = "Coils"
    AIR_HANDLERS = "Air Handlers"


LOCAL_STORAGE = {ADPProductClasses.COILS: {}, ADPProductClasses.AIR_HANDLERS: {}}


def restructure_included(included: list[dict], primary: str, ids: list[int] = None):
    structured = defaultdict(dict)
    primary_objs = []
    for item in included:
        if item["type"] == primary:
            if ids:
                if item["id"] in ids:
                    primary_objs.append(item)
            else:
                primary_objs.append(item)

    for item in primary_objs:
        structured[item["id"]] = {
            attr: value for attr, value in item["attributes"].items()
        }
        for rel_key, rel_item in item["relationships"].items():
            if "data" in rel_item:
                related_ids = []
                match rel_item["data"]:
                    case dict():
                        related_ids.append(rel_item["data"]["id"])
                    case list():
                        if not rel_item["data"]:
                            continue
                        for data_item in rel_item["data"]:
                            related_ids.append(data_item["id"])
                structured[item["id"]].setdefault(rel_key, {})
                structured[item["id"]][rel_key] |= restructure_included(
                    included, rel_key, related_ids
                )

    return {k: v for k, v in structured.items() if v}


def restructure_pricing_by_class(obj: dict) -> dict:
    result = dict()
    for price_class_mapping in obj.values():
        price_class_mapping: dict[str, None | dict]
        for price_class in price_class_mapping["vendor-pricing-classes"].values():
            price_class: dict[str, None | dict | str]
            if price_class["name"] == ADPPricingClasses.ZERO_DISCOUNT:
                for product_price in price_class["vendor-pricing-by-class"].values():
                    product_price: dict[str, int | None | dict]
                    id_, product_info = product_price["vendor-products"].popitem()
                    product_attrs: dict = product_info.get("vendor-product-attrs", {})
                    if product_attrs:
                        product_attrs = {
                            attr["attr"]: attr["value"]
                            for attr in product_attrs.values()
                        }
                    product_attrs |= {
                        "model_number": product_info["vendor-product-identifier"],
                        "description": product_info["vendor-product-description"],
                        "price": product_price["price"],
                    }

                    result.update({id_: product_attrs})
    return result


def restructure_pricing_by_customer(obj: dict) -> dict:
    result = dict()
    for product_price in obj.values():
        product_price: dict[str, int | bool | dict | None]
        product: dict
        id_, product = product_price["vendor-products"].popitem()
        product_attrs: dict = product.get("vendor-product-attrs", {})
        if product_attrs:
            product_attrs = {
                attr["attr"]: attr["value"] for attr in product_attrs.values()
            }
        product_attrs |= {
            "model_number": product["vendor-product-identifier"],
            "description": product["vendor-product-description"],
            "price": product_price["price"],
            "effective_date": product_price["effective-date"],
        }
        if product_price["use-as-override"]:
            result.update({id_: product_attrs})
        else:
            result.update({f"{id_} override": product_attrs})
    return result


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

# V2
V2 = "/v2/vendors/adp"

VERIFY = configs.getboolean("SSL", "verify")

if VERIFY:
    if path := configs.get("SSL", "path", fallback=None):
        VERIFY = path


def retry(func: Callable) -> Callable:
    @wraps(func)
    def inner(*args, **kwargs):
        auth_header = AuthToken.header
        resp: r.Response = func(*args, headers=auth_header, **kwargs)
        if resp.status_code == 401:
            reset_request_methods()
            auth_header = AuthToken.header
            resp = func(*args, headers=auth_header, **kwargs)
            if resp.status_code == 401:
                raise Exception("Unable to authenticate")
        return resp

    return inner


r_get = partial(retry(r.get), verify=VERIFY)
r_post = partial(retry(r.post), verify=VERIFY)
r_patch = partial(retry(r.patch), verify=VERIFY)
r_delete = partial(retry(r.delete), verify=VERIFY)


class FileSaveError(Exception):
    def __init__(self, filename: str, *args, **kwargs):
        super().__init__(*args, *kwargs)
        self.filename = filename


class UploadError(Exception):
    """Exception for an error in uploading a file"""


def get_product_from_api(
    product_type: ADPProductClasses, customer: ADPCustomer
) -> dict:
    product_url = BACKEND_URL + f"/v2/vendors/{VENDOR}/vendor-customers/{customer.id}"
    includes = [
        "vendor-pricing-by-customer.vendor-products.vendor-product-attrs",
        "vendor-pricing-by-customer.vendor-products.vendor-product-to-class-mapping"
        ".vendor-product-classes",
    ]
    include = "include=" + ",".join(incl for incl in includes)
    filters = {
        "filter_vendor_product_classes__name": [product_type.value],
        "filter_vendor_product_classes__rank": [1],
    }
    filters_formatted = "&".join(
        f"{k}={','.join(str(i) for i in v)}" for k, v in filters.items()
    )
    query_params = "&".join(j for j in (include, filters_formatted))
    resp: r.Response = r_get(f"{product_url}?{query_params}")
    data: dict = resp.json()
    if not data.get("data"):
        raise Exception(f"No {product_type}")

    includes_pricing_by_customer = restructure_included(
        data["included"], "vendor-pricing-by-customer"
    )
    pricing = restructure_pricing_by_customer(includes_pricing_by_customer)
    return pricing


def get_coils(for_customer: ADPCustomer, version: int = 1) -> Coils | CoilsV2:
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
            customer_id = for_customer.id
            if stored_coils := LOCAL_STORAGE[ADPProductClasses.COILS].get(customer_id):
                pricing = stored_coils
            else:
                pricing = get_product_from_api(ADPProductClasses.COILS, for_customer)
                LOCAL_STORAGE[ADPProductClasses.COILS][customer_id] = pricing

            result = CoilsV2(
                data=[
                    CoilV2(id=id_, attributes=CoilAttrsV2(**attrs))
                    for id_, attrs in pricing.items()
                ]
            )
            return result
        case _:
            raise Exception(f"Incompatible version used: {version}")


def get_air_handlers(for_customer: ADPCustomer, version: int = 1) -> AHs | AHsV2:
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
            return AHs(data=customer_ahs)

        case 2:
            customer_id = for_customer.id
            if stored_ahs := LOCAL_STORAGE[ADPProductClasses.AIR_HANDLERS].get(
                customer_id
            ):
                pricing = stored_ahs
            else:
                pricing = get_product_from_api(
                    ADPProductClasses.AIR_HANDLERS, for_customer
                )
                LOCAL_STORAGE[ADPProductClasses.AIR_HANDLERS][customer_id] = pricing

            result = AHsV2(
                data=[
                    AHV2(id=id_, attributes=AHAttrsV2(**attrs))
                    for id_, attrs in pricing.items()
                ]
            )
            return result
        case _:
            raise Exception(f"Incompatible version used: {version}")


def get_ratings(for_customer: ADPCustomer, version: int = 1) -> Ratings:
    match version:
        case 1 | 2:
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
        case _:
            raise Exception(f"Incompatible version used: {version}")
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
            v2_adp_resource = f"/v2/vendors/{VENDOR}"
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
        case _:
            raise Exception(f"Incompatible version number used: {version}")

    return result


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
    year = kwargs.get("BASE_YEAR", 2025)
    query = f"?model_num={model}&customer_id={customer_id}&price_year={year}"
    return r_get(url=MODEL_LOOKUP + query)


def custom_response(data: dict) -> r.Response:
    resp = r.Response()
    resp.status_code = 200
    resp._content = json.dumps(dict(data=data)).encode("utf-8")
    resp.headers["Content-Type"] = "application/json"
    resp.encoding = "utf-8"
    return resp


def post_new_coil(customer_id: int, model: str) -> r.Response:
    coils = ADPProductClasses.COILS
    data = post_new_product(customer_id=customer_id, model=model, class_1=coils)
    return custom_response(data=data)


def post_new_ah(customer_id: int, model: str) -> r.Response:
    ahs = ADPProductClasses.AIR_HANDLERS
    data = post_new_product(customer_id=customer_id, model=model, class_1=ahs)
    return custom_response(data=data)


def post_new_product(customer_id: int, model: str, class_1: ADPProductClasses) -> dict:
    """
    STEPS
        check for existence
        if not exists hit model-lookup
        create model
        assign to customer with customer price
        add custom description
    """

    PRICING_CLASS_ID = 2  # being lazy - for STRATEGY_PRICING
    product_resource = (
        f"/v2/vendors/{VENDOR}/vendor-products?filter_vendor_product_identifier={model}"
    )

    product_check_resp: r.Response = r_get(url=BACKEND_URL + product_resource)
    if product_check_resp.status_code == 204:
        # look up model
        model_lookup_query = f"?model_num={model}&customer_id={customer_id}"
        model_lookup_resp: r.Response = r_get(url=MODEL_LOOKUP + model_lookup_query)
        model_lookup_content: dict = model_lookup_resp.json()
        material_group = model_lookup_content.pop("mpg")

        # for now, just popping to remove them from the object
        model_returned = model_lookup_content.pop("model-number")
        zero_discount_price = model_lookup_content.pop("zero-discount-price")
        material_group_discount = model_lookup_content.pop(
            "material-group-discount", None
        )
        material_group_net_price = model_lookup_content.pop(
            "material-group-net-price", None
        )
        snp_discount = model_lookup_content.pop("snp-discount", None)
        snp_net_price = model_lookup_content.pop("snp-net-price", None)
        net_price = int(model_lookup_content.pop("net-price"))
        default_description = model_lookup_content.pop("category")

        # register model, get id
        new_product_route = "/v2/vendors/vendor-products"
        pl = {
            "type": "vendor-products",
            "attributes": {
                "vendor-product-identifier": model,
                "vendor-product-description": default_description,
            },
            "relationships": {
                "vendors": {"data": {"type": "vendors", "id": "adp"}},
            },
        }
        new_product_resp: r.Response = r_post(
            url=BACKEND_URL + new_product_route, json=dict(data=pl)
        )
        new_product_data = new_product_resp.json()["data"]
        new_product_id = int(new_product_data["id"])

        # associate stable product attributes to product
        payloads = []
        for attr, value in model_lookup_content.items():
            attr: str
            try:
                int(value)
            except:
                val_type = "STRING"
            else:
                val_type = "NUMBER"

            pl = {
                "type": "vendor-product-attrs",
                "attributes": {
                    "attr": attr.replace("-", "_"),
                    "type": val_type,
                    "value": str(value),
                },
                "relationships": {
                    "vendor-products": {
                        "data": {"type": "vendor-products", "id": new_product_id}
                    },
                    "vendors": {"data": {"type": "vendors", "id": "adp"}},
                },
            }
            payloads.append(pl)

        new_product_attr_route = "/v2/vendors/vendor-product-attrs"
        for payload in payloads:
            resp = r_post(
                url=BACKEND_URL + new_product_attr_route, json=dict(data=payload)
            )
        # map model to its product class
        for cl, rank in [(material_group, 2), (class_1.value, 1)]:
            product_class_query = f"/v2/vendors/{VENDOR}/vendor-product-classes?filter_name={cl}&filter_rank={rank}"
            product_class_resp: r.Response = r_get(
                url=BACKEND_URL + product_class_query
            )
            product_class_resp_data = product_class_resp.json()["data"]
            # there should be only 1 object
            if isinstance(product_class_resp_data, list):
                product_class_id = product_class_resp_data.pop()["id"]
            else:
                product_class_id = product_class_resp_data["id"]
            mapping_ep = "/v2/vendors/vendor-product-to-class-mapping"
            pl = {
                "type": "vendor-product-to-class-mapping",
                "attributes": None,
                "relationships": {
                    "vendor-products": {
                        "data": {"type": "vendor-products", "id": new_product_id}
                    },
                    "vendor-product-classes": {
                        "data": {
                            "type": "vendor-product-classes",
                            "id": product_class_id,
                        }
                    },
                    "vendors": {"data": {"type": "vendors", "id": "adp"}},
                },
            }
            resp = r_post(BACKEND_URL + mapping_ep, json=dict(data=pl))

        # map product to customer with price
        customer_pricing_ep = "/v2/vendors/vendor-pricing-by-customer"
        pl = {
            "type": "vendor-pricing-by-customer",
            "attributes": {
                "use-as-override": True,
                "price": net_price,
            },
            "relationships": {
                "vendor-products": {
                    "data": {"type": "vendor-products", "id": new_product_id}
                },
                "vendor-customers": {
                    "data": {"type": "vendor-customers", "id": customer_id}
                },
                "vendor-pricing-classes": {
                    "data": {"type": "vendor-pricing-classes", "id": PRICING_CLASS_ID}
                },
                "vendors": {"data": {"type": "vendors", "id": "adp"}},
            },
        }
        resp: r.Response = r_post(
            url=BACKEND_URL + customer_pricing_ep, json=dict(data=pl)
        )
        new_pricing_id = resp.json()["data"]["id"]

        # set a customer price attr, custom_description, to the default for the product
        customer_price_attr_ep = "/v2/vendors/vendor-pricing-by-customer-attrs"
        pl = {
            "type": "vendor-pricing-by-customer-attrs",
            "attributes": {
                "attr": "custom_description",
                "type": "STRING",
                "value": default_description,
            },
            "relationships": {
                "vendor-pricing-by-customer": {
                    "data": {"type": "vendor-pricing-by-customer", "id": new_pricing_id}
                },
                "vendors": {"data": {"type": "vendors", "id": "adp"}},
            },
        }
        resp: r.Response = r_post(
            url=BACKEND_URL + customer_price_attr_ep, json=dict(data=pl)
        )
        # add these back in for the return object
        model_lookup_content |= {"zero-discount-price": zero_discount_price}
        model_lookup_content |= {"material-group-discount": material_group_discount}
        model_lookup_content |= {"material-group-net-price": material_group_net_price}
        model_lookup_content |= {"snp-discount": snp_discount}
        model_lookup_content |= {"snp-net-price": snp_net_price}
        model_lookup_content |= {"model-returned": model_returned}
        model_lookup_content |= {"model-number": model_returned}
        model_lookup_content |= {"mpg": material_group}

        product_result = dict(id=new_pricing_id, attributes=model_lookup_content)
    else:
        existing_product_data = product_check_resp.json()["data"]
        if isinstance(existing_product_data, list):
            existing_product_id = existing_product_data.pop()["id"]
        else:
            existing_product_id = existing_product_data["id"]

        model_lookup_query = f"?model_num={model}&customer_id={customer_id}"
        model_lookup_resp: r.Response = r_get(url=MODEL_LOOKUP + model_lookup_query)
        model_lookup_content: dict = model_lookup_resp.json()
        material_group = model_lookup_content.get("mpg")
        net_price = int(model_lookup_content.get("net-price"))
        default_description = model_lookup_content.get("category")

        # map product to customer with price

        customer_pricing_ep = "/v2/vendors/vendor-pricing-by-customer"
        pl = {
            "type": "vendor-pricing-by-customer",
            "attributes": {
                "use-as-override": True,
                "price": net_price,
            },
            "relationships": {
                "vendor-products": {
                    "data": {"type": "vendor-products", "id": existing_product_id}
                },
                "vendor-customers": {
                    "data": {"type": "vendor-customers", "id": customer_id}
                },
                "vendor-pricing-classes": {
                    "data": {"type": "vendor-pricing-classes", "id": PRICING_CLASS_ID}
                },
                "vendors": {"data": {"type": "vendors", "id": "adp"}},
            },
        }
        resp: r.Response = r_post(
            url=BACKEND_URL + customer_pricing_ep, json=dict(data=pl)
        )
        new_pricing_id = resp.json()["data"]["id"]

        # set a customer price attr, custom_description, to the default for the product
        customer_price_attr_ep = "/v2/vendors/vendor-pricing-by-customer-attrs"
        pl = {
            "type": "vendor-pricing-by-customer-attrs",
            "attributes": {
                "attr": "custom_description",
                "type": "STRING",
                "value": default_description,
            },
            "relationships": {
                "vendor-pricing-by-customer": {
                    "data": {"type": "vendor-pricing-by-customer", "id": new_pricing_id}
                },
                "vendors": {"data": {"type": "vendors", "id": "adp"}},
            },
        }
        resp: r.Response = r_post(
            url=BACKEND_URL + customer_price_attr_ep, json=dict(data=pl)
        )
        product_result = dict(id=new_pricing_id, attributes=model_lookup_content)

    return product_result


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
