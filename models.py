from datetime import datetime
from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Callable, Iterable, Literal
from enum import StrEnum, auto
from urwid import Columns, Text, AttrMap, Widget, Align

@dataclass
class ADPCustomer:
    adp_alias: str
    id: int

@dataclass
class SCACustomer:
    sca_name: str
    adp_objs: list[ADPCustomer]

class Stage(StrEnum):
    PROPOSED = auto()
    ACTIVE = auto()
    REJECTED = auto()
    REMOVED = auto()

@dataclass
class ProgramTypeSelection:
    label: str
    type_selected: Stage

class Actions(StrEnum):
    DOWNLOAD_PROGRAM = 'Download Program'
    UPLOAD_RATINGS = 'Upload Ratings'
    REVIEW_RATINGS = 'Review Ratings'
    VIEW_COILS = 'Coils'
    VIEW_AHS = 'Air Handlers'
    VIEW_ACCESSORIES = 'Accessories'


class CoilAttrs(BaseModel):
    model_config = ConfigDict(populate_by_name=True, protected_namespaces={})
    category: str
    model_number: str = Field(alias="model-number")
    mpg: str
    series: str
    tonnage: int
    pallet_qty: int = Field(alias="pallet-qty")
    width: float
    depth: Optional[float] = None
    length: Optional[float] = None
    height: float
    weight: int
    metering: str
    cabinet: str
    zero_discount_price: int = Field(alias="zero-discount-price")
    material_group_discount: Optional[float] = Field(default=None,
                                                     alias='material-group-discount')
    material_group_net_price: Optional[float] = Field(default=None,
                                                      alias='material-group-net-price')
    snp_discount: Optional[float] = Field(default=None, alias='snp-discount')
    snp_price: Optional[float] = Field(default=None, alias='snp-price')
    net_price: Optional[float] = Field(default=None, alias='net-price')
    effective_date: datetime = Field(default=None, alias='effective-date')
    last_file_gen: datetime = Field(default=None, alias='last-file-gen')
    stage: str

class Coil(BaseModel):
    id: int
    attributes: CoilAttrs

class Coils(BaseModel):
    data: list[Coil]

class AHAttrs(BaseModel):
    model_config = ConfigDict(populate_by_name=True, protected_namespaces={})
    category: str
    model_number: str = Field(alias="model-number")
    mpg: str
    series: str
    tonnage: int
    pallet_qty: Optional[int] = Field(default=None, alias="pallet-qty")
    min_qty: Optional[int] = Field(default=None, alias="min-qty")
    width: float
    depth: float
    height: float
    weight: int
    metering: str
    motor: str
    heat: str
    zero_discount_price: int = Field(alias="zero-discount-price")
    material_group_discount: Optional[float] = Field(default=None,
                                                     alias='material-group-discount')
    material_group_net_price: Optional[float] = Field(default=None,
                                                      alias='material-group-net-price')
    snp_discount: Optional[float] = Field(default=None, alias='snp-discount')
    snp_price: Optional[float] = Field(default=None, alias='snp-price')
    net_price: Optional[float] = Field(default=None, alias='net-price')
    effective_date: datetime = Field(default=None, alias='effective-date')
    last_file_gen: datetime = Field(default=None, alias='last-file-gen')
    stage: str

class AH(BaseModel):
    id: int
    attributes: AHAttrs

class AHs(BaseModel):
    data: list[AH]

class RatingAttrs(BaseModel):
    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())
    ahrinumber: Optional[str] = None
    outdoor_model: Optional[str] = Field(default=None,alias='outdoor-model')
    oem_name: Optional[str] = Field(default=None, alias='oem-name')
    oem_name_1: Optional[str] = Field(default=None,alias='oem-name-1')
    indoor_model: Optional[str] = Field(default=None,alias='indoor-model')
    furnace_model: Optional[str] = None
    oem_name_2: Optional[str] = Field(default=None, alias='OEM Name')
    m1: Optional[str] = None
    status: Optional[str] = None
    oem_series: Optional[str] = Field(default=None, alias='OEM Series')
    adp_series: Optional[str] = Field(default=None, alias='ADP Series')
    model_number: Optional[str] = Field(default=None, alias='Model Number')
    coil_model_number: Optional[str] = Field(default=None, alias='Coil Model Number')
    furnace_model_number: Optional[str] = Field(default=None,
                                                alias='Furnace Model Number')
    seer: Optional[float] = None
    eer: Optional[float] = None
    capacity: Optional[float] = None
    four_seven_o: Optional[float] = Field(default=None, alias='47o')
    one_seven_o: Optional[float] = Field(default=None, alias='17o')
    hspf: Optional[float] = None
    seer2: Optional[float] = None
    eer2: Optional[float] = None
    capacity2: Optional[float] = None
    four_seven_o2: Optional[float] = Field(default=None, alias='47o2')
    one_seven_o2: Optional[float] = Field(default=None, alias='17o2')
    hspf2: Optional[float] = None
    ahri_ref_number: Optional[int] = Field(default=None, alias='AHRI Ref Number')
    region: Optional[str] = None
    effective_date: str = Field(alias='effective-date')
    seer2_as_submitted: Optional[float] = None
    eer95f2_as_submitted: Optional[float] = None
    capacity2_as_submitted: Optional[float] = None
    hspf2_as_submitted: Optional[float] = None

class Rating(BaseModel):
    id: int
    attributes: RatingAttrs

class Ratings(BaseModel):
    data: list[Rating]

@dataclass
class Route:
    callable_: Callable
    callable_title: str
    choice_title: str
    callable_choices: Iterable = None
    callable_label_attrs: list[str] = None
    callable_as_table: bool = False,
    callable_headers: list[str] = None

class TableHeader(Columns):
    def __init__(self, headers: Iterable) -> None:
        header_cells = [
            Text(('normal', str(header)), align='center')
            for header in headers
        ]
        super().__init__(header_cells, dividechars=1)

class TableRow(Columns):
    signals = ['click']
    def __init__(self, contents, selector_text='>',
                 displayable_elements: tuple[str]=None) -> None:
        self.selector_text = selector_text
        self.displayable = displayable_elements
        self.selector = Text(selector_text, align='right')
        match contents:
            case Coil() | AH() | Rating():
                attrs = contents.attributes
                if self.displayable:
                    attrs_treated = [(attr, str(value)) 
                                     for attr, value in attrs 
                                     if attr in self.displayable]
                else:
                    attrs_treated = [(attr, str(value)) for attr, value in attrs]
                cells = []
                for attr in attrs_treated:
                    name, value = attr
                    cells.append(self.selective_coloring(value, 'center'))
                cells.insert(0, AttrMap(self.selector, 'normal', 'selector'))
            case _:
                cells = [Text(c,align='center') for c in contents]
        super().__init__(cells, dividechars=1)

    def selectable(self) -> bool:
        return True

    def keypress(self, size: tuple[()] | tuple[int] | tuple[int, int], key: str) -> str | None:
        if key == 'enter':
            self._emit('click')
        else:
            return super().keypress(size, key)

    def mouse_event(
            self,
            size: tuple[()] | tuple[int] | tuple[int, int],
            event: str,
            button: int,
            col: int,
            row: int,
            focus: bool
    ) -> bool | None:
        if event == 'mouse press' and button == 1:
            self._emit('click')
        else:
            return super().mouse_event(size, event, button, col, row, focus)

    @staticmethod
    def selective_coloring(
            text: str,
            align: Literal["left", "center", "right"] = Align.LEFT
    ) -> Text:
        if text == Stage.REJECTED:
            attr_map = 'norm_red'
        elif text == Stage.REMOVED:
            attr_map = 'norm_red'
        elif text == Stage.ACTIVE:
            attr_map = 'norm_green'
        else:
            attr_map = 'normal'
        return Text((attr_map, text), align=align)

    def render(self, size, focus=False):
        if focus:
            self.selector.set_text(('selector', self.selector_text))
        else:
            self.selector.set_text(('normal', ' '))
        for cell in self.contents:
            cell: tuple[Widget, tuple]
            widget, options = cell
            widget: Text
            if focus:
                try:
                    widget_text, display_options = widget.get_text()
                    widget.set_text(('selector', widget_text))
                except:
                    pass
            else:
                try:
                    widget_text, display_options = widget.get_text()
                    widget_text, styling = self.selective_coloring(widget_text).get_text()
                    widget.set_text((styling[0][0], widget_text))
                except:
                    pass
        return super().render(size, focus)
    