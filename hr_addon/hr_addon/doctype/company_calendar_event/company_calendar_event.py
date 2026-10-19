# Copyright (c) 2026, RieckMedia
# For license information, please see license.txt

"""Neutral company calendar events.

No effects on Workday, Attendance, Leave or Time Account.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, get_timedelta


class CompanyCalendarEvent(Document):

    def validate(self):
        self._validate_title()
        self._validate_dates()
        self._validate_times()

    def _validate_title(self):
        self.title = str(self.title or "").strip()

        if not self.title:
            frappe.throw(
                _("An event title is required.")
            )

    def _validate_dates(self):
        if not self.start_date:
            frappe.throw(
                _("A start date is required.")
            )

        if not self.end_date:
            self.end_date = self.start_date

        if getdate(self.end_date) < getdate(self.start_date):
            frappe.throw(
                _("End date cannot be before start date.")
            )

    def _validate_times(self):
        if self.all_day:
            self.start_time = None
            self.end_time = None
            return

        if not self.start_time or not self.end_time:
            frappe.throw(
                _("Timed events require start and end times.")
            )

        if (
            getdate(self.start_date) == getdate(self.end_date)
            and get_timedelta(self.end_time)
            <= get_timedelta(self.start_time)
        ):
            frappe.throw(
                _("End time must be after start time.")
            )
