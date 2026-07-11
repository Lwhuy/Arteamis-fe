from open_notebook.domain.connectors import oauth_state


def test_state_roundtrip_is_single_use():
    s = oauth_state.create_state("workspace:w1", "user:u1")
    assert isinstance(s, str) and len(s) >= 16
    assert oauth_state.consume_state(s) == ("workspace:w1", "user:u1")
    assert oauth_state.consume_state(s) is None  # already consumed


def test_unknown_state_rejected():
    assert oauth_state.consume_state("never-issued") is None


def test_state_roundtrip_preserves_distinct_workspace_and_user():
    s = oauth_state.create_state("workspace:acme", "user:alice")
    workspace_id, user_id = oauth_state.consume_state(s)
    assert workspace_id == "workspace:acme"
    assert user_id == "user:alice"
