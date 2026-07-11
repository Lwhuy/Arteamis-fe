import pytest

from open_notebook.domain.connection import Connection


def test_prepare_save_encrypts_both_tokens(monkeypatch):
    monkeypatch.setattr(
        "open_notebook.domain.connection.encrypt_value", lambda v: f"enc({v})"
    )
    conn = Connection(
        provider="gdrive",
        account_label="a@b.com",
        access_token="ACCESS",
        refresh_token="REFRESH",
        scopes=["drive.readonly"],
    )
    data = conn._prepare_save_data()
    assert data["access_token"] == "enc(ACCESS)"
    assert data["refresh_token"] == "enc(REFRESH)"
    assert data["provider"] == "gdrive"
    assert data["workspace"] is None  # nullable, unset now


def test_from_db_row_decrypts_tokens(monkeypatch):
    monkeypatch.setattr(
        "open_notebook.domain.connection.decrypt_value", lambda v: v.replace("enc(", "").rstrip(")")
    )
    row = {
        "id": "connection:1",
        "provider": "notion",
        "account_label": "My WS",
        "access_token": "enc(TOK)",
        "refresh_token": None,
        "scopes": [],
        "status": "connected",
    }
    conn = Connection._from_db_row(row)
    assert conn.access_token.get_secret_value() == "TOK"
    assert conn.refresh_token is None
