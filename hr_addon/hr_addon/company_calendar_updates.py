"""
Stage 7.4c - Transaction-safe company-calendar refresh scheduling.

No HRMS source records are modified.
"""

import frappe


REFRESH_METHOD = (
    "hr_addon.hr_addon.company_calendar_updates."
    "refresh_private_company_calendar"
)

PENDING_FLAG = "_rm_company_calendar_refresh_registered"


def schedule_refresh(doc=None, method=None):
    """Schedule once per transaction, only after successful commit."""

    if getattr(frappe.flags, PENDING_FLAG, False):
        return

    setattr(frappe.flags, PENDING_FLAG, True)

    def clear_pending():
        setattr(frappe.flags, PENDING_FLAG, False)

    def enqueue_after_commit():
        try:
            # No global job deduplication: an edit committed while
            # another job runs must not be silently discarded.
            frappe.enqueue(
                REFRESH_METHOD,
                queue="short",
                timeout=300,
            )
        except Exception:
            # The database transaction has already committed.
            # Do not turn a successful HRMS save into a user error.
            # The daily reconciliation provides recovery.
            frappe.logger("company_calendar").exception(
                "Company calendar refresh could not be enqueued"
            )
        finally:
            clear_pending()

    frappe.db.after_commit.add(enqueue_after_commit)
    frappe.db.after_rollback.add(clear_pending)


def refresh_private_company_calendar():
    """Background job: rebuild snapshot only when bytes differ."""
    from hr_addon.hr_addon.company_calendar_ics import (
        write_private_company_calendar_snapshot,
    )

    return write_private_company_calendar_snapshot()


def daily_reconcile():
    """Daily safety net, including annual export-window rollover."""
    return refresh_private_company_calendar()
