"""Copertine: scaricate da Inducks solo quando servono e salvate su disco.

Ogni copertina viene richiesta al massimo una volta (poi si usa la cache),
con poche richieste in parallelo per non pesare sul sito.
"""

import hashlib
import io
import shutil
import logging
import threading
import time

import httpx
from PIL import Image

from . import config

log = logging.getLogger("topotracker.covers")

_sem = threading.Semaphore(3)
_client = None
_client_lock = threading.Lock()
# Copertine che non si sono potute scaricare: non riprovare per un po'.
_failed: dict[str, float] = {}
RETRY_AFTER = 1800
# Indice del modello di indirizzo che ha funzionato l'ultima volta.
_preferred = 0


def _http():
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                headers={"User-Agent": config.USER_AGENT, "Referer": "https://inducks.org/",
                         "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"},
                timeout=30, follow_redirects=True)
        return _client


def candidate_urls(sitecode: str, url: str):
    templates = config.COVER_URL_TEMPLATES
    order = [_preferred] + [i for i in range(len(templates)) if i != _preferred]
    seen = []
    for i in order:
        if i < len(templates):
            u = templates[i].format(sitecode=sitecode or "", url=(url or "").lstrip("/"))
            if u not in seen:
                seen.append(u)
                yield i, u


# Le copertine della prima versione erano miniature ritagliate: la cache nuova sta in
# una sottocartella separata e quella vecchia viene cancellata all'avvio.
CACHE_VERSION = "v2"


def cache_path(sitecode: str, url: str):
    h = hashlib.sha1(f"{sitecode}/{url}".encode()).hexdigest()
    return config.COVER_DIR / CACHE_VERSION / h[:2] / f"{h}.jpg"


def clean_old_cache():
    if not config.COVER_DIR.exists():
        return
    for d in config.COVER_DIR.iterdir():
        if d.is_dir() and d.name != CACHE_VERSION:
            shutil.rmtree(d, ignore_errors=True)


def fetch_image(src: str):
    """Scarica un indirizzo e restituisce l'immagine, oppure solleva un errore leggibile."""
    r = _http().get(src)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if "html" in ctype or "text" in ctype:
        raise ValueError(f"risposta {ctype or 'senza tipo'} invece di un'immagine")
    img = Image.open(io.BytesIO(r.content))
    img.load()
    # Una copertina è verticale: un'immagine larga e piccola è una miniatura ritagliata.
    if img.width > img.height * 1.15 and img.width < 300:
        raise ValueError(f"miniatura ritagliata {img.width}x{img.height}, non la copertina intera")
    return img


def get(sitecode: str, url: str):
    """Percorso della miniatura in cache, oppure None se non disponibile."""
    global _preferred
    path = cache_path(sitecode, url)
    if path.exists():
        return path
    key = f"{sitecode}/{url}"
    if time.time() - _failed.get(key, 0) < RETRY_AFTER:
        return None
    with _sem:
        if path.exists():
            return path
        errors = []
        for i, src in candidate_urls(sitecode, url):
            try:
                img = fetch_image(src)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{src}: {e}")
                continue
            img = img.convert("RGB")
            if img.width > config.THUMB_WIDTH:
                img = img.resize((config.THUMB_WIDTH, round(img.height * config.THUMB_WIDTH / img.width)),
                                 Image.LANCZOS)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            img.save(tmp, "JPEG", quality=85, optimize=True)
            tmp.replace(path)
            _preferred = i
            return path
        log.warning("Copertina non disponibile (%s): %s", key, " | ".join(errors))
        _failed[key] = time.time()
        return None


def diagnose(sitecode: str, url: str):
    """Prova tutti gli indirizzi possibili per una copertina e riporta cosa risponde ciascuno."""
    out = []
    for _, src in candidate_urls(sitecode, url):
        row = {"url": src}
        try:
            r = _http().get(src)
            row.update(status=r.status_code, content_type=r.headers.get("content-type"), bytes=len(r.content),
                       final_url=str(r.url))
            if r.is_success:
                try:
                    img = Image.open(io.BytesIO(r.content))
                    row["image"] = f"{img.format} {img.width}x{img.height}"
                except Exception:  # noqa: BLE001
                    row["inizio_risposta"] = r.text[:300]
        except Exception as e:  # noqa: BLE001
            row["error"] = f"{type(e).__name__}: {e}"
        out.append(row)
    return out
