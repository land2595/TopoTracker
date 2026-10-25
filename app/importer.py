"""Importa le testate italiane dai dump ufficiali di Inducks (file .isv).

I file ISV hanno una riga di intestazione con i nomi dei campi e i valori
separati da "^". Vengono scaricati una volta in DATA_DIR/isv e riletti in
streaming, tenendo solo le righe del paese configurato (default: Italia).
Se il download automatico non funziona, si possono copiare a mano i file
in DATA_DIR/isv: l'importazione userà quelli.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import config, db

log = logging.getLogger("topotracker.import")

FILES = ["inducks_publication.isv", "inducks_issue.isv", "inducks_entryurl.isv", "inducks_entry.isv"]

# Ordine dei campi usato se un file non avesse la riga di intestazione.
DEFAULT_COLUMNS = {
    "inducks_publication.isv": ["publicationcode", "countrycode", "languagecode", "title", "size", "publicationcomment",
                                "circulation", "numbersarefake", "error", "locked", "inxforbidden", "inputfilecode",
                                "maintenanceteamcode"],
    "inducks_issue.isv": ["issuecode", "issuerangecode", "publicationcode", "issuenumber", "title", "size", "pages",
                          "price", "printrun", "attached", "oldestdate", "fullyindexed", "issuecomment", "error",
                          "filledoldestdate", "locked", "inxforbidden", "inputfilecode", "maintenanceteamcode"],
    "inducks_entryurl.isv": ["entrycode", "sitecode", "pagenumber", "url"],
    "inducks_entry.isv": ["entrycode", "issuecode", "storyversioncode", "languagecode", "includedinentrycode",
                          "position", "printedcode", "guessedcode", "title", "reallytitle", "printedhero", "changes",
                          "cut", "minorcolouring", "printedcomment", "typeset", "printedissuecomment", "entrycomment",
                          "error", "hide", "zapped", "inputfilecode", "maintenanceteamcode"],
}

_lock = threading.Lock()
state = {"running": False, "step": None, "error": None, "started_at": None}
_last_attempt = 0.0


def read_isv(path: Path, required: str):
    """Restituisce le righe di un file ISV come dizionari."""
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        first = f.readline().rstrip("\r\n")
        fields = first.split("^")
        if required in fields:
            header = fields
            pending = None
        else:
            header = DEFAULT_COLUMNS[path.name]
            pending = first
        lines = f if pending is None else _prepend(pending, f)
        for line in lines:
            line = line.rstrip("\r\n")
            if not line:
                continue
            yield dict(zip(header, line.split("^")))


def _prepend(first, rest):
    yield first
    yield from rest


def download(force: bool = False):
    config.ISV_DIR.mkdir(parents=True, exist_ok=True)
    max_age = max(config.UPDATE_INTERVAL_DAYS, 1) * 86400
    with httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=httpx.Timeout(60, read=300),
                      follow_redirects=True) as client:
        for name in FILES:
            dest = config.ISV_DIR / name
            if dest.exists() and not force and time.time() - dest.stat().st_mtime < max_age:
                log.info("Uso %s già scaricato", name)
                continue
            state["step"] = f"Scarico {name}"
            url = config.INDUCKS_ISV_URL + name
            log.info("Scarico %s", url)
            tmp = dest.with_suffix(".part")
            try:
                with client.stream("GET", url) as r:
                    r.raise_for_status()
                    ctype = r.headers.get("content-type", "")
                    if "html" in ctype:
                        raise RuntimeError(f"{url} ha restituito una pagina HTML invece del file dati")
                    with open(tmp, "wb") as out:
                        for chunk in r.iter_bytes(1 << 20):
                            out.write(chunk)
                tmp.replace(dest)
            except Exception:
                tmp.unlink(missing_ok=True)
                if dest.exists():
                    log.exception("Download di %s fallito, uso la copia precedente", name)
                else:
                    raise


def build(conn):
    """Legge gli ISV e riscrive testate e numeri. Le letture restano intatte."""
    country = config.COUNTRY
    prefix = country + "/"

    state["step"] = "Leggo le testate"
    pubs = {}
    for row in read_isv(config.ISV_DIR / "inducks_publication.isv", "publicationcode"):
        code = row.get("publicationcode", "")
        if row.get("countrycode") == country or code.startswith(prefix):
            pubs[code] = (row.get("title") or code).strip()

    state["step"] = "Leggo i numeri"
    issues = {}
    for row in read_isv(config.ISV_DIR / "inducks_issue.isv", "issuecode"):
        pub = row.get("publicationcode", "")
        if pub not in pubs:
            continue
        number = (row.get("issuenumber") or "").strip()
        issues[row["issuecode"]] = {
            "pub": pub,
            "number": number,
            "title": (row.get("title") or "").strip(),
            "date": (row.get("oldestdate") or row.get("filledoldestdate") or "").strip(),
        }

    # Prima gli URL delle immagini (pochi), poi le storie solo per quegli URL:
    # così non teniamo in memoria tutto inducks_entry.
    state["step"] = "Leggo gli indirizzi delle copertine"
    urls = {}
    for row in read_isv(config.ISV_DIR / "inducks_entryurl.isv", "entrycode"):
        code = row.get("entrycode", "")
        if not code.startswith(prefix) or not row.get("url"):
            continue
        try:
            page = int(row.get("pagenumber") or 0)
        except ValueError:
            page = 0
        prev = urls.get(code)
        if prev is None or page < prev[0]:
            urls[code] = (page, row.get("sitecode", ""), row["url"])

    state["step"] = "Abbino le copertine ai numeri"
    covers = {}
    for row in read_isv(config.ISV_DIR / "inducks_entry.isv", "entrycode"):
        code = row.get("entrycode", "")
        if code not in urls:
            continue
        issuecode = row.get("issuecode", "")
        if issuecode not in issues:
            continue
        key = (row.get("position") or "", urls[code][0])
        prev = covers.get(issuecode)
        if prev is None or key < prev[0]:
            covers[issuecode] = (key, urls[code][1], urls[code][2])

    state["step"] = "Salvo nel database"
    counts = {}
    for i in issues.values():
        counts[i["pub"]] = counts.get(i["pub"], 0) + 1
    conn.execute("DELETE FROM issues")
    conn.execute("DELETE FROM publications")
    conn.executemany("INSERT INTO publications(code, title, issue_count) VALUES (?, ?, ?)",
                     [(c, t, counts.get(c, 0)) for c, t in pubs.items()])
    rows = []
    for code, i in issues.items():
        n, rest = db.sort_key(i["number"])
        cov = covers.get(code)
        rows.append((code, i["pub"], i["number"], i["title"], i["date"], n, rest,
                     cov[1] if cov else None, cov[2] if cov else None))
    conn.executemany("INSERT INTO issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    db.set_meta(conn, "last_import", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    db.set_meta(conn, "last_import_stats", f"{len(pubs)} testate, {len(issues)} numeri, {len(covers)} copertine")
    log.info("Import completato: %d testate, %d numeri, %d copertine", len(pubs), len(issues), len(covers))
    return {"publications": len(pubs), "issues": len(issues), "covers": len(covers)}


def run(force_download: bool = False):
    global _last_attempt
    if not _lock.acquire(blocking=False):
        return False
    _last_attempt = time.time()
    state.update(running=True, error=None, started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    try:
        download(force=force_download)
        with db.session() as conn:
            build(conn)
            db.set_meta(conn, "last_error", "")
        return True
    except Exception as e:  # noqa: BLE001 - lo mostriamo nell'interfaccia
        log.exception("Importazione fallita")
        state["error"] = str(e)
        with db.session() as conn:
            db.set_meta(conn, "last_error", str(e))
        return False
    finally:
        state.update(running=False, step=None)
        _lock.release()


def run_in_background(force_download: bool = False):
    if state["running"]:
        return False
    threading.Thread(target=run, kwargs={"force_download": force_download}, daemon=True).start()
    return True


def scheduler():
    """Aggiorna i dati periodicamente in un thread separato."""
    while True:
        try:
            with db.session() as conn:
                last = db.get_meta(conn, "last_import")
                empty = conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == 0
            due = False
            if empty and config.AUTO_IMPORT:
                # Dopo un errore riprova ogni 6 ore, non a raffica.
                due = not state["error"] or time.time() - _last_attempt > 6 * 3600
            elif last and config.UPDATE_INTERVAL_DAYS > 0:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
                due = age > config.UPDATE_INTERVAL_DAYS * 86400
            if due:
                run(force_download=not empty)
        except Exception:  # noqa: BLE001
            log.exception("Errore nello scheduler")
        time.sleep(3600)
