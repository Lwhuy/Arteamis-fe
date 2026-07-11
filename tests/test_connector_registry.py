import pytest

from open_notebook.domain.connectors import get_connector, COMING_SOON


def test_get_unknown_provider_raises():
    with pytest.raises(ValueError):
        get_connector("does-not-exist")


def test_coming_soon_ids():
    ids = {c["provider"] for c in COMING_SOON}
    assert ids == {"sharepoint", "box", "dropbox", "confluence", "msteams", "gmail", "s3"}
