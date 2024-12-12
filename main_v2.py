from typing import Optional, Any, Union, NoReturn
import urwid
from dataclasses import dataclass
import json

from collections.abc import Callable, Hashable, MutableSequence

from auth import set_up_token
from models import ADPCustomer, Coil, Stage, AH, Rating, CoilsV2, CoilV2, AHV2, AHsV2

set_up_token()

from actions import (
    download_file,
    get_coils,
    FileSaveError,
    patch_new_coil_status,
    post_new_coil,
    select_file,
    get_sca_customers_w_adp_accounts,
    get_air_handlers,
    patch_new_ah_status,
    post_new_ah,
    get_ratings,
    post_new_ratings,
    delete_rating,
    price_check,
)
from menus import menu_v2

type Callback = Callable[["ActionButton"], Any]
type Choices = MutableSequence[MenuOption]
type Primitive = int | float | str
type Footer = list[urwid.Widget]


@dataclass
class UpdateAttr:
    obj: Any
    attr: str
    new_value: Primitive


class ActionButton(urwid.Button):
    def __init__(
        self,
        option: "MenuOption",
        callback: Callback,
    ) -> None:
        super().__init__("", on_press=callback, user_data=(option,))
        self._w = urwid.AttrMap(
            urwid.SelectableIcon(str(option), 1), None, focus_map="reversed"
        )
        self.option = option


class Action(urwid.WidgetWrap[ActionButton]):

    parent: "ParentApp"

    def __init__(self, name: str, callback: Callable) -> None:
        mo = MenuOption(f" * {name}")
        super().__init__(ActionButton(mo, self.execute_action))
        self.name = name
        self.callback = callback

    @classmethod
    def set_parent(cls, parent_app: "ParentApp") -> None:
        cls.parent = parent_app

    def execute_action(self, button: ActionButton, data: "MenuOption") -> None:
        self.parent.execute_action(self)


@dataclass
class MenuOption:
    title: Optional[str] = None
    obj: Optional[Any] = None
    next: Union["Menu", "Action"] = None

    def __str__(self) -> str:
        return f" > {self.title}"


class Menu:

    parent: "ParentApp"

    def __init__(self, title: str, choices: Choices) -> None:
        self.title = urwid.Text(title)
        self.choices = list()
        for choice in choices:
            match choice.next:
                case Menu():
                    button = ActionButton(choice, self.next_menu)
                case Action():
                    button = choice.next
            self.choices.append(button)

    def __str__(self) -> str:
        return self.title.text.lower().strip().replace(" ", "_")

    @classmethod
    def set_parent(cls, parent_app: "ParentApp") -> None:
        cls.parent = parent_app

    def next_menu(self, button: ActionButton, data: tuple[MenuOption]) -> None:
        (option_selected,) = data
        self.parent.next_menu(option_selected)


class ParentApp:
    def next_menu(self, value_selected: MenuOption) -> None:
        pass

    def execute_action(self, action: Action) -> None:
        pass

    def add_callback_arg(self, arg) -> None:
        pass


class DataPassThroughToAction(ParentApp):
    def __init__(self, mapping: Menu) -> None:
        self.log = urwid.SimpleFocusListWalker([])
        self.top = urwid.Frame(body=urwid.ListBox(self.log))
        self.menus = mapping
        self.menu: Menu = None
        self.nav = [mapping]
        self.action_args = dict()
        self.next_menu(MenuOption(obj=mapping, next=mapping))

    def add_callback_arg(self, new_arg: dict) -> None:
        self.action_args.update(new_arg)

    def next_menu(self, value_selected: MenuOption) -> None:
        if self.log:
            self.log.pop()
        menu = value_selected.next
        self.log.append(urwid.Pile([menu.title, *menu.choices]))
        self.top.body.focus_position = len(self.log) - 1
        if self.menu:
            self.add_callback_arg({str(self.menu): value_selected.obj})
            self.nav.append(self.menu)
        else:
            self.add_callback_arg({"app": value_selected.obj})
        self.menu = menu

    def execute_action(self, action: Action) -> None:
        result = action.callback(**self.action_args)
        self.top.footer = urwid.Pile([*result])

    def back_one(self, remove_content=None, update_attr: UpdateAttr = None):
        if self.nav:
            if self.log:
                self.log.pop()
                menu: Menu = self.nav.pop()
                if remove_content:
                    rem_i = -1
                    for i, choice in enumerate(menu.choices):
                        choice: ActionButton
                        if choice.option.obj is remove_content:
                            rem_i = i
                            break
                    if rem_i + 1:
                        menu.choices.pop(rem_i)
                self.log.append(urwid.Pile([menu.title, *menu.choices]))
                self.top.body.focus_position = len(self.log) - 1
                self.top.header = None
                self.top.footer = None
                self.menu = menu

    def custom_switches(self, key):
        match key:
            case "backspace":
                self.back_one()
            case "esc":
                exit_program()


class ADPManagement:

    def __init__(self) -> None:
        adp_customers = get_sca_customers_w_adp_accounts(2)
        adp_customers.sort(key=lambda x: x.sca_name)
        actions = [
            MenuOption(next=Action("Price Check", None)),
            MenuOption(next=Action("Coils", self.gen_coil_menus)),
            MenuOption(next=Action("Air Handlers", self.gen_ah_menus)),
            MenuOption(next=Action("Ratings", self.gen_ratings_menus)),
            MenuOption(next=Action("Accessories", None)),
        ]
        sca_customers = [
            MenuOption(
                customer.sca_name,
                customer,
                Menu(
                    "ADP Customer",
                    [
                        MenuOption(
                            adp_name.adp_alias, adp_name, Menu("Action", actions)
                        )
                        for adp_name in customer.adp_objs
                    ],
                ),
            )
            for customer in adp_customers
        ]
        map_top = Menu("SCA Customers", sca_customers)
        self.app = DataPassThroughToAction(map_top)
        Menu.set_parent(self.app)
        Action.set_parent(self.app)
        urwid.MainLoop(
            self.app.top,
            palette=[("reversed", "standout", "")],
            unhandled_input=self.app.custom_switches,
        ).run()
        return

    def soft_del_customer(self, adp_customer: ADPCustomer, **kwargs):
        """Proof of concept for soft delete in the app using back_one"""
        self.app.back_one(remove_content=adp_customer)
        return [urwid.Text(f"removed {adp_customer.adp_alias}")]

    def update_product(self, products: Coil, new_stage: Stage, **kwargs):
        """The concept of 'status' for pricing has been left out of the update
        to v2. Price changes and effective dates are captured in a changelog. The status
        can be derived by sales records from time to time. The only updates
        needed or allowed in this use case are the price points and effective dates.

        In addition, coils and air handlers have been unified, so they can now share
        the same method for updates.

        Updates may include deletion."""
        pass

    def update_ah_status(self, products: AH, new_stage: Stage, **kwargs):
        pass

    def gen_coil_menus(self, adp_customer: ADPCustomer, **kwargs) -> Footer:
        coils: CoilsV2 = get_coils(for_customer=adp_customer, version=2)
        coil_product_actions = []
        coil_menu_options = [
            MenuOption(
                f"{coil.attributes.model_number} : ${coil.attributes.price:.02f} "
                f"effective {coil.attributes.effective_date}",
                coil,
                # Action(coil.attributes.model_number, self.update_product),
                Menu("Update", [MenuOption("Price", coil)]),
            )
            for coil in coils.data
        ]
        new_menu = Menu(f"{adp_customer.adp_alias}'s Coils", coil_menu_options)
        self.app.next_menu(MenuOption(next=new_menu))
        return [urwid.Text("coils menu")]

    def gen_ah_menus(self, adp_customer: ADPCustomer, **kwargs) -> Footer:
        ahs: AHsV2 = get_air_handlers(for_customer=adp_customer, version=2)
        ah_menu_options = [
            MenuOption(
                ah.attributes.model_number,
                ah,
                Action(ah.attributes.model_number, self.update_ah_status),
            )
            for ah in ahs.data
        ]
        new_menu = Menu(f"{adp_customer.adp_alias}'s ahs", ah_menu_options)
        self.app.next_menu(MenuOption(next=new_menu))
        return [urwid.Text("get ahs")]

    def gen_ratings_menus(self, adp_customer: ADPCustomer, **kwargs) -> Footer:
        ratings = get_ratings(for_customer=adp_customer, version=2)
        return [urwid.Text("get ratings")]


def exit_program() -> NoReturn:
    raise urwid.ExitMainLoop()


ADPManagement()
