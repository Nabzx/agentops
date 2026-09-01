import ephor


def test_package_imports_and_has_a_version() -> None:
    assert ephor.__version__ == "0.0.1"
