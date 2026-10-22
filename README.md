# LexTracker

Zeiterfassung und Projektsteuerung mit Anbindung an die [Lexware Office Public API](https://developers.lexware.io/docs/).

> Die erste Version dieser App liegt auf dem Branch `old`. `main` ist ein Neuanfang.

## Stand und Fahrplan

1. **Fundament** ✓: Projektgerüst, Login, Datenmodell für Kunden, Projekte, Aufgaben und Zeiteinträge, Docker, Tests, CI.
2. **Lexware-Anbindung** ✓: Kunden aus Lexware Office importieren und abgleichen.
3. **Projekte und Zeiterfassung** ✓: Projekte und Aufgaben anlegen, Zeiten per Timer oder manuell buchen, Wochenübersicht.
4. **Später**: Abrechnungsmodelle (z. B. Stundenkontingent pro Quartal zum Festpreis, Rest nach Stundensatz), Rechnungen über Lexware, Dashboards, Zugänge für Mitarbeiter und Kunden.

## Technik

| Bereich | Wahl | Warum |
| --- | --- | --- |
| Backend | Django 6, async Views, ASGI mit uvicorn | Login, Benutzer, Admin und Migrationen sind eingebaut; async Views blockieren sich nicht gegenseitig, z. B. bei langsamen API-Aufrufen an Lexware. |
| Oberfläche | Server-gerenderte Templates + [htmx](https://htmx.org) | Interaktive Seiten ohne eigenes JavaScript. |
| Styling | Tailwind CSS 4 über [django-tailwind-cli](https://github.com/django-commons/django-tailwind-cli), eigene Komponenten | Nutzt das Standalone-CLI, also kein Node.js nötig. Farben und Komponenten (`.btn`, `.card`, `.input` …) stehen in `app/assets/tailwind.css`; Hell- und Dunkelmodus folgen der Systemeinstellung. |
| Datenbank | SQLite (WAL-Modus) | Kein extra DB-Server. WAL erlaubt Lesen während geschrieben wird; das reicht für wenige Benutzer locker. |
| Statische Dateien | [ServeStatic](https://github.com/Archmonger/ServeStatic) | Liefert CSS/JS async, komprimiert und mit Cache-Headern aus. |
| Pakete | [uv](https://docs.astral.sh/uv/) | Schnell, mit Lockfile. |

### Projektstruktur

```
app/
  config/      Einstellungen (aus Umgebungsvariablen), URLs, ASGI
  core/        Basis-Modelle, Middleware, Übersicht, Health-Check
  accounts/    Benutzer mit Rolle (Admin, Mitarbeiter, Kunde) und Login
  customers/   Kunden (mit Verknüpfung zum Lexware-Kontakt) und Import aus Lexware
  lexware/     Async Client für die Lexware Office Public API
  projects/    Projekte und Aufgaben
  tracking/    Zeiteinträge (ein Eintrag ohne Ende ist ein laufender Timer)
  templates/   HTML-Templates
  assets/      Tailwind-Quelle mit Farben und eigenen Komponenten
  static/      Statische Dateien (htmx, gebautes CSS)
tests/
docker/
```

## Entwicklung

Voraussetzung: [uv](https://docs.astral.sh/uv/getting-started/installation/) (installiert Python 3.14 bei Bedarf selbst).

```sh
make install     # Abhängigkeiten installieren, .env anlegen
make css         # Stylesheet bauen (lädt beim ersten Mal das Tailwind-CLI)
make migrate     # Datenbank anlegen (liegt in ./data)
make superuser   # Admin-Konto anlegen
make run         # http://localhost:8000
```

Während du an Templates arbeitest, hält `make css-watch` in einem zweiten Terminal das Stylesheet aktuell.
`make test` startet die Tests, `make lint` prüft den Code-Stil. `make help` zeigt alle Befehle.

## Lexware Office

Den API-Schlüssel erstellst du in Lexware Office unter *Erweiterungen > Public API* und trägst ihn als `APP_LEXWARE_API_KEY` ein.
Danach importiert der Button **Aus Lexware importieren** auf der Kundenseite alle Kontakte mit Kundenrolle.
Auf der Kommandozeile geht das auch: `uv run app/manage.py sync_lexware_customers`
(im Container `docker compose exec app python manage.py sync_lexware_customers`).

Der Import legt neue Kunden an und aktualisiert Name, Kundennummer, E-Mail, Telefon und Archiv-Status, wenn sich der Kontakt in Lexware geändert hat (erkannt an der Versionsnummer).
Felder, die es nur hier gibt, etwa Stundensatz und Notizen, bleiben unberührt.
Der Client hält das Rate-Limit der API ein (2 Anfragen pro Sekunde) und wiederholt Anfragen, die mit HTTP 429 abgelehnt werden.

## Betrieb mit Docker

```sh
cp .env.example .env    # APP_ENVIRONMENT=production und APP_SECRET_KEY setzen
docker compose up -d --build
```

Die App lauscht auf Port 8000. Datenbank und alle Daten liegen im Volume `lextracker-data` (`/data` im Container).
Vor jedem Start führt Compose über `pre_start`-Hooks die Migrationen aus und legt, falls `DJANGO_SUPERUSER_USERNAME` und `DJANGO_SUPERUSER_PASSWORD` gesetzt sind, das Admin-Konto an (sofern es noch nicht existiert). Schlägt ein Hook fehl, startet die App nicht. Dafür ist ein aktuelles Docker Compose nötig (getestet mit v5.6).

Hinter einem Reverse Proxy mit HTTPS (empfohlen) zusätzlich setzen:

```env
APP_ALLOWED_HOSTS=zeit.example.de
APP_CSRF_TRUSTED_ORIGINS=https://zeit.example.de
FORWARDED_ALLOW_IPS=<IP des Proxys>
```

Ohne HTTPS funktioniert der Login nur mit `APP_SECURE_COOKIES=false`.

**Backup:** SQLite im WAL-Modus nicht einfach im laufenden Betrieb kopieren, sondern z. B.
`docker compose exec app python -c "import sqlite3; sqlite3.connect('/data/db.sqlite3').backup(sqlite3.connect('/data/backup.sqlite3'))"`.
