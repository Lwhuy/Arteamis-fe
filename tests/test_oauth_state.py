from open_notebook.domain.connectors import oauth_state


def test_state_roundtrip_is_single_use():
    s = oauth_state.create_state()
    assert isinstance(s, str) and len(s) >= 16
    assert oauth_state.consume_state(s) is True
    assert oauth_state.consume_state(s) is False  # already consumed


def test_unknown_state_rejected():
    assert oauth_state.consume_state("never-issued") is False
