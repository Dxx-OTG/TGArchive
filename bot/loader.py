import importlib
import pkgutil
from pathlib import Path

from aiogram import Router

MODULES_PACKAGE = "bot.modules"


def discover_routers() -> list[Router]:
    """Import every module in bot/modules/ and collect its `router` attribute.
    Adding a feature = adding a file here, no edits to main.py needed."""
    routers: list[Router] = []

    package = importlib.import_module(MODULES_PACKAGE)
    package_path = Path(package.__file__).parent

    for module_info in sorted(pkgutil.iter_modules([str(package_path)]), key=lambda m: m.name):
        if module_info.name.startswith("_"):
            continue

        module = importlib.import_module(f"{MODULES_PACKAGE}.{module_info.name}")
        router = getattr(module, "router", None)
        if router is None:
            continue

        routers.append(router)

    return routers
