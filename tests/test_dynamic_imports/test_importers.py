from pathlib import Path

import pytest

from dynamic_imports import dynamic_imports

module_path = Path(__file__).parent.joinpath("pkg1", "mod1.py")


def test_import_module_from_file_path():
    module = dynamic_imports.import_module(module_path)
    assert module.__name__.split(".")[-1] == "mod1"


def test_load_module_from_name():
    module = dynamic_imports.import_module("dynamic_imports")
    assert module.__name__ == "dynamic_imports"


def test_import_module_attr():
    function = dynamic_imports.import_module_attr(module_path, "a_function")
    assert function.__name__ == "a_function"


def test_import_module_attr_error():
    with pytest.raises(AttributeError):
        dynamic_imports.import_module_attr(module_path, "not_a_function")
