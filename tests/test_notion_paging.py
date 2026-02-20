import menubar_notes_to_notion as appmod


class DummyResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_find_first_h1_id_paginates(monkeypatch):
    notion = appmod.NotionClient(token="x")

    calls = {"n": 0}

    def fake_get(url, headers):
        calls["n"] += 1
        if calls["n"] == 1:
            return DummyResp(200, {
                "results": [{"id": "a", "type": "paragraph"}],
                "has_more": True,
                "next_cursor": "CURSOR1"
            })
        return DummyResp(200, {
            "results": [{"id": "H1ID", "type": "heading_1"}],
            "has_more": False,
            "next_cursor": None
        })

    monkeypatch.setattr(appmod.requests, "get", fake_get)

    assert notion.find_first_h1_id("PAGE", page_size=1) == "H1ID"
    assert calls["n"] == 2


def test_list_children_ids_paginates(monkeypatch):
    notion = appmod.NotionClient(token="x")

    calls = {"n": 0}

    def fake_get(url, headers):
        calls["n"] += 1
        if calls["n"] == 1:
            return DummyResp(200, {
                "results": [{"id": "a"}, {"id": "b"}],
                "has_more": True,
                "next_cursor": "CURSOR1"
            })
        return DummyResp(200, {
            "results": [{"id": "c"}],
            "has_more": False,
            "next_cursor": None
        })

    monkeypatch.setattr(appmod.requests, "get", fake_get)

    assert notion.list_children_ids("PAGE", page_size=2) == ["a", "b", "c"]
    assert calls["n"] == 2


def test_append_children_returns_json(monkeypatch):
    notion = appmod.NotionClient(token="x")

    payload = {"results": [{"id": "abc", "type": "heading_2"}]}

    def fake_patch(url, headers, data):
        return DummyResp(200, payload)

    monkeypatch.setattr(appmod.requests, "patch", fake_patch)

    out = notion.append_children("PAGE", [{"object": "block"}], after_block_id=None)
    assert out == payload
