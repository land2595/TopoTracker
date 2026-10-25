import http.server
import io
import shutil
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import config, covers, db, importer, main

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "ISV_DIR", tmp_path / "isv")
    monkeypatch.setattr(config, "COVER_DIR", tmp_path / "covers")
    shutil.copytree(FIXTURES, tmp_path / "isv")
    for f in (tmp_path / "isv").iterdir():  # file "freschi": niente download
        f.touch()
    covers._failed.clear()
    main.app.state.no_scheduler = True
    with TestClient(main.app) as c:
        db.init()
        assert importer.run() is True
        yield c


def test_import_only_italian(client):
    s = client.get("/api/status").json()
    assert s["publications"] == 2
    assert s["issues"] == 7
    assert s["last_import_stats"].endswith("2 copertine")


def test_publication_sorted_naturally(client):
    pub = client.get("/api/publication", params={"code": "it/TL"}).json()
    assert [i["number"] for i in pub["issues"]] == ["1", "2", "10", "1000", "1500", "1500B"]
    assert pub["followed"] is True  # testata di default
    by_num = {i["number"]: i for i in pub["issues"]}
    assert by_num["1000"]["has_cover"] and by_num["1"]["has_cover"]
    assert not by_num["2"]["has_cover"]


def test_mark_read_any_order(client):
    code = "it/TL 1000"
    client.post("/api/read", json={"issuecodes": [code], "read": True})
    pub = client.get("/api/publication", params={"code": "it/TL"}).json()
    read = [i["number"] for i in pub["issues"] if i["read"]]
    assert read == ["1000"]  # il 1500 resta non letto
    client.post("/api/read", json={"issuecodes": [code], "read": False})
    pub = client.get("/api/publication", params={"code": "it/TL"}).json()
    assert pub["read_count"] == 0


def test_range_and_reads_survive_reimport(client):
    from app import importer

    r = client.post("/api/read-range", json={"pubcode": "it/TL", "start": 1500, "end": 1, "read": True}).json()
    assert r["count"] == 6
    assert importer.run() is True
    pub = client.get("/api/publication", params={"code": "it/TL"}).json()
    assert pub["read_count"] == 6


def test_search_and_follow(client):
    res = client.get("/api/search", params={"q": "almanacco 12"}).json()
    assert [r["issuecode"] for r in res] == ["it/AT  12"]
    res = client.get("/api/search", params={"q": "1000"}).json()
    assert res[0]["issuecode"] == "it/TL 1000"
    client.post("/api/follow", json={"pubcode": "it/AT", "follow": True})
    followed = client.get("/api/publications", params={"followed": True}).json()
    assert {p["code"] for p in followed} == {"it/TL", "it/AT"}


def test_backup_restore(client):
    client.post("/api/read", json={"issuecodes": ["it/TL 1500"], "read": True})
    data = client.get("/api/backup").json()
    client.post("/api/read", json={"issuecodes": ["it/TL 1500"], "read": False})
    r = client.post("/api/restore", json=data).json()
    assert r["reads"] == 1
    assert client.get("/api/status").json()["reads"] == 1


def test_cover_placeholder_and_cache(client, monkeypatch, tmp_path):
    from app import config

    # Nessuna copertina per il n. 2: segnaposto SVG.
    r = client.get("/api/cover", params={"code": "it/TL    2"})
    assert r.headers["content-type"].startswith("image/svg")

    buf = io.BytesIO()
    Image.new("RGB", (800, 1100), "red").save(buf, "JPEG")
    payload = buf.getvalue()
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(config, "COVER_URL_TEMPLATE", f"http://127.0.0.1:{srv.server_port}/{{sitecode}}/{{url}}")
    try:
        for _ in range(2):
            r = client.get("/api/cover", params={"code": "it/TL 1000"})
            assert r.headers["content-type"] == "image/jpeg"
            assert Image.open(io.BytesIO(r.content)).width == config.THUMB_WIDTH
        assert hits == ["/webusers/webusers/2010/01/it_tl_1000a_001.jpg"]  # scaricata una volta sola
    finally:
        srv.shutdown()


def test_isv_without_header(tmp_path):
    from app import importer

    p = tmp_path / "inducks_entryurl.isv"
    p.write_text("it/TL 1a^webusers^1^a.jpg\nit/TL 2a^webusers^1^b.jpg\n")
    rows = list(importer.read_isv(p, "entrycode"))
    assert [r["url"] for r in rows] == ["a.jpg", "b.jpg"]


def test_index_served(client):
    r = client.get("/")
    assert "TopoTracker" in r.text
    assert client.get("/static/app.js").status_code == 200
