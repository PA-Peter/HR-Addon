# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

"""Suppress misleading leave-balance warnings for unlimited sick leave.

Only applies to the configured paid, negative-balance-enabled
leave type "Krankheit". All other HRMS validations remain active.
"""

import frappe
from frappe.utils import cint


class SickLeaveBalanceWarningMixin:
    def show_insufficient_balance_message(
        self,
        leave_balance_for_consumption: float,
    ) -> None:
        if self.leave_type == "Krankheit":
            configuration = frappe.db.get_value(
                "Leave Type",
                self.leave_type,
                ["allow_negative", "is_lwp"],
                as_dict=True,
            )

            if (
                configuration
                and cint(configuration.allow_negative)
                and not cint(configuration.is_lwp)
            ):
                # No finite leave allocation is intended
                # for this unlimited sick-leave type.
                # Leave validation, overlap and attendance
                # processing are deliberately untouched.
                return

        return super().show_insufficient_balance_message(
            leave_balance_for_consumption
        )
