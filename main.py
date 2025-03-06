import urwid
from functools import partial
from typing import Callable, Annotated, Any, Iterable
from os.path import dirname, abspath
from pathlib import Path
from configparser import ConfigParser
from auth import set_up_token
import logging

set_up_token()
from models import SCACustomer, SCACustomerV2, Vendor, VendorCustomer, Route, Palette
from actions import get_vendors, get_sca_customers_w_vendor_accounts, debug
from models import TableHeader, TableRow, Route
from vendor_handlers import HANDLERS

FILE_DIR = Path(dirname(abspath(__file__)))
CONFIGS = ConfigParser()
CONFIGS.read(str(FILE_DIR / "config.ini"))
BACKEND_URL = CONFIGS["ENDPOINTS"]["backend_url"]
BASE_YEAR = CONFIGS["OTHER"]["price_year"]
V2_AVAILABILITY_ENDPOINT = BACKEND_URL + "/v2"

CACHE = {}

logging.basicConfig(
    filename="log.log",
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    filemode="a",
)

logger = logging.getLogger(__name__)


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
            top, palette=[p.value for p in Palette], unhandled_input=self.change_focus
        )

    def run(self):
        self.main_loop.run()

    def top_menu(self, button=None) -> urwid.ListBox | None:
        logger.info("Getting Vendors ...")
        menu_widget = self.menu(
            "Choose a vendor:",
            self.vendor_chosen,
            choices=get_vendors(),
            label_attrs=["name"],
        )
        logger.info("Done.")
        self.frame.set_focus("body")
        if button:
            self.frame.body = menu_widget
        else:
            return menu_widget

    def go_back(self, *args, button=None) -> "Application":
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
        msg = f"""Welcome to the SCA Data Administration Program \n\n
        This program is meant to address our needs with managing company data by interfacing
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
        self.frame.header = urwid.AttrMap(urwid.Text(title), Palette.HEADER.value[0])
        body = [urwid.Divider()]
        if as_table:
            # body.append(TableHeader([" "] + headers))
            pass
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

    def routing_menu(
        self,
        title: str,
        elements: list[Route | urwid.Widget],
    ) -> urwid.ListBox:
        """Builds the menu UI with callables associated by choice"""
        self.frame.header = urwid.AttrMap(urwid.Text(title), "header")
        body = [urwid.Divider()]
        focus_map = Palette.REVERSED.value[0]

        def menu_callback(next_, button):
            self.next_screen = next_
            self.show_new_screen()

        for element in elements:
            match element:
                case Route():
                    route = element
                    button = urwid.Button(route.choice_title)
                    if route.callable_choices:
                        callback_ = partial(
                            self.menu,
                            route.callable_title,
                            route.callable_,
                            route.callable_choices,
                        )
                        if route.callable_label_attrs:
                            callback_ = partial(callback_, route.callable_label_attrs)
                        elif route.callable_as_table:
                            callback_ = partial(
                                callback_, None, True, route.callable_headers
                            )
                        next_screen = partial(menu_callback, callback_)
                    else:
                        next_screen = partial(menu_callback, route.callable_)
                    urwid.connect_signal(button, "click", next_screen)
                    body.append(urwid.AttrMap(button, None, focus_map=focus_map))
                case urwid.Widget():
                    body.append(element)
        return urwid.ListBox(urwid.SimpleFocusListWalker(body))

    # Menu Path Construction Begins
    def vendor_chosen(self, vendor: Vendor, button) -> None:
        if not vendor.id == "adp":
            msg = f"{vendor.name} has not been implemented yet"
            text = urwid.Text(("flash_bad", msg))
            self.frame.header = urwid.Pile([text, self.frame.header])
            logger.warning(msg)
        else:
            new_title = f"Choose the SCA Customer for {vendor.name}:"
            entities = CACHE.get(vendor.id, None)
            if not entities:
                logger.info(f"Getting customers for {vendor.name}")
                entities = get_sca_customers_w_vendor_accounts(vendor)
                logger.info("Done.")
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

    def customer_account_chosen(self, chosen_customer: VendorCustomer, button) -> None:
        """Delegate from here to the vendor-specific handlers"""
        self.vendor_customer = chosen_customer
        if Handler := HANDLERS.get(chosen_customer.vendor.id):
            handler = Handler(self)
            self.next_screen = handler.get_action_flow()
            handler.app.show_new_screen()

    def edit_last_column(self, listbox: urwid.ListBox):
        # Get the index of the selected row
        selected_index: int | None = listbox.get_focus()[1]
        if selected_index is None:
            return  # No row is selected

        # Get the current TableRow widget
        row: urwid.Widget = listbox[selected_index]

        # Extract the current contents (excluding the selector)
        contents = row.contents[1:]  # Skip the selector (index 0)
        if not contents:
            return  # No data columns to edit

        # Get the text from the last column
        last_widget, _ = contents[-1]
        if isinstance(last_widget, urwid.Edit):
            # Finish editing: Replace Edit with Text
            new_text = last_widget.get_edit_text()
            text_widget = TableRow.selective_coloring(new_text, "center")
            new_contents = row.contents[:-1] + [(text_widget, row.contents[-1][1])]
            row.contents = new_contents
        else:
            try:
                last_text, _ = last_widget.get_text()
                if isinstance(last_text, tuple):
                    last_text = last_text[0]  # Extract the text if it's a styled tuple
            except:
                last_text = ""  # Default to empty if extraction fails

            # Replace the last column with an Edit widget pre-filled with the current value
            edit_widget = urwid.Edit(caption="", edit_text=str(last_text))
            new_contents = row.contents[:-1] + [(edit_widget, row.contents[-1][1])]
            row.contents = new_contents

        # Update the listbox and re-render
        walker: urwid.SimpleFocusListWalker = listbox.body
        walker[selected_index] = row
        walker._modified()  # Notify the listbox that the content has changed
        try:
            row.set_focus(2)
        except:
            pass
        return


if __name__ == "__main__":
    app = Application()
    app.run()
