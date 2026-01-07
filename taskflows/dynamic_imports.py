import importlib
import importlib.util
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
    package: Union[ModuleType, str],
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
    if isinstance(package, str):
        # import the package.
        package = import_module(package)
    if package.__package__ != package.__name__:
        # `package` is a module, not a package.
        return [package] if not names_only else [package.__name__]
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
    base_class: Union[ModuleType, str],
    search_in: Union[ModuleType, str],
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
    subclasses = []
    for module in find_modules(search_in, search_subpackages, names_only):
        if isinstance(module, str):
            if names_only:
                # check if module_name is a path to a Python file.
                if (module_path := Path(module)).is_file():
                    # read python file path
                    module_classes = pyclbr.readmodule(
                        module_path.stem, path=module_path.parent
                    )
                else:
                    # read installed module path.
                    module_classes = pyclbr.readmodule(module)
                base_class = (
                    base_class if isinstance(base_class, str) else base_class.__name__
                )
                subclasses += [
                    cls_name
                    for cls_name, cls_obj in module_classes.items()
                    if any(getattr(s, "name", s) == base_class for s in cls_obj.super)
                ]
                continue
            module = import_module(module)
        # parse the imported module.
        subclasses += _extract_subclasses_from_module(module, base_class, names_only)
    return subclasses


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
    if isinstance(search_in, (Path, str)):
        search_in = import_module(search_in)
    instances = [
        c
        for module in find_modules(search_in, search_subpackages)
        for c in module.__dict__.values()
        if isinstance(c, class_type)
    ]
    return list({id(i): i for i in instances}.values())


def _extract_subclasses_from_module(module: ModuleType, base_class: Union[Type, str], names_only: bool) -> List[Union[str, Type]]:
    """Extract subclasses of base_class from a module.
    
    Args:
        module: Module to search in
        base_class: Base class to search for subclasses of
        names_only: Whether to return class names or class objects
        
    Returns:
        List of subclass names or objects
    """
    if isinstance(base_class, str):
        subclass_objects = [
            obj
            for obj in module.__dict__.values()
            if base_class in [c.__name__ for c in getattr(obj, "__bases__", [])]
        ]
    else:
        subclass_objects = [
            obj
            for obj in module.__dict__.values()
            if base_class in getattr(obj, "__bases__", [])
        ]
    
    return [c.__name__ for c in subclass_objects] if names_only else subclass_objects
