__version__ = 2

import urwid
from functools import partial
from typing import Literal, Callable
from requests import Response
from auth import set_up_token; set_up_token()
from models import (
    ADPCustomer, SCACustomer,
    Coil, AH, Rating, Stage,
    Actions, ProgramTypeSelection, Route
)
from actions import (
    download_file, get_coils, FileSaveError,
    patch_new_coil_status, post_new_coil,
    select_file, get_sca_customers_w_adp_accounts,
    get_air_handlers, patch_new_ah_status,
    post_new_ah, get_ratings, post_new_ratings,
    delete_rating, price_check
)
from menus import menu, routing_menu, show_new_screen

def customer_chosen(frame: urwid.Frame, choice: SCACustomer, button) -> None:
    """Generate the next menu, where the user 
        selects the ADP customer name"""
    new_title = f"Choose the ADP account for {choice.sca_name}:"
    new_menu =  partial(
        menu,
        frame,
        new_title,
        action_menu,
        choice.adp_objs,
        ["adp_alias"]
    )
    show_new_screen(frame, new_menu, NAV_STACK)

def action_menu(frame: urwid.Frame, chosen_customer: ADPCustomer,
                button) -> None:
    """Once an ADP customer is selected, 
        user can choose to do various administrative tasks"""
    new_menu = partial(
        menu,
        frame,
        f'{chosen_customer.adp_alias}',
        partial(action_chosen,chosen_customer),
        choices=Actions
    )
    show_new_screen(frame, new_menu, NAV_STACK)

def program_type_selected(
        customer: ADPCustomer,
        frame: urwid.Frame,
        program_type: ProgramTypeSelection,
        button
    ) -> None:
    try:
        download_file(customer.id, program_type.type_selected)
    except FileSaveError as e:
        response = 'There was an error trying to save the file. '\
                  f'If an existing file with the name {e.filename} is open, '\
                    'please close it and try downloading again.'
        response_text = urwid.Text(('flash_bad', response))
    except Exception as e:
        response_text = urwid.Text(('flash_bad', str(e)))
    else:
        response = f'{program_type.type_selected} program downloaded '\
                   f'for {customer.adp_alias}'
        response_text = urwid.Text(('flash_good', response))
    go_back()
    frame.header = urwid.Pile([response_text, frame.header])

def show_coil_status_change_menu(
        customer: ADPCustomer,
        frame: urwid.Frame,
        coil: Coil,
        button
    ) -> None:
    title = f'{customer.adp_alias}\n '\
            f'Model: {coil.attributes.model_number}\n '\
            f'Status: {coil.attributes.stage.title()}'
    new_menu = partial(
        menu,
        frame,
        title,
        partial(update_coil_status, customer, coil),
        choices=Stage
    ) 
    show_new_screen(frame, new_menu, NAV_STACK)

def show_ah_status_change_menu(
        customer: ADPCustomer,
        frame: urwid.Frame,
        ah: AH,
        button
    ) -> None:
    title = f'{customer.adp_alias}\n '\
            f'Model: {ah.attributes.model_number}\n '\
            f'Status: {ah.attributes.stage.title()}'
    new_menu = partial(
        menu,
        frame,
        title,
        partial(update_ah_status, customer, ah),
        choices=Stage
    ) 
    show_new_screen(frame, new_menu, NAV_STACK)

def update_coil_status(
        customer: ADPCustomer,
        coil: Coil,
        frame: urwid.Frame,
        new_stage: str,
        button
    ) -> None:
    old_stage = coil.attributes.stage.title()
    new_stage_ = Stage(new_stage)
    resp = patch_new_coil_status(customer.id, coil.id, new_stage_)
    if resp.status_code == 200:
        response = urwid.Text((
            'flash_good',
            f'Successfully Updated Coil {coil.attributes.model_number} '
            f'from {old_stage} to {new_stage_.value.title()}'
        ))
    else:
        response = urwid.Text(('flash_bad', 'Unable to update coil status.'))
    go_back()
    go_back()
    go_back()
    frame.header = urwid.Pile([response, frame.header])

def update_ah_status(
        customer: ADPCustomer,
        ah: AH,
        frame: urwid.Frame,
        new_stage: str,
        button
    ) -> None:
    old_stage = ah.attributes.stage.title()
    new_stage_ = Stage(new_stage)
    resp = patch_new_ah_status(customer.id, ah.id, new_stage_)
    if resp.status_code == 200:
        response = urwid.Text((
            'flash_good',
            f'Successfully Updated ah {ah.attributes.model_number} '
            f'from {old_stage} to {new_stage_.value.title()}'
        ))
    else:
        response = urwid.Text(('flash_bad', 'Unable to update ah status.'))
    go_back()
    go_back()
    go_back()
    frame.header = urwid.Pile([response, frame.header])

def add_new_model(submit_method: Callable, 
                  customer: ADPCustomer) -> urwid.ListBox:
    edit = urwid.Edit('Enter Model Number: ')
    submit = urwid.Button(
        'Submit',
        on_press=partial(submit_method, customer),
        user_data=edit
    )
    return urwid.ListBox([
        edit, 
        urwid.AttrMap(submit, None, focus_map='reversed')
    ])


def do_model_lookup(customer: ADPCustomer):
    user_input = urwid.Edit('Enter Model Number: ')
    action = partial(display_price_check, customer, user_input)
    submit = urwid.Button('Submit', on_press=action)
    return urwid.ListBox([user_input, urwid.AttrMap(submit, None, focus_map='reversed')])

def display_price_check(customer: ADPCustomer, user_input: urwid.Edit, button):
    raw_input = user_input.edit_text
    resp: Response = price_check(customer.id, raw_input)
    if resp.status_code == 200:
        body: dict = resp.json()
        zero_disc_price = body['zero-discount-price']
        net_price = body['net-price']
        discount_used = 0
        if net_price != zero_disc_price:
            mgd = body.get('material-group-net-price', 0)
            snp = body.get('snp-price', 0)
            if mgd == net_price:
                discount_used = body.get('material-group-discount')
            if snp == net_price:
                discount_used = body.get('snp-discount')
        net_price = f"Pricing\n   ${body['net-price']:,.2f} with discount of {discount_used:0.2f}%"
        orig_price = f"   Zero Discount Pricing = ${zero_disc_price:,.2f}"
        features = [
            f"   {k}: {v}" for k,v in body.items()
            if k in [
                'model-number',
                'series',
                'tonnage',
                'width',
                'depth', 
                'height',
                'motor',
                'heat',
            ]
        ]
        # not a JSONAPI obj with a data key, just the features as keys
        frame.body = urwid.Filler(
            urwid.Pile(
                [urwid.Text(e) for e in [net_price, orig_price, 'Features', *features]]
            )
        )
    else:
        response_header = urwid.Text(('flash_bad',
                                    f'{raw_input} is not valid'))
        response_body = urwid.Text(resp.content)
        frame.header = urwid.Pile([response_header, frame.header])
        frame.body = urwid.Filler(urwid.Pile([response_body]))


def add_new_coil(customer: ADPCustomer) -> urwid.ListBox:
    return add_new_model(submit_coil_model, customer)

def add_new_ah(customer: ADPCustomer) -> urwid.ListBox:
    return add_new_model(submit_ah_model, customer)

def submit_coil_model(customer: ADPCustomer, button,
                      user_input: urwid.Edit) -> None:
    return submit_model(post_new_coil, customer, user_input)

def submit_ah_model(customer: ADPCustomer, button,
                    user_input: urwid.Edit) -> None:
    return submit_model(post_new_ah, customer, user_input)

def submit_model(product_type_method: Callable,
                 customer: ADPCustomer, user_input: urwid.Edit) -> None:
    """sends new model payload to the API"""
    user_text: str = user_input.edit_text
    model_list: list = [model.strip().upper() for model in user_text.split(',')]
    results = list()
    for model in model_list:
        resp: Response = product_type_method(customer.id, model)
        body = resp.json()
        if resp.status_code == 200:
            body_data: dict[str,str|dict] = body['data']
            response_header = urwid.Text((
                'flash_good',
                f'Model {model} successfully added '
                f'for {customer.adp_alias} under id {body_data['id']}'
            ))
        else:
            response_header = urwid.Text(('flash_bad',
                                        f'Unable to add model {model}'))
        results.append(response_header)
    go_back()
    go_back()
    frame.header = urwid.Pile([*results, frame.header])

def remove_rating(
        rating: Rating,
        frame: urwid.Frame,
        confirm: Literal["Yes", "No"],
        button=None
    ) -> None:
    if confirm == 'No':
        go_back()
        return
    try:
        delete_rating(rating.id, rating.relationships.adp_customers.data.id)
    except Exception as e:
        header_text = urwid.Text(('flash_bad', str(e)))
    else:
        header_text = urwid.Text(('flash_good', 'Successfully deleted rating'))
    finally:
        go_back()
        go_back()
        frame.header = urwid.Pile([header_text, frame.header])

def confirm_rating_delete(frame: urwid.Frame, rating: Rating, button) -> None:
    new_menu = partial(
        menu,
        frame,
        'Delete?',
        partial(remove_rating, rating),
        ["Yes", "No"]
    )
    show_new_screen(frame, new_menu, NAV_STACK)
    
def upload_ratings(customer: ADPCustomer, selected_file: str):
    try:
        post_new_ratings(customer.id, selected_file)
    except Exception as e:
        header_text = urwid.Text(('flash_bad', str(e)))
    else:
        header_text = urwid.Text(('flash_good', 
                                  'Successfully uploaded ratings'))
    finally:
        frame.header = urwid.Pile([header_text, frame.header])

def action_chosen(customer: ADPCustomer, frame: urwid.Frame,
                  choice: str, button) -> None:
    """determine which administrative action
        the user chose and route them to the proper next menu"""
    choice = Actions(choice)
    match choice:
        case Actions.DOWNLOAD_PROGRAM:
            new_title = "Include Proposed Line Items?"
            choices = [
                ProgramTypeSelection('Yes', Stage.PROPOSED),
                ProgramTypeSelection('No', Stage.ACTIVE)
            ]
            new_menu = partial(
                menu,
                frame,
                new_title,
                partial(program_type_selected, customer),
                choices=choices,
                label_attrs=['label']
            )
            show_new_screen(frame, new_menu, NAV_STACK)
        case Actions.UPLOAD_RATINGS:
            upload_ratings(customer, select_file())
        case Actions.REVIEW_RATINGS:
            try:
                ratings = get_ratings(for_customer=customer).data
            except Exception as e:
                flash_text = urwid.Text(('flash_bad', 'No Ratings to Display'))
                flash_detail = urwid.Text(('flash_bad', str(e)))
                frame.header = urwid.Pile([flash_text, flash_detail, frame.header])
            else:
                displayable = ['ahrinumber', 'outdoor_model',
                               'indoor_model', 'effective_date']
                new_menu = partial(
                    menu,
                    frame,
                    'Ratings',
                    confirm_rating_delete,
                    ratings,
                    None,
                    True,
                    displayable
                )
                show_new_screen(frame, new_menu, NAV_STACK)
        case Actions.VIEW_COILS:
            routes = []
            try:
                coils = get_coils(for_customer=customer).data
            except:
                flash_text = urwid.Text(('flash_bad', 'No Coils on prgram'))
                frame.header = urwid.Pile([flash_text, frame.header])
            else:
                displayable = ['model_number', 'series',
                               'tonnage', 'width', 'net_price', 'stage']
                status_change = Route(
                    callable_=partial(show_coil_status_change_menu, customer),
                    choice_title='View Models',
                    callable_title='Coil Models',
                    callable_choices=coils,
                    # callable_label_attrs=["attributes","model_number"],
                    callable_as_table=True,
                    callable_headers=displayable
                )
                routes.append(status_change)
            finally:
                new_coil = Route(
                    callable_=partial(add_new_coil, customer),
                    choice_title="Add a new coil",
                    callable_title="Enter Coil Model Number"
                )
                routes.append(new_coil)
                new_menu = partial(
                    routing_menu,
                    frame,
                    NAV_STACK,
                    f'{customer.adp_alias}',
                    routes
                )
                show_new_screen(frame, new_menu, NAV_STACK)
        case Actions.VIEW_AHS:
            routes = []
            try:
                ahs = get_air_handlers(for_customer=customer).data
            except:
                flash_text = urwid.Text(('flash_bad',
                                         'No Air Handlers to Display'))
                frame.header = urwid.Pile([flash_text, frame.header])
            else:
                displayable = ['model_number', 'series',
                               'tonnage', 'width', 'net_price', 'stage']
                status_change = Route(
                    callable_=partial(show_ah_status_change_menu, customer),
                    choice_title='View Models',
                    callable_title='Air Handler Models',
                    callable_choices=ahs,
                    callable_as_table=True,
                    callable_headers=displayable
                )
                routes.append(status_change)
            finally:
                new_ah = Route(
                    callable_=partial(add_new_ah, customer),
                    choice_title="Add a new air handler",
                    callable_title="Enter Air Handler Model Number"
                )
                routes.append(new_ah)
                new_menu = partial(
                    routing_menu,
                    frame,
                    NAV_STACK,
                    f'{customer.adp_alias}', routes
                )
                show_new_screen(frame, new_menu, NAV_STACK)
        case Actions.VIEW_ACCESSORIES:
            ...
        case Actions.PRICE_CHECK:
            show_new_screen(
                frame,
                partial(do_model_lookup, customer),
                NAV_STACK
            )
        case _:
            response = 'No Action taken'
            response_text = urwid.Text(response)
            frame.body = urwid.Filler(urwid.Pile([response_text]))

## MAIN MENU, MENU OPENER, and EXIT BUTTONS
def top_menu(button=None) -> urwid.ListBox | None:
    menu_widget = menu(
        frame,
        'Choose a customer:',
        customer_chosen,
        choices=adp_customers,
        label_attrs=['sca_name']
    )
    frame.set_focus('body')
    if button:
        frame.body = menu_widget
    else:
        return menu_widget

def go_back(button=None) -> None:
    frame.set_focus('body')
    try:
        header, frame.body = NAV_STACK.pop()
        if isinstance(header, urwid.Pile):
            while isinstance(header, urwid.Pile):
                header = header.contents.pop()[0]
            frame.header = header
        else:
            frame.header = header 
    except:
        frame.body = top_menu()
        frame.header = None

def exit_program(button) -> None:
    raise urwid.ExitMainLoop()

def change_focus(key) -> None:
    if key == 'tab':
        if frame.focus_position == 'body':
            frame.focus_position = 'footer'
        else:
            frame.focus_position = 'body'
        
## WELCOME SCREEN
def welcome_screen(next_screen) -> urwid.Filler:
    msg = f"""Welcome to the ADP Program Administration Program (v{__version__})\n\n
    This program is meant to address our needs with managing ADP programs by interfacing
    directly with the new system until we have a web application interface in place."""
    text = urwid.Text(msg, align='center')
    enter_btn = urwid.Button('Enter')
    urwid.connect_signal(
        enter_btn,
        'click', 
        lambda button: show_new_screen(frame, next_screen, NAV_STACK)
    )
    layout = urwid.Filler(urwid.Pile([
        text,
        urwid.Divider(),
        urwid.Divider(),
        urwid.AttrMap(enter_btn, None, focus_map='reversed')
    ]))
    return layout

NAV_STACK = []
back_to_top = urwid.Button('Main Menu')
urwid.connect_signal(back_to_top, 'click', top_menu)
go_back_btn = urwid.Button('Go Back')
urwid.connect_signal(go_back_btn, 'click', go_back)
done = urwid.Button('Exit')
urwid.connect_signal(done, 'click', exit_program)

button_row = urwid.Columns([
        ('pack', go_back_btn),
        ('pack', back_to_top),
        ('pack', done),
    ], dividechars=3)

palette = [
    ('reversed', 'standout', ''),
    ('header', 'white', 'black'),
    ('flash_bad', 'white', 'dark red', 'standout'),
    ('flash_good', 'white', 'dark green', 'standout'),
    ('selector', 'light cyan', ''),
    ('normal', 'white', ''),
    ('norm_red', 'dark red', ''),
    ('norm_green', 'dark green', '')
]
adp_customers = get_sca_customers_w_adp_accounts()
adp_customers.sort(key=lambda x: x.sca_name)

main = urwid.Padding(welcome_screen(top_menu), left=2, right=2)
frame = urwid.Frame(main)
frame.footer = button_row
top = urwid.Overlay(frame, urwid.SolidFill(u'\N{MEDIUM SHADE}'),
                    align='center', width=('relative', 80),
                    valign='middle', height=('relative', 60),
                    min_width=20, min_height=9)
main_loop = urwid.MainLoop(top, palette=palette, unhandled_input=change_focus)
main_loop.run()
