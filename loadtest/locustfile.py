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
_ids_cache: dict[str, list[str]] = {}


@events.test_start.add_listener
def _reset_counter(environment, **kwargs) -> None:
    global _logged_in
    _logged_in = 0


def _login_name() -> str:
    global _next_user
    _next_user += 1
    return f"loadtest{(_next_user - 1) % USERS + 1:02d}"


UUID = r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"


def _ids(html: str, pattern: str) -> list[str]:
    return sorted(set(re.findall(pattern, html)))


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
            start_form = self.client.get("/time/timer/start/", headers=HTMX, name="/time/timer/start/").text
            _ids_cache["tasks"] = _ids(start_form, rf'<option value="{UUID}"')
            _ids_cache["projects"] = _ids(self.client.get("/projects/").text, rf'href="/projects/{UUID}/"')
            _ids_cache["customers"] = _ids(self.client.get("/customers/").text, rf'href="/customers/{UUID}/"')
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
        self.client.get("/time/timer/", headers=HTMX, name="/time/timer/")

    @task(5)
    def week(self) -> None:
        self.client.get("/time/", name="/time/")

    @task(2)
    def older_week(self) -> None:
        day = date.today() - timedelta(weeks=random.randint(1, 100))
        year, week, _ = day.isocalendar()
        self.client.get(f"/time/?week={year}-W{week:02d}", name="/time/?week=…")

    @task(3)
    def start_and_stop_timer(self) -> None:
        if not self.task_ids:
            return
        self._post("/time/timer/start/", {"task": random.choice(self.task_ids)}, headers=HTMX)
        self._post("/time/timer/stop/", headers=HTMX)

    @task(2)
    def book_time(self) -> None:
        if not self.task_ids:
            return
        self.client.get("/time/new/", name="/time/new/")
        start = date.today() - timedelta(days=random.randint(0, 14))
        hour = random.randint(7, 17)
        self._post(
            "/time/new/",
            {
                "task": random.choice(self.task_ids),
                "started_at": f"{start}T{hour:02d}:00",
                "ended_at": f"{start}T{hour + 1:02d}:30",
                "description": "Lasttest",
                "is_billable": "on",
            },
            name="/time/new/ [POST]",
        )

    @task(2)
    def customers_page(self) -> None:
        self.client.get("/customers/", name="/customers/")

    @task(1)
    def customer_search(self) -> None:
        self.client.get(f"/customers/?q={random.randint(1, 299):04d}", headers=HTMX, name="/customers/?q=…")

    @task(2)
    def projects_page(self) -> None:
        self.client.get("/projects/", name="/projects/")

    @task(2)
    def project_detail(self) -> None:
        if self.projects:
            self.client.get(f"/projects/{random.choice(self.projects)}/", name="/projects/[id]/")

    @task(1)
    def billing(self) -> None:
        self.client.get("/billing/", name="/billing/")

    @task(1)
    def customer_billing(self) -> None:
        if self.customers:
            self.client.get(f"/billing/customer/{random.choice(self.customers)}/", name="/billing/customer/[id]/")

    @task(1)
    def invoices(self) -> None:
        self.client.get("/billing/invoices/", name="/billing/invoices/")

    @task(1)
    def reports(self) -> None:
        period = random.choice(["month", "quarter", "year", "last-year"])
        self.client.get(f"/reports/?range={period}", name="/reports/?range=…")

    @task(1)
    def csv_export(self) -> None:
        if random.random() < 0.2:
            self.client.get("/reports/time.csv?range=year", name="/reports/time.csv")
