// The service worker. It does only one thing: show the push notifications of the app and open the app when one
// is clicked. It caches nothing and does not touch requests.
// Served by push.views.service_worker.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
// The summary of a stopped timer is shown for this long, then it goes away.
const TIMER_END_SHOWN_MS = 8000;

async function closeTimerSummary() {
  for (const notification of await self.registration.getNotifications({ tag: "timer" })) {
    // Not the running timer of a timer that was started in the meantime.
    if (notification.data?.kind === "timer-end") notification.close();
  }
}

async function show(message) {
  const options = {
    body: message.body || "",
    icon: message.icon,
    data: { url: message.url || "/", kind: message.kind },
  };
  if (message.kind === "timer") {
    // One notification that stays (and is replaced, not added to) while the timer runs. It is silent, and the
    // time shown on it is the start of the timer.
    await self.registration.showNotification(message.title, {
      ...options,
      tag: "timer",
      requireInteraction: true,
      silent: true,
      timestamp: message.since,
    });
  } else if (message.kind === "timer-end") {
    // A push has to show something, so the end of the timer shows its duration for a moment.
    await self.registration.showNotification(message.title, { ...options, tag: "timer", silent: true });
    await sleep(TIMER_END_SHOWN_MS);
    await closeTimerSummary();
  } else {
    await self.registration.showNotification(message.title, { ...options, tag: message.tag });
  }
}

self.addEventListener("push", (event) => {
  let message = {};
  try {
    message = event.data.json();
  } catch {
    // Without a readable message there is still something to show: a push must not stay unanswered.
    message = { title: "Neue Nachricht", kind: "message" };
  }
  event.waitUntil(show(message));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/", self.location.origin).href;
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of windows) {
        if (new URL(client.url).origin !== self.location.origin) continue;
        // Navigating can fail for a window the worker does not control: then open a new one.
        try {
          await client.focus();
          return await client.navigate(url);
        } catch {
          break;
        }
      }
      return self.clients.openWindow(url);
    })(),
  );
});
