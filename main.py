import urwid
from functools import partial
from typing import Callable, Annotated, Any, Iterable
from requests import Response, get
from auth import set_up_token
from abc import ABC, abstractmethod

set_up_token()
from models import (
    SCACustomer,
    SCACustomerV2,
    Vendor,
    VendorCustomer,
    Actions,
    Route,
)
from actions import (
    download_file,
    FileSaveError,
    post_new_coil,
    select_file,
    get_vendors,
    get_sca_customers_w_vendor_accounts,
    post_new_ah,
    post_new_ratings,
    price_check,
)
from models import TableHeader, TableRow, Route

from os.path import dirname, abspath
from pathlib import Path
from configparser import ConfigParser

FILE_DIR = Path(dirname(abspath(__file__)))
CONFIGS = ConfigParser()
CONFIGS.read(str(FILE_DIR / "config.ini"))
BACKEND_URL = CONFIGS["ENDPOINTS"]["backend_url"]
BASE_YEAR = CONFIGS["OTHER"]["price_year"]
V2_AVAILABILITY_ENDPOINT = BACKEND_URL + "/v2"

CACHE = {}

resp = get(V2_AVAILABILITY_ENDPOINT)
match resp.status_code:
    case 200:
        __version__ = 2
    case _:
        __version__ = 1

PALETTE = [
    ("reversed", "standout", ""),
    ("header", "white", "black"),
    ("flash_bad", "white", "dark red", "standout"),
    ("flash_good", "white", "dark green", "standout"),
    ("selector", "light cyan", ""),
    ("normal", "white", ""),
    ("norm_red", "dark red", ""),
    ("norm_green", "dark green", ""),
]


class Application:

    def __init__(self):
        self.sca_customer: SCACustomer = None
        self.vendor_customer: VendorCustomer = None
        self.user_input: urwid.Edit = None
        self.next_screen: Callable = self.top_menu
        self.NAV_STACK = []
        self.WELCOME_SCREEN = True

        # footer buttons
        back_to_top = urwid.Button("Main Menu")
        urwid.connect_signal(back_to_top, "click", self.top_menu)
        go_back_btn = urwid.Button("Go Back")
        urwid.connect_signal(go_back_btn, "click", self.go_back)
        done = urwid.Button("Exit")
        urwid.connect_signal(done, "click", self.exit_program)
        button_row = urwid.Columns(
            [
                ("pack", go_back_btn),
                ("pack", back_to_top),
                ("pack", done),
            ],
            dividechars=3,
        )

        # self.all_adp_customers = get_sca_customers_w_adp_accounts()

        main = urwid.Padding(self.welcome_screen(), left=2, right=2)
        self.frame = urwid.Frame(main)
        self.frame.footer = button_row
        self.frame.header = urwid.Text(
            f"connecting to backend: {BACKEND_URL} | price year: {BASE_YEAR}"
        )
        top = urwid.Overlay(
            self.frame,
            urwid.SolidFill("\N{MEDIUM SHADE}"),
            align="center",
            width=("relative", 80),
            valign="middle",
            height=("relative", 60),
            min_width=20,
            min_height=9,
        )
        self.main_loop = urwid.MainLoop(
            top, palette=PALETTE, unhandled_input=self.change_focus
        )

    def run(self):
        self.main_loop.run()

    def top_menu(self, button=None) -> urwid.ListBox | None:
        menu_widget = self.menu(
            "Choose a vendor:",
            self.vendor_chosen,
            choices=get_vendors(),
            label_attrs=["name"],
        )
        self.frame.set_focus("body")
        if button:
            self.frame.body = menu_widget
        else:
            return menu_widget

    def go_back(self, button=None) -> "Application":
        self.frame.set_focus("body")
        try:
            header, self.frame.body = self.NAV_STACK.pop()
            if isinstance(header, urwid.Pile):
                while isinstance(header, urwid.Pile):
                    header = header.contents.pop()[0]
                self.frame.header = header
            else:
                self.frame.header = header
        except:
            self.frame.body = self.top_menu()
            self.frame.header = None
        finally:
            return self

    def exit_program(self, button) -> None:
        raise urwid.ExitMainLoop()

    def change_focus(self, key) -> None:
        if key == "tab":
            if self.frame.focus_position == "body":
                self.frame.focus_position = "footer"
            else:
                self.frame.focus_position = "body"

    def welcome_screen(self) -> urwid.Filler:
        msg = f"""Welcome to the ADP Program Administration Program (v{__version__})\n\n
        This program is meant to address our needs with managing ADP programs by interfacing
        directly with the new system until we have a web application interface in place."""
        text = urwid.Text(msg, align="center")
        enter_btn = urwid.Button("Enter")
        urwid.connect_signal(
            enter_btn,
            "click",
            lambda button: self.show_new_screen(),
        )
        layout = urwid.Filler(
            urwid.Pile(
                [
                    text,
                    urwid.Divider(),
                    urwid.Divider(),
                    urwid.AttrMap(enter_btn, None, focus_map="reversed"),
                ]
            )
        )
        return layout

    @staticmethod
    def extract_attr(choice, attr_stack: list) -> str:
        if len(attr_stack) == 1:
            return getattr(choice, attr_stack[0])
        elif len(attr_stack) > 1:
            obj = choice
            for attr in attr_stack:
                val = getattr(obj, attr)
                obj = val
            return val

    def menu(
        self,
        title: str,
        callback: Callable,
        choices: Iterable,
        label_attrs: list[str] = None,
        as_table: bool = False,
        headers: list[str] = None,
    ) -> urwid.ListBox:
        """Builds the menu UI with the given choices."""
        self.frame.header = urwid.AttrMap(urwid.Text(title), "header")
        body = [urwid.Divider()]
        if as_table:
            body.append(TableHeader([" "] + headers))
        for c in choices:
            c: Annotated[str, Any]
            if label_attrs:
                button = urwid.Button(self.extract_attr(c, label_attrs))
            elif as_table:
                button = TableRow(c, displayable_elements=headers)
            else:
                button = urwid.Button(c)
            urwid.connect_signal(button, "click", callback, user_args=(c,))
            if as_table:
                body.append(button)
            else:
                body.append(urwid.AttrMap(button, attr_map=None, focus_map="reversed"))
        return urwid.ListBox(urwid.SimpleFocusListWalker(body))

    def show_new_screen(self, *args) -> None:
        if self.WELCOME_SCREEN:
            # don't retain the welcome screen in the nav
            # but next calls will get appended
            self.WELCOME_SCREEN = False
        else:
            self.NAV_STACK.append((self.frame.header, self.frame.body))
        try:
            new_screen = self.next_screen()
        except Exception as e:
            import traceback as tb

            flash_text = urwid.Text(
                ("flash_bad", f"an error occured - {str(e)}"), align="center"
            )
            self.frame.header = urwid.Pile([flash_text, self.frame.header])
            self.frame.body = urwid.Filler(urwid.Pile([urwid.Text(tb.format_exc())]))
        else:
            self.frame.body = urwid.Padding(new_screen, left=2, right=2)

    def routing_menu(self, title: str, routes: list[Route]) -> urwid.ListBox:
        """Builds the menu UI with callables associated by choice"""
        self.frame.header = urwid.AttrMap(urwid.Text(title), "header")
        body = [urwid.Divider()]
        focus_map = "reversed"
        for route in routes:
            button = urwid.Button(route.choice_title)
            if route.callable_choices:
                menu_callback = partial(
                    self.menu,
                    route.callable_title,
                    route.callable_,
                    route.callable_choices,
                )
                if route.callable_label_attrs:
                    menu_callback = partial(menu_callback, route.callable_label_attrs)
                elif route.callable_as_table:
                    menu_callback = partial(
                        menu_callback, None, True, route.callable_headers
                    )
                self.next_screen = menu_callback
            else:
                self.next_screen = route.callable_
            urwid.connect_signal(button, "click", self.show_new_screen)
            body.append(urwid.AttrMap(button, None, focus_map=focus_map))
        return urwid.ListBox(urwid.SimpleFocusListWalker(body))

    # Menu Path Construction Begins
    def vendor_chosen(self, vendor: Vendor, button) -> None:
        if not vendor.id == "adp":
            msg = f"{vendor.name} has not been implemented yet"
            text = urwid.Text(("flash_bad", msg))
            self.frame.header = urwid.Pile([text, self.frame.header])
        else:
            new_title = f"Choose the SCA Customer for {vendor.name}:"
            entities = CACHE.get(vendor.id, None)
            if not entities:
                entities = get_sca_customers_w_vendor_accounts(vendor)
                CACHE[vendor.id] = entities

            self.next_screen = partial(
                self.menu,
                new_title,
                self.customer_entity_chosen,
                entities,
                ["sca_name"],
            )
            self.show_new_screen()

    def customer_entity_chosen(self, chosen_customer: SCACustomerV2, button) -> None:
        """Once an vendor customer entity is selected,
        user can choose to do various administrative tasks"""
        self.sca_customer = chosen_customer
        accounts = chosen_customer.entity_accounts
        self.next_screen = partial(
            self.menu,
            f"{chosen_customer.sca_name}",
            self.customer_account_chosen,
            choices=accounts,
            label_attrs=["name"],
        )
        self.show_new_screen()

    # TODO Figure out how to delegate from here
    # The actions to take once we get here will depend on the vendor
    def customer_account_chosen(self, chosen_customer: VendorCustomer, button) -> None:
        """Once an vendor customer is selected,
        user can choose to do various administrative tasks"""
        self.vendor_customer = chosen_customer
        handler = ADPHandler(self)
        self.next_screen = handler.get_action_flow()
        handler.app.show_new_screen()


class VendorHandler(ABC):
    def __init__(self, app: Application) -> None:
        self.app = app

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
            choices=Actions,
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
        resp: Response = price_check(customer.id, raw_input, BASE_YEAR=BASE_YEAR)
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
            net_price = f"Pricing\n   ${body['net-price']:,.2f} with discount of {discount_used:0.2f}%"
            orig_price = f"   Zero Discount Pricing = ${zero_disc_price:,.2f}"
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
            self.app.frame.header = urwid.Pile([current_msg, self.app.frame.header])
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
        choice = Actions(choice)
        customer = self.app.vendor_customer
        match choice:
            case Actions.DOWNLOAD_PROGRAM:
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
            case Actions.UPLOAD_RATINGS:
                self.upload_ratings(select_file())
            case Actions.VIEW_COILS:
                routes = []
                new_coil = Route(
                    callable_=self.add_new_coil,
                    choice_title="Add a new coil",
                    callable_title="Enter Coil Model Number",
                )
                routes.append(new_coil)
                self.app.next_screen = partial(
                    self.app.routing_menu,
                    f"{customer.name}",
                    routes,
                )
                self.app.show_new_screen()
            case Actions.VIEW_AHS:
                routes = []
                new_ah = Route(
                    callable_=self.add_new_ah,
                    choice_title="Add a new air handler",
                    callable_title="Enter Air Handler Model Number",
                )
                routes.append(new_ah)
                self.app.next_screen = partial(
                    self.app.routing_menu,
                    f"{customer.name}",
                    routes,
                )
                self.app.show_new_screen()
            case Actions.PRICE_CHECK:
                self.app.next_screen = self.do_model_lookup
                self.app.show_new_screen()
            case _:
                response = "No Action taken"
                response_text = urwid.Text(response)
                self.app.frame.body = urwid.Filler(urwid.Pile([response_text]))


if __name__ == "__main__":
    app = Application()
    app.run()
