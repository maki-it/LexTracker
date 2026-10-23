# LexTracker

Zeiterfassung und Projektsteuerung mit Anbindung an die [Lexware Office Public API](https://developers.lexware.io/docs/).

> Die erste Version dieser App liegt auf dem Branch `old`. `main` ist ein Neuanfang.

## Stand und Fahrplan

1. **Fundament** ✓: Projektgerüst, Login, Datenmodell für Kunden, Projekte, Aufgaben und Zeiteinträge, Docker, Tests, CI.
2. **Lexware-Anbindung** ✓: Kunden aus Lexware Office importieren und abgleichen.
3. **Projekte und Zeiterfassung** ✓: Projekte und Aufgaben anlegen, Zeiten per Timer oder manuell buchen, Wochenübersicht.
4. **Abrechnung** ✓: Abrechnung nach Stundensatz oder als Retainer (z. B. 20 Stunden pro Quartal zum Festpreis, Rest nach Stundensatz), Vorschau und Rechnungsentwürfe in Lexware.
5. **Auswertungen** ✓: Stunden, Umsatz, Budgets und Retainer, CSV-Export.
6. **MCP-Server** ✓: KI-Agenten erfassen Zeiten über das Model Context Protocol.
7. **Zugänge** ✓: Mitarbeiter und Kunden mit eigenen Rechten, Einladung per Link.

## Technik

| Bereich | Wahl | Warum |
| --- | --- | --- |
| Backend | Django 6, async Views, ASGI mit uvicorn | Login, Benutzer, Admin und Migrationen sind eingebaut; async Views blockieren sich nicht gegenseitig, z. B. bei langsamen API-Aufrufen an Lexware. |
| Oberfläche | Server-gerenderte Templates + [htmx](https://htmx.org) | Interaktive Seiten ohne eigenes JavaScript. |
| Styling | Tailwind CSS 4 über [django-tailwind-cli](https://github.com/django-commons/django-tailwind-cli), eigene Komponenten | Nutzt das Standalone-CLI, also kein Node.js nötig. Farben und Komponenten (`.btn`, `.card`, `.table`, `.badge` …) stehen in `app/assets/tailwind.css`, Icons kommen über `{% icon "name" %}` (`core/templatetags/icons.py`). Schrift ist Inter, selbst gehostet statt über Google Fonts. Hell- und Dunkelmodus folgen der Systemeinstellung. |
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
  lexware/     Async Client für die Lexware Office Public API, verschlüsselt gespeicherter API-Schlüssel
  projects/    Projekte und Aufgaben
  tracking/    Zeiteinträge (ein Eintrag ohne Ende ist ein laufender Timer)
  billing/     Abrechnungsvereinbarungen, Berechnung und Rechnungen
  reports/     Auswertungen und CSV-Export
  mcpserver/   MCP-Server für KI-Agenten
  portal/      Kundenportal (nur lesen)
  setup/       Einrichtung einer neuen Instanz (Admin-Konto, Lexware-Schlüssel, Datensicherung)
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
make run         # http://localhost:8000
```

Beim ersten Aufruf führt die **Einrichtung** durch das Anlegen des Admin-Kontos, das Verbinden mit Lexware Office und die Datensicherung (das Konto alternativ mit `make superuser`).
Solange es kein Konto gibt, leitet jede Seite dorthin. Damit niemand anderes eine frische Instanz übernehmen kann, öffnet sich die Einrichtung nur mit einem Code: Die App schreibt den Einrichtungslink beim ersten Aufruf ins Log (`docker compose logs app`), alternativ zeigt ihn `manage.py setup_link` (`docker compose exec app python manage.py setup_link`). Der Code ist aus `APP_SECRET_KEY` abgeleitet und nach dem ersten Konto wertlos.

Während du an Templates arbeitest, hält `make css-watch` in einem zweiten Terminal das Stylesheet aktuell.
Den automatischen Kundenimport startest du lokal bei Bedarf mit `make scheduler`.
`make test` startet die Tests, `make lint` prüft den Code-Stil. `make help` zeigt alle Befehle.
Einen Last- und Performancetest mit Testdaten beschreibt [loadtest/README.md](loadtest/README.md).

## Lexware Office

Den API-Schlüssel erstellst du in Lexware Office unter *Erweiterungen > Public API* und trägst ihn bei der Einrichtung oder später unter **Einstellungen > Lexware Office** ein. Die App prüft ihn vorher mit einem Testaufruf.
Er wird verschlüsselt in der Datenbank gespeichert (mit einem Schlüssel, der aus `APP_SECRET_KEY` abgeleitet ist; auch Backups enthalten ihn also nicht im Klartext) und danach nur noch maskiert angezeigt. Zum Ändern trägst du einfach einen neuen ein. Änderst du `APP_SECRET_KEY`, musst du den Lexware-Schlüssel neu eintragen; die Einstellungsseite weist dann darauf hin. Der Schlüssel landet nie in Logs.
`APP_LEXWARE_API_KEY` funktioniert weiter als Ersatz, solange in der App keiner hinterlegt ist; danach kannst du die Variable entfernen.

**Import:** Kontakte mit Kundenrolle werden automatisch importiert, standardmäßig stündlich. Unter **Einstellungen** stellst du für den Kundenimport und den Abgleich des Rechnungsstatus getrennt ein, wie oft sie laufen (aus, alle 15 Minuten bis wöchentlich) und optional in welchem Zeitfenster (z. B. 07:00 bis 19:00, auch über Mitternacht). Bei „täglich“ oder „wöchentlich“ bestimmt „ab“ die Uhrzeit. Der Button **Aus Lexware importieren** auf der Kundenseite startet den Import sofort, auf der Kommandozeile geht das mit `uv run app/manage.py sync_lexware_customers` (im Container `docker compose exec app python manage.py sync_lexware_customers`).
Der Import legt neue Kunden an und aktualisiert Name, Kundennummer, E-Mail, Telefon und Archiv-Status, wenn sich der Kontakt in Lexware geändert hat (erkannt an der Versionsnummer).

**Bearbeiten:** Ein Klick auf den Kundennamen öffnet das Formular. Änderungen an Name, E-Mail und Telefon speichert LexTracker auch im Lexware-Kontakt; der Kontakt wird dafür frisch geladen, damit in Lexware geänderte andere Felder erhalten bleiben. Stundensatz und Notizen gibt es nur hier.
Kundennummer und Archiv-Status pflegst du weiter in Lexware.
**Kategorien** für Kunden (z. B. „Stammkunde“) vergibst du im Formular; Lexware liefert über die API keine. Auf der Kundenseite filterst du danach und suchst nach Name, Nummer, E-Mail oder Notiz.

**Gelöschte Kontakte:** Taucht ein Kunde beim Import nicht mehr auf (in Lexware gelöscht oder ohne Kundenrolle), wird er archiviert und als „in Lexware gelöscht“ markiert, aber nicht gelöscht, weil Zeiten und Rechnungen an ihm hängen. Kommt der Kontakt zurück, wird die Markierung entfernt.

Der Client hält das Rate-Limit der API ein (2 Anfragen pro Sekunde) und wiederholt Anfragen, die mit HTTP 429 abgelehnt werden.

## Zeiterfassung

Unter **Einstellungen** legst du fest, ob Zeiten exakt oder auf jede angefangene Zeiteinheit (z. B. Viertelstunde) aufgerundet werden. Gerundet wird beim Stoppen des Timers und beim Speichern eines Eintrags, indem das Ende verschoben wird; so sind Anzeige, Summen und Abrechnung immer gleich. Bestehende Einträge bleiben unverändert.
Ob Dauern als `2:45` oder als Dezimalstunden `2,75` angezeigt werden, stellt jeder im Konto ein. Abgerechnet wird immer in Dezimalstunden (z. B. 2,75 Stunden × 80 €).

## Bedienung

Bearbeiten-Masken (Zeiteinträge, Projekte, Aufgaben, Kunden, Abrechnungsvereinbarungen) und **Timer starten** in der Seitenleiste öffnen sich als Dialog über der aktuellen Seite. Nach dem Speichern lädt die Seite dahinter neu; Esc, das X oder ein Klick daneben schließt den Dialog. Jeder dieser Links funktioniert auch als eigene Seite (z. B. in einem neuen Tab).
In der Übersicht und unter **Zeiten** filtert ein Klick auf Kunde oder Projekt eines Eintrags die Liste. Projekte ohne gebuchte Zeiten lassen sich in ihrer Bearbeiten-Maske löschen.
Beim Zeitbuchen (Übersicht, Timer starten, Zeiteintrag) stehen nur Aufgaben aktiver Projekte zur Wahl, die zuletzt benutzten zuerst.
Die Listen der Kunden, Projekte und Rechnungen laden beim Scrollen weitere Einträge nach. Wie viele auf einmal, stellt jeder im Konto ein (25, 50, 100 oder 200). Die Projektliste zeigt zuerst die aktiven Projekte; geplante, pausierte, abgeschlossene oder alle wählst du darüber aus.

## Abrechnung

Pro Kunde legst du unter **Abrechnung** eine Vereinbarung an:

- **Stundensatz**: Jede abrechenbare Stunde kostet den Satz der Aufgabe, sonst des Projekts, sonst des Kunden, sonst den Standard-Stundensatz aus den Einstellungen.
- **Retainer**: Ein Festpreis pro Monat, Quartal oder Jahr enthält ein Stundenkontingent. Stunden darüber hinaus kosten den Mehrstundensatz der Vereinbarung oder, wenn keiner gesetzt ist, den normalen Satz. Nicht genutzte Stunden verfallen am Ende des Zeitraums.

Für einen gewählten Zeitraum zeigt die Vorschau alle noch nicht abgerechneten, abrechenbaren Zeiten als Rechnungspositionen.
**Rechnungsentwurf in Lexware anlegen** erstellt daraus einen Entwurf (nicht finalisiert), den du in Lexware prüfst und abschließt. Die Zeiten gelten danach als abgerechnet und tauchen in keiner weiteren Rechnung auf.
Der Kunde muss dafür mit einem Lexware-Kontakt verknüpft sein. Die Umsatzsteuer richtet sich nach deinem Lexware-Konto: Ist es als Kleinunternehmer (§ 19 UStG) eingerichtet, entsteht die Rechnung ohne Umsatzsteuer, sonst mit 19 %.

Der Reiter **Rechnungen** listet alle Rechnungen mit Nummer, Status (Entwurf, offen, überfällig, bezahlt, storniert) und Fälligkeit, filterbar nach Status und Kunde und durchsuchbar nach Kunde oder Nummer. Die neuesten stehen oben (nach Rechnungsdatum, dann Rechnungsnummer).
Der Rechnungsabgleich übernimmt auch Rechnungen, die du direkt in Lexware für einen importierten Kunden schreibst, mit Datum, Leistungszeitraum, Nettosumme und Status. Sie sind mit „in Lexware erstellt“ markiert, haben keine Zeiteinträge, erscheinen im Kundenzugang und zählen in den Auswertungen zum Umsatz. Löschst du eine solche Rechnung in Lexware, verschwindet sie auch hier.
Den Status holt der Scheduler nach dem eingestellten Zeitplan aus der Belegliste von Lexware; **Status aktualisieren** gleicht sofort ab.
Löschst du einen Entwurf in Lexware, wird die Rechnung hier als gelöscht markiert und ihre Zeiten sind wieder offen. Bei einer stornierten Rechnung gibst du die Zeiten mit **Zeiten freigeben** selbst wieder frei, falls du sie neu abrechnen willst.

## Auswertungen

Unter **Auswertungen** wählst du einen Zeitraum (dieser oder letzter Monat, Quartal, Jahr oder frei) und optional einen Kunden. Die Seite zeigt:

- erfasste, abrechenbare und noch nicht abgerechnete Stunden, dazu den Wert der offenen Zeit nach Stundensatz (ohne Retainer-Kunden),
- den abgerechneten Umsatz netto (Rechnungen, deren Leistungszeitraum im gewählten Zeitraum endet; stornierte und gelöschte zählen nicht), aufgeteilt in bezahlt, offen und Entwurf,
- ein Diagramm der Stunden pro Tag oder Monat,
- den Verbrauch laufender Retainer im aktuellen Abrechnungszeitraum,
- Stunden je Kunde und je Projekt, mit dem Gesamtverbrauch gegenüber dem Projektbudget.

**Zeiten als CSV** lädt alle Einträge des Zeitraums herunter (Semikolon-getrennt, Dezimalkomma, für Excel und LibreOffice).

## KI-Agenten (MCP)

LexTracker ist ein [MCP-Server](https://modelcontextprotocol.io): Ein KI-Agent wie Claude Code kann damit Zeiten erfassen, während er an einer Aufgabe arbeitet. Er handelt dabei als der Benutzer, dem der Token gehört.

1. Unter **Konto → KI-Agenten und API-Tokens** einen Token erstellen. Er wird nur einmal angezeigt; gespeichert wird nur sein Hash.
2. Den Agenten verbinden, z. B. in Claude Code:

   ```sh
   claude mcp add --transport http lextracker https://lextracker.example.de/mcp/ \
     --header "Authorization: Bearer lxt_..."
   ```

   Andere Clients brauchen dieselben Angaben: Transport „Streamable HTTP“, die Adresse `/mcp/` und den Header `Authorization: Bearer <Token>`.

Werkzeuge für den Agenten:

| Tool | Was es tut |
| --- | --- |
| `list_projects`, `find_tasks` | Projekte und offene Aufgaben finden |
| `create_task` | Aufgabe in einem Projekt anlegen |
| `start_timer`, `stop_timer`, `get_running_timer` | Timer steuern; beim Stoppen kann der Agent die Beschreibung durch eine Zusammenfassung ersetzen |
| `add_time_entry` | Zeit nachtragen, mit Ende oder Dauer; gerundet wie eingestellt |
| `list_time_entries` | Gebuchte Zeiten eines Zeitraums mit Summe |

Ein Hinweis für den Agenten, etwa in der `CLAUDE.md` eines Projekts, sorgt dafür, dass er es auch tut. Fertige Beispiel-Prompts zum Kopieren (dauerhaft, einmalig im Chat, Zeit nachtragen) stehen im Konto unter **Beispiel-Prompts für deinen Agenten**.

Der Server ist zustandslos und antwortet mit JSON, ohne Event-Stream. Ein widerrufener Token funktioniert sofort nicht mehr.

## Benutzer und Rechte

Unter **Benutzer** legst du Zugänge an. Danach zeigt die App einen Einladungslink, den du der Person schickst. Damit legt sie ihr Passwort fest. Der Link gilt eine Woche und nur einmal; über **Einladungslink** in der Liste erzeugst du jederzeit einen neuen, auch wenn jemand sein Passwort vergessen hat.

| Rolle | Sieht und darf |
| --- | --- |
| Administrator | alles |
| Mitarbeiter | Übersicht, Timer und Zeiten: bucht nur auf die Kunden (mit allen ihren Projekten) und einzelnen Projekte, die ein Admin unter **Benutzer** freischaltet, und sieht nur die eigenen Zeiten. Keine Projekte, Kunden, Abrechnung, Auswertungen oder Einstellungen. Kann einen API-Token für den MCP-Server erstellen. |
| Kunde | nur lesend und nur die eigenen Daten: Projekte und je nach Einstellung Budgets, Zeiteinträge (mit oder ohne Beschreibung) und Rechnungen. Entwürfe und in Lexware gelöschte Rechnungen sieht er nie. |

Was ein Kundenzugang sieht, stellst du pro Zugang beim Benutzer ein. Welche Seiten eine Rolle öffnen darf, steht in `app/core/access.py`.

## Konto und Sicherheit

Unter deinem Namen oben rechts stellst du Darstellung (hell, dunkel oder wie das System) und Datumsformat ein und änderst dein Passwort.
Dort schaltest du auch die **Zwei-Faktor-Anmeldung** mit einer Authenticator-App ein (TOTP, über [django-otp](https://django-otp-official.readthedocs.io/)). Dabei entstehen zehn Wiederherstellungscodes, die je einmal statt des App-Codes funktionieren.
Auch die Verwaltung unter `/admin/` meldet über diese Anmeldung an, damit der zweite Faktor dort nicht umgangen wird.
Nach zu vielen falschen Passwörtern oder Codes von einer IP-Adresse ist die Anmeldung von dort eine Weile gesperrt. Wie viele Fehlversuche und wie lange, legst du unter **Einstellungen** fest (Standard: 5 Versuche, 15 Minuten; 0 Versuche schaltet die Sperre aus). Hinter einem Reverse Proxy muss `FORWARDED_ALLOW_IPS` stimmen, sonst sehen alle Anfragen wie die IP des Proxys aus.

## Betrieb mit Docker

```sh
cp .env.example .env    # APP_ENVIRONMENT=production und APP_SECRET_KEY setzen
docker compose up -d --build
```

Seiten gehen mit Brotli oder gzip komprimiert an den Browser.
Ein Worker (`UVICORN_WORKERS`) nutzt höchstens einen CPU-Kern und braucht etwa 80 bis 200 MB RAM; bei mehreren Kernen und mehreren gleichzeitigen Benutzern lohnt einer pro Kern (siehe [loadtest/README.md](loadtest/README.md)).
Die App lauscht auf Port 8000 (über `APP_PORT` änderbar, z. B. `127.0.0.1:8000`, wenn nur ein Reverse Proxy auf demselben Server sie erreichen soll). Datenbank und alle Daten liegen im Volume `lextracker-data` (`/data` im Container), Backups im Volume `lextracker-backups` (`/backups`).
Neben der App startet ein zweiter Container `scheduler` aus demselben Image, sobald die App gesund ist. Er führt wiederkehrende Aufgaben wie den automatischen Kundenimport, den Rechnungsabgleich und das tägliche Backup aus und prüft dafür jede Minute, was fällig ist. Sein Healthcheck schlägt an, wenn er länger als fünf Minuten nicht mehr geprüft hat.
Vor jedem Start führt Compose über `pre_start`-Hooks die Migrationen aus und legt, falls `DJANGO_SUPERUSER_USERNAME` und `DJANGO_SUPERUSER_PASSWORD` gesetzt sind, das Admin-Konto an (sofern es noch nicht existiert). Schlägt ein Hook fehl, startet die App nicht. Dafür ist ein aktuelles Docker Compose nötig (getestet mit v5.6).
Beide Container laufen ohne Root, mit schreibgeschütztem Dateisystem (beschreibbar sind nur `/data`, `/backups` und `/tmp`), ohne Linux-Capabilities und mit begrenzten Logs (5 × 10 MB).

Hinter einem Reverse Proxy mit HTTPS (empfohlen) zusätzlich setzen:

```env
APP_ALLOWED_HOSTS=zeit.example.de
APP_CSRF_TRUSTED_ORIGINS=https://zeit.example.de
FORWARDED_ALLOW_IPS=<IP des Proxys>
```

Ohne HTTPS funktioniert der Login nur mit `APP_SECURE_COOKIES=false`.

**Backup:** Der Scheduler kopiert die Datenbank täglich nach `/backups`. Ob, ab welcher Uhrzeit (Standard 03:00) und wie viele Kopien er behält (Standard 14), stellst du unter Einstellungen → Datensicherung ein; dort steht auch, wann die letzte Sicherung lief. Nur der Zielordner kommt aus der Umgebung (`APP_BACKUP_DIR`, in Docker fest `/backups`, ohne Docker `data/backups`). Der Scheduler nutzt dafür die Backup-Funktion von SQLite, die auch im laufenden Betrieb eine stimmige Kopie liefert; die Datei einfach zu kopieren reicht im WAL-Modus nicht.
Ein Backup sofort: `make docker-backup` (oder `docker compose exec scheduler python manage.py backup_database`).
Damit die Backups auch außerhalb von Docker liegen, z. B. für ein Offsite-Backup, kannst du das Volume durch einen Ordner auf dem Server ersetzen. Er muss dem Benutzer mit der UID 1000 gehören:

```yaml
# compose.override.yaml, ersetzt das Volume für /backups
services:
  app:
    volumes: ["/srv/backups/lextracker:/backups"]
  scheduler:
    volumes: ["/srv/backups/lextracker:/backups"]
```

Zum Wiederherstellen die App stoppen (`docker compose down`), die gewünschte Kopie als `/data/db.sqlite3` zurückspielen und dabei `db.sqlite3-wal` und `db.sqlite3-shm` löschen, dann wieder starten.
