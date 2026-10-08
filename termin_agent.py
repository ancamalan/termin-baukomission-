#!/usr/bin/env python3
"""
Termin-Agent: Registratur Bauvorhaben (LBK München)
Checks the booking page for free Tuesday/Thursday slots and optionally books.

Optional: NTFY_TOPIC=my-topic  -> push notification via https://ntfy.sh
Optional: HEADLESS=1, INTERVAL=300 (seconds between checks), ONCE=1
"""
import os, re, time, datetime as dt, urllib.request
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = ("https://stadt.muenchen.de/buergerservice/terminvereinbarung.html"
       "#/services/10317257/locations/10234374")
WANTED_WEEKDAYS = {1, 3}  # Monday=0 -> Tuesday=1, Thursday=3
DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})?")
INTERVAL = int(os.getenv("INTERVAL", "300"))
BOOK = os.getenv("BOOK") == "1"


def notify(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}")
    topic = os.getenv("NTFY_TOPIC")
    if topic:
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"https://ntfy.sh/{topic}", data=msg.encode(), method="POST"))
        except Exception as e:
            print("ntfy failed:", e)


def dismiss_cookies(page):
    for label in ("Alle akzeptieren", "Akzeptieren", "Nur notwendige", "Ablehnen"):
        btn = page.get_by_role("button", name=re.compile(label, re.I))
        if btn.count():
            try:
                btn.first.click(timeout=2000)
                return
            except PWTimeout:
                pass


def parse_date(text):
    m = DATE_RE.search(text)
    if not m:
        return None
    d, mo, y = int(m[1]), int(m[2]), int(m[3] or dt.date.today().year)
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def collect_slots(page):
    """Return [(date, element)] for enabled date/time controls on Tue/Thu."""
    hits = []
    loc = page.locator("button, [role=button], a, td, li")
    for i in range(min(loc.count(), 600)):
        el = loc.nth(i)
        try:
            text = (el.get_attribute("aria-label") or el.inner_text(timeout=300) or "").strip()
            disabled = el.get_attribute("disabled") is not None or \
                el.get_attribute("aria-disabled") == "true"
        except Exception:
            continue
        d = parse_date(text)
        if d and not disabled and d >= dt.date.today() and d.weekday() in WANTED_WEEKDAYS:
            hits.append((d, text, el))
    return hits


def advance_to_calendar(page):
    """Click through intro steps until a calendar/date list shows up."""
    for label in ("Termin buchen", "Weiter", "Termin vereinbaren", "Zum Kalender"):
        btn = page.get_by_role("button", name=re.compile(label, re.I))
        if btn.count():
            try:
                btn.first.click(timeout=2000)
                page.wait_for_timeout(1200)
            except PWTimeout:
                pass


def try_book(page, el):
    el.click()
    page.wait_for_timeout(1000)
    times = page.get_by_role("button", name=re.compile(r"\b\d{1,2}:\d{2}\b"))
    if times.count():
        times.first.click()
        page.wait_for_timeout(800)
    for label in ("Weiter", "Termin auswählen"):
        b = page.get_by_role("button", name=re.compile(label, re.I))
        if b.count():
            b.first.click()
            page.wait_for_timeout(1000)
    fields = {"name": os.getenv("NAME"), "mail": os.getenv("EMAIL"),
              "telefon|phone": os.getenv("PHONE")}
    for pattern, value in fields.items():
        if value:
            f = page.get_by_label(re.compile(pattern, re.I))
            if f.count():
                f.first.fill(value)
    for cb in page.get_by_role("checkbox").all():
        try:
            cb.check()
        except Exception:
            pass
    page.screenshot(path="termin_booking_form.png", full_page=True)
    notify("Booking form filled. Review it in the browser window and confirm manually.")


def check_once(page):
    page.goto(URL, wait_until="networkidle")
    dismiss_cookies(page)
    advance_to_calendar(page)
    for _ in range(3):
        slots = collect_slots(page)
        if slots:
            return slots
        nxt = page.get_by_role("button", name=re.compile(r"(nächst|weiter|vor)", re.I))
        if not nxt.count():
            break
        try:
            nxt.first.click(timeout=1500)
            page.wait_for_timeout(1000)
        except PWTimeout:
            break
    return []


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=os.getenv("HEADLESS") == "1")
        page = browser.new_page(locale="de-DE")
        while True:
            try:
                slots = check_once(page)
            except Exception as e:
                notify(f"Check failed: {e}")
                slots = []
            if slots:
                days = sorted({f"{d:%a %d.%m.%Y}" for d, _, _ in slots})
                notify("Free Tue/Thu slots: " + ", ".join(days))
                if BOOK:
                    try_book(page, slots[0][2])
                    input("Press Enter to close the browser...")
                    break
                page.screenshot(path="termin_slots.png", full_page=True)
            else:
                print("No Tuesday/Thursday slots right now.")
            if os.getenv("ONCE") == "1":
                break
            time.sleep(INTERVAL)
        browser.close()


if __name__ == "__main__":
    main()
