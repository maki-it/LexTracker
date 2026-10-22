# Lasttest

Ein wiederholbarer Last- und Performancetest mit [Locust](https://locust.io). Simulierte Benutzer melden sich an und klicken sich durch die App: Übersicht, Woche, Timer starten und stoppen, Zeiten buchen, Kunden, Projekte, Abrechnung, Auswertungen und CSV-Export. Lexware wird nie angesprochen: Die Testkunden haben keine Lexware-ID, und ohne `APP_LEXWARE_API_KEY` gibt es keinen Abgleich.

| Datei | Zweck |
| --- | --- |
| `seed.py` | Füllt eine **leere** Datenbank mit Testdaten (Standard: 300 Kunden, 900 Projekte, 3.600 Aufgaben, 25.000 Zeiteinträge über zwei Jahre, ältere davon abgerechnet, 10 Logins `loadtest01` bis `loadtest10` mit Passwort `lasttest-123`). Bricht ab, wenn schon Kunden da sind. |
| `locustfile.py` | Was ein Benutzer tut und wie oft. Pause zwischen zwei Klicks 1 bis 3 Sekunden, mit `LOADTEST_WAIT=0` ohne Pause. |
| `run.sh` | Läuft nacheinander mit 5, 10, 20 und 40 Benutzern (`LEVELS`), je 60 Sekunden, und legt die CSV-Dateien unter `loadtest/results/` ab. Die Anmeldungen zählen nicht mit. |
| `summary.py` | Fasst einen Lauf als Tabelle zusammen (Anfragen pro Sekunde, p50/p95/p99, langsamste Seiten). |

## Gegen den Docker-Container

Nie gegen die echte Datenbank laufen lassen. Ein eigenes Volume hält die Testdaten getrennt:

```sh
docker build -f docker/Dockerfile -t lextracker:loadtest .
docker volume create lextracker-loadtest

# Datenbank anlegen und füllen
docker run --rm -v lextracker-loadtest:/data -v "$PWD/loadtest:/loadtest:ro" -e APP_SECRET_KEY=loadtest \
  lextracker:loadtest sh -c "python manage.py migrate && python /loadtest/seed.py"

# App starten, begrenzt auf 2 CPUs wie ein kleiner Server
docker run -d --name lextracker-loadtest --cpus 2 -p 8000:8000 -v lextracker-loadtest:/data \
  -e APP_SECRET_KEY=loadtest -e APP_ALLOWED_HOSTS='*' -e APP_SECURE_COOKIES=false -e UVICORN_WORKERS=1 \
  --read-only --tmpfs /tmp lextracker:loadtest

make loadtest                                   # oder: loadtest/run.sh http://localhost:8000 60
LOADTEST_WAIT=0 LEVELS="1 4" loadtest/run.sh    # maximaler Durchsatz

docker rm -f lextracker-loadtest && docker volume rm lextracker-loadtest
```

Die Größe der Testdaten stellst du mit `seed.py --customers 40 --projects-per-customer 2 --entries 5000` usw. ein (`--help` zeigt alles).
Locust selbst wird über `uv run --with locust` geholt und ist keine Abhängigkeit der App. Mit `uv run --with locust locust -f loadtest/locustfile.py -H http://localhost:8000` gibt es die Weboberfläche unter http://localhost:8089.

## Ohne Docker

```sh
cd app
APP_DATA_DIR=/tmp/lextracker-loadtest uv run python manage.py migrate
APP_DATA_DIR=/tmp/lextracker-loadtest uv run python ../loadtest/seed.py
APP_DATA_DIR=/tmp/lextracker-loadtest uv run uvicorn config.asgi:application --port 8000
```
