import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, covers, db, importer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app):
    db.init()
    if not getattr(app.state, "no_scheduler", False):
        threading.Thread(target=importer.scheduler, daemon=True).start()
    yield


app = FastAPI(title="TopoTracker", lifespan=lifespan)


def inducks_issue_url(code):
    return "https://inducks.org/issue.php?c=" + quote_plus(code)


def issue_dict(row):
    d = dict(row)
    d["read"] = bool(d.pop("read_at", None))
    d["read_at"] = row["read_at"]
    d["has_cover"] = bool(d.pop("cover_url", None))
    d.pop("cover_site", None)
    d["inducks_url"] = inducks_issue_url(row["issuecode"])
    return d


ISSUE_COLS = "i.issuecode, i.pubcode, i.number, i.title, i.date, i.cover_site, i.cover_url, r.read_at"


@app.get("/api/status")
def status():
    with db.session() as conn:
        return {
            "import": dict(importer.state),
            "last_import": db.get_meta(conn, "last_import"),
            "last_import_stats": db.get_meta(conn, "last_import_stats"),
            "last_error": db.get_meta(conn, "last_error") or None,
            "publications": conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0],
            "issues": conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0],
            "reads": conn.execute("SELECT COUNT(*) FROM reads").fetchone()[0],
            "isv_url": config.INDUCKS_ISV_URL,
        }


class UpdateBody(BaseModel):
    force: bool = True


@app.post("/api/update")
def update(body: UpdateBody):
    started = importer.run_in_background(force_download=body.force)
    return {"started": started}


@app.get("/api/publications")
def publications(q: str = "", followed: bool = False):
    sql = """
        SELECT p.code, p.title, p.issue_count,
               (f.pubcode IS NOT NULL) AS followed,
               (SELECT COUNT(*) FROM reads r JOIN issues i ON i.issuecode = r.issuecode
                 WHERE i.pubcode = p.code) AS read_count,
               (SELECT i.issuecode FROM issues i WHERE i.pubcode = p.code AND i.cover_url IS NOT NULL
                 ORDER BY i.sort_num DESC, i.sort_rest DESC LIMIT 1) AS sample_issue
        FROM publications p LEFT JOIN followed f ON f.pubcode = p.code
        WHERE 1=1
    """
    args = []
    if followed:
        sql += " AND f.pubcode IS NOT NULL"
    if q:
        sql += " AND (p.title LIKE ? OR p.code LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY followed DESC, p.issue_count DESC, p.title"
    if not followed and not q:
        sql += " LIMIT 400"
    with db.session() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) | {"followed": bool(r["followed"])} for r in rows]


class FollowBody(BaseModel):
    pubcode: str
    follow: bool = True


@app.post("/api/follow")
def follow(body: FollowBody):
    with db.session() as conn:
        if body.follow:
            conn.execute("INSERT OR IGNORE INTO followed(pubcode) VALUES (?)", (body.pubcode,))
        else:
            conn.execute("DELETE FROM followed WHERE pubcode = ?", (body.pubcode,))
    return {"ok": True}


@app.get("/api/publication")
def publication(code: str):
    with db.session() as conn:
        p = conn.execute("""SELECT p.*, (f.pubcode IS NOT NULL) AS followed FROM publications p
                            LEFT JOIN followed f ON f.pubcode = p.code WHERE p.code = ?""", (code,)).fetchone()
        if not p:
            raise HTTPException(404, "Testata non trovata")
        rows = conn.execute(f"""SELECT {ISSUE_COLS} FROM issues i LEFT JOIN reads r ON r.issuecode = i.issuecode
                                WHERE i.pubcode = ? ORDER BY i.sort_num, i.sort_rest, i.number""", (code,)).fetchall()
    issues = [issue_dict(r) for r in rows]
    return {
        "code": p["code"], "title": p["title"], "followed": bool(p["followed"]),
        "issue_count": len(issues), "read_count": sum(i["read"] for i in issues),
        "inducks_url": "https://inducks.org/publication.php?c=" + quote_plus(code),
        "issues": issues,
    }


@app.get("/api/search")
def search(q: str = Query(..., min_length=1)):
    """Cerca un numero (es. "1000" o "topolino 1000") nelle testate, prima quelle seguite."""
    q = q.strip()
    words = q.split()
    number = words[-1] if words and any(ch.isdigit() for ch in words[-1]) else None
    text = " ".join(words[:-1]) if number else q
    sql = f"""SELECT {ISSUE_COLS}, p.title AS pubtitle, (f.pubcode IS NOT NULL) AS followed
              FROM issues i JOIN publications p ON p.code = i.pubcode
              LEFT JOIN reads r ON r.issuecode = i.issuecode
              LEFT JOIN followed f ON f.pubcode = i.pubcode WHERE 1=1"""
    args = []
    if number:
        sql += " AND (i.number = ? COLLATE NOCASE OR i.issuecode = ? COLLATE NOCASE)"
        args += [number, q]
    if text:
        sql += " AND (p.title LIKE ? OR p.code LIKE ? OR i.title LIKE ?)"
        args += [f"%{text}%", f"%{text}%", f"%{text}%"]
    sql += " ORDER BY followed DESC, p.issue_count DESC LIMIT 60"
    with db.session() as conn:
        rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = issue_dict(r)
        d["pubtitle"] = r["pubtitle"]
        d["followed"] = bool(r["followed"])
        out.append(d)
    return out


class ReadBody(BaseModel):
    issuecodes: list[str]
    read: bool = True


def _set_read(conn, codes, read):
    if read:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.executemany("INSERT OR IGNORE INTO reads(issuecode, read_at) VALUES (?, ?)", [(c, now) for c in codes])
    else:
        conn.executemany("DELETE FROM reads WHERE issuecode = ?", [(c,) for c in codes])


@app.post("/api/read")
def mark_read(body: ReadBody):
    with db.session() as conn:
        _set_read(conn, body.issuecodes, body.read)
    return {"ok": True, "count": len(body.issuecodes)}


class RangeBody(BaseModel):
    pubcode: str
    start: int
    end: int
    read: bool = True


@app.post("/api/read-range")
def mark_range(body: RangeBody):
    lo, hi = sorted((body.start, body.end))
    with db.session() as conn:
        codes = [r[0] for r in conn.execute(
            "SELECT issuecode FROM issues WHERE pubcode = ? AND sort_num BETWEEN ? AND ?", (body.pubcode, lo, hi))]
        _set_read(conn, codes, body.read)
    return {"ok": True, "count": len(codes)}


PLACEHOLDER = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 400">
<rect width="300" height="400" fill="#f6e7c1"/><rect x="12" y="12" width="276" height="376" fill="none"
stroke="#d4001a" stroke-width="6" stroke-dasharray="14 10"/>
<circle cx="110" cy="150" r="34" fill="#1d1d1b"/><circle cx="190" cy="150" r="34" fill="#1d1d1b"/>
<circle cx="150" cy="205" r="52" fill="#1d1d1b"/>
<text x="150" y="310" font-family="sans-serif" font-size="26" font-weight="700" text-anchor="middle"
fill="#d4001a">Copertina</text><text x="150" y="342" font-family="sans-serif" font-size="22"
text-anchor="middle" fill="#d4001a">non disponibile</text></svg>"""


@app.get("/api/cover")
def cover(code: str):
    with db.session() as conn:
        row = conn.execute("SELECT cover_site, cover_url FROM issues WHERE issuecode = ?", (code,)).fetchone()
    path = covers.get(row["cover_site"], row["cover_url"]) if row and row["cover_url"] else None
    if path is None:
        return Response(PLACEHOLDER, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "max-age=2592000"})


@app.get("/api/diagnosi-copertine")
def cover_diagnosis(code: str = ""):
    """Aiuta a capire perché le copertine non arrivano: da aprire nel browser."""
    with db.session() as conn:
        with_cover = conn.execute("SELECT COUNT(*) FROM issues WHERE cover_url IS NOT NULL").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
        if code:
            row = conn.execute("SELECT issuecode, cover_site, cover_url FROM issues WHERE issuecode = ?",
                               (code,)).fetchone()
        else:
            row = conn.execute("""SELECT issuecode, cover_site, cover_url FROM issues WHERE cover_url IS NOT NULL
                                  ORDER BY (pubcode = 'it/TL') DESC, sort_num DESC LIMIT 1""").fetchone()
        sample_urls = [dict(r) for r in conn.execute(
            "SELECT issuecode, cover_site, cover_url FROM issues WHERE cover_url IS NOT NULL LIMIT 5")]
    out = {"numeri": total, "numeri_con_copertina": with_cover, "esempi": sample_urls}
    if row and row["cover_url"]:
        out["prova"] = {"numero": row["issuecode"], "sitecode": row["cover_site"], "url": row["cover_url"],
                        "tentativi": covers.diagnose(row["cover_site"], row["cover_url"])}
    return out


@app.get("/api/stats")
def stats():
    with db.session() as conn:
        total_read = conn.execute("SELECT COUNT(*) FROM reads").fetchone()[0]
        per_pub = conn.execute("""SELECT p.code, p.title, p.issue_count, COUNT(r.issuecode) AS read_count
                                  FROM publications p JOIN issues i ON i.pubcode = p.code
                                  JOIN reads r ON r.issuecode = i.issuecode
                                  GROUP BY p.code ORDER BY read_count DESC""").fetchall()
        recent = conn.execute(f"""SELECT {ISSUE_COLS}, p.title AS pubtitle FROM reads r
                                  JOIN issues i ON i.issuecode = r.issuecode
                                  JOIN publications p ON p.code = i.pubcode
                                  ORDER BY r.read_at DESC LIMIT 24""").fetchall()
    return {
        "total_read": total_read,
        "per_publication": [dict(r) for r in per_pub],
        "recent": [issue_dict(r) | {"pubtitle": r["pubtitle"]} for r in recent],
    }


@app.get("/api/backup")
def backup():
    with db.session() as conn:
        data = {
            "app": "TopoTracker", "version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reads": [dict(r) for r in conn.execute("SELECT issuecode, read_at FROM reads ORDER BY issuecode")],
            "followed": [r[0] for r in conn.execute("SELECT pubcode FROM followed")],
        }
    name = f"topotracker-backup-{datetime.now().strftime('%Y%m%d')}.json"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{name}"'})


class RestoreBody(BaseModel):
    reads: list[dict]
    followed: list[str] = []


@app.post("/api/restore")
def restore(body: RestoreBody):
    with db.session() as conn:
        conn.executemany("INSERT OR REPLACE INTO reads(issuecode, read_at) VALUES (?, ?)",
                         [(r["issuecode"], r.get("read_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"))
                          for r in body.reads if r.get("issuecode")])
        conn.executemany("INSERT OR IGNORE INTO followed(pubcode) VALUES (?)", [(c,) for c in body.followed])
    return {"ok": True, "reads": len(body.reads), "followed": len(body.followed)}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
