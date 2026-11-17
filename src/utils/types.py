import discord
import inspect

from dataclasses import dataclass
from time import perf_counter

from utils.log import debug_log

from .config import settings


class NiceBytes(bytes):
    def __repr__(self):
        if len(self) <= 40:
            return super().__repr__()
        else:
            return f"{super().__repr__()[:15]}... {super().__repr__()[-15:]} (len={len(self)})"


@dataclass
class MediaItem:
    name: str
    data: bytes
    url: str
    path: str = None
    catalog: str = None
    category: str = None
    category_schema_data: dict = None
    upload: bool = False
    overwrite_risk: bool = False
    overwrite_confirmed: bool = False
    upload_success: bool = False
    catalog_success: bool = False

    def __post_init__(self):
        if not isinstance(self.data, NiceBytes):
            self.data = NiceBytes(self.data)

        if self.path is None:
            self.path = f"{self.name}"

    @property
    def public_url(self) -> str:
        if self.path is None:
            return None
        return f"{settings.bucket_public_url}/{self.path}"

    @property
    def upload_configured(self) -> bool:
        return self.upload and self.path is not None

    @property
    def upload_ready(self) -> bool:
        return self.upload and self.path is not None and (not self.overwrite_risk or self.overwrite_confirmed)

    @property
    def catalog_configured(self) -> bool:
        return self.catalog is not None and self.category is not None

    @property
    def catalog_ready(self) -> bool:
        return not self.catalog_configured or (self.catalog_configured and self.category_schema_data is not None)


class Stage:
    def __init__(
            self, name: str = None, 
            container_class: type[discord.ui.Container] = None, container_args: dict = {},
            controls_class: type = None, controls_args: dict = {},
            item_filter: callable = lambda item: True
        ):
        self.name = name
        self.container_class = container_class
        self.container_args = container_args
        self.controls_class = controls_class
        self.controls_args = controls_args
        self.item_filter = item_filter


class PostInitMeta(type):
    def __call__(cls, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        if hasattr(instance, "__post_init__"):
            instance.__post_init__()
        return instance


class Timer:
    _timers: dict[tuple[str, str], float] = {}

    @classmethod
    def start(cls):
        caller = inspect.stack()[1]

        cls._timers[(caller.filename, caller.function)] = perf_counter()

    @classmethod
    def stop(cls):
        end_time = perf_counter()

        caller = inspect.stack()[1]
        start_time = cls._timers.pop((caller.filename, caller.function), None)

        if start_time is not None:
            total = end_time - start_time
            debug_log(f"[{caller.function}] executed in {total:.4f}s", 2)