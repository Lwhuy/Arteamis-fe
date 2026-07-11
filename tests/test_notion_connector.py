from open_notebook.domain.connectors.notion import NotionConnector


def test_authorize_url_shape(monkeypatch):
    monkeypatch.setenv("NOTION_CLIENT_ID", "cid")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "sec")
    url = NotionConnector().authorize_url("ST", "http://localhost:5055/api/connectors/notion/callback")
    assert "api.notion.com/v1/oauth/authorize" in url
    assert "owner=user" in url
    assert "state=ST" in url


def test_blocks_to_markdown_renders_headings_and_paragraphs():
    blocks = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Title"}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hello world"}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "point"}]}},
    ]
    md = NotionConnector()._blocks_to_markdown(blocks)
    assert "# Title" in md
    assert "Hello world" in md
    assert "- point" in md
