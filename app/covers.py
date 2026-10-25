"""Copertine: scaricate da outducks.org solo quando servono e salvate su disco.

Ogni copertina viene richiesta al massimo una volta (poi si usa la cache),
con poche richieste in parallelo per non pesare sul sito.
"""

import hashlib
import io
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
RETRY_AFTER = 6 * 3600


def _http():
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=30, follow_redirects=True)
        return _client


def remote_url(sitecode: str, url: str) -> str:
    return config.COVER_URL_TEMPLATE.format(sitecode=sitecode, url=url)


def cache_path(sitecode: str, url: str):
    h = hashlib.sha1(f"{sitecode}/{url}".encode()).hexdigest()
    return config.COVER_DIR / h[:2] / f"{h}.jpg"


def get(sitecode: str, url: str):
    """Percorso della miniatura in cache, oppure None se non disponibile."""
    path = cache_path(sitecode, url)
    if path.exists():
        return path
    src = remote_url(sitecode, url)
    if time.time() - _failed.get(src, 0) < RETRY_AFTER:
        return None
    with _sem:
        if path.exists():
            return path
        try:
            r = _http().get(src)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content))
            img = img.convert("RGB")
            if img.width > config.THUMB_WIDTH:
                img = img.resize((config.THUMB_WIDTH, round(img.height * config.THUMB_WIDTH / img.width)),
                                 Image.LANCZOS)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            img.save(tmp, "JPEG", quality=85, optimize=True)
            tmp.replace(path)
            return path
        except Exception as e:  # noqa: BLE001
            log.warning("Copertina non disponibile %s: %s", src, e)
            _failed[src] = time.time()
            return None
