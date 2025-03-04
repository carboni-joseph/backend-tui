import urwid
from requests import Response
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable
from models import ADPActions, Route, Palette
from actions import (
    download_file,
    FileSaveError,
    price_check,
    get_pricing_by_customer,
    post_new_coil,
    post_new_ah,
    post_new_ratings,
    select_file,
    debug,
)
from functools import partial

if TYPE_CHECKING:
    from main import Application


class VendorHandler(ABC):
    def __init__(self, app: "Application") -> None:
        self.app: "Application" = app

    @abstractmethod
    def get_action_flow(self) -> list[Route]:
        pass


class ADPHandler(VendorHandler):
    """ADP Management Flows"""

    def get_action_flow(self):
        return partial(
            self.app.menu,
            f"{self.app.vendor_customer.name}",
            self.action_chosen,
            choices=ADPActions,
        )

    def program_type_selected(self) -> None:
        try:
            customer = self.app.vendor_customer
            download_file(customer.id)
        except FileSaveError as e:
            response = (
                "There was an error trying to save the file. "
                f"If an existing file with the name {e.filename} is open, "
                "please close it and try downloading again."
            )
            response_text = urwid.Text(("flash_bad", response))
        except Exception as e:
            response_text = urwid.Text(("flash_bad", str(e)))
        else:
            response = f"Strategy file downloaded for {customer.name}"
            response_text = urwid.Text(("flash_good", response))
        self.app.go_back()
        self.app.frame.header = urwid.Pile([response_text, self.app.frame.header])

    def add_new_model(self, submit_method: Callable) -> urwid.ListBox:
        self.user_input = urwid.Edit("Enter Model Number: ")
        submit = urwid.Button("Submit", on_press=submit_method)
        return urwid.ListBox(
            [self.user_input, urwid.AttrMap(submit, None, focus_map="reversed")]
        )

    def do_model_lookup(self):
        self.user_input = urwid.Edit("Enter Model Number: ")
        submit = urwid.Button("Submit", on_press=self.display_price_check)
        return urwid.ListBox(
            [self.user_input, urwid.AttrMap(submit, None, focus_map="reversed")]
        )

    def display_price_check(self, button):
        customer = self.app.vendor_customer
        user_input = self.user_input
        raw_input = user_input.edit_text
        resp: Response = price_check(customer.id, raw_input)
        if resp.status_code == 200:
            body: dict = resp.json()
            zero_disc_price = body["zero-discount-price"]
            net_price = body["net-price"]
            discount_used = 0
            if net_price != zero_disc_price:
                mgd = body.get("material-group-net-price", 0)
                snp = body.get("snp-price", 0)
                if mgd == net_price:
                    discount_used = body.get("material-group-discount")
                if snp == net_price:
                    discount_used = body.get("snp-discount")
            net_price = f"Pricing\n   Price:  ${body['net-price']:,.2f}\n   Discount: {discount_used:0.2f}%"
            orig_price = f"   ZDP:  ${zero_disc_price:,.2f}\n"
            features = [
                f"   {k}: {v}"
                for k, v in body.items()
                if k
                in [
                    "model-number",
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

    def add_new_coil(self) -> urwid.ListBox:
        return self.add_new_model(partial(self.submit_model, post_new_coil))

    def add_new_ah(self) -> urwid.ListBox:
        return self.add_new_model(partial(self.submit_model, post_new_ah))

    def submit_model(self, product_type_method: Callable, button) -> None:
        """sends new model payload to the API"""
        customer = self.app.vendor_customer
        user_text: str = self.user_input.edit_text
        model_list: list = [model.strip().upper() for model in user_text.split(",")]
        results = list()
        total_items = len(model_list)
        for i, model in enumerate(model_list):
            current_msg = urwid.Text(
                ("flash_good", f"Working on {model}  ({i+1} of {total_items})")
            )
            debug(current_msg.text)
            resp: Response = product_type_method(customer.id, model)
            body = resp.json()
            if resp.status_code == 200:
                body_data: dict[str, str | dict] = body["data"]
                response_header = urwid.Text(
                    (
                        "flash_good",
                        f"Model {model} successfully added "
                        f"for {customer.name} under id {body_data['id']}",
                    )
                )
            else:
                response_header = urwid.Text(
                    ("flash_bad", f"Unable to add model {model}")
                )
            results.append(response_header)
        self.app.go_back().go_back()
        self.app.frame.header = urwid.Pile([*results, self.app.frame.header])

    def upload_ratings(self, selected_file: str):
        customer = self.app.vendor_customer
        try:
            post_new_ratings(customer.id, selected_file)
        except Exception as e:
            header_text = urwid.Text(("flash_bad", str(e)))
        else:
            header_text = urwid.Text(("flash_good", "Successfully uploaded ratings"))
        finally:
            self.app.frame.header = urwid.Pile([header_text, self.app.frame.header])

    def action_chosen(self, choice: str, button) -> None:
        """determine which administrative action
        the user chose and route them to the proper next menu"""
        choice = ADPActions(choice)
        customer = self.app.vendor_customer
        match choice:
            case ADPActions.DOWNLOAD_PROGRAM:
                try:
                    download_file(customer_id=customer.id)
                except Exception as e:
                    flash_text = urwid.Text(
                        ("flash_bad", f"an error occured - {str(e)}"), align="center"
                    )
                else:
                    flash_text = urwid.Text(
                        ("flash_good", "downloaded file"), align="center"
                    )
                finally:
                    self.app.frame.header = urwid.Pile(
                        [flash_text, self.app.frame.header]
                    )
            case ADPActions.UPLOAD_RATINGS:
                self.upload_ratings(select_file())
            case ADPActions.PRODUCT:
                products = get_pricing_by_customer(customer)
                routes = []
                new_coil = Route(
                    callable_=self.add_new_coil,
                    choice_title="Add a new coil",
                    callable_title="Enter Coil Model Number",
                )
                routes.append(new_coil)
                new_ah = Route(
                    callable_=self.add_new_ah,
                    choice_title="Add a new air handler",
                    callable_title="Enter Air Handler Model Number",
                )
                routes.append(new_ah)
                routes.append(urwid.Divider("-"))
                routes.append(
                    urwid.Text((Palette.NORMAL.value[0], "Strategy Products\n"))
                )
                for p in products:
                    route = Route(
                        callable_=None,
                        callable_title="select attribute",
                        choice_title=p.model_number,
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


class BerryHandler(VendorHandler):
    def get_action_flow(self):
        return super().get_action_flow()


HANDLERS: dict[str, type[VendorHandler]] = {"adp": ADPHandler}
