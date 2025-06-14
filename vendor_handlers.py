import urwid
import logging
from requests import Response
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable
from models import (
    ADPActions,
    Route,
    Palette,
    ProductPriceBasic,
    Attr,
    Vendor,
    VendorCustomer,
)
from actions import (
    download_file,
    price_check,
    get_pricing_by_customer,
    new_product,
    post_new_ratings,
    select_file,
    debug,
)
from functools import partial

if TYPE_CHECKING:
    from main import Application

logger = logging.getLogger(__name__)


class VendorHandler(ABC):
    def __init__(self, app: "Application") -> None:
        self.app: "Application" = app

    @abstractmethod
    def get_action_flow(self) -> Callable:
        pass


class AtcoHandler(VendorHandler):

    vendor = Vendor("atco", "Atco Flex")

    def get_action_flow(self) -> Callable:
        return partial(
            self.app.menu,
            f"{self.app.vendor_customer.name}",
            self.download_pricing,
            choices=["Download Price File"],
        )

    def download_pricing(self, *args, **kwargs) -> None:
        customer = self.app.vendor_customer
        try:
            logger.info(f"Downloading {customer.vendor.name} file for {customer.name}")
            download_file(vendor=self.vendor, customer_id=customer.id)
        except Exception as e:
            flash_text = urwid.Text(
                ("flash_bad", f"an error occured - {str(e)}"), align="center"
            )
            logger.error(f"{e}")
        else:
            flash_text = urwid.Text(("flash_good", "downloaded file"), align="center")
            logger.info("Done.")
        finally:
            self.app.frame.header = urwid.Pile([flash_text, self.app.frame.header])


class VybondHandler(VendorHandler):

    vendor = Vendor("vybond", "Vybond")

    def get_action_flow(self) -> Callable:
        return partial(
            self.app.menu,
            f"{self.app.vendor_customer.name}",
            self.download_pricing,
            choices=["Download Price File"],
        )

    def download_pricing(self, *args, **kwargs) -> None:
        customer = self.app.vendor_customer
        try:
            logger.info(f"Downloading {customer.vendor.name} file for {customer.name}")
            download_file(vendor=self.vendor, customer_id=customer.id)
        except Exception as e:
            flash_text = urwid.Text(
                ("flash_bad", f"an error occured - {str(e)}"), align="center"
            )
            logger.error(f"{e}")
        else:
            flash_text = urwid.Text(("flash_good", "downloaded file"), align="center")
            logger.info("Done.")
        finally:
            self.app.frame.header = urwid.Pile([flash_text, self.app.frame.header])


class ADPHandler(VendorHandler):
    """ADP Management Flows"""

    vendor = Vendor("adp", "ADP")

    def get_action_flow(self) -> Callable:
        return partial(
            self.app.menu,
            f"{self.app.vendor_customer.name}",
            self.action_chosen,
            choices=ADPActions,
        )

    def _add_new_model(self, submit_method: Callable) -> urwid.ListBox:
        self.user_input = urwid.Edit("Enter Model Number: ")
        submit = urwid.Button("Submit", on_press=submit_method)
        return urwid.ListBox(
            [self.user_input, urwid.AttrMap(submit, None, focus_map="reversed")]
        )

    def do_model_lookup(self) -> urwid.ListBox:
        self.user_input = urwid.Edit("Enter Model Number: ")
        submit = urwid.Button("Submit", on_press=self.display_price_check)
        return urwid.ListBox(
            [self.user_input, urwid.AttrMap(submit, None, focus_map="reversed")]
        )

    def display_price_check(self, button) -> None:
        customer = self.app.vendor_customer
        user_input = self.user_input
        raw_input = user_input.edit_text
        resp: Response = price_check(customer.id, raw_input)
        if resp.status_code == 200:
            body: dict = resp.json()
            zero_disc_price = body["zero_discount_price"]
            net_price = body["net_price"]
            discount_used = 0
            if net_price != zero_disc_price:
                mgd = body.get("material_group_net_price", 0)
                snp = body.get("snp_price", 0)
                if mgd == net_price:
                    discount_used = body.get("material_group_discount")
                if snp == net_price:
                    discount_used = body.get("snp_discount")
                if discount_used > 1:
                    discount_used /= 100
            net_price = f"Pricing\n   Price:  ${body['net_price']:,.2f}\n   Discount: {discount_used*100:0.2f}%"
            orig_price = f"   ZDP:  ${zero_disc_price:,.2f}\n"
            features = [
                f"   {k}: {v}"
                for k, v in body.items()
                if k
                in [
                    "model_number",
                    "series",
                    "tonnage",
                    "width",
                    "depth",
                    "height",
                    "motor",
                    "heat",
                ]
            ]
            # not a JSONAPI obj with a data key, just the features as keys
            self.app.frame.body = urwid.Filler(
                urwid.Pile(
                    [
                        urwid.Text(e)
                        for e in [net_price, orig_price, "Features", *features]
                    ]
                )
            )
        else:
            response_header = urwid.Text(("flash_bad", f"{raw_input} is not valid"))
            response_body = urwid.Text(resp.content)
            self.app.frame.header = urwid.Pile([response_header, self.app.frame.header])
            self.app.frame.body = urwid.Filler(urwid.Pile([response_body]))
        return

    def add_new_product(self) -> urwid.ListBox:
        return self._add_new_model(partial(self.submit_model, new_product))

    def submit_model(self, product_type_method: Callable, button) -> None:
        """sends new model payload to the API"""
        customer = self.app.vendor_customer
        user_text: str = self.user_input.edit_text
        model_list: list = [model.strip().upper() for model in user_text.split(",")]
        results = list()
        total_items = len(model_list)
        for i, model in enumerate(model_list):
            current_msg = f"Working on {model}  ({i+1} of {total_items})"
            logger.info(current_msg)
            resp: Response = product_type_method(customer.id, model)
            body = resp.json()
            if resp.status_code == 200:
                logger.info("Success")
                body_data: dict[str, str | dict] = body["data"]
                response_header = urwid.Text(
                    (
                        "flash_good",
                        f"Model {model} successfully added "
                        f"for {customer.name} under id {body_data['id']}",
                    )
                )
            else:
                logger.error("Failure")
                response_header = urwid.Text(
                    ("flash_bad", f"Unable to add model {model}")
                )
            results.append(response_header)
        self.app.go_back().go_back()
        self.app.frame.header = urwid.Pile([*results, self.app.frame.header])
        return

    def upload_ratings(self, selected_file: str) -> None:
        customer = self.app.vendor_customer
        try:
            post_new_ratings(customer.id, selected_file)
        except Exception as e:
            header_text = urwid.Text(("flash_bad", str(e)))
            logging.info(f"error uploading ratings: {e}")
        else:
            header_text = urwid.Text(("flash_good", "Successfully uploaded ratings"))
            logging.info(f"ratings uploaded")
        finally:
            self.app.frame.header = urwid.Pile([header_text, self.app.frame.header])
        return

    def action_chosen(self, choice: str, button) -> None:
        """determine which administrative action
        the user chose and route them to the proper next menu"""
        choice = ADPActions(choice)
        customer = self.app.vendor_customer
        match choice:
            case ADPActions.DOWNLOAD_PROGRAM:
                try:
                    logger.info(
                        f"Downloading {customer.vendor.name} file for {customer.name}"
                    )
                    download_file(vendor=self.vendor, customer_id=customer.id)
                except Exception as e:
                    flash_text = urwid.Text(
                        ("flash_bad", f"an error occured - {str(e)}"), align="center"
                    )
                    logger.error(f"{e}")
                else:
                    flash_text = urwid.Text(
                        ("flash_good", "downloaded file"), align="center"
                    )
                    logger.info("Done.")
                finally:
                    self.app.frame.header = urwid.Pile(
                        [flash_text, self.app.frame.header]
                    )
            case ADPActions.UPLOAD_RATINGS:
                file = select_file()
                logging.info(f"uploading ratings from {file}")
                self.upload_ratings(file)
            case ADPActions.PRODUCT:
                logging.info(f"Getting products for {customer.name}...")
                products = get_pricing_by_customer(customer)
                logging.info(f"Done")
                routes = []
                new_product_ = Route(
                    callable_=self.add_new_product,
                    choice_title="Add product",
                    callable_title="Enter Model Numbers",
                )
                routes.append(new_product_)
                routes.append(urwid.Divider("="))
                routes.append(
                    urwid.Text(
                        (Palette.NORMAL.value[0], "Strategy Products"),
                        align="center",
                    )
                )
                cats = set()
                for p in products:
                    if category_obj := p.attrs.get("custom_description", None):
                        category = category_obj.value
                    else:
                        category = ""
                    if category not in cats:
                        routes.append(urwid.Divider("-"))
                        routes.append(
                            urwid.Text(
                                (Palette.NORMAL.value[0], f"{category}"),
                                align="center",
                            )
                        )
                        cats.add(category)
                    route = Route(
                        callable_=self.app.product_selected(p),
                        choice_title=f"{p.id:05}   {p.model_number}   ${p.price:.02f}",
                    )
                    routes.append(route)
                self.app.next_screen = partial(
                    self.app.routing_menu,
                    f"{customer.name}",
                    routes,
                )
                self.app.show_new_screen()
            case ADPActions.PRICE_CHECK:
                self.app.next_screen = self.do_model_lookup
                self.app.show_new_screen()
            case _:
                response = "No Action taken"
                response_text = urwid.Text(response)
                self.app.frame.body = urwid.Filler(urwid.Pile([response_text]))
        return


HANDLERS: dict[str, type[VendorHandler]] = {
    "adp": ADPHandler,
    "vybond": VybondHandler,
    "atco": AtcoHandler,
}
