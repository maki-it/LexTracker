"""Load test for LexTracker: each simulated user logs in as one of the seeded accounts and clicks around.

See loadtest/README.md for how to run it.
"""

import os
import random
import re
from datetime import date, timedelta

from locust import HttpUser, between, constant, events, task

PASSWORD = "lasttest-123"
USERS = 10
HTMX = {"HX-Request": "true"}

_next_user = 0
_logged_in = 0
# IDs of tasks, projects and customers, read from the pages by the first user.
_ids_cache: dict[str, list[int]] = {}


@events.test_start.add_listener
def _reset_counter(environment, **kwargs) -> None:
    global _logged_in
    _logged_in = 0


def _login_name() -> str:
    global _next_user
    _next_user += 1
    return f"loadtest{(_next_user - 1) % USERS + 1:02d}"


def _ids(html: str, pattern: str) -> list[int]:
    return sorted({int(m) for m in re.findall(pattern, html)})


class Kim(HttpUser):
    """Someone working in the app: mostly the dashboard, the week view and the timer, now and then the rest."""

    # Pause between two clicks. LOADTEST_WAIT=0 clicks without pause, to find the maximum throughput.
    wait_time = constant(0) if os.environ.get("LOADTEST_WAIT") == "0" else between(1, 3)

    def on_start(self) -> None:
        page = self.client.get("/accounts/login/", name="/accounts/login/")
        self.client.post(
            "/accounts/login/",
            {"username": _login_name(), "password": PASSWORD, "csrfmiddlewaretoken": self._csrf(page.text)},
            name="/accounts/login/ [POST]",
        )
        self.csrf = self.client.cookies.get("csrftoken", "")
        if not _ids_cache:
            start_form = self.client.get("/zeiten/timer/start/", headers=HTMX, name="/zeiten/timer/start/").text
            _ids_cache["tasks"] = _ids(start_form, r'<option value="(\d+)"')
            _ids_cache["projects"] = _ids(self.client.get("/projekte/").text, r'href="/projekte/(\d+)/"')
            _ids_cache["customers"] = _ids(self.client.get("/kunden/").text, r'href="/kunden/(\d+)/"')
        self.task_ids, self.projects, self.customers = (_ids_cache[k] for k in ("tasks", "projects", "customers"))
        # Once everyone is logged in, start counting afresh: logins are rare in real use.
        global _logged_in
        _logged_in += 1
        if _logged_in == self.environment.runner.target_user_count:
            self.environment.stats.reset_all()

    @staticmethod
    def _csrf(html: str) -> str:
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
        return match.group(1) if match else ""

    def _post(self, url: str, data: dict | None = None, name: str | None = None, **kwargs):
        headers = {"X-CSRFToken": self.csrf, "Referer": self.host + url, **kwargs.pop("headers", {})}
        return self.client.post(url, data or {}, headers=headers, name=name or url, **kwargs)

    @task(6)
    def dashboard(self) -> None:
        self.client.get("/", name="/")

    @task(6)
    def timer_badge(self) -> None:
        # The sidebar reloads it every minute in every open tab.
        self.client.get("/zeiten/timer/", headers=HTMX, name="/zeiten/timer/")

    @task(5)
    def week(self) -> None:
        self.client.get("/zeiten/", name="/zeiten/")

    @task(2)
    def older_week(self) -> None:
        day = date.today() - timedelta(weeks=random.randint(1, 100))
        year, week, _ = day.isocalendar()
        self.client.get(f"/zeiten/?woche={year}-W{week:02d}", name="/zeiten/?woche=…")

    @task(3)
    def start_and_stop_timer(self) -> None:
        if not self.task_ids:
            return
        self._post("/zeiten/timer/start/", {"task": random.choice(self.task_ids)}, headers=HTMX)
        self._post("/zeiten/timer/stop/", headers=HTMX)

    @task(2)
    def book_time(self) -> None:
        if not self.task_ids:
            return
        self.client.get("/zeiten/neu/", name="/zeiten/neu/")
        start = date.today() - timedelta(days=random.randint(0, 14))
        hour = random.randint(7, 17)
        self._post(
            "/zeiten/neu/",
            {
                "task": random.choice(self.task_ids),
                "started_at": f"{start}T{hour:02d}:00",
                "ended_at": f"{start}T{hour + 1:02d}:30",
                "description": "Lasttest",
                "is_billable": "on",
            },
            name="/zeiten/neu/ [POST]",
        )

    @task(2)
    def customers_page(self) -> None:
        self.client.get("/kunden/", name="/kunden/")

    @task(1)
    def customer_search(self) -> None:
        self.client.get(f"/kunden/?q={random.randint(1, 299):04d}", headers=HTMX, name="/kunden/?q=…")

    @task(2)
    def projects_page(self) -> None:
        self.client.get("/projekte/", name="/projekte/")

    @task(2)
    def project_detail(self) -> None:
        if self.projects:
            self.client.get(f"/projekte/{random.choice(self.projects)}/", name="/projekte/[id]/")

    @task(1)
    def billing(self) -> None:
        self.client.get("/abrechnung/", name="/abrechnung/")

    @task(1)
    def customer_billing(self) -> None:
        if self.customers:
            self.client.get(f"/abrechnung/kunde/{random.choice(self.customers)}/", name="/abrechnung/kunde/[id]/")

    @task(1)
    def invoices(self) -> None:
        self.client.get("/abrechnung/rechnungen/", name="/abrechnung/rechnungen/")

    @task(1)
    def reports(self) -> None:
        period = random.choice(["monat", "quartal", "jahr", "vorjahr"])
        self.client.get(f"/auswertungen/?zeitraum={period}", name="/auswertungen/?zeitraum=…")

    @task(1)
    def csv_export(self) -> None:
        if random.random() < 0.2:
            self.client.get("/auswertungen/zeiten.csv?zeitraum=jahr", name="/auswertungen/zeiten.csv")
