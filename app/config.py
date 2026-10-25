import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "topotracker.db"
ISV_DIR = DATA_DIR / "isv"
COVER_DIR = DATA_DIR / "covers"

# Dump ufficiali di Inducks (formato ISV, campi separati da "^").
INDUCKS_ISV_URL = os.environ.get("INDUCKS_ISV_URL", "https://inducks.org/inducks/isv/").rstrip("/") + "/"
# Le immagini delle copertine sono servite da outducks.org; {sitecode} e {url}
# arrivano da inducks_entryurl.isv.
COVER_URL_TEMPLATE = os.environ.get("COVER_URL_TEMPLATE", "https://outducks.org/{sitecode}/{url}")
COUNTRY = os.environ.get("COUNTRY", "it")
# Testate seguite di default al primo avvio (codici Inducks, separati da virgola).
DEFAULT_FOLLOWED = [c.strip() for c in os.environ.get("DEFAULT_FOLLOWED", "it/TL").split(",") if c.strip()]
# Ogni quanti giorni riscaricare i dump (0 = mai in automatico).
UPDATE_INTERVAL_DAYS = float(os.environ.get("UPDATE_INTERVAL_DAYS", "7"))
# Importazione automatica al primo avvio se il database è vuoto.
AUTO_IMPORT = os.environ.get("AUTO_IMPORT", "1") not in ("0", "false", "no")
USER_AGENT = os.environ.get(
    "USER_AGENT", "TopoTracker/1.0 (tracker personale di letture; github.com/land2595/topotracker)"
)
# Larghezza delle miniature salvate in cache.
THUMB_WIDTH = int(os.environ.get("THUMB_WIDTH", "360"))
