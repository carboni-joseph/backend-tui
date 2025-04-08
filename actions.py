import json
import re
import os
import logging
import requests as r
import configparser
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
from enum import StrEnum, Enum
from typing import Callable, Any, Optional
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
    Attr,
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
            case tuple() | list() | set():
                f.write(", ".join(content))
            case BaseModel():
                f.write(str(content))


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


class FuturePrice(BaseModel):
    effective_date: datetime
    future_price: int


class NewProductDetails(BaseModel):
    id: int
    effective_date: datetime
    zero_discount_price: int
    material_group_discount: Optional[float] = None
    material_group_net_price: Optional[int] = None
    snp_discount: Optional[float] = None
    snp_price: Optional[int] = None
    net_price: Optional[int] = None
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
                    product_info: dict
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
    obj: dict[str, dict | str],
) -> dict[str, dict[str, str | dict[str | str]]]:
    result = dict()
    for id_, product_price in obj.items():
        product_price: dict[str, int | bool | dict | None]
        product: dict[str, dict]
        _, product = product_price["vendor-products"].popitem()

        # TODO come back to this to just display features that may not be changed?
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
                attr["attr"]: {
                    "id": id,
                    "attr": attr["attr"],
                    "type_": attr["type"],
                    "value": attr["value"],
                }
                for id, attr in pricing_by_customer_attrs.items()
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
MODEL_LOOKUP = BACKEND_URL + "/vendors/model-lookup/adp"
ADP_FILE_DOWNLOAD_LINK = (
    BACKEND_URL
    + "/v2/vendors/adp/vendor-customers/{customer_id}/pricing?return_type=xlsx&effective_date={effective_date}"
)

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
    default_sort_attr = Attr(id=-1, attr="", type_="", value="999999")
    default_desc_attr = Attr(id=-1, attr="", type_="", value="")
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
            int(p.attrs.get("sort_order", default_sort_attr).value),
            p.attrs.get("custom_description", default_desc_attr).value,
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
    effective_date = datetime.today().date()
    url = ADP_FILE_DOWNLOAD_LINK.format(
        customer_id=customer_id, effective_date=effective_date
    )
    resp: r.Response = r_get(url=url)
    if not resp.status_code == 200:
        raise Exception(
            f"Unable to obtain download link from {url}.\n"
            f"Message: {resp.content.decode()}"
        )
    return resp.json()["download_link"]


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
    query = f"?model_number={model}&customer_id={customer_id}&price_year={year}"
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
    data["attributes"]["price"] = data["attributes"].pop("net_price")
    LOCAL_STORAGE["pricing_by_customer"][customer_id] |= {
        data["id"]: data["attributes"]
    }
    return custom_response(data=data)


def post_new_ah(customer_id: int, model: str) -> r.Response:
    ahs = ADPProductClasses.AIR_HANDLERS
    data = post_new_product(customer_id=customer_id, model=model, class_1=ahs)
    data["attributes"]["price"] = data["attributes"].pop("net_price")
    LOCAL_STORAGE["pricing_by_customer"][customer_id] |= {
        data["id"]: data["attributes"]
    }
    return custom_response(data=data)


def new_product_setup(
    customer_id: int, model: str, class_1: ADPProductClasses
) -> NewProductDetails:

    # look up model
    logger.info("\tLooking up model details")
    model_lookup_query = f"?model_number={model}&customer_id={customer_id}"
    model_lookup_resp: r.Response = r_get(url=MODEL_LOOKUP + model_lookup_query)
    model_lookup_content: dict = model_lookup_resp.json()

    ## remove anything not considered an arbitrary attribute
    # product class
    material_group = model_lookup_content.pop("mpg")
    # obviously
    effective_date = model_lookup_content.pop("effective_date")
    # primary product attributes
    model_returned = model_lookup_content.pop("model_number")
    default_description = model_lookup_content.pop("category")
    # pricing & discounts
    zero_discount_price = model_lookup_content.pop("zero_discount_price")
    material_group_discount = model_lookup_content.pop("material_group_discount", None)
    material_group_net_price = model_lookup_content.pop(
        "material_group_net_price", None
    )
    snp_discount = model_lookup_content.pop("snp_discount", None)
    snp_net_price = model_lookup_content.pop("snp_net_price", None)
    net_price = int(model_lookup_content.pop("net_price"))

    # set up custom attr objects for the payload
    attrs = []
    logger.info("\tSetting up attributes")
    for attr, value in model_lookup_content.items():
        attr: str
        try:
            int(value)
        except:
            val_type = "STRING"
        else:
            val_type = "NUMBER"

        attr = {
            "attr": attr.replace("-", "_"),
            "type": val_type,
            "value": str(value),
        }
        attrs.append(attr)
    # register model
    new_product_route = "/v2/vendors/vendor-products"
    pl = {
        "type": "vendor-products",
        "attributes": {
            "vendor-product-identifier": model,
            "vendor-product-description": default_description,
            "vendor-product-attrs": attrs,
        },
        "relationships": {
            "vendors": {"data": {"type": "vendors", "id": "adp"}},
        },
    }
    new_product_resp: r.Response = r_post(
        url=BACKEND_URL + new_product_route, json=dict(data=pl)
    )
    new_product_data = new_product_resp.json()["data"]
    logger.info("\tProduct parent record with model and description registered")
    logger.info("\tProduct attributes registered to the product")
    new_product_id = int(new_product_data["id"])

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
        effective_date=effective_date,
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
    new_product = False
    if product_check_resp.status_code == 200:
        existing_product_data = product_check_resp.json()["data"]
        if isinstance(existing_product_data, list):
            filtered = [
                e
                for e in existing_product_data
                if e["attributes"]["vendor-product-identifier"] == model
            ]
            if not filtered:
                new_product = True
            else:
                new_product = False
                existing_product_id = filtered.pop()["id"]
        else:
            existing_product_id = existing_product_data["id"]
    if product_check_resp.status_code == 204 or new_product:
        new_product = True
        logger.info(f"\t{model} needs to be built")
        new_product_details = new_product_setup(customer_id, model, class_1)

        logger.info(f"\t{model} has been setup")
        new_product_id = new_product_details.id
        effective_date = new_product_details.effective_date
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
                "effective-date": str(effective_date),
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
        new_attr = resp.json()
        logger.info("\tCustom description established")
        # add these back in for the return object
        model_lookup_content |= {"zero_discount_price": zero_discount_price}
        model_lookup_content |= {"material_group_discount": material_group_discount}
        model_lookup_content |= {"material_group_net_price": material_group_net_price}
        model_lookup_content |= {"snp_discount": snp_discount}
        model_lookup_content |= {"snp_net_price": snp_net_price}
        model_lookup_content |= {"model_returned": model_returned}
        model_lookup_content |= {"model_number": model_returned}
        model_lookup_content |= {"mpg": material_group}
        model_lookup_content |= {"net_price": net_price}

        model_lookup_content["attrs"] = {
            "custom_description": {
                "id": new_attr["data"]["id"],
                "attr": new_attr["data"]["attributes"]["attr"],
                "type_": new_attr["data"]["attributes"]["type"],
                "value": new_attr["data"]["attributes"]["value"],
            }
        }
        product_result = dict(id=new_pricing_id, attributes=model_lookup_content)
    else:
        model_lookup_query = f"?model_number={model}&customer_id={customer_id}"
        model_lookup_resp: r.Response = r_get(url=MODEL_LOOKUP + model_lookup_query)
        model_lookup_content: dict = model_lookup_resp.json()
        material_group = model_lookup_content.get("mpg")
        net_price = int(model_lookup_content.get("net_price"))
        default_description = model_lookup_content.get("category")
        effective_date = datetime.strptime(
            model_lookup_content.get("effective_date").split(".")[0],
            "%Y-%m-%dT%H:%M:%S",
        )

        # map product to customer with price

        customer_pricing_ep = "/v2/vendors/vendor-pricing-by-customer"
        pl = {
            "type": "vendor-pricing-by-customer",
            "attributes": {
                "use-as-override": True,
                "price": net_price * 100,
                "effective-date": str(effective_date),
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
        new_attr = resp.json()
        model_lookup_content["attrs"] = {
            "custom_description": {
                "id": new_attr["data"]["id"],
                "attr": new_attr["data"]["attributes"]["attr"],
                "type_": new_attr["data"]["attributes"]["type"],
                "value": new_attr["data"]["attributes"]["value"],
            }
        }
        product_result = dict(id=new_pricing_id, attributes=model_lookup_content)

    model_lookup_query_future = (
        f"?model_number={model}&customer_id={customer_id}&future=true"
    )
    future_price_resp: r.Response = r_get(url=MODEL_LOOKUP + model_lookup_query_future)
    future_price_json = future_price_resp.json()
    future_price = FuturePrice(
        effective_date=future_price_json["effective_date"],
        future_price=future_price_json["net_price"],
    )
    future_price_eff_date = future_price.effective_date
    setup_future_price_record = False
    if (
        future_price_eff_date > effective_date
        and future_price_eff_date > datetime.today()
    ):
        setup_future_price_record = True
        future_price_fig = future_price.future_price

    if setup_future_price_record:
        new_price_pl = {
            "type": "vendor-pricing-by-customer-future",
            "attributes": {
                "price": int(future_price_fig * 100),
                "effective-date": str(future_price_eff_date),
            },
            "relationships": {
                "vendor-pricing-by-customer": {
                    "data": {"type": "vendor-pricing-by-customer", "id": new_pricing_id}
                },
                "vendors": {"data": {"type": "vendors", "id": "adp"}},
            },
        }
        customer_pricing_future = "/v2/vendors/vendor-pricing-by-customer-future"
        resp: r.Response = r_post(
            url=BACKEND_URL + customer_pricing_future, json=dict(data=new_price_pl)
        )
        if resp.status_code == 200:
            logger.info(
                f"\tFuture Pricing set with effective date: {future_price_eff_date}"
            )
        else:
            logger.error(f"failed to set future price")

    return product_result


def post_new_ratings(customer_id: int, file: str) -> None:
    if not file:
        raise UploadError("no file selected")
    with open(file, "rb") as fh:
        file_data = fh.read()
    resp: r.Response = r_post(
        url=BACKEND_URL + f"/vendors/admin/adp/ratings/{customer_id}",
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
