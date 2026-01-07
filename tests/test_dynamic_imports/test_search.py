import pytest

from taskflows import dynamic_imports as search
from tests.test_dynamic_imports import pkg1
from tests.test_dynamic_imports.pkg1.mod1 import Base, find_instances1
from tests.test_dynamic_imports.pkg1.pkg2 import mod2


@pytest.mark.parametrize(
    "search_subpackages,result",
    [(True, ["tests.test_dynamic_imports.pkg1.mod1", "tests.test_dynamic_imports.pkg1.pkg2.mod2"]), (False, ["tests.test_dynamic_imports.pkg1.mod1"])],
)
def test_module_search(search_subpackages, result):
    module_names = [
        m.__name__
        for m in search.find_modules(pkg1, search_subpackages=search_subpackages)
    ]
    assert module_names == result


@pytest.mark.parametrize("base_class", [Base, "Base"])
@pytest.mark.parametrize("module", [mod2, "tests.test_dynamic_imports.pkg1.pkg2.mod2"])
def test_module_class_impl(base_class, module):
    class_impl = search.find_subclasses(
        base_class=base_class, search_in=module, names_only=True
    )
    assert class_impl == ["ClassImpl2"]


@pytest.mark.parametrize("base_class", [Base, "Base"])
@pytest.mark.parametrize("package", [pkg1, "tests.test_dynamic_imports.pkg1"])
@pytest.mark.parametrize(
    "search_subpackages,result",
    [(True, ["ClassImpl1", "ClassImpl2"]), (False, ["ClassImpl1"])],
)
def test_pkg_class_impl(base_class, package, search_subpackages, result):
    class_impl = search.find_subclasses(
        base_class=base_class,
        search_in=package,
        search_subpackages=search_subpackages,
        names_only=True,
    )
    assert class_impl == result


@pytest.mark.parametrize("module", [mod2, "tests.test_dynamic_imports.pkg1.pkg2.mod2"])
def test_module_find_instances(module):
    find_instances = search.find_instances(mod2.ClassImpl2, module)
    assert find_instances == [mod2.find_instances2]


@pytest.mark.parametrize("package", [pkg1, "tests.test_dynamic_imports.pkg1"])
@pytest.mark.parametrize("search_subpackages", [True, False])
def test_pkg_find_instances(package, search_subpackages):
    find_instances = search.find_instances(
        class_type=pkg1.mod1.ClassImpl1,
        search_in=package,
        search_subpackages=search_subpackages,
    )
    assert find_instances == [find_instances1]
