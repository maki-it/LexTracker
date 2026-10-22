# LexTracker

Zeiterfassung und Projektsteuerung mit Anbindung an die [Lexware Office Public API](https://developers.lexware.io/docs/).

> Die erste Version dieser App liegt auf dem Branch `old`. `main` ist ein Neuanfang.

## Stand und Fahrplan

1. **Fundament** ✓: Projektgerüst, Login, Datenmodell für Kunden, Projekte, Aufgaben und Zeiteinträge, Docker, Tests, CI.
2. **Lexware-Anbindung** ✓: Kunden aus Lexware Office importieren und abgleichen.
3. **Projekte und Zeiterfassung** ✓: Projekte und Aufgaben anlegen, Zeiten per Timer oder manuell buchen, Wochenübersicht.
4. **Abrechnung** ✓: Abrechnung nach Stundensatz oder als Retainer (z. B. 20 Stunden pro Quartal zum Festpreis, Rest nach Stundensatz), Vorschau und Rechnungsentwürfe in Lexware.
5. **Später**: Dashboards und Auswertungen, Zugänge für Mitarbeiter und Kunden.

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
  core/        Basis-Modelle, Einstellungen, Middleware, Übersicht, Health-Check, Scheduler
  accounts/    Benutzer mit Rolle (Admin, Mitarbeiter, Kunde), Login mit Zwei-Faktor, Kontoeinstellungen
  customers/   Kunden (mit Verknüpfung zum Lexware-Kontakt) und Import aus Lexware
  lexware/     Async Client für die Lexware Office Public API
  projects/    Projekte und Aufgaben
  tracking/    Zeiteinträge (ein Eintrag ohne Ende ist ein laufender Timer)
  billing/     Abrechnungsvereinbarungen, Berechnung und Rechnungen
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
Den automatischen Kundenimport startest du lokal bei Bedarf mit `make scheduler`.
`make test` startet die Tests, `make lint` prüft den Code-Stil. `make help` zeigt alle Befehle.

## Lexware Office

Den API-Schlüssel erstellst du in Lexware Office unter *Erweiterungen > Public API* und trägst ihn als `APP_LEXWARE_API_KEY` ein.

**Import:** Kontakte mit Kundenrolle werden automatisch importiert, standardmäßig stündlich. Das Intervall stellst du unter **Einstellungen** ein (0 schaltet den automatischen Import ab). Der Button **Aus Lexware importieren** auf der Kundenseite startet den Import sofort, auf der Kommandozeile geht das mit `uv run app/manage.py sync_lexware_customers` (im Container `docker compose exec app python manage.py sync_lexware_customers`).
Der Import legt neue Kunden an und aktualisiert Name, Kundennummer, E-Mail, Telefon und Archiv-Status, wenn sich der Kontakt in Lexware geändert hat (erkannt an der Versionsnummer).

**Bearbeiten:** Ein Klick auf den Kundennamen öffnet das Formular. Änderungen an Name, E-Mail und Telefon speichert LexTracker auch im Lexware-Kontakt; der Kontakt wird dafür frisch geladen, damit in Lexware geänderte andere Felder erhalten bleiben. Stundensatz und Notizen gibt es nur hier.
Kundennummer und Archiv-Status pflegst du weiter in Lexware.

Der Client hält das Rate-Limit der API ein (2 Anfragen pro Sekunde) und wiederholt Anfragen, die mit HTTP 429 abgelehnt werden.

## Abrechnung

Pro Kunde legst du unter **Abrechnung** eine Vereinbarung an:

- **Stundensatz**: Jede abrechenbare Stunde kostet den Satz der Aufgabe, sonst des Projekts, sonst des Kunden, sonst den Standard-Stundensatz aus den Einstellungen.
- **Retainer**: Ein Festpreis pro Monat, Quartal oder Jahr enthält ein Stundenkontingent. Stunden darüber hinaus kosten den Mehrstundensatz der Vereinbarung oder, wenn keiner gesetzt ist, den normalen Satz. Nicht genutzte Stunden verfallen am Ende des Zeitraums.

Für einen gewählten Zeitraum zeigt die Vorschau alle noch nicht abgerechneten, abrechenbaren Zeiten als Rechnungspositionen.
**Rechnungsentwurf in Lexware anlegen** erstellt daraus einen Entwurf (nicht finalisiert), den du in Lexware prüfst und abschließt. Die Zeiten gelten danach als abgerechnet und tauchen in keiner weiteren Rechnung auf.
Der Kunde muss dafür mit einem Lexware-Kontakt verknüpft sein. Den Steuersatz der Positionen stellst du unter **Einstellungen** ein (Standard 19 %, für Kleinunternehmer 0).

## Konto und Sicherheit

Unter deinem Namen oben rechts stellst du Darstellung (hell, dunkel oder wie das System) und Datumsformat ein und änderst dein Passwort.
Dort schaltest du auch die **Zwei-Faktor-Anmeldung** mit einer Authenticator-App ein (TOTP, über [django-otp](https://django-otp-official.readthedocs.io/)). Dabei entstehen zehn Wiederherstellungscodes, die je einmal statt des App-Codes funktionieren.
Auch die Verwaltung unter `/admin/` meldet über diese Anmeldung an, damit der zweite Faktor dort nicht umgangen wird.

## Betrieb mit Docker

```sh
cp .env.example .env    # APP_ENVIRONMENT=production und APP_SECRET_KEY setzen
docker compose up -d --build
```

Die App lauscht auf Port 8000. Datenbank und alle Daten liegen im Volume `lextracker-data` (`/data` im Container).
Neben der App startet ein zweiter Container `scheduler` aus demselben Image. Er führt wiederkehrende Aufgaben wie den automatischen Kundenimport aus.
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
