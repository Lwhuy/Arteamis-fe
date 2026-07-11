from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.domain.notebook import Project, Source


@pytest.mark.asyncio
async def test_get_sources_filters_to_viewer_set():
    p = Project(id="notebook:p1", name="P", description="")
    rows = [
        {"source": {"id": "source:a", "title": "A"}},
        {"source": {"id": "source:b", "title": "B"}},
    ]
    with patch("open_notebook.domain.notebook.repo_query", new=AsyncMock(return_value=rows)):
        got = await p.get_sources(viewer_source_ids={"source:a"})
    assert [s.id for s in got] == ["source:a"]


@pytest.mark.asyncio
async def test_get_sources_no_filter_returns_all():
    p = Project(id="notebook:p1", name="P", description="")
    rows = [{"source": {"id": "source:a", "title": "A"}}]
    with patch("open_notebook.domain.notebook.repo_query", new=AsyncMock(return_value=rows)):
        got = await p.get_sources()
    assert [s.id for s in got] == ["source:a"]
