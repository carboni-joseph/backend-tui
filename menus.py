"""Custom Menu builders"""
from functools import partial
from typing import Iterable, Annotated, Any, Callable
from urwid import (
    AttrMap, ListBox, SimpleFocusListWalker,
    connect_signal, Button, Divider, Text,
    Frame, Filler, Pile, Padding
)
from models import TableHeader, TableRow, Route

WELCOME_SCREEN = True

def menu(
        frame: Frame,
        title: str,
        callback: Callable,
        choices: Iterable,
        label_attrs: list[str]=None,
        as_table: bool=False,
        headers:list[str]=None
    ) -> ListBox:
    """Builds the menu UI with the given choices."""
    frame.header = AttrMap(Text(title), 'header')
    body = [Divider()]
    if as_table:
        body.append(TableHeader([' '] + headers))
    for c in choices:
        c: Annotated[str, Any]
        if label_attrs:
            button = Button(extract_attr(c, label_attrs))
        elif as_table:
            button = TableRow(c, displayable_elements=headers)
        else:
            button = Button(c)
        connect_signal(button, 'click', callback, user_args=(frame, c))
        if as_table:
            body.append(button)
        else:
            body.append(AttrMap(button, attr_map=None, focus_map='reversed'))
    return ListBox(SimpleFocusListWalker(body))


def extract_attr(choice, attr_stack: list) -> str:
    if len(attr_stack) == 1:
        return getattr(choice, attr_stack[0])
    elif len(attr_stack) > 1:
        obj = choice
        for attr in attr_stack:
            val = getattr(obj, attr)
            obj = val
        return val
        
def routing_menu(frame: Frame, nav: list[tuple],
                 title: str, routes: list[Route]) -> ListBox:
    """Builds the menu UI with callables associated by choice"""
    frame.header = AttrMap(Text(title), 'header')
    body = [Divider()]
    focus_map = 'reversed'
    for route in routes:
        button = Button(route.choice_title)
        if route.callable_choices:
            menu_callback = partial(
                menu, frame,
                route.callable_title, route.callable_,
                route.callable_choices
            )
            if route.callable_label_attrs:
                menu_callback = partial(menu_callback,
                                        route.callable_label_attrs)
            elif route.callable_as_table:
                menu_callback = partial(menu_callback, None,
                                        True, route.callable_headers)
            route = partial(show_new_screen, frame, menu_callback, nav)
        else:
            route = partial(show_new_screen, frame, route.callable_, nav)
        connect_signal(button, 'click', route)
        body.append(AttrMap(button, None, focus_map=focus_map))
    return ListBox(SimpleFocusListWalker(body))

def popup(frame: Frame, title: str, callback: Callable, choices: Iterable):
    ...

def show_new_screen(frame: Frame, new_screen_callable,
                    nav: list[tuple], *args) -> None:
    global WELCOME_SCREEN
    if WELCOME_SCREEN:
        # don't retain the welcome screen in the nav
        # but next calls will get appended
        WELCOME_SCREEN = False
    else:
        nav.append((frame.header, frame.body))
    try:
        new_screen = new_screen_callable()
    except Exception as e:
        import traceback as tb
        flash_text = Text((
                'flash_bad',
                f'an error occured - {str(e)}'),
            align='center')
        frame.header = Pile([flash_text, frame.header])
        frame.body = Filler(Pile([Text(tb.format_exc())]))
    else:
        frame.body = Padding(new_screen, left=2, right=2)
