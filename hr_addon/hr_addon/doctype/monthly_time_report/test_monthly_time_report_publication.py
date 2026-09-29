# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

from datetime import datetime
from unittest.mock import MagicMock, patch

import frappe

from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report import (
    SERVICE_FLAG,
    STATUS_GENERATED,
    STATUS_SUPERSEDED,
)
from hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report_publication import (
    PDF_OPTIONS,
    PDF_TEMPLATE,
    _assert_publication_state,
    _assert_revision_source,
    _create_revision_snapshot,
    _employee_document_values,
    _save_private_pdf,
    build_pdf_context,
    create_and_publish_monthly_time_report,
    format_minutes,
    publish_monthly_time_report,
    regenerate_and_publish_monthly_time_report,
    render_monthly_time_report_pdf,
)


IGNORE_TEST_RECORD_DEPENDENCIES = [
    "Employee",
    "User",
    "Employee Document",
    "Workday",
    "Leave Application",
    "Leave Type",
    "Time Account Ledger Entry",
    "DocType",
    "File",
]


MODULE = (
    "hr_addon.hr_addon.doctype."
    "monthly_time_report."
    "monthly_time_report_publication"
)


class TestMonthlyTimeReportPublication(
    IntegrationTestCase
):
    def _day(
        self,
        **overrides,
    ):
        values = {
            "report_date": (
                getdate(
                    "2026-08-03"
                )
            ),
            "snapshot_status": (
                "OK"
            ),
            "checkins_text": (
                "08:00 IN · 16:30 OUT"
            ),
            "leave_type": None,
            "leave_portion": None,
            "target_minutes": 480,
            "raw_work_minutes": 480,
            "physical_break_minutes": 30,
            "automatic_break_deduction_minutes": 0,
            "absence_credit_minutes": 0,
            "accountable_minutes": 480,
            "daily_delta_minutes": 0,
        }

        values.update(
            overrides
        )

        return frappe._dict(
            values
        )

    def _ledger(
        self,
        **overrides,
    ):
        values = {
            "effective_date": (
                getdate(
                    "2026-08-03"
                )
            ),
            "entry_type": (
                "Positive Adjustment"
            ),
            "delta_minutes": 60,
            "remarks": (
                "Korrektur"
            ),
        }

        values.update(
            overrides
        )

        return frappe._dict(
            values
        )

    def _report(
        self,
        **overrides,
    ):
        values = {
            "name": (
                "MTR-2026-00001"
            ),
            "employee": (
                "HR-EMP-00001"
            ),
            "employee_name": (
                "Christian Gold"
            ),
            "report_year": 2026,
            "report_month": 8,
            "period_from": (
                getdate(
                    "2026-08-01"
                )
            ),
            "period_to": (
                getdate(
                    "2026-08-31"
                )
            ),
            "generated_at": (
                datetime(
                    2026,
                    9,
                    3,
                    8,
                    0,
                    0,
                )
            ),
            "revision": 1,
            "previous_revision": None,
            "is_current_revision": 1,
            "status": (
                STATUS_GENERATED
            ),
            "is_complete": 1,
            "blocking_issue_count": 0,
            "opening_balance_minutes": 120,
            "ledger_movement_minutes": 45,
            "closing_balance_minutes": 165,
            "employee_document": None,
            "pdf_file": None,
            "days": [
                self._day(),
                self._day(
                    report_date=(
                        getdate(
                            "2026-08-04"
                        )
                    ),
                    target_minutes=0,
                    raw_work_minutes=120,
                    accountable_minutes=120,
                    daily_delta_minutes=120,
                ),
            ],
            "ledger_entries": [
                self._ledger(
                    entry_type="Workday",
                    delta_minutes=0,
                ),
                self._ledger(),
                self._ledger(
                    entry_type=(
                        "Negative Adjustment"
                    ),
                    delta_minutes=-15,
                ),
            ],
        }

        values.update(
            overrides
        )

        return frappe._dict(
            values
        )

    def test_format_minutes_signed_and_unsigned(
        self,
    ):
        self.assertEqual(
            format_minutes(
                125
            ),
            "02:05",
        )

        self.assertEqual(
            format_minutes(
                125,
                signed=True,
            ),
            "+02:05",
        )

        self.assertEqual(
            format_minutes(
                -125,
                signed=True,
            ),
            "-02:05",
        )

        self.assertEqual(
            format_minutes(
                0,
                signed=True,
            ),
            "00:00",
        )

    def test_pdf_context_uses_snapshot_values(
        self,
    ):
        context = (
            build_pdf_context(
                self._report()
            )
        )

        self.assertEqual(
            context[
                "total_target"
            ],
            "08:00",
        )

        self.assertEqual(
            context[
                "total_raw_work"
            ],
            "10:00",
        )

        self.assertEqual(
            context[
                "total_accountable"
            ],
            "10:00",
        )

        self.assertEqual(
            context[
                "total_daily_delta"
            ],
            "+02:00",
        )

        self.assertEqual(
            context[
                "opening_balance"
            ],
            "+02:00",
        )

        self.assertEqual(
            context[
                "closing_balance"
            ],
            "+02:45",
        )

        self.assertEqual(
            len(
                context[
                    "ledger_rows"
                ]
            ),
            2,
        )

    def test_app_template_renders(
        self,
    ):
        html = frappe.render_template(
            PDF_TEMPLATE,
            build_pdf_context(
                self._report()
            ),
        )

        self.assertIn(
            "Arbeitszeitnachweis 08/2026",
            html,
        )

        self.assertIn(
            "Christian Gold",
            html,
        )

        self.assertIn(
            "Tagesübersicht",
            html,
        )

    def test_render_uses_app_template_and_pdf_options(
        self,
    ):
        report = (
            self._report()
        )

        with (
            patch(
                (
                    f"{MODULE}."
                    "frappe.render_template"
                ),
                return_value=(
                    "<html>ok</html>"
                ),
            ) as render,
            patch(
                f"{MODULE}.get_pdf",
                return_value=b"PDF",
            ) as pdf,
        ):
            result = (
                render_monthly_time_report_pdf(
                    report
                )
            )

        self.assertEqual(
            result,
            b"PDF",
        )

        self.assertEqual(
            render.call_args.args[0],
            PDF_TEMPLATE,
        )

        self.assertEqual(
            pdf.call_args.kwargs[
                "options"
            ],
            PDF_OPTIONS,
        )

        self.assertTrue(
            pdf.call_args.kwargs[
                "smart_shrinking"
            ]
        )

    def test_incomplete_report_cannot_be_published(
        self,
    ):
        with self.assertRaises(
            frappe.ValidationError
        ):
            _assert_publication_state(
                self._report(
                    is_complete=0,
                    blocking_issue_count=1,
                )
            )

    def test_non_current_report_cannot_be_published(
        self,
    ):
        with self.assertRaises(
            frappe.ValidationError
        ):
            _assert_publication_state(
                self._report(
                    is_current_revision=0,
                    status=(
                        STATUS_SUPERSEDED
                    ),
                )
            )

    def test_inconsistent_publication_state_is_rejected(
        self,
    ):
        with self.assertRaises(
            frappe.ValidationError
        ):
            _assert_publication_state(
                self._report(
                    employee_document=(
                        "EDOC-1"
                    ),
                    pdf_file=None,
                )
            )

    def test_already_published_report_is_idempotent(
        self,
    ):
        report = self._report(
            employee_document="EDOC-1",
            pdf_file=(
                "/private/files/report.pdf"
            ),
        )

        with (
            patch(
                (
                    f"{MODULE}."
                    "frappe.get_doc"
                ),
                return_value=report,
            ),
            patch(
                (
                    f"{MODULE}."
                    "render_monthly_time_report_pdf"
                )
            ) as render,
        ):
            result = (
                publish_monthly_time_report(
                    report.name
                )
            )

        self.assertTrue(
            result[
                "already_published"
            ]
        )

        self.assertEqual(
            result[
                "employee_document"
            ],
            "EDOC-1",
        )

        render.assert_not_called()

    def test_pdf_is_saved_private_and_attached_to_report(
        self,
    ):
        report = (
            self._report()
        )

        file_doc = frappe._dict(
            {
                "file_url": (
                    "/private/files/report.pdf"
                )
            }
        )

        with patch(
            f"{MODULE}.save_file",
            return_value=file_doc,
        ) as save:
            result = (
                _save_private_pdf(
                    report,
                    b"PDF",
                )
            )

        self.assertEqual(
            result.file_url,
            "/private/files/report.pdf",
        )

        self.assertEqual(
            save.call_args.args[2],
            "Monthly Time Report",
        )

        self.assertEqual(
            save.call_args.args[3],
            report.name,
        )

        self.assertEqual(
            save.call_args.kwargs[
                "is_private"
            ],
            1,
        )

    def test_employee_document_values_match_report_revision_family(
        self,
    ):
        report = self._report(
            revision=2
        )

        values = (
            _employee_document_values(
                report,
                "/private/files/report.pdf",
                previous_employee_document=(
                    "EDOC-1"
                ),
            )
        )

        self.assertEqual(
            values[
                "employee"
            ],
            report.employee,
        )

        self.assertEqual(
            values[
                "document_type"
            ],
            "Monthly Time Report",
        )

        self.assertEqual(
            values[
                "source"
            ],
            "Monthly Time Report",
        )

        self.assertEqual(
            values[
                "period_from"
            ],
            report.period_from,
        )

        self.assertEqual(
            values[
                "period_to"
            ],
            report.period_to,
        )

        self.assertEqual(
            values[
                "previous_revision"
            ],
            "EDOC-1",
        )

        self.assertEqual(
            values[
                "external_reference"
            ],
            report.name,
        )

    def test_publish_creates_pdf_document_and_links_without_email(
        self,
    ):
        report = (
            self._report()
        )

        file_doc = frappe._dict(
            {
                "file_url": (
                    "/private/files/report.pdf"
                )
            }
        )

        employee_document = (
            frappe._dict(
                {
                    "name": (
                        "EDOC-1"
                    )
                }
            )
        )

        with (
            patch(
                (
                    f"{MODULE}."
                    "frappe.get_doc"
                ),
                return_value=report,
            ),
            patch(
                (
                    f"{MODULE}."
                    "render_monthly_time_report_pdf"
                ),
                return_value=b"PDF",
            ),
            patch(
                (
                    f"{MODULE}."
                    "_save_private_pdf"
                ),
                return_value=file_doc,
            ),
            patch(
                (
                    f"{MODULE}."
                    "_insert_employee_document"
                ),
                return_value=(
                    employee_document
                ),
            ),
            patch(
                (
                    f"{MODULE}."
                    "_set_report_publication_links"
                )
            ) as link,
            patch.object(
                frappe,
                "sendmail",
            ) as sendmail,
        ):
            result = (
                publish_monthly_time_report(
                    report.name
                )
            )

        self.assertFalse(
            result[
                "already_published"
            ]
        )

        self.assertEqual(
            result[
                "employee_document"
            ],
            "EDOC-1",
        )

        link.assert_called_once_with(
            report,
            "/private/files/report.pdf",
            "EDOC-1",
        )

        sendmail.assert_not_called()

    def test_create_and_publish_uses_snapshot_service(
        self,
    ):
        report = (
            self._report()
        )

        with (
            patch(
                (
                    f"{MODULE}."
                    "create_monthly_time_report_snapshot"
                ),
                return_value=report,
            ) as create,
            patch(
                (
                    f"{MODULE}."
                    "publish_monthly_time_report"
                ),
                return_value={
                    "report": (
                        report.name
                    )
                },
            ) as publish,
        ):
            result = (
                create_and_publish_monthly_time_report(
                    report.employee,
                    2026,
                    8,
                    reference_datetime=(
                        datetime(
                            2026,
                            9,
                            3,
                            8,
                            0,
                            0,
                        )
                    ),
                )
            )

        self.assertEqual(
            result[
                "report"
            ],
            report.name,
        )

        create.assert_called_once()

        publish.assert_called_once_with(
            report.name
        )

    def test_revision_source_must_already_be_published(
        self,
    ):
        with self.assertRaises(
            frappe.ValidationError
        ):
            _assert_revision_source(
                self._report()
            )

    def test_revision_snapshot_increments_and_links_previous_report(
        self,
    ):
        current = self._report(
            revision=2,
            employee_document="EDOC-2",
            pdf_file=(
                "/private/files/r2.pdf"
            ),
        )

        snapshot = {
            "doctype": (
                "Monthly Time Report"
            ),
            "employee": (
                current.employee
            ),
            "report_year": 2026,
            "report_month": 8,
        }

        new_doc = MagicMock()

        new_doc.flags = {}

        new_doc.insert.return_value = (
            new_doc
        )

        with (
            patch(
                (
                    f"{MODULE}."
                    "build_monthly_time_report_snapshot"
                ),
                return_value=snapshot,
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.get_doc"
                ),
                return_value=new_doc,
            ),
        ):
            result = (
                _create_revision_snapshot(
                    current
                )
            )

        self.assertIs(
            result,
            new_doc,
        )

        self.assertEqual(
            snapshot[
                "revision"
            ],
            3,
        )

        self.assertEqual(
            snapshot[
                "previous_revision"
            ],
            current.name,
        )

        self.assertEqual(
            snapshot[
                "status"
            ],
            STATUS_GENERATED,
        )

        self.assertTrue(
            new_doc.flags[
                SERVICE_FLAG
            ]
        )

        new_doc.insert.assert_called_once_with(
            ignore_permissions=True
        )

    def test_regenerate_publishes_new_revision_and_supersedes_previous(
        self,
    ):
        current = self._report(
            employee_document="EDOC-1",
            pdf_file=(
                "/private/files/r1.pdf"
            ),
        )

        new_report = self._report(
            name="MTR-2026-00002",
            revision=2,
            previous_revision=(
                current.name
            ),
        )

        publication = {
            "report": (
                new_report.name
            ),
            "pdf_file": (
                "/private/files/r2.pdf"
            ),
            "employee_document": (
                "EDOC-2"
            ),
            "already_published": False,
        }

        with (
            patch(
                (
                    f"{MODULE}."
                    "frappe.get_doc"
                ),
                return_value=current,
            ),
            patch(
                (
                    f"{MODULE}."
                    "_create_revision_snapshot"
                ),
                return_value=(
                    new_report
                ),
            ),
            patch(
                (
                    f"{MODULE}."
                    "publish_monthly_time_report"
                ),
                return_value=(
                    publication.copy()
                ),
            ) as publish,
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.set_value"
                )
            ) as set_value,
        ):
            result = (
                regenerate_and_publish_monthly_time_report(
                    current.name
                )
            )

        publish.assert_called_once_with(
            new_report.name,
            previous_employee_document=(
                "EDOC-1"
            ),
        )

        set_value.assert_called_once_with(
            "Monthly Time Report",
            current.name,
            {
                "status": (
                    STATUS_SUPERSEDED
                ),
                "is_current_revision": 0,
            },
            update_modified=True,
        )

        self.assertEqual(
            result[
                "previous_report"
            ],
            current.name,
        )

        self.assertEqual(
            result[
                "revision"
            ],
            2,
        )
