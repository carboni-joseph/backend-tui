from datetime import datetime
from dataclasses import dataclass
from enum import StrEnum, auto, Enum
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Callable, Iterable, Literal
from urwid import Columns, Text, AttrMap, Widget, Align


class Palette(Enum):
    REVERSED = ("reversed", "standout", "")
    HEADER = ("header", "white", "black")
    FLASH_BAD = ("flash_bad", "white", "dark red", "standout")
    FLASH_GOOD = ("flash_good", "white", "dark green", "standout")
    SELECTOR = ("selector", "light cyan", "")
    NORMAL = ("normal", "white", "")
    NORM_RED = ("norm_red", "dark red", "")
    NORM_GREEN = ("norm_green", "dark green", "")


@dataclass
class ADPCustomer:
    adp_alias: str
    id: int


@dataclass
class SCACustomer:
    sca_name: str
    adp_objs: list[ADPCustomer]


@dataclass
class Vendor:
    id: str
    name: str


@dataclass
class VendorCustomer:
    id: int
    vendor: Vendor
    name: str


@dataclass
class VendorCustomers:
    entites: list[VendorCustomer]


@dataclass
class SCACustomerV2:
    sca_id: int
    sca_name: str
    vendor: Vendor
    entity_accounts: list[VendorCustomer]


class Stage(StrEnum):
    PROPOSED = auto()
    ACTIVE = auto()
    REJECTED = auto()
    REMOVED = auto()


class ADPActions(StrEnum):
    DOWNLOAD_PROGRAM = "Download Program"
    UPLOAD_RATINGS = "Upload Ratings"
    # REVIEW_RATINGS = "Review Ratings"
    PRODUCT = "Product Strategy"
    PRICE_CHECK = "Price Check"


class VendorProductAttrs(BaseModel):
    model_config = ConfigDict(populate_by_name=True, protected_namespaces={})
    vendor_product_identifier: str
    vendor_product_description: str


class VendorProduct(BaseModel):
    id: int
    attributes: VendorProductAttrs


class VendorProductAttrAttrs(BaseModel):
    model_config = ConfigDict(populate_by_name=True, protected_namespaces={})
    attr: str
    type: str
    value: str


class VendorProductAttr(BaseModel):
    id: int
    attributes: VendorProductAttrAttrs


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
    material_group_discount: Optional[float] = Field(
        default=None, alias="material-group-discount"
    )
    material_group_net_price: Optional[float] = Field(
        default=None, alias="material-group-net-price"
    )
    snp_discount: Optional[float] = Field(default=None, alias="snp-discount")
    snp_price: Optional[float] = Field(default=None, alias="snp-price")
    net_price: Optional[float] = Field(default=None, alias="net-price")
    effective_date: datetime = Field(default=None, alias="effective-date")
    last_file_gen: datetime = Field(default=None, alias="last-file-gen")
    stage: str


class ProductPriceBasic(BaseModel):
    model_config = ConfigDict(populate_by_name=True, protected_namespaces={})
    id: int
    model_number: str = Field(alias="model-number")
    description: Optional[str] = None
    price: int
    effective_date: datetime = Field(default=None, alias="effective-date")

    def model_post_init(self, __context) -> None:
        self.price = int(self.price / 100)
        self.effective_date: str = str(self.effective_date)
        return super().model_post_init(__context)


class CoilAttrsV2(BaseModel):
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
    price: int
    effective_date: datetime = Field(default=None, alias="effective-date")

    def model_post_init(self, __context):
        self.price = int(self.price / 100)
        self.effective_date: str = str(self.effective_date)
        return super().model_post_init(__context)


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
    material_group_discount: Optional[float] = Field(
        default=None, alias="material-group-discount"
    )
    material_group_net_price: Optional[float] = Field(
        default=None, alias="material-group-net-price"
    )
    snp_discount: Optional[float] = Field(default=None, alias="snp-discount")
    snp_price: Optional[float] = Field(default=None, alias="snp-price")
    net_price: Optional[float] = Field(default=None, alias="net-price")
    effective_date: datetime = Field(default=None, alias="effective-date")
    last_file_gen: datetime = Field(default=None, alias="last-file-gen")
    stage: str


class AHAttrsV2(BaseModel):
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
    price: int
    effective_date: datetime = Field(default=None, alias="effective-date")

    def model_post_init(self, __context):
        self.price = int(self.price / 100)
        self.effective_date: str = str(self.effective_date)
        return super().model_post_init(__context)


class AH(BaseModel):
    id: int
    attributes: AHAttrs


class AHV2(BaseModel):
    id: int
    attributes: AHAttrsV2


class AHs(BaseModel):
    data: list[AH]


class AHsV2(BaseModel):
    data: list[AHV2]


class RatingAttrs(BaseModel):
    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())
    ahrinumber: Optional[str] = None
    outdoor_model: Optional[str] = Field(default=None, alias="outdoor-model")
    oem_name: Optional[str] = Field(default=None, alias="oem-name")
    oem_name_1: Optional[str] = Field(default=None, alias="oem-name-1")
    indoor_model: Optional[str] = Field(default=None, alias="indoor-model")
    furnace_model: Optional[str] = None
    oem_name_2: Optional[str] = Field(default=None, alias="OEM Name")
    m1: Optional[str] = None
    status: Optional[str] = None
    oem_series: Optional[str] = Field(default=None, alias="OEM Series")
    adp_series: Optional[str] = Field(default=None, alias="ADP Series")
    model_number: Optional[str] = Field(default=None, alias="Model Number")
    coil_model_number: Optional[str] = Field(default=None, alias="Coil Model Number")
    furnace_model_number: Optional[str] = Field(
        default=None, alias="Furnace Model Number"
    )
    seer: Optional[float] = None
    eer: Optional[float] = None
    capacity: Optional[float] = None
    four_seven_o: Optional[float] = Field(default=None, alias="47o")
    one_seven_o: Optional[float] = Field(default=None, alias="17o")
    hspf: Optional[float] = None
    seer2: Optional[float] = None
    eer2: Optional[float] = None
    capacity2: Optional[float] = None
    four_seven_o2: Optional[float] = Field(default=None, alias="47o2")
    one_seven_o2: Optional[float] = Field(default=None, alias="17o2")
    hspf2: Optional[float] = None
    ahri_ref_number: Optional[int] = Field(default=None, alias="AHRI Ref Number")
    region: Optional[str] = None
    effective_date: str = Field(alias="effective-date")
    seer2_as_submitted: Optional[float] = None
    eer95f2_as_submitted: Optional[float] = None
    capacity2_as_submitted: Optional[float] = None
    hspf2_as_submitted: Optional[float] = None


class Rel(BaseModel):
    id: int
    type: str


class RelObj(BaseModel):
    data: Rel


class RatingRels(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    adp_customers: RelObj = Field(alias="adp-customers")


class Rating(BaseModel):
    id: int
    attributes: RatingAttrs
    relationships: RatingRels


class Ratings(BaseModel):
    data: list[Rating]


@dataclass
class Route:
    callable_: Callable
    callable_title: str
    choice_title: str
    callable_choices: Iterable = None
    callable_label_attrs: list[str] = None
    callable_as_table: bool = (False,)
    callable_headers: list[str] = None


class TableHeader(Columns):
    def __init__(self, headers: Iterable) -> None:
        header_cells = [
            Text(("normal", str(header)), align="center") for header in headers
        ]
        super().__init__(header_cells, dividechars=1)


class TableRow(Columns):
    KeypressSize = tuple[()] | tuple[int] | tuple[int, int]
    signals = ["click"]

    def __init__(
        self, contents, selector_text=">", displayable_elements: tuple[str] = None
    ) -> None:
        self.selector_text = selector_text
        self.displayable = displayable_elements
        self.selector = Text(selector_text, align="right")
        match contents:
            case Coil() | AH() | Rating():
                attrs = contents.attributes
                if self.displayable:
                    attrs_treated = [
                        (attr, str(value))
                        for attr, value in attrs
                        if attr in self.displayable
                    ]
                else:
                    attrs_treated = [(attr, str(value)) for attr, value in attrs]
                cells = []
                for attr in attrs_treated:
                    name, value = attr
                    cells.append(self.selective_coloring(value, "center"))
                cells.insert(0, AttrMap(self.selector, "normal", "selector"))
            case _:
                cells = [Text(c, align="center") for c in contents]
        super().__init__(cells, dividechars=1)

    def selectable(self) -> bool:
        return True

    def keypress(self, size: KeypressSize, key: str) -> str | None:
        if key == "enter":
            self._emit("click")
        else:
            return super().keypress(size, key)

    def mouse_event(
        self,
        size: KeypressSize,
        event: str,
        button: int,
        col: int,
        row: int,
        focus: bool,
    ) -> bool | None:
        if event == "mouse press" and button == 1:
            self._emit("click")
        else:
            return super().mouse_event(size, event, button, col, row, focus)

    @staticmethod
    def selective_coloring(
        text: str, align: Literal["left", "center", "right"] = Align.LEFT
    ) -> Text:
        attr_map = "normal"
        if text in Stage:
            match Stage(text):
                case Stage.REJECTED:
                    attr_map = "norm_red"
                case Stage.REMOVED:
                    attr_map = "norm_red"
                case Stage.ACTIVE:
                    attr_map = "norm_green"
        return Text((attr_map, text), align=align)

    def render(self, size, focus=False):
        if focus:
            self.selector.set_text(("selector", self.selector_text))
        else:
            self.selector.set_text(("normal", " "))
        for cell in self.contents:
            cell: tuple[Widget, tuple]
            widget, options = cell
            widget: Text
            if focus:
                try:
                    widget_text, display_options = widget.get_text()
                    widget.set_text(("selector", widget_text))
                except:
                    pass
            else:
                try:
                    widget_text, display_options = widget.get_text()
                    widget_text, styling = self.selective_coloring(
                        widget_text
                    ).get_text()
                    widget.set_text((styling[0][0], widget_text))
                except:
                    pass
        return super().render(size, focus)
