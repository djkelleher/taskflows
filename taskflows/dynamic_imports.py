import importlib
import importlib.util
import inspect
import pkgutil
import pyclbr
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, List, Type, Union


@lru_cache
def import_module(name_or_path: Union[Path, str]) -> ModuleType:
    """Import a module.

    Args:
        name_or_path (Union[Path, str]): Name of module (e.g. `my_package.my_module`) or path to module file (e.g. `/home/user/my_package/my_module.py`)

    Returns:
        ModuleType: The imported module.
    """
    if (path := Path(name_or_path)).suffix == ".py":
        # import module from file path.
        module_spec = importlib.util.spec_from_file_location(
            path.stem, str(name_or_path)
        )
        if module_spec is None or module_spec.loader is None:
            raise ImportError(f"Could not import module from path: {path}")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module
    # import installed module.
    return importlib.import_module(str(name_or_path))


def import_module_attr(module_name_or_path: Union[Path, str], attr_name: str) -> Any:
    """Get reference to a module's attribute (e.g. a function or class), importing the module if needed.

    Args:
        module_name_or_path (Union[Path, str]): Name of module (e.g. `requests`) or path to module file (e.g. `/home/user/my_package/my_module.py`)
        attr_name (str): Name of the attribute.

    Returns:
        Any: The attribute.
    """
    module = import_module(module_name_or_path)
    if not hasattr(module, attr_name):
        raise AttributeError(
            f"Could not load {attr_name} from module {module_name_or_path}!"
        )
    return getattr(module, attr_name)


def find_modules(
    package: Union[ModuleType, Path, str],
    search_subpackages: bool = True,
    names_only: bool = False,
) -> Union[List[str], List[ModuleType]]:
    """Find all modules in a package or nested packages.

    Args:
        package (Union[ModuleType, str]): Top-level package where search should begin.
        search_subpackages (bool, optional): Search sub-packages within `package`. Defaults to True.
        names_only (bool, optional): Return module names instead of imported modules. Defaults to False.

    Returns:
        Union[List[str], List[ModuleType]]: The discovered modules or module names.
    """
    if not isinstance(package, ModuleType):
        # import the package.
        package = import_module(package)
    if package.__package__ != package.__name__:
        # `package` is a module, not a package.
        if names_only:
            return [package.__name__]
        return [package]
    # search for module names.
    searcher = pkgutil.walk_packages if search_subpackages else pkgutil.iter_modules
    module_names = [
        name
        for _, name, ispkg in searcher(package.__path__, f"{package.__name__}.")
        if not ispkg
    ]
    if names_only:
        return module_names
    # import the discovered modules.
    return [import_module(name) for name in module_names]


def find_subclasses(
    base_class: Union[Type, str],
    search_in: Union[ModuleType, Path, str],
    search_subpackages: bool = True,
    names_only: bool = False,
) -> Union[List[str], List[Type]]:
    """Find all subclasses of a base class within a module or package.

    Args:
        base_class (Union[ModuleType, str]): The base class whose subclasses should be searched for.
        search_in (Union[ModuleType, str]): The module or package to search in.
        search_subpackages (bool, optional): Search sub-packages within `package`. Defaults to True.
        names_only (bool, optional): Return class names instead of imported classes. Defaults to False.

    Returns:
        Union[List[str], List[Type]]: The discovered subclasses or class names.
    """
    subclasses: list[Any] = []
    base_class_name = base_class if isinstance(base_class, str) else base_class.__name__
    if (
        names_only
        and not isinstance(search_in, ModuleType)
        and (module_path := Path(search_in)).suffix == ".py"
    ):
        module_classes = pyclbr.readmodule(
            module_path.stem,
            path=[str(module_path.parent)],
        )
        return _extract_static_subclass_names(module_classes, base_class_name)

    static_names = names_only and not isinstance(search_in, ModuleType)
    for module in find_modules(search_in, search_subpackages, static_names):
        if isinstance(module, str):
            if names_only:
                module_classes = pyclbr.readmodule(module)
                subclasses += _extract_static_subclass_names(
                    module_classes,
                    base_class_name,
                )
                continue
            module = import_module(module)
        # parse the imported module.
        subclasses += _extract_subclasses_from_module(module, base_class, names_only)
    return _dedupe_discovered(subclasses, names_only=names_only)


def find_instances(
    class_type: Type,
    search_in: Union[ModuleType, str],
    search_subpackages: bool = True,
) -> List[Any]:
    """Find all instances of a class within a package or module.

    Args:
        class_type (Type): The class whose instances should be searched for.
        search_in (Union[ModuleType, str]): The package or module to search in.
        search_subpackages (bool, optional): Search sub-packages within `package`. Defaults to True.

    Returns:
        List[Any]: The discovered class instances.
    """
    if not isinstance(search_in, ModuleType):
        search_in = import_module(search_in)
    instances = [
        c
        for module in find_modules(search_in, search_subpackages)
        for c in module.__dict__.values()
        if isinstance(c, class_type)
    ]
    return list({id(i): i for i in instances}.values())


def _is_subclass_of(obj: Any, base_class: Union[Type, str]) -> bool:
    """Return True when obj is a non-base subclass of base_class."""
    if not inspect.isclass(obj):
        return False
    if isinstance(base_class, str):
        return obj.__name__ != base_class and base_class in [
            cls.__name__ for cls in obj.__mro__[1:]
        ]
    return obj is not base_class and issubclass(obj, base_class)


def _extract_subclasses_from_module(
    module: ModuleType, base_class: Union[Type, str], names_only: bool
) -> List[Union[str, Type]]:
    """Extract subclasses of base_class from a module.

    Args:
        module: Module to search in
        base_class: Base class to search for subclasses of
        names_only: Whether to return class names or class objects

    Returns:
        List of subclass names or objects
    """
    subclass_objects = [
        obj for obj in module.__dict__.values() if _is_subclass_of(obj, base_class)
    ]
    return [c.__name__ for c in subclass_objects] if names_only else subclass_objects


def _extract_static_subclass_names(
    module_classes: dict[str, pyclbr.Class],
    base_class_name: str,
) -> list[str]:
    """Extract subclass names from pyclbr metadata, including indirect subclasses."""

    def inherits_from(class_name: str, seen: set[str] | None = None) -> bool:
        seen = seen or set()
        if class_name in seen:
            return False
        seen.add(class_name)

        class_info = module_classes.get(class_name)
        if class_info is None:
            return False

        for parent in class_info.super or []:
            parent_name = getattr(parent, "name", parent)
            if parent_name == base_class_name:
                return True
            if isinstance(parent_name, str) and inherits_from(parent_name, seen):
                return True
        return False

    return [
        class_name
        for class_name in module_classes
        if class_name != base_class_name and inherits_from(class_name)
    ]


def _dedupe_discovered(discovered: list[Any], names_only: bool) -> list[Any]:
    """Deduplicate discovered classes or names while preserving discovery order."""
    seen = set()
    deduped = []
    for item in discovered:
        key = item if names_only else id(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
