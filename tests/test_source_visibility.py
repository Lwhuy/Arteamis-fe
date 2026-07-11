from open_notebook.domain.notebook import Source


def test_source_defaults_to_private():
    s = Source(title="x")
    assert s.visibility == "private"


def test_source_accepts_company_visibility():
    s = Source(title="x", visibility="company")
    assert s.visibility == "company"
