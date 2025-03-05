import json
import re
import os
import logging
import requests as r
import configparser
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from enum import StrEnum, Enum
from typing import Callable, Any
from collections import defaultdict
import concurrent.futures as futures
from functools import partial, wraps
from tkinter import Tk, filedialog
from models import (
    SCACustomerV2,
    ProductPriceBasic,
    Stage,
    Rating,
    Ratings,
    RatingAttrs,
    RatingRels,
    Vendor,
    VendorCustomer,
)
from auth import AuthToken

logger = logging.getLogger(__name__)
os.chdir(os.path.dirname(os.path.abspath(__file__)))
configs = configparser.ConfigParser()
configs.read("config.ini")


def debug(content: Any) -> None:
    with open("debug.txt", "w") as f:
        match content:
            case dict():
                f.write(json.dumps(content, indent=4))
            case str():
                f.write(content)
            case tuple():
                f.write(", ".join(content))


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
    PREFERRED_PARTS = "PREFERRED_PARTS"
    STANDARD_PARTS = "STANDARD_PARTS"


class ADPProductClasses(Enum):
    COILS = {"name": "Coils", "rank": 1}
    AIR_HANDLERS = {"name": "Air Handlers", "rank": 1}


@dataclass
class NewProductDetails:
    id: int
    zero_discount_price: int
    material_group_discount: float
    material_group_net_price: int
    snp_discount: float
    snp_price: int
    net_price: int
    model_returned: str
    category: str
    model_lookup_obj: dict
    material_group: str


LOCAL_STORAGE = {"pricing_by_customer": {}}


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


def restructure_pricing_by_customer(
    obj: dict[str, dict | str]
) -> dict[str, dict[str, str | dict[str | str]]]:
    result = dict()
    for product_price in obj.values():
        product_price: dict[str, int | bool | dict | None]
        product: dict[str, dict]
        id_, product = product_price["vendor-products"].popitem()
        # product_attrs = product.get("vendor-product-attrs", {})
        # if product_attrs:
        #     product_attrs = {
        #         attr["attr"]: attr["value"] for attr in product_attrs.values()
        #     }
        product_attrs = {
            "model_number": product["vendor-product-identifier"],
            "description": product["vendor-product-description"],
            "price": product_price["price"],
            "effective_date": product_price["effective-date"],
        }
        product_attrs.setdefault("attrs", {})
        customer_specific = "vendor-pricing-by-customer-attrs"
        if pricing_by_customer_attrs := product_price.get(customer_specific):
            product_attrs["attrs"] = {
                attr["attr"]: attr["value"]
                for attr in pricing_by_customer_attrs.values()
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
RATINGS = ADP_RESOURCE + "/adp-program-ratings"
MODEL_LOOKUP = ADP_RESOURCE + "/model-lookup"
ADP_FILE_DOWNLOAD_LINK = ADP_RESOURCE + "/programs/{customer_id}/download?stage={stage}"

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


def get_pricing_by_customer(for_customer: VendorCustomer) -> list[ProductPriceBasic]:
    customer_id = for_customer.id
    vendor_id = for_customer.vendor.id
    if stored_pricing := LOCAL_STORAGE["pricing_by_customer"].get(customer_id):
        pricing = stored_pricing
    else:
        pricing_url = (
            BACKEND_URL + f"/v2/vendors/{vendor_id}/vendor-customers/{customer_id}"
        )
        includes = "include=vendor-pricing-by-customer.vendor-products"
        includes += ",vendor-pricing-by-customer.vendor-pricing-by-customer-attrs"
        resp: r.Response = r_get(f"{pricing_url}?{includes}")
        data: dict = resp.json()
        if not data.get("data"):
            raise Exception("No product")

        includes_pricing_by_customer = restructure_included(
            data["included"], "vendor-pricing-by-customer"
        )
        pricing = restructure_pricing_by_customer(includes_pricing_by_customer)
        LOCAL_STORAGE["pricing_by_customer"][customer_id] = pricing

    result = [ProductPriceBasic(id=id_, **attrs) for id_, attrs in pricing.items()]
    result.sort(
        key=lambda p: (
            int(p.attrs.get("sort_order", 999999)),
            p.attrs.get("custom_description", ""),
            (p.description if p.description else ""),
            p.price,
            p.model_number,
        )
    )
    return result


def get_ratings(for_customer: VendorCustomer) -> Ratings:
    url = f"/vendors/adp/{for_customer.id}/adp-program-ratings"
    resp: r.Response = r_get(url)
    data: dict = resp.json()
    if not data.get("data"):
        raise Exception("No Ratings")
    customer_ratings = [
        Rating(
            id=record["id"],
            attributes=RatingAttrs(**record["attributes"]),
            relationships=RatingRels(
                adp_customers={"data": {"id": for_customer.id, "type": "adp-customers"}}
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
    return Ratings(data=customer_ratings)


def get_vendors() -> list[Vendor]:
    resource = "/v2/vendors"
    page_num = "page_number=0"
    url = f"{BACKEND_URL}{resource}?{page_num}"
    resp: r.Response = r_get(url=url)
    resp_data = resp.json()
    return [Vendor(v["id"], v["attributes"]["name"]) for v in resp_data["data"]]


def get_sca_customers_w_vendor_accounts(vendor: Vendor) -> list[SCACustomerV2]:
    v2_vendor_resource = f"/v2/vendors/{vendor.id}/vendor-customers"
    page_num = "page_number=0"
    includes = "include=customer-location-mapping.customer-locations.customers"
    url = f"{BACKEND_URL}{v2_vendor_resource}?{includes}&{page_num}"
    resp: r.Response = r_get(url=url)
    resp_data = resp.json()
    data, included = resp_data["data"], resp_data["included"]
    customers = {
        r["id"]: r["attributes"]["name"] for r in included if r["type"] == "customers"
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
    vendor_customers_w_mapping = {
        r["id"]: (
            r["attributes"]["name"],
            [
                mapping["id"]
                for mapping in r["relationships"]["customer-location-mapping"]["data"]
            ],
        )
        for r in data
        if r["relationships"]["customer-location-mapping"]["data"]
    }
    result: list[SCACustomerV2] = []
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
        vendor_customers_selected = [
            VendorCustomer(id=id_, vendor=vendor, name=v[0])
            for id_, v in vendor_customers_w_mapping.items()
            if set(v[1]) <= set(mapping_ids_for_locations)
        ]
        vendor_customers_selected.sort(key=lambda vc: vc.name)
        customer_obj = SCACustomerV2(
            sca_id=sca_id,
            sca_name=sca_name,
            vendor=vendor,
            entity_accounts=vendor_customers_selected,
        )
        result.append(customer_obj)

    result.sort(key=lambda c: c.sca_name)
    return result


def request_dl_link(customer_id: int, stage: Stage) -> str:
    url = ADP_FILE_DOWNLOAD_LINK.format(customer_id=customer_id, stage=stage.value)
    resp: r.Response = r_post(url=url)
    if not resp.status_code == 200:
        raise Exception(
            "Unable to obtain download link.\n" f"Message: {resp.content.decode()}"
        )
    return resp.json()["downloadLink"]


def download_file(customer_id: str) -> None:
    stage = Stage.PROPOSED
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
    data["attributes"]["price"] = data["attributes"].pop("net-price")
    LOCAL_STORAGE["pricing_by_customer"][customer_id] |= {
        data["id"]: data["attributes"]
    }
    return custom_response(data=data)


def post_new_ah(customer_id: int, model: str) -> r.Response:
    ahs = ADPProductClasses.AIR_HANDLERS
    data = post_new_product(customer_id=customer_id, model=model, class_1=ahs)
    data["attributes"]["price"] = data["attributes"].pop("net-price")
    LOCAL_STORAGE["pricing_by_customer"][customer_id] |= {
        data["id"]: data["attributes"]
    }
    return custom_response(data=data)


def new_product_setup(
    customer_id: int, model: str, class_1: ADPProductClasses
) -> NewProductDetails:

    # look up model
    logger.info("\tLooking up model details")
    model_lookup_query = f"?model_num={model}&customer_id={customer_id}"
    model_lookup_resp: r.Response = r_get(url=MODEL_LOOKUP + model_lookup_query)
    model_lookup_content: dict = model_lookup_resp.json()
    material_group = model_lookup_content.pop("mpg")

    # for now, just popping to remove them from the object
    model_returned = model_lookup_content.pop("model-number")
    zero_discount_price = model_lookup_content.pop("zero-discount-price")
    material_group_discount = model_lookup_content.pop("material-group-discount", None)
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
    logger.info("\tProduct parent record with model and description registered")
    new_product_data = new_product_resp.json()["data"]
    new_product_id = int(new_product_data["id"])

    # associate stable product attributes to product
    payloads = []
    logger.info("\tSetting up attributes")
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

    def post_attribute(payload: dict) -> None:
        attr, value = payload["attributes"]["attr"], payload["attributes"]["value"]
        r_post(url=BACKEND_URL + new_product_attr_route, json=dict(data=payload))
        logger.info(f"\t  * {attr} = {value}")

    with futures.ThreadPoolExecutor() as executor:
        futures_ = [executor.submit(post_attribute, payload) for payload in payloads]
        futures.wait(futures_)

    # map model to its product classes
    for cl in [material_group, class_1.value["name"]]:
        product_class_query = f"/v2/vendors/adp/vendor-product-classes?filter_name={cl}"
        product_class_resp: r.Response = r_get(url=BACKEND_URL + product_class_query)
        product_class_resp_data = product_class_resp.json()["data"]
        if isinstance(product_class_resp_data, list):
            data_list = [
                e for e in product_class_resp_data if e["attributes"]["name"] == cl
            ]
            product_class_id = data_list.pop()["id"]
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
        r_post(BACKEND_URL + mapping_ep, json=dict(data=pl))
        logger.info(f"\tMapped to class: {cl}")

    return NewProductDetails(
        id=new_product_id,
        zero_discount_price=zero_discount_price,
        material_group_discount=material_group_discount,
        material_group_net_price=material_group_net_price,
        snp_discount=snp_discount,
        snp_price=snp_net_price,
        net_price=net_price,
        model_returned=model_returned,
        category=default_description,
        model_lookup_obj=model_lookup_content,
        material_group=material_group,
    )


def post_new_product(
    customer_id: int, model: str, class_1: ADPProductClasses
) -> dict[str, int | dict]:
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
        f"/v2/vendors/adp/vendor-products?filter_vendor_product_identifier={model}"
    )

    logger.info(f"\tChecking for existence.")
    product_check_resp: r.Response = r_get(url=BACKEND_URL + product_resource)
    if product_check_resp.status_code == 204:
        logger.info(f"\t{model} needs to be built")
        new_product_details = new_product_setup(customer_id, model, class_1)
        logger.info(f"\t{model} has been setup")
        new_product_id = new_product_details.id
        zero_discount_price = new_product_details.zero_discount_price
        material_group_discount = new_product_details.material_group_discount
        material_group_net_price = new_product_details.material_group_net_price
        snp_discount = new_product_details.snp_discount
        snp_net_price = new_product_details.snp_price
        net_price = new_product_details.net_price
        model_returned = new_product_details.model_returned
        default_description = new_product_details.category
        model_lookup_content = new_product_details.model_lookup_obj
        material_group = new_product_details.material_group

        # map product to customer with price
        customer_pricing_ep = "/v2/vendors/vendor-pricing-by-customer"
        pl = {
            "type": "vendor-pricing-by-customer",
            "attributes": {
                "use-as-override": True,
                "price": net_price * 100,
                "effective-date": str(datetime.now()),
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
        logger.info("\tPricing set.")
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
        logger.info("\tCustom description established")
        # add these back in for the return object
        model_lookup_content |= {"zero-discount-price": zero_discount_price}
        model_lookup_content |= {"material-group-discount": material_group_discount}
        model_lookup_content |= {"material-group-net-price": material_group_net_price}
        model_lookup_content |= {"snp-discount": snp_discount}
        model_lookup_content |= {"snp-net-price": snp_net_price}
        model_lookup_content |= {"model-returned": model_returned}
        model_lookup_content |= {"model-number": model_returned}
        model_lookup_content |= {"mpg": material_group}
        model_lookup_content |= {"net-price": net_price}

        model_lookup_content["attrs"] = {"custom_description": default_description}
        product_result = dict(id=new_pricing_id, attributes=model_lookup_content)
    else:
        logger.info(f"\t{model} exists. Performing lookup.")
        existing_product_data = product_check_resp.json()["data"]
        if isinstance(existing_product_data, list):
            filtered = [
                e
                for e in existing_product_data
                if e["attributes"]["vendor-product-identifier"] == model
            ]
            existing_product_id = filtered.pop()["id"]
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
                "price": net_price * 100,
                "effective-date": str(datetime.now()),
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
        logger.info("\tPricing set.")

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
        logger.info("\tCustom description established")
        model_lookup_content["attrs"] = {"custom_description": default_description}
        product_result = dict(id=new_pricing_id, attributes=model_lookup_content)

    return product_result


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
