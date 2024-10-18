import typing
import urwid

from collections.abc import Callable, Hashable, MutableSequence

from auth import set_up_token

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

type Caption = str | tuple[Hashable, str] | list[str | tuple[Hashable, str]]
type Callback = Callable[["ActionButton"], typing.Any]
type Choices = MutableSequence[urwid.Widget]


class ActionButton(urwid.Button):
    def __init__(
        self,
        caption: Caption,
        callback: Callback,
    ) -> None:
        super().__init__("", on_press=callback, user_data=(caption[-1],))
        self._w = urwid.AttrMap(
            urwid.SelectableIcon(caption, 1), None, focus_map="reversed"
        )


class Action(urwid.WidgetWrap[ActionButton]):

    parent: "ParentApp"

    def __init__(self, name: str, callback: Callable) -> None:
        super().__init__(ActionButton([" * ", name], self.execute_action))
        self.name = name
        self.callback = callback

    @classmethod
    def set_parent(cls, parent_app: "ParentApp") -> None:
        cls.parent = parent_app

    def execute_action(self, button: ActionButton, data: typing.Any) -> None:
        self.parent.execute_action(self)


class Menu(urwid.WidgetWrap[ActionButton]):

    parent: "ParentApp"

    def __init__(self, name: str, choices: Choices) -> None:
        super().__init__(ActionButton([" > ", name], self.next_menu))
        self._name = name
        self.heading = urwid.Text(["\n", name, "\n"])
        self.choices = choices
        # create links back to ourself
        # for child in choices:
        #     getattr(child, "choices", []).insert(0, self)

    def __str__(self) -> str:
        return self._name.lower().strip().replace(" ", "_")

    @classmethod
    def set_parent(cls, parent_app: "ParentApp") -> None:
        cls.parent = parent_app

    def next_menu(self, button: ActionButton, data: typing.Any) -> None:
        self.parent.next_menu(self, data)


class ParentApp:
    def next_menu(self, menu: Menu, value_selected: typing.Any) -> None:
        pass

    def execute_action(self, action: Action) -> None:
        pass

    def add_callback_arg(self, arg) -> None:
        pass


class DataPassThroughToAction(ParentApp):
    def __init__(self, mapping: Menu) -> None:
        self.log = urwid.SimpleFocusListWalker([])
        self.top = urwid.ListBox(self.log)
        self.menu: Menu = None
        self.nav = [mapping]
        self.action_args = dict()
        self.next_menu(mapping, None)

    def add_callback_arg(self, new_arg: dict) -> None:
        self.action_args.update(new_arg)

    def next_menu(self, menu: Menu, value_selected: tuple[typing.Any] | None) -> None:
        if self.log:
            self.log.pop()
        (data,) = value_selected if value_selected else (None,)
        self.log.append(urwid.Pile([menu.heading, *menu.choices]))
        self.top.focus_position = len(self.log) - 1
        if self.menu:
            self.add_callback_arg({str(self.menu): data})
            self.nav.append(self.menu)
        else:
            self.add_callback_arg({str(menu): data})
        self.menu = menu

    def execute_action(self, action: Action) -> None:
        action.callback(**self.action_args)
        self.next_menu(self.menu, None)
        # if self.inventory >= {"sugar", "lemon", "jug"}:
        #     response = urwid.Text("You can make lemonade!\n")
        #     done = ActionButton(" - Joy", exit_program)
        #     self.log[:] = [response, done]
        # else:
        #     self.next_menu(self.menu)

    def last_menu(self, key):
        if key == "backspace":
            if self.nav:
                if self.log:
                    self.log.pop()
                    menu: Menu = self.nav.pop()
                    self.log.append(urwid.Pile([menu.heading, *menu.choices]))
                    self.top.focus_position = len(self.log) - 1
                    self.menu = menu
        else:
            print("\n", key)


def exit_program(button: ActionButton) -> typing.NoReturn:
    raise urwid.ExitMainLoop()


def print_cb(**kwargs) -> None:
    for k, v in kwargs.items():
        print(f"{k} -> {v}")


adp_customers = get_sca_customers_w_adp_accounts()
adp_customers.sort(key=lambda x: x.sca_name)

sca_customer_menus = list()
actions = [Action("Price Check", print_cb)]
for customer in adp_customers:
    sub_menu = Menu(
        customer.sca_name,
        [Menu(alias.adp_alias, actions) for alias in customer.adp_objs],
    )
    sca_customer_menus.append(sub_menu)

map_top = Menu("SCA Customers", sca_customer_menus)
management = DataPassThroughToAction(map_top)
Menu.set_parent(management)
Action.set_parent(management)

urwid.MainLoop(
    management.top,
    palette=[("reversed", "standout", "")],
    unhandled_input=management.last_menu,
).run()
