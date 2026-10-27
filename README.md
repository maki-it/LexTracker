# LexTracker

Zeiterfassung und Projektsteuerung mit Anbindung an die [Lexware Office Public API](https://developers.lexware.io/docs/): Kunden aus Lexware Office übernehmen, Projekte und Aufgaben steuern, Zeiten per Timer oder manuell buchen, nach Stundensatz oder Retainer abrechnen und Rechnungsentwürfe in Lexware anlegen.

> Die erste Version dieser App liegt auf dem Branch `old`. `main` ist ein Neuanfang.

**Inhalt:** [Schnellstart](#schnellstart-docker-produktiv) · [Funktionen](#funktionen) · [Betrieb](#betrieb) · [Entwicklung](#entwicklung) · [Releases](#releases)

## Schnellstart (Docker, produktiv)

Du brauchst einen Server mit Docker und einem aktuellen Docker Compose (getestet mit v5.6) sowie Git. Die App läuft aus dem veröffentlichten Image `ghcr.io/maki-it/lextracker`, gebaut wird nichts.

1. **Repository holen**

   ```sh
   git clone https://github.com/maki-it/LexTracker.git
   cd LexTracker
   ```

   Für den Betrieb brauchst du daraus nur `compose.yaml` und `.env.example`.

2. **Konfiguration anlegen**

   ```sh
   cp .env.example .env
   ```

   Öffne `.env` und setze mindestens diese zwei Werte:

   ```env
   APP_ENVIRONMENT=production
   APP_SECRET_KEY=<zufälliger Wert>
   ```

   Einen Wert erzeugst du mit `python -c "import secrets; print(secrets.token_urlsafe(50))"`. Bewahre ihn gut auf: Daraus leitet die App die Verschlüsselung des Lexware-Schlüssels ab.

3. **Adresse festlegen**, unter der du die App öffnest (nur eine der beiden Varianten):

   - **Mit HTTPS hinter einem Reverse Proxy (empfohlen):**

     ```env
     APP_ALLOWED_HOSTS=zeit.example.de
     APP_CSRF_TRUSTED_ORIGINS=https://zeit.example.de
     FORWARDED_ALLOW_IPS=<IP des Proxys>
     APP_PORT=127.0.0.1:8000
     ```

   - **Zum Ausprobieren über HTTP:** `APP_SECURE_COOKIES=false` setzen und die Adresse, unter der du die App aufrufst, in `APP_ALLOWED_HOSTS` eintragen (Standard: `localhost,127.0.0.1`). Ohne HTTPS funktioniert der Login nur so.

4. **Starten**

   ```sh
   docker compose up -d
   docker compose ps          # app und scheduler sollten "healthy" sein
   ```

   Ist das Image nicht öffentlich, meldest du dich vorher mit `docker login ghcr.io` an (Token mit der Berechtigung `read:packages`). Standardmäßig zieht Compose `latest`; mit `LEXTRACKER_VERSION=0.4.0` in der `.env` bleibst du auf einer Version.

5. **Einrichtung öffnen**: Solange es kein Konto gibt, leitet jede Seite zur Einrichtung. Sie öffnet sich nur mit einem Code, damit niemand eine frische Instanz übernehmen kann. Den Link findest du im Log:

   ```sh
   docker compose logs app
   # oder
   docker compose exec app python manage.py setup_link
   ```

6. **Einrichtung durchlaufen**: Admin-Konto anlegen (mit Zwei-Faktor-Anmeldung per Authenticator-App), Lexware Office verbinden und die Datensicherung einstellen. Den API-Schlüssel erstellst du in Lexware Office unter *Erweiterungen > Public API*.

7. **Loslegen**: Unter **Kunden** mit **Aus Lexware importieren** die Kunden holen, dann Projekte und Aufgaben anlegen und über **Timer starten** Zeiten buchen.

Optional danach: den E-Mail-Versand unter **Einstellungen → E-Mail-Versand verwalten** einrichten ([E-Mail](#e-mail)), weitere Benutzer unter **Benutzer** einladen ([Benutzer und Rechte](#benutzer-und-rechte)) und einen KI-Agenten verbinden ([KI-Agenten](#ki-agenten-mcp)).

Alle Einstellungen, Sicherungen, Updates und den Betrieb hinter einem Reverse Proxy beschreibt der Abschnitt [Betrieb](#betrieb).

## Funktionen

Das kann LexTracker:

- **Fundament**: Projektgerüst, Login, Datenmodell für Kunden, Projekte, Aufgaben und Zeiteinträge, Docker, Tests, CI.
- **Lexware-Anbindung**: Kunden aus Lexware Office importieren und abgleichen.
- **Projekte und Zeiterfassung**: Projekte und Aufgaben anlegen, Zeiten per Timer oder manuell buchen, Wochenübersicht.
- **Abrechnung**: Abrechnung nach Stundensatz oder als Retainer (z. B. 20 Stunden pro Quartal zum Festpreis, Rest nach Stundensatz), Vorschau und Rechnungsentwürfe in Lexware.
- **Auswertungen**: Stunden, Umsatz, Budgets und Retainer, CSV-Export.
- **MCP-Server**: KI-Agenten erfassen Zeiten über das Model Context Protocol.
- **Zugänge**: Mitarbeiter und Kunden mit eigenen Rechten, Einladung per Link.
- **E-Mail**: Passwort zurücksetzen, Anmeldelink ohne Passwort, Einladung neuer Benutzer, Wochenbericht, Erinnerung an laufende Timer und Hinweis auf überfällige Rechnungen.
- **Erinnerungen**: Notizen zu Kunden und Projekten, auf Wunsch mit Datum und Uhrzeit und einer Benachrichtigung per Glocke und E-Mail.
- **Nachrichten**: Glocke und Postfach für Meldungen der App (Sicherung, Lexware-Abgleich, E-Mail-Versand, Timer) mit Prioritäten Kritisch, Warnung, Info und Debug, pro Benutzer einstellbar.

Die Einzelheiten stehen in den folgenden Abschnitten.

### Lexware Office

Den API-Schlüssel erstellst du in Lexware Office unter *Erweiterungen > Public API* und trägst ihn bei der Einrichtung oder später unter **Einstellungen > Lexware Office** ein. Die App prüft ihn vorher mit einem Testaufruf.
Er wird verschlüsselt in der Datenbank gespeichert (mit einem Schlüssel, der aus `APP_SECRET_KEY` abgeleitet ist; auch Backups enthalten ihn also nicht im Klartext) und danach nur noch maskiert angezeigt. Zum Ändern trägst du einfach einen neuen ein. Änderst du `APP_SECRET_KEY`, musst du den Lexware-Schlüssel neu eintragen; die Einstellungsseite weist dann darauf hin. Der Schlüssel landet nie in Logs.
`APP_LEXWARE_API_KEY` funktioniert weiter als Ersatz, solange in der App keiner hinterlegt ist; danach kannst du die Variable entfernen.

**Import:** Kontakte mit Kundenrolle werden automatisch importiert, standardmäßig stündlich. Unter **Einstellungen** stellst du für den Kundenimport und den Abgleich des Rechnungsstatus getrennt ein, wie oft sie laufen (aus, alle 15 Minuten bis wöchentlich) und optional in welchem Zeitfenster (z. B. 07:00 bis 19:00, auch über Mitternacht). Bei „täglich“ oder „wöchentlich“ bestimmt „ab“ die Uhrzeit. Der Button **Aus Lexware importieren** auf der Kundenseite startet den Import sofort, auf der Kommandozeile geht das mit `uv run app/manage.py sync_lexware_customers` (im Container `docker compose exec app python manage.py sync_lexware_customers`).
Der Import legt neue Kunden an und aktualisiert Name, Kundennummer, E-Mail, Telefon, Notiz und Archiv-Status, wenn sich der Kontakt in Lexware geändert hat (erkannt an der Versionsnummer).

**Bearbeiten:** Ein Klick auf den Kundennamen öffnet das Formular. Änderungen an Name, E-Mail, Telefon und Notizen speichert LexTracker auch im Lexware-Kontakt; der Kontakt wird dafür frisch geladen, damit in Lexware geänderte andere Felder erhalten bleiben. Den Stundensatz gibt es nur hier.
Kundennummer und Archiv-Status pflegst du weiter in Lexware.
**Kontakte mit mehreren Einträgen:** Lexware lässt einen Kontakt nicht über die API ändern, sobald E-Mail-Adressen, Telefonnummern, Adressen oder Ansprechpartner mehr als einen Eintrag einer Art haben (zum Beispiel zwei geschäftliche E-Mail-Adressen). Die App prüft das vor dem Speichern und sagt dir, bei welchen Angaben das so ist. Eine geänderte Notiz bleibt dann nur in LexTracker und wird beim Import nicht überschrieben; Name, E-Mail und Telefon musst du in Lexware ändern. Gehen kann es wieder, sobald der Kontakt in Lexware nur noch einen Eintrag pro Art hat.

**Notizen:** Die Notiz eines Kunden ist das Feld „Notiz“ des Lexware-Kontakts und wird in beide Richtungen abgeglichen. Lexware nimmt höchstens 1000 Zeichen an; das Formular prüft das bei Kunden mit Lexware-Kontakt, Kunden nur in LexTracker haben keine Grenze. Eine in Lexware geänderte Notiz übernimmt der nächste Import, solange die Notiz hier nicht anders geändert wurde. Beim ersten Import nach der Umstellung bleiben vorhandene Notizen erhalten: Gibt es hier und in Lexware verschiedene, stehen beide untereinander in der Notiz und gehen beim nächsten Speichern des Kunden nach Lexware. Lexware zeigt Markdown als einfachen Text. Dateien, Aufgaben und Tags der Lexware-Kontakte bietet die Public API nicht an; Erinnerungen und Kategorien gibt es deshalb nur in LexTracker.
**Webhooks:** Statt auf den nächsten Lauf zu warten, kann Lexware die App bei jeder Änderung selbst aufrufen. Unter **Einstellungen > Lexware Office > Webhooks** richtest du das mit einem Klick ein: Die App abonniert bei Lexware Kontakt-, Rechnungs- und Zahlungsereignisse (`contact.*`, `invoice.*`, `payment.changed`) und nennt dafür eine Adresse der Form `https://deine-app/webhooks/lexware/<Geheimnis>/`. Dafür muss die App aus dem Internet über HTTPS erreichbar sein; die Adresse nimmt sie aus **Einstellungen > Allgemein > Adresse der App**, sonst aus der aktuellen Seite. Dieselbe Adresse steht in Links in E-Mails; sie stand früher bei den E-Mail-Einstellungen, ein dort eingetragener Wert wird beim Update übernommen. Kommt ein Aufruf an, stößt der Scheduler (alle 5 Sekunden geprüft) den passenden Abgleich an: Bei Kontakt-Ereignissen lädt er nur die geänderten Kontakte (die Aufrufe nennen deren ID) und aktualisiert diese Kunden; bei Rechnungs- und Zahlungsereignissen liest er nur die genannten Rechnungen samt Zahlungsstand (offener Betrag) und aktualisiert diese. Aufrufe zu Belegen, die keine Rechnung eines bekannten Kunden sind (etwa Zahlungen von Gutschriften), ignoriert er. Erst bei mehr als zehn Änderungen auf einmal oder wenn ein Aufruf keine ID nennt, läuft der volle Kundenimport bzw. Rechnungsabgleich. Der Zeitpunkt des letzten vollen Laufs bleibt dabei unberührt, der Lauf nach Zeitplan läuft also weiter. Den Inhalt des Aufrufs übernimmt die App nie; er sagt nur, wo sie bei Lexware nachsehen soll. Ein gefälschter Aufruf kann deshalb höchstens einen Abgleich auslösen, und ohne das Geheimnis in der Adresse antwortet die App mit 404. Zusätzlich signiert Lexware jeden Aufruf (RSA-SHA512, Header `X-Lxo-Signature`): Trägst du unter **Webhooks** den öffentlichen Schlüssel aus der API-Dokumentation ein (Event Subscriptions, Verify Authenticity, Link „this public key“), nimmt die App nur noch Aufrufe mit gültiger Signatur an (sonst 401). Das ist optional und nicht vorausgesetzt, weil der Inhalt ohnehin nie übernommen wird. Ein neuer API-Schlüssel richtet die Abos automatisch neu ein, denn Lexware entfernt sie mit dem alten Schlüssel; wird der Schlüssel entfernt, vergisst die App sie. Der Zeitplan oben bleibt als Netz für Aufrufe, die nie ankommen (Lexware wiederholt fehlgeschlagene Zustellungen eine Zeit lang, danach nicht mehr); mit Webhooks genügt dafür ein seltener Lauf, etwa täglich. **Webhooks entfernen** kündigt die Abos bei Lexware und macht die Adresse ungültig; **Neu einrichten** erzeugt ein neues Geheimnis. Fehlgeschlagene Abgleiche wiederholt der Scheduler nach einer Minute.

**Kategorien** für Kunden (z. B. „Stammkunde“) vergibst du im Formular; Lexware liefert über die API keine. Auf der Kundenseite filterst du danach und suchst nach Name, Nummer, E-Mail oder Notiz.

**Gelöschte Kontakte:** Taucht ein Kunde beim Import nicht mehr auf (in Lexware gelöscht oder ohne Kundenrolle), wird er archiviert und als „in Lexware gelöscht“ markiert, aber nicht gelöscht, weil Zeiten und Rechnungen an ihm hängen. Kommt der Kontakt zurück, wird die Markierung entfernt.

Der Client hält das Rate-Limit der API ein (2 Anfragen pro Sekunde) und wiederholt Anfragen, die mit HTTP 429 abgelehnt werden.

### Zeiterfassung

Unter **Einstellungen** legst du fest, ob Zeiten exakt oder auf einen Schritt (z. B. Viertelstunde) gerundet werden. Beim Stoppen des Timers und beim Speichern eines Eintrags werden Beginn und Ende auf den nächstgelegenen Schritt gerundet (9:07 wird 9:00, 9:08 wird 9:15); ein Eintrag dauert mindestens einen Schritt. Gespeichert werden die gerundeten Zeiten, so sind Anzeige, Summen und Abrechnung immer gleich. Bestehende Einträge bleiben unverändert.
Ob Dauern als `2:45` oder als Dezimalstunden `2,75` angezeigt werden, stellt jeder im Konto ein. Abgerechnet wird immer in Dezimalstunden (z. B. 2,75 Stunden × 80 €).

### Bedienung

Bearbeiten-Masken (Zeiteinträge, Projekte, Aufgaben, Kunden, Abrechnungsvereinbarungen) und **Timer starten** in der Seitenleiste öffnen sich als Dialog über der aktuellen Seite. Nach dem Speichern lädt die Seite dahinter neu; Esc, das X oder ein Klick daneben schließt den Dialog. Jeder dieser Links funktioniert auch als eigene Seite (z. B. in einem neuen Tab).
In der Übersicht und unter **Aufgaben** filtert ein Klick auf Kunde oder Projekt eines Eintrags die Liste. Projekte ohne gebuchte Zeiten lassen sich in ihrer Bearbeiten-Maske löschen.
Beim Zeitbuchen (Übersicht, Timer starten, Zeiteintrag) stehen nur Aufgaben aktiver Projekte zur Wahl, die zuletzt benutzten zuerst.
Die Listen der Kunden, Projekte und Rechnungen laden beim Scrollen weitere Einträge nach. Wie viele auf einmal, stellt jeder im Konto ein (25, 50, 100 oder 200). Die Projektliste zeigt zuerst die aktiven Projekte; geplante, pausierte, abgeschlossene oder alle wählst du darüber aus.

### Abrechnung

Pro Kunde legst du unter **Abrechnung** eine Vereinbarung an:

- **Stundensatz**: Jede abrechenbare Stunde kostet den Satz der Aufgabe, sonst des Projekts, sonst des Kunden, sonst den Standard-Stundensatz aus den Einstellungen.
- **Retainer**: Ein Festpreis pro Monat, Quartal oder Jahr enthält ein Stundenkontingent. Stunden darüber hinaus kosten den Mehrstundensatz der Vereinbarung oder, wenn keiner gesetzt ist, den normalen Satz. Nicht genutzte Stunden verfallen am Ende des Zeitraums.

Für einen gewählten Zeitraum zeigt die Vorschau alle noch nicht abgerechneten, abrechenbaren Zeiten als Rechnungspositionen.
**Rechnungsentwurf in Lexware anlegen** erstellt daraus einen Entwurf (nicht finalisiert), den du in Lexware prüfst und abschließt. Die Zeiten gelten danach als abgerechnet und tauchen in keiner weiteren Rechnung auf.
Jede Position heißt wie die Aufgabe (Mehrstunden eines Retainers: „… (Mehrstunden)“), die Beschreibung darunter nennt Projekt und Zeitraum. Unter **Einstellungen → Allgemein** kannst du zusätzlich die Tätigkeiten (Datum, Dauer, Beschreibung des Zeiteintrags) in die Beschreibung schreiben lassen; der Kunde sieht sie dann auf der Rechnung.
Der Kunde muss dafür mit einem Lexware-Kontakt verknüpft sein. Die Umsatzsteuer richtet sich nach deinem Lexware-Konto: Ist es als Kleinunternehmer (§ 19 UStG) eingerichtet, entsteht die Rechnung ohne Umsatzsteuer, sonst mit 19 %.

Der Reiter **Rechnungen** listet alle Rechnungen mit Nummer, Status (Entwurf, offen, überfällig, bezahlt, storniert) und Fälligkeit, filterbar nach Status und Kunde und durchsuchbar nach Kunde oder Nummer. Die neuesten stehen oben (nach Rechnungsdatum, dann Rechnungsnummer).
Der Rechnungsabgleich übernimmt auch Rechnungen, die du direkt in Lexware für einen importierten Kunden schreibst, mit Datum, Leistungszeitraum, Nettosumme und Status. Sie tragen in der Rechnungsliste ein kleines Label „Lexware“ (Tooltip: „In Lexware Office erstellt“), haben keine Zeiteinträge, erscheinen im Kundenzugang und zählen in den Auswertungen zum Umsatz. Löschst du eine solche Rechnung in Lexware, verschwindet sie auch hier.
Den Status holt der Scheduler nach dem eingestellten Zeitplan aus der Belegliste von Lexware; **Status aktualisieren** gleicht sofort ab.
Löschst du einen Entwurf in Lexware, wird die Rechnung hier als gelöscht markiert und ihre Zeiten sind wieder offen. Bei einer stornierten Rechnung gibst du die Zeiten mit **Zeiten freigeben** selbst wieder frei, falls du sie neu abrechnen willst.

### Auswertungen

Unter **Auswertungen** wählst du einen Zeitraum (dieser oder letzter Monat, Quartal, Jahr oder frei) und optional einen Kunden. Die Seite zeigt:

- erfasste, abrechenbare und noch nicht abgerechnete Stunden, dazu den Wert der offenen Zeit nach Stundensatz (ohne Retainer-Kunden),
- den abgerechneten Umsatz netto (Rechnungen, deren Leistungszeitraum im gewählten Zeitraum endet; stornierte und gelöschte zählen nicht), aufgeteilt in bezahlt, offen und Entwurf,
- ein Diagramm der Stunden pro Tag oder Monat,
- den Verbrauch laufender Retainer im aktuellen Abrechnungszeitraum,
- Stunden je Kunde und je Projekt, mit dem Gesamtverbrauch gegenüber dem Projektbudget.

**Zeiten als CSV** lädt alle Einträge des Zeitraums herunter (Semikolon-getrennt, Dezimalkomma, für Excel und LibreOffice).

### KI-Agenten (MCP)

LexTracker ist ein [MCP-Server](https://modelcontextprotocol.io): Ein KI-Agent wie Claude Code kann damit Zeiten erfassen, während er an einer Aufgabe arbeitet. Er handelt dabei als der Benutzer, dem der Token gehört.

1. Unter **Konto → KI-Agenten und API-Tokens** einen Token erstellen. Er wird nur einmal angezeigt; gespeichert wird nur sein Hash.
2. Den Agenten verbinden, z. B. in Claude Code:

   ```sh
   claude mcp add --transport http lextracker https://lextracker.example.de/mcp/ \
     --header "Authorization: Bearer lxt_..."
   ```

   Fertige Konfigurationen zum Kopieren für Claude Code, Claude (Desktop und Web), VS Code, Cursor und Codex stehen im Konto unter **Agent verbinden**, mit der Adresse deiner Instanz und, direkt nach dem Erstellen, mit dem neuen Token. Andere Clients brauchen dieselben Angaben: Transport „Streamable HTTP“, die Adresse `/mcp/` und den Header `Authorization: Bearer <Token>`. Claude Desktop und Web verbinden sich aus der Anthropic-Cloud, dafür muss die Instanz über HTTPS aus dem Internet erreichbar sein.

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

### Benutzer und Rechte

Unter **Benutzer** legst du Zugänge an. Danach zeigt die App einen Einladungslink, den du der Person schickst. Damit legt sie ihr Passwort fest. Der Link gilt eine Woche und nur einmal; über **Einladungslink** in der Liste erzeugst du jederzeit einen neuen, auch wenn jemand sein Passwort vergessen hat.

| Rolle | Sieht und darf |
| --- | --- |
| Administrator | alles |
| Mitarbeiter | Übersicht, Timer und Zeiten: bucht nur auf die Kunden (mit allen ihren Projekten) und einzelnen Projekte, die ein Admin unter **Benutzer** freischaltet, und sieht nur die eigenen Zeiten. Keine Projekte, Kunden, Abrechnung, Auswertungen oder Einstellungen. Kann einen API-Token für den MCP-Server erstellen. |
| Kunde | nur lesend und nur die eigenen Daten: Projekte und je nach Einstellung Budgets, Zeiteinträge (mit oder ohne Beschreibung) und Rechnungen. Entwürfe und in Lexware gelöschte Rechnungen sieht er nie. |

Was ein Kundenzugang sieht, stellst du pro Zugang beim Benutzer ein. Welche Seiten eine Rolle öffnen darf, steht in `app/core/access.py`.

### Sprachen

Die Oberfläche gibt es auf Deutsch (Standard) und Englisch. Jeder Benutzer wählt seine Sprache unter **Konto → Darstellung**; E-Mails und Nachrichten der App kommen in der Sprache des Empfängers. Auf der Anmeldeseite gilt die Sprache, die der Browser verlangt, und nach dem Abmelden die zuletzt gewählte; mit dem Umschalter unter dem Anmeldeformular (Deutsch / English) stellst du sie auch ohne Anmeldung um. Ein Konto, das noch keine eigene Sprache hat (neu angelegt, noch nie angemeldet), übernimmt beim ersten Anmelden die der Anmeldeseite. Datumsformat und Dezimaltrenner richten sich nach Sprache und Kontoeinstellung.

Die Quelltexte sind deutsch, `app/locale/en/LC_MESSAGES/django.po` enthält die englische Übersetzung. Nach Änderungen an Texten (`_("…")` im Code, `{% trans %}` und `{% blocktrans %}` in Templates):

```bash
make messages    # Texte einsammeln und die .po-Datei aktualisieren, dann kompilieren
```

Neue Einträge in `django.po` bekommen ihre englische Übersetzung (`msgstr`); die CI prüft, dass der Katalog aktuell und vollständig ist. Die kompilierten `.mo`-Dateien liegen nicht im Git: Das Docker-Image erzeugt sie beim Bauen (gettext steckt nur in der Build-Stufe), lokal und in der CI übernimmt das `compilemessages`. Absichtlich nicht übersetzt sind Texte, die in Lexware Office auf Rechnungen landen, und die Ausgaben des MCP-Servers.

### Name und Logo (Whitelabel)

Unter **Einstellungen → Allgemein → Erscheinungsbild** ersetzt du „LexTracker“ und das Logo, ohne Code oder Umgebungsvariablen anzufassen. Die Einstellung gilt für alle Benutzer.

- **App-Name** (höchstens 40 Zeichen): Seitenleiste und Anmeldeseiten, Titel des Browser-Tabs, Betreff, Kopfzeile, Text und Fußzeile aller E-Mails, die Texte der Einrichtung, die Beispiele unter **Konto → Agenten**, der Name im Authenticator (für Codes, die danach eingerichtet werden) und der Titel des MCP-Servers. Leer lassen heißt „LexTracker“.
- **Logo**: PNG, JPEG, WebP oder SVG, höchstens 256 KB, möglichst quadratisch. Es ersetzt die Marke neben dem Namen und das Tab-Symbol (SVG nur dort, das Symbol für den iOS-Home-Bildschirm braucht ein Rasterbild). Die App prüft den Inhalt der Datei, nicht nur die Endung. Ohne Logo bleibt die Uhr-Marke. Das Logo liegt in der Datenbank, steckt also auch in den Sicherungen, und ist ohne Anmeldung abrufbar (`/branding/logo/`), weil die Anmeldeseite es zeigt.

Fest bleiben technische Namen, auf die sich Clients und Docker verlassen (MCP-Server-Kennung `lextracker`, Containernamen, Image) sowie das Manifest für die Installation als Web-App (`site.webmanifest`). Der Absendername der E-Mails ist eine eigene Einstellung unter **Einstellungen → E-Mail-Versand**.

### Konto und Sicherheit

Unter deinem Namen oben rechts stellst du Sprache (Deutsch oder Englisch), Darstellung (hell, dunkel oder wie das System) und Datumsformat ein und änderst dein Passwort.
Dort schaltest du auch die **Zwei-Faktor-Anmeldung** mit einer Authenticator-App ein (TOTP, über [django-otp](https://django-otp-official.readthedocs.io/)). Dabei entstehen zehn Wiederherstellungscodes, die je einmal statt des App-Codes funktionieren.

#### Single Sign-on (OpenID Connect)

Neben Benutzername und Passwort kannst du die Anmeldung über einen OpenID-Connect-Anbieter anbieten (Keycloak, Authentik, Entra ID, Google und andere). Sie ist aus, bis in der `.env` drei Werte stehen:

```env
APP_OIDC_ISSUER=https://sso.example.de/realms/main
APP_OIDC_CLIENT_ID=lextracker
APP_OIDC_CLIENT_SECRET=<Secret des Clients>
```

Beim Anbieter legst du einen Client mit Authorization-Code-Flow an und trägst als Redirect-URI `https://<deine Adresse>/accounts/sso/callback/` ein. Danach zeigt die Anmeldeseite zusätzlich den Button **Mit SSO anmelden**; den Namen im Button legt `APP_OIDC_NAME` fest.

- **Wer sich anmelden darf:** Beim ersten SSO-Login ordnet die App das Konto einem vorhandenen Benutzer zu, und zwar über die E-Mail-Adresse, wenn der Anbieter sie als geprüft meldet (`email_verified`). Hinterlegt also die E-Mail-Adresse in der Benutzerverwaltung. Danach erkennt die App den Benutzer an der Kennung des Anbieters (`sub`), nicht mehr an der Adresse. Gibt es keinen passenden Benutzer, bleibt die Anmeldung aus.
- **Konten automatisch anlegen:** Nur mit `APP_OIDC_CREATE_USERS=true` legt die App für unbekannte Personen einen Mitarbeiter-Zugang ohne Passwort an (nie einen Administrator). `APP_OIDC_ALLOWED_EMAIL_DOMAINS=example.de` beschränkt das auf bestimmte E-Mail-Domains. Schalte es nur ein, wenn der Anbieter nur Personen anmeldet, die Zugang haben sollen.
- **Zwei-Faktor:** Eine Anmeldung über SSO fragt nicht nach dem Code der Authenticator-App; den zweiten Faktor verlangt der Anbieter. Die Anmeldung mit Passwort bleibt daneben bestehen (inklusive Code).
- **Gesperrte Benutzer** können sich auch über SSO nicht anmelden. Fehlgeschlagene SSO-Anmeldungen zählen zur Sperre nach Fehlversuchen.

Auch die Verwaltung unter `/admin/` meldet über diese Anmeldung an, damit der zweite Faktor dort nicht umgangen wird.
Nach zu vielen falschen Passwörtern oder Codes von einer IP-Adresse ist die Anmeldung von dort eine Weile gesperrt. Wie viele Fehlversuche und wie lange, legst du unter **Einstellungen** fest (Standard: 5 Versuche, 15 Minuten; 0 Versuche schaltet die Sperre aus). Hinter einem Reverse Proxy muss `FORWARDED_ALLOW_IPS` stimmen, sonst sehen alle Anfragen wie die IP des Proxys aus.

### Erinnerungen

Unter **Erinnerungen** in der Seitenleiste (nur für Admins) legst du Dinge ab, an die du bei einem Kunden oder Projekt denken willst, z. B. „Angebot nachfassen“ oder „Vertrag zum Jahresende prüfen“. Dieselbe Liste steht auch auf der Seite des Kunden und des Projekts, dort legst du eine Erinnerung auch an. Eine Erinnerung hat einen Titel, Notizen (Markdown) und optional Datum und Uhrzeit.

Wird eine Erinnerung fällig, sagt dir der Scheduler Bescheid (jede Minute geprüft, einmal pro Erinnerung): als Nachricht in der Glocke und als E-Mail, beides pro Erinnerung ein- und ausschaltbar (Standard: beides, die E-Mail nur, wenn der E-Mail-Versand eingerichtet ist). Erinnerungen in der Glocke siehst du unabhängig von der Priorität, ab der du Nachrichten angezeigt bekommst, und die E-Mail hängt nicht an der Einstellung für Nachrichten per E-Mail. Die Zahl in der Seitenleiste zeigt, wie viele Erinnerungen fällig sind. Mit **Erledigt** legst du eine ab (die Nachricht in der Glocke gilt dann als gelesen), ein neues Datum macht sie wieder offen und kündigt sie erneut an. Ohne Datum gibt es keine Benachrichtigung. Die Liste zeigt standardmäßig die offenen Erinnerungen; oben stellst du auf **Erledigt** oder **Alle** um und filterst nach Kunde und Projekt (Projekte eines Kunden stehen auch beim Kunden).

### Nachrichten

Die App meldet sich bei dir, wenn im Hintergrund etwas passiert: Die **Glocke** oben in der Seitenleiste zeigt, wie viele Nachrichten ungelesen sind, und öffnet sie als Fenster. Dort liest, löscht und öffnest du sie (der Titel führt zur passenden Seite); **Als Seite öffnen** zeigt alle mit Filtern nach Priorität. Eine ungelesene kritische Nachricht steht zusätzlich als Banner auf jeder Seite, bis du sie gelesen hast.

Es gibt vier Prioritäten: **Kritisch**, **Warnung**, **Info** und **Debug**. Im Konto stellst du ein, ab welcher Priorität du Nachrichten siehst (Standard: Info) und ab welcher du sie zusätzlich per E-Mail bekommst (Standard: Kritisch, nur wenn der E-Mail-Versand eingerichtet ist). Kritische Nachrichten siehst du immer. Die Einstellung filtert beim Anzeigen: Stellst du später auf Debug um, erscheinen auch die älteren.

Was die App meldet, und an wen (Administratoren, außer wo es dich selbst betrifft):

| Ereignis | Priorität |
| --- | --- |
| Datensicherung fehlgeschlagen | Kritisch |
| Lexware lehnt den API-Schlüssel ab | Kritisch |
| Kundenimport oder Rechnungsabgleich fehlgeschlagen | Warnung, ab dem dritten Fehlschlag in Folge Kritisch |
| E-Mail endgültig nicht zugestellt | Warnung |
| Dein Timer läuft länger als eingestellt (an den Mitarbeiter selbst) | Warnung |
| Kundenimport oder Rechnungsabgleich mit Änderungen, Sicherung hochgeladen oder wiederhergestellt | Info |
| Sicherung erstellt, Import oder Abgleich ohne Änderungen | Debug |

Gleiche Meldungen werden zusammengefasst: Scheitert der stündliche Abgleich einen Tag lang, steht dort eine Nachricht mit „24×“, und es geht nur eine E-Mail raus. Sobald der Job wieder läuft, gilt sie als gelesen. Andere Programmteile melden über `inbox.service.anotify(level, kind, title, body, url=…, to=…, dedupe_key=…)`; der Scheduler läuft in einem eigenen Prozess, deshalb geht jede Nachricht über die Datenbank, und die Glocke fragt alle 15 Sekunden nach (auch sofort, wenn du zum Tab zurückkehrst), ebenso das geöffnete Nachrichtenfenster und der Zähler der fälligen Erinnerungen in der Seitenleiste.

Aufgeräumt wird stündlich im Scheduler: Gelesene Nachrichten bleiben bei Debug 3 Tage, Info 30, Warnung 90 und Kritisch 365 Tage; ungelesene Debug- und Info-Nachrichten gehen nach der doppelten Zeit, ungelesene Warnungen und kritische bleiben, bis du sie liest. Mehr als 1000 Nachrichten pro Benutzer werden nicht aufbewahrt. Kunden haben (noch) kein Postfach.

### E-Mail

Unter **Einstellungen → E-Mail-Versand verwalten** trägst du den SMTP-Server ein (Server, Port, Verschlüsselung, Zugangsdaten, Absender). Das Passwort wird wie der Lexware-Schlüssel verschlüsselt gespeichert. Eine **Testmail** geht sofort raus und zeigt direkt, was der Server antwortet. Port 587 gehört zu STARTTLS, Port 465 zu SSL/TLS; passen Port und Verschlüsselung nicht zusammen, weist dich das Formular darauf hin, und ein TLS-Fehler der Testmail nennt die passende Einstellung.

Alle anderen E-Mails legt die App in eine Warteschlange in der Datenbank, damit keine Seite auf den SMTP-Server wartet. Der Scheduler schaut alle fünf Sekunden hinein, verschickt, was ansteht, und versucht es bei Fehlern nach 1, 5, 15 und 60 Minuten erneut. Die letzten E-Mails mit Status und Fehlermeldung stehen auf derselben Seite unter **Postausgang**. Ohne laufenden Scheduler (`make scheduler` oder der Container `scheduler`) geht also nichts raus.

Sobald der Versand eingerichtet ist, bietet die Anmeldeseite an:

- **Passwort vergessen:** Link für ein neues Passwort, eine Stunde gültig, nur einmal nutzbar.
- **Anmeldelink per E-Mail:** meldet ohne Passwort an, 15 Minuten gültig, nur einmal nutzbar. Der Link öffnet erst eine Seite mit Knopf, damit Mailprogramme, die Links vorab prüfen, ihn nicht verbrauchen. Wer die Zwei-Faktor-Anmeldung nutzt, gibt danach trotzdem den Code ein. Abschalten lässt sich der Anmeldelink unter **Einstellungen → Anmeldung**.

Beide gibt es für Benutzername oder E-Mail-Adresse, und die Antwort ist immer gleich, ob es das Konto gibt oder nicht. Jede Anfrage zählt wie ein Fehlversuch zur Login-Sperre, und ein Konto bekommt höchstens drei Links pro Sperrzeitraum. Ist eine solche E-Mail verschickt oder verfallen, löscht die App ihren Text, damit keine Datenbankkopie die Links enthält.

Legst du unter **Benutzer** jemanden mit E-Mail-Adresse an, bekommt er die **Einladung** gleich per E-Mail: einen Link, mit dem er sein Passwort festlegt, eine Woche gültig und nur einmal nutzbar. Auf der Einladungsseite schickst du sie jederzeit neu oder kopierst den Link selbst. Den automatischen Versand schaltest du unter **Einstellungen → E-Mail** ab. Auch der Text der Einladung wird nach dem Versand gelöscht.

Der Scheduler verschickt außerdem nach dem Zeitplan unter **Einstellungen → E-Mail**:

- **Wochenbericht** (Standard montags 07:00): die eigenen Stunden der sieben Tage davor, nach Tag und Projekt; Administratoren dazu die Stunden aller Benutzer, noch nicht abgerechnete Zeit, offene Rechnungen und Retainer. Wer nichts gebucht hat, bekommt keinen.
- **Erinnerung an laufende Timer** (Standard nach 10 Stunden): eine E-Mail pro Timer, falls jemand vergessen hat, ihn zu stoppen.

Beides geht an Administratoren und Mitarbeiter mit E-Mail-Adresse; jeder schaltet es für sich unter **Konto** ab. Für Links in diesen E-Mails braucht die App ihre **Adresse** (z. B. `https://zeit.example.de`) unter **Einstellungen > Allgemein**.

Der **Hinweis auf überfällige Rechnungen** (Standard: an Administratoren, 3 Tage nach Fälligkeit) geht einmal pro Rechnung und Fälligkeitsdatum raus. Wahlweise bekommt auch der Kunde eine freundliche Zahlungserinnerung an seine E-Mail-Adresse aus Lexware, unterschrieben mit dem Absendernamen aus den E-Mail-Einstellungen; der Hinweis an dich sagt dann, wohin sie ging. Damit keine bezahlte Rechnung angemahnt wird, zählt nur der Status aus dem Rechnungsabgleich, und der muss jünger als einen Tag sein. Rechnungen, die schon mehr als eine Woche über die Frist sind, bekommen keinen Hinweis mehr, damit das Einschalten nicht alle alten Rechnungen auf einmal anmahnt.

## Betrieb

Der Schnellstart genügt für den Start. Dieser Abschnitt beschreibt, was danach wichtig wird.

### Konfiguration

Alle Einstellungen der App kommen aus der Datei `.env` neben der `compose.yaml` (Vorlage: [.env.example](.env.example)) und tragen das Präfix `APP_`. Alles Weitere (Lexware, E-Mail, Zeitpläne, Datensicherung) stellst du in der App unter **Einstellungen** ein.

| Variable | Bedeutung | Standard |
| --- | --- | --- |
| `APP_ENVIRONMENT` | `development` oder `production` | `development` in der Vorlage, `production` in `compose.yaml` |
| `APP_SECRET_KEY` | Pflicht. Daraus sind Sitzungen, Einrichtungscode und die Verschlüsselung von Lexware-Schlüssel und SMTP-Passwort abgeleitet | – |
| `APP_ALLOWED_HOSTS` | Host-Namen, unter denen die App erreichbar ist (kommagetrennt) | `localhost,127.0.0.1` |
| `APP_CSRF_TRUSTED_ORIGINS` | Ursprünge mit Schema, z. B. `https://zeit.example.de` (nötig hinter einem Reverse Proxy mit HTTPS) | leer |
| `APP_SECURE_COOKIES` | `false` nur, wenn du die App ohne HTTPS öffnest | `true` |
| `FORWARDED_ALLOW_IPS` | IP des Reverse Proxys, damit uvicorn dessen `X-Forwarded-*`-Header vertraut | `127.0.0.1` |
| `UVICORN_WORKERS` | Anzahl der uvicorn-Prozesse | `1` |
| `LEXTRACKER_VERSION` | Docker: Version des Images (`0.4.0`, `0.4` oder `latest`) | `latest` |
| `APP_PORT` | Docker: Port, auf dem die App veröffentlicht wird, z. B. `127.0.0.1:8000` | `8000` |
| `APP_TIME_ZONE` | Zeitzone | `Europe/Berlin` |
| `APP_LOG_LEVEL` | Log-Stufe | `info` |
| `APP_LEXWARE_API_KEY` | Ersatz für den Lexware-Schlüssel, solange in der App keiner hinterlegt ist ([Lexware Office](#lexware-office)) | leer |
| `APP_OIDC_ISSUER`, `APP_OIDC_CLIENT_ID`, `APP_OIDC_CLIENT_SECRET` | Schalten die Anmeldung per OpenID Connect ein ([Single Sign-on](#single-sign-on-openid-connect)) | leer |
| `APP_OIDC_NAME`, `APP_OIDC_SCOPES` | Name im Login-Button und angeforderte Scopes | `SSO`, `openid email profile` |
| `APP_OIDC_CREATE_USERS`, `APP_OIDC_ALLOWED_EMAIL_DOMAINS` | Legt Mitarbeiter für unbekannte SSO-Nutzer an, optional nur für bestimmte E-Mail-Domains (kommagetrennt) | `false`, leer |
| `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `DJANGO_SUPERUSER_EMAIL` | Legt beim Start das Admin-Konto an, falls es noch nicht existiert. Ohne sie legt die Einrichtung im Browser das Konto an | leer |

Das Backup-Ziel `APP_BACKUP_DIR` ist in Docker fest `/backups` (siehe [Datensicherung](#datensicherung)).

### Container und Scheduler

Seiten gehen mit Brotli oder gzip komprimiert an den Browser.

Ein Worker (`UVICORN_WORKERS`) nutzt höchstens einen CPU-Kern und braucht etwa 80 bis 200 MB RAM; bei mehreren Kernen und mehreren gleichzeitigen Benutzern lohnt einer pro Kern (siehe [loadtest/README.md](loadtest/README.md)).

Die App lauscht auf Port 8000 (über `APP_PORT` änderbar, z. B. `127.0.0.1:8000`, wenn nur ein Reverse Proxy auf demselben Server sie erreichen soll). Datenbank und alle Daten liegen im Volume `lextracker-data` (`/data` im Container), Backups im Volume `lextracker-backups` (`/backups`).

Neben der App startet ein zweiter Container `scheduler` aus demselben Image, sobald die App gesund ist. Er führt wiederkehrende Aufgaben wie den automatischen Kundenimport, den Rechnungsabgleich, das tägliche Backup, Wochenberichte und Erinnerungen aus und prüft dafür jede Minute, was fällig ist. Außerdem verschickt er die E-Mails aus der Warteschlange. Sein Healthcheck schlägt an, wenn er länger als fünf Minuten nicht mehr geprüft hat.

Unter Einstellungen → Hintergrundaufgaben (oben rechts) siehst du als Admin, ob der Scheduler lebt (er meldet sich bei jeder Prüfung in der Datenbank; nach fünf Minuten Stille warnt die Seite und die Übersicht) und für jede Aufgabe Zeitplan, nächsten und letzten Lauf mit Dauer, Ergebnis, letzter Fehlermeldung und Fehlschlägen in Folge. Fehler kommen weiterhin als Nachricht in die Glocke; die Seite legt keine eigenen an. Prüfungen, die nichts zu tun hatten (E-Mail-Warteschlange, Webhook-Aufrufe, Berichte, Timer-Nachrichten, Erinnerungen), hinterlassen keine Spur, außer sie folgen auf einen Fehler.

Vor jedem Start führt Compose über `pre_start`-Hooks die Migrationen aus und legt, falls `DJANGO_SUPERUSER_USERNAME` und `DJANGO_SUPERUSER_PASSWORD` gesetzt sind, das Admin-Konto an (sofern es noch nicht existiert). Schlägt ein Hook fehl, startet die App nicht. Dafür ist ein aktuelles Docker Compose nötig (getestet mit v5.6).

Beide Container laufen ohne Root, mit schreibgeschütztem Dateisystem (beschreibbar sind nur `/data`, `/backups` und `/tmp`), ohne Linux-Capabilities und mit begrenzten Logs (5 × 10 MB).

### Reverse Proxy und HTTPS

Hinter einem Reverse Proxy mit HTTPS (empfohlen) zusätzlich setzen:

```env
APP_ALLOWED_HOSTS=zeit.example.de
APP_CSRF_TRUSTED_ORIGINS=https://zeit.example.de
FORWARDED_ALLOW_IPS=<IP des Proxys>
```

Ohne HTTPS funktioniert der Login nur mit `APP_SECURE_COOKIES=false`.

### Datensicherung

**Backup:** Der Scheduler kopiert die Datenbank täglich nach `/backups`. Ob, ab welcher Uhrzeit (Standard 03:00) und wie viele Kopien er behält (Standard 14), stellst du unter Einstellungen → Datensicherung ein; dort steht auch, wann die letzte Sicherung lief. Nur der Zielordner kommt aus der Umgebung (`APP_BACKUP_DIR`, in Docker fest `/backups`, ohne Docker `data/backups`). Der Scheduler nutzt dafür die Backup-Funktion von SQLite, die auch im laufenden Betrieb eine stimmige Kopie liefert; die Datei einfach zu kopieren reicht im WAL-Modus nicht.

Unter Einstellungen → Sicherungen siehst du alle Kopien, kannst sofort eine anlegen, sie herunterladen, löschen oder wiederherstellen. Über „Hochladen“ legst du eine Sicherung von einem anderen Server in den Ordner (Name mit `-hochgeladen`) und stellst sie danach wie jede andere wieder her. Die App prüft die Datei vorher wie beim Wiederherstellen und nimmt höchstens 100 MB an (`APP_BACKUP_UPLOAD_MAX_MB`); größere Anfragen weist sie ab, bevor sie gelesen werden. Ein Backup sofort geht auch mit `make docker-backup` (oder `docker compose exec scheduler python manage.py backup_database`).

Damit die Backups auch außerhalb von Docker liegen, z. B. für ein Offsite-Backup, kannst du das Volume durch einen Ordner auf dem Server ersetzen. Er muss dem Benutzer mit der UID 1000 gehören:

```yaml
# compose.override.yaml, ersetzt das Volume für /backups
services:
  app:
    volumes: ["/srv/backups/lextracker:/backups"]
  scheduler:
    volumes: ["/srv/backups/lextracker:/backups"]
```

Beim Wiederherstellen in der Oberfläche sichert die App zuerst den aktuellen Stand (Datei mit `-vorher` im Namen), schreibt die Kopie mit der Backup-Funktion von SQLite in die laufende Datenbank und führt danach die Migrationen aus. App und Scheduler laufen dabei weiter. Kopien aus einer neueren Version der App lehnt sie ab. Startet die App gar nicht mehr, geht es auch von Hand: App stoppen (`docker compose down`), die gewünschte Kopie als `/data/db.sqlite3` zurückspielen und dabei `db.sqlite3-wal` und `db.sqlite3-shm` löschen, dann wieder starten.

### Update

```sh
docker compose pull
docker compose up -d
```

Compose lädt das neue Image und führt vor dem Start die Migrationen aus. Mit festgelegter `LEXTRACKER_VERSION` trägst du zuerst die neue Version in der `.env` ein. Vorher lohnt sich ein Backup (`make docker-backup`).

### IDs (UUID-Umstellung)

Alle Datensätze (Kunden, Projekte, Aufgaben, Zeiteinträge, Rechnungen, Benutzer …) haben eine UUID (Version 7, zeitlich sortierbar) als ID, auch in URLs, Formularen und im MCP-Server. Nur die Einzeleinträge der Einstellungen (Einstellungen, E-Mail-Versand, Lexware-Verbindung) behalten ihre feste interne Nummer 1. Beim Update einer älteren Instanz stellt die Migration `core.0011` alle IDs und Verweise um (auch in den Tabellen von django-otp und dem Admin-Log). Vorher legt `core.0010` eine Kopie mit `-vor-umstellung` im Namen im Backup-Ordner an. Danach sind alle angemeldeten Sitzungen ungültig (einmal neu anmelden), und Links mit den alten Nummern (Lesezeichen, verschickte Einladungen) liefern 404. Zurück auf die alte Version geht nur mit dieser Kopie: erst die alte Version starten, dann die Kopie wiederherstellen; in der neuen Version würde die Wiederherstellung sie sofort wieder umstellen.

## Entwicklung

Voraussetzung: [uv](https://docs.astral.sh/uv/getting-started/installation/) (installiert Python 3.15 bei Bedarf selbst).

### Lokal starten

```sh
make install     # Abhängigkeiten installieren, .env anlegen
make css         # Stylesheet bauen (lädt beim ersten Mal das Tailwind-CLI)
make migrate     # Datenbank anlegen (liegt in ./data)
make run         # http://localhost:8000
```

Beim ersten Aufruf führt die [Einrichtung](#schnellstart-docker-produktiv) durch das Anlegen des Admin-Kontos (das Konto geht alternativ mit `make superuser`). Den Einrichtungslink schreibt die App beim ersten Aufruf ins Terminal, alternativ zeigt ihn `uv run app/manage.py setup_link`.

Neue oder geänderte Texte übersetzt du mit `make messages` (siehe [Sprachen](#sprachen)).
Während du an Templates arbeitest, hält `make css-watch` in einem zweiten Terminal das Stylesheet aktuell.
Den automatischen Kundenimport und den E-Mail-Versand startest du lokal bei Bedarf mit `make scheduler`.
`make help` zeigt alle Befehle.

### Tests und Code-Stil

```sh
make test     # Testsuite (pytest)
make lint     # Code-Stil prüfen (ruff)
make format   # Code-Stil korrigieren
```

### Entwicklung mit Docker

Wer lieber im Container entwickelt (gleiche Basis und Python wie in Produktion), startet die Entwicklungsumgebung aus [dev.compose.yaml](dev.compose.yaml). Sie baut mit `extends` auf der `compose.yaml` auf und braucht ein aktuelles Docker Compose (getestet mit v5.6):

```sh
cp .env.example .env    # APP_SECRET_KEY setzen, für die Entwicklung genügt ein beliebiger Wert
make docker-dev         # oder: docker compose -f dev.compose.yaml watch
```

Das baut das Image aus dem lokalen Quelltext (die `compose.yaml` für den Betrieb nutzt dagegen das veröffentlichte Image), startet App und Scheduler auf http://localhost:8000 und beobachtet danach den Code:

- Änderungen unter `app/` werden in den Container kopiert; `uvicorn --reload` lädt bei Python-Dateien selbst neu, der Scheduler startet neu.
- Bei Änderungen an Templates, Skripten oder `assets/tailwind.css` wird zusätzlich das Stylesheet neu gebaut (`manage.py tailwind build`). Beim ersten Mal lädt das das Tailwind-CLI herunter; es bleibt in einem Volume erhalten. Die Seite lädst du selbst neu.
- Änderungen an `pyproject.toml`, `uv.lock` oder `docker/Dockerfile` bauen das Image neu.

Die Umgebung läuft als eigenes Compose-Projekt `lextracker-dev` mit eigenen Volumes und Containernamen, berührt also keine Produktionsdaten auf demselben Rechner. Sie nutzt `APP_ENVIRONMENT=development`, hört nur auf `127.0.0.1:8000`, und das Dateisystem ist beschreibbar, weil `watch` Dateien hineinkopiert.
Neue Migrationen wendest du mit `docker compose -f dev.compose.yaml exec app python manage.py migrate` an (beim Neustart laufen sie ohnehin). Zum Aufräumen: `make docker-dev-down`, mit `-v` an `docker compose -f dev.compose.yaml down` auch die Daten.

### Lasttest

Einen Last- und Performancetest mit Testdaten beschreibt [loadtest/README.md](loadtest/README.md) (`make loadtest`).

### Technik

| Bereich | Wahl | Warum |
| --- | --- | --- |
| Backend | Django 6, async Views, ASGI mit uvicorn | Login, Benutzer, Admin und Migrationen sind eingebaut; async Views blockieren sich nicht gegenseitig, z. B. bei langsamen API-Aufrufen an Lexware. |
| Oberfläche | Server-gerenderte Templates + [htmx](https://htmx.org) | Interaktive Seiten ohne eigenes JavaScript. |
| Styling | Tailwind CSS 4 über [django-tailwind-cli](https://github.com/django-commons/django-tailwind-cli), eigene Komponenten | Nutzt das Standalone-CLI, also kein Node.js nötig. Farben und Komponenten (`.btn`, `.card`, `.table`, `.badge` …) stehen in `app/assets/tailwind.css`, Icons kommen über `{% icon "name" %}` (`core/templatetags/icons.py`). Schrift ist Inter, selbst gehostet statt über Google Fonts. Hell- und Dunkelmodus folgen der Systemeinstellung. |
| Sprachen | Djangos i18n: Deutsch (Standard) und Englisch | Die Texte im Code und in den Templates sind deutsch, `app/locale/en` enthält die englische Übersetzung. Siehe [Sprachen](#sprachen). |
| Datenbank | SQLite (WAL-Modus) | Kein extra DB-Server. WAL erlaubt Lesen während geschrieben wird; das reicht für wenige Benutzer locker. |
| Statische Dateien | [ServeStatic](https://github.com/Archmonger/ServeStatic) | Liefert CSS/JS async, komprimiert und mit Cache-Headern aus. |
| Pakete | [uv](https://docs.astral.sh/uv/) | Schnell, mit Lockfile. |

#### Projektstruktur

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
  mailer/      E-Mail-Versand: SMTP-Einstellungen, Warteschlange, Wochenbericht, Erinnerungen und Hinweise
  reminders/   Erinnerungen zu Kunden und Projekten mit Benachrichtigung
  inbox/       Nachrichten an Benutzer: Glocke, Postfach, Prioritäten, Weitergabe per E-Mail
  setup/       Einrichtung einer neuen Instanz (Admin-Konto mit Zwei-Faktor-Anmeldung, Lexware-Schlüssel, Datensicherung)
  templates/   HTML-Templates
  assets/      Tailwind-Quelle mit Farben und eigenen Komponenten
  static/      Statische Dateien (htmx, gebautes CSS)
tests/
docker/
```

## Releases

Versionen entstehen aus den Commit-Nachrichten ([Conventional Commits](https://www.conventionalcommits.org/)): `fix:` erhöht die Patch-Version, `feat:` die Minor-Version, ein Breaking Change (`!` oder `BREAKING CHANGE:`) vor 1.0 ebenfalls die Minor-Version.
Auf `main` hält [release-please](https://github.com/googleapis/release-please) einen Pull Request „chore(main): release x.y.z“ aktuell. Mit seinem Merge steigt die Version in `pyproject.toml` und `uv.lock`, `CHANGELOG.md` wird ergänzt, und es entstehen der Tag `lextracker-vx.y.z` und das GitHub-Release.
Danach baut [build.yaml](.github/workflows/build.yaml) das Image für `linux/amd64` und `linux/arm64` und lädt es als `ghcr.io/maki-it/lextracker` mit den Tags `x.y.z`, `x.y` (ab 1.0 auch `x`) und `latest` hoch. Dasselbe Image lässt sich über „Run workflow“ für einen bestehenden Tag neu bauen.
Version, Commit und Bauzeitpunkt gibt der Workflow dem Image als Build-Argumente mit (`APP_VERSION`, `APP_COMMIT`, `APP_BUILD_DATE`); die App zeigt sie unter Einstellungen → Info zusammen mit dem Link zum Repo. Läuft die App aus dem Quellcode, liest sie die Version aus `pyproject.toml` und kennzeichnet sich als Entwicklungsstand.
Den Release-PR mergst du entweder selbst oder über Actions → Publish Release → Run workflow: Ohne Eingabe mergt der Workflow den offenen Release-PR mit der vorgeschlagenen Version, mit einer Version (z. B. `1.0.0`) setzt er sie zuerst per `Release-As`-Commit auf `main`, wartet, bis der Release-PR darauf umgestellt ist, und mergt ihn dann. Sind für `main` Checks als Pflicht eingestellt, schlägt das Mergen fehl, solange sie auf dem Release-PR nicht grün sind.
Damit das klappt, braucht das Repo eine GitHub App (Contents und Pull requests jeweils Read and write), die den Release-PR anlegt und dadurch auch CI darauf auslöst. Ihre App-ID steht als Variable `RELEASE_APP_ID`, ihr privater Schlüssel als Secret `RELEASE_APP_PRIVATE_KEY` unter Settings → Secrets and variables → Actions.
