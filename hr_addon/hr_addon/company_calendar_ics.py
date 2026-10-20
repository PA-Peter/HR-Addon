# Copyright (c) 2026, RieckMedia
# For license information, please see license.txt

"""
Stage 7.4c - Internal HRMS company-calendar generator.

Produces iCalendar bytes only. No public endpoint, file writes
or changes to HRMS source records.

Only explicitly approved publication data may enter this feed.
"""

from datetime import date, datetime, time, timedelta, timezone
from html import unescape
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import (
    cint,
    getdate,
    get_datetime,
    get_timedelta,
    strip_html_tags,
)
from icalendar import Calendar, Event


LOCAL_TZ = ZoneInfo("Europe/Berlin")
VACATION_TYPES = frozenset({"Urlaub"})

COMPANY = "RieckMedia"
REFERENCE_HOLIDAY_LIST = "RM Firmenkalender RLP 2026-2027"


def _uid(source, name, suffix=""):
    """Opaque and stable calendar identity, without raw record IDs."""
    value = f"rieckmedia:company-calendar:{source}:{name}:{suffix}"
    return f"{uuid5(NAMESPACE_URL, value).hex}@kalender.rieckmedia.com"


def _stamp(modified):
    """Stable UTC timestamp based on the source record."""
    value = get_datetime(modified)

    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL_TZ)

    return value.astimezone(timezone.utc)


def _event(summary, uid, modified, start, end,
           location=None, all_day=True):
    event = Event()

    event.add("uid", uid)
    event.add("summary", summary)
    event.add("dtstamp", _stamp(modified))
    event.add("last-modified", _stamp(modified))
    event.add("status", "CONFIRMED")

    if all_day:
        # RFC 5545: DTEND is exclusive.
        event.add("dtstart", start)
        event.add("dtend", end + timedelta(days=1))
    else:
        event.add("dtstart", start)
        event.add("dtend", end)

    if location:
        event.add("location", location)

    # No DESCRIPTION, CONTACT, ATTENDEE or ORGANIZER.
    return event


def _clock(value):
    duration = get_timedelta(value)
    seconds = int(duration.total_seconds())

    if not 0 <= seconds < 86400:
        raise ValueError("Invalid company-event time")

    return time(
        hour=seconds // 3600,
        minute=(seconds % 3600) // 60,
        second=seconds % 60,
    )


def _utc_datetime(day, clock):
    local = datetime.combine(
        getdate(day),
        _clock(clock),
        tzinfo=LOCAL_TZ,
    )
    return local.astimezone(timezone.utc)


def _add_approved_leaves(calendar, first, last):
    employee_ids = frappe.get_all(
        "Employee",
        filters={"company": COMPANY},
        pluck="name",
        limit_page_length=0,
    )

    if not employee_ids:
        return 0

    rows = frappe.get_all(
        "Leave Application",
        filters={
            "employee": ["in", employee_ids],
            "docstatus": 1,
            "status": "Approved",
            "from_date": ["<=", last],
            "to_date": [">=", first],
        },
        fields=[
            "name",
            "employee_name",
            "leave_type",
            "from_date",
            "to_date",
            "half_day",
            "half_day_date",
            "modified",
        ],
        order_by="from_date asc, name asc",
        limit_page_length=0,
    )

    count = 0

    for row in rows:
        start = getdate(row.from_date)
        end = getdate(row.to_date)

        if end < start:
            continue

        public_type = (
            "Urlaub"
            if row.leave_type in VACATION_TYPES
            else "abwesend"
        )

        summary = f"{row.employee_name} – {public_type}"

        # A half-day must not imply invented start/end times.
        if cint(row.half_day):
            half_day = (
                getdate(row.half_day_date)
                if row.half_day_date
                else start
            )

            current = max(start, first)

            while current <= min(end, last):
                title = summary

                if current == half_day:
                    title += " (halbtags)"

                calendar.add_component(
                    _event(
                        title,
                        _uid("leave", row.name, str(current)),
                        row.modified,
                        current,
                        current,
                    )
                )

                count += 1
                current += timedelta(days=1)

        else:
            calendar.add_component(
                _event(
                    summary,
                    _uid("leave", row.name),
                    row.modified,
                    start,
                    end,
                )
            )
            count += 1

    return count


def _annual_date(original, year):
    """Do not invent a Feb 29 observation date in non-leap years."""
    original = getdate(original)

    try:
        return date(year, original.month, original.day)
    except ValueError:
        return None


def _add_employee_anniversaries(calendar, first, last):
    employees = frappe.get_all(
        "Employee",
        filters={
            "status": "Active",
            "company": COMPANY,
        },
        fields=[
            "name",
            "employee_name",
            "date_of_birth",
            "date_of_joining",
            "modified",
        ],
        order_by="name asc",
        limit_page_length=0,
    )

    count = 0

    for employee in employees:
        if not employee.employee_name:
            continue

        for year in range(first.year, last.year + 1):
            if employee.date_of_birth:
                birthday = _annual_date(
                    employee.date_of_birth, year
                )

                if birthday and first <= birthday <= last:
                    calendar.add_component(
                        _event(
                            f"{employee.employee_name} – Geburtstag",
                            _uid("birthday", employee.name, str(year)),
                            employee.modified,
                            birthday,
                            birthday,
                        )
                    )
                    count += 1

            if employee.date_of_joining:
                joined = getdate(employee.date_of_joining)
                anniversary = _annual_date(joined, year)

                if (
                    anniversary
                    and joined.year < year
                    and first <= anniversary <= last
                ):
                    years = year - joined.year

                    calendar.add_component(
                        _event(
                            f"{employee.employee_name} – "
                            f"Firmenjubiläum ({years} Jahre)",
                            _uid(
                                "anniversary",
                                employee.name,
                                str(year),
                            ),
                            employee.modified,
                            anniversary,
                            anniversary,
                        )
                    )
                    count += 1

    return count



def _add_reference_holidays(calendar, first, last):
    """Publish RLP holidays without changing employee Workdays."""

    reference = frappe.db.get_value(
        "Holiday List",
        REFERENCE_HOLIDAY_LIST,
        ["from_date", "to_date", "modified"],
        as_dict=True,
    )

    if not reference:
        raise ValueError("RLP reference holiday list missing")

    rows = frappe.get_all(
        "Holiday",
        filters={
            "parent": REFERENCE_HOLIDAY_LIST,
            "weekly_off": 0,
            "holiday_date": ["between", [first, last]],
        },
        fields=[
            "holiday_date",
            "description",
            "is_half_day",
        ],
        order_by="holiday_date asc",
        limit_page_length=0,
    )

    seen_dates = set()

    for row in rows:
        day = getdate(row.holiday_date)

        if day in seen_dates:
            raise ValueError("Duplicate reference holiday date")

        seen_dates.add(day)

        title = unescape(
            strip_html_tags(row.description or "")
        ).strip()

        if not title:
            raise ValueError("Reference holiday without title")

        if cint(row.is_half_day):
            title += " (halbtags)"

        calendar.add_component(
            _event(
                title,
                _uid(
                    "holiday",
                    REFERENCE_HOLIDAY_LIST,
                    day.isoformat(),
                ),
                reference.modified,
                day,
                day,
            )
        )

    return len(rows)

def _add_company_events(calendar, first, last):
    rows = frappe.get_all(
        "Company Calendar Event",
        filters={
            "is_published": 1,
            "start_date": ["<=", last],
            "end_date": [">=", first],
        },
        fields=[
            "name",
            "title",
            "location",
            "start_date",
            "end_date",
            "all_day",
            "start_time",
            "end_time",
            "modified",
        ],
        order_by="start_date asc, name asc",
        limit_page_length=0,
    )

    for row in rows:
        start = getdate(row.start_date)
        end = getdate(row.end_date)

        if cint(row.all_day):
            event = _event(
                row.title,
                _uid("company", row.name),
                row.modified,
                start,
                end,
                location=row.location,
            )
        else:
            event = _event(
                row.title,
                _uid("company", row.name),
                row.modified,
                _utc_datetime(start, row.start_time),
                _utc_datetime(end, row.end_time),
                location=row.location,
                all_day=False,
            )

        calendar.add_component(event)

    return len(rows)



def _add_imported_calendar_events(calendar, first, last):
    """Merge an optional, preprocessed private ICS without recalculation."""
    from pathlib import Path

    directory = Path(
        frappe.get_site_path("private", "calendar_import")
    )
    source = directory / "muell_firma.ics"

    if directory.is_symlink() or source.is_symlink():
        raise ValueError("Unexpected calendar-import symlink")

    if not source.exists():
        return 0

    if not source.is_file() or source.stat().st_size > 2_000_000:
        raise ValueError("Invalid calendar-import file")

    imported = Calendar.from_ical(source.read_bytes())
    events = imported.walk("VEVENT")

    if not 0 < len(events) <= 500:
        raise ValueError("Invalid calendar-import event count")

    known_uids = {
        str(event.get("UID"))
        for event in calendar.walk("VEVENT")
    }

    count = 0

    for event in events:
        uid = str(event.get("UID") or "").strip()
        start = event.decoded("DTSTART")
        end = event.decoded("DTEND")

        if not uid or uid in known_uids:
            raise ValueError("Missing or duplicate imported UID")

        known_uids.add(uid)

        if (
            not isinstance(start, date)
            or isinstance(start, datetime)
            or not isinstance(end, date)
            or isinstance(end, datetime)
            or end != start + timedelta(days=1)
        ):
            raise ValueError("Imported event must be all-day")

        if str(event.get("TRANSP", "")).upper() != "TRANSPARENT":
            raise ValueError("Imported event must be non-blocking")

        if any(
            field in event
            for field in ("LOCATION", "ATTENDEE", "ORGANIZER", "CONTACT")
        ):
            raise ValueError("Private fields in imported calendar")

        alarms = [
            part for part in event.subcomponents
            if part.name == "VALARM"
        ]

        if len(alarms) != 1:
            raise ValueError("Imported event needs one alarm")

        alarm = alarms[0]
        trigger = alarm.decoded("TRIGGER")

        if (
            str(alarm.get("ACTION", "")).upper() != "DISPLAY"
            or not isinstance(trigger, datetime)
            or trigger.tzinfo is None
        ):
            raise ValueError("Invalid imported calendar alarm")

        if first <= start <= last:
            # Preserve UID, event properties and existing VALARM.
            calendar.add_component(event)
            count += 1

    return count


def generate_company_calendar_ics(first_year, last_year):
    """
    Internal use only. Returns (ics_bytes, counts).

    The caller decides where to store the generated bytes.
    This method does not authenticate public requests.
    """
    first_year = int(first_year)
    last_year = int(last_year)

    if (
        first_year < 2000
        or last_year > 2100
        or last_year < first_year
        or last_year - first_year > 5
    ):
        raise ValueError("Invalid calendar export period")

    first = date(first_year, 1, 1)
    last = date(last_year, 12, 31)

    calendar = Calendar()
    calendar.add("prodid", "-//RieckMedia//HRMS Company Calendar//DE")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", "RieckMedia Firmenkalender")

    counts = {
        "leaves": _add_approved_leaves(calendar, first, last),
        "anniversaries": _add_employee_anniversaries(
            calendar, first, last
        ),
        "holidays": _add_reference_holidays(
            calendar, first, last
        ),
        "company_events": _add_company_events(
            calendar, first, last
        ),
    }

    counts["imported_ics"] = _add_imported_calendar_events(
        calendar, first, last
    )

    return calendar.to_ical(), counts



def _snapshot_matches(existing, generated):
    """True only if the published calendar bytes are identical."""
    return existing is not None and existing == generated


def write_private_company_calendar_snapshot():
    """
    Reconcile the private, persistent company calendar.

    - All readers see complete ICS files.
    - Concurrent writers are serialized across containers.
    - Unchanged files are not replaced.
    - No public endpoint or HRMS source modifications.
    """
    import fcntl
    import hashlib
    import os
    import tempfile
    from pathlib import Path

    current_year = getdate(frappe.utils.nowdate()).year

    directory = Path(
        frappe.get_site_path("private", "calendar_export")
    )

    target = directory / "firmenkalender.ics"
    lock_path = directory / ".firmenkalender.lock"

    if directory.is_symlink():
        raise ValueError("Unexpected calendar-directory symlink")

    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)

    if target.is_symlink() or lock_path.is_symlink():
        raise ValueError("Unexpected calendar-file symlink")

    flags = (
        os.O_CREAT
        | os.O_RDWR
        | os.O_NOFOLLOW
    )

    lock_fd = os.open(str(lock_path), flags, 0o600)

    try:
        os.fchmod(lock_fd, 0o600)

        # Shared lock across backend, scheduler and worker
        # containers using the persistent sites volume.
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        payload, counts = generate_company_calendar_ics(
            current_year - 1,
            current_year + 2,
        )

        parsed = Calendar.from_ical(payload)
        actual_count = len(parsed.walk("VEVENT"))

        if actual_count != sum(counts.values()):
            raise ValueError("ICS event-count validation failed")

        if target.is_symlink():
            raise ValueError("Unexpected snapshot symlink")

        existing = None

        if target.exists():
            if not target.is_file():
                raise ValueError("Snapshot is not a regular file")

            if target.stat().st_mode & 0o077:
                raise ValueError(
                    "Snapshot file permissions are too broad"
                )

            existing = target.read_bytes()

        changed = not _snapshot_matches(existing, payload)

        if changed:
            temporary = None

            try:
                descriptor, temporary = tempfile.mkstemp(
                    prefix=".firmenkalender-",
                    suffix=".tmp",
                    dir=str(directory),
                )

                with os.fdopen(descriptor, "wb") as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())

                os.replace(temporary, target)
                temporary = None

                directory_fd = os.open(
                    str(directory),
                    os.O_RDONLY | os.O_DIRECTORY,
                )

                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)

            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)

        return {
            "path": str(target),
            "changed": changed,
            "bytes": len(payload),
            "sha256": hashlib.sha256(
                payload
            ).hexdigest(),
            "events": actual_count,
            "counts": counts,
            "years": [
                current_year - 1,
                current_year + 2,
            ],
        }

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
