from shared.version import DEV_VERSION, read_version


def test_read_version_returns_tag_or_dev_fallback():
    version = read_version()
    assert version == DEV_VERSION or version.startswith("v")
