import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "topotracker.db"
ISV_DIR = DATA_DIR / "isv"
COVER_DIR = DATA_DIR / "covers"

# Dump ufficiali di Inducks (formato ISV, campi separati da "^").
INDUCKS_ISV_URL = os.environ.get("INDUCKS_ISV_URL", "https://inducks.org/inducks/isv/").rstrip("/") + "/"
# Indirizzi delle copertine; {sitecode} e {url} arrivano da inducks_entryurl.isv.
# Le scansioni stanno su outducks.org sotto /webusers/ (es. url "webusers/2007/06/x.jpg"
# -> outducks.org/webusers/webusers/2007/06/x.jpg). Il sitecode "thumbnails" indica solo
# una miniatura ritagliata, quindi non lo usiamo come cartella.
# Si prova un indirizzo dopo l'altro finché uno restituisce una copertina intera; quello
# che funziona viene usato per primo le volte successive. COVER_URL_TEMPLATE, se
# impostato, viene provato per primo.
COVER_URL_TEMPLATES = [t for t in [os.environ.get("COVER_URL_TEMPLATE", "")] if t] + [
    "https://outducks.org/webusers/{url}",
    "https://inducks.org/hr.php?normalsize=1&image=https://outducks.org/webusers/{url}",
    "https://outducks.org/{sitecode}/{url}",
    "https://outducks.org/{url}",
]
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
