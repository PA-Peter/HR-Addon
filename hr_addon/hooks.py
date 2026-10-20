from . import __version__ as app_version

from hr_addon.hr_addon.holiday_semantics import (
    install_hrms_half_day_leave_patch,
)

install_hrms_half_day_leave_patch()

app_name = "hr_addon"
app_title = "HR Addon"
app_publisher = "phamos.eu"
app_description = "Addon for Erpnext attendance and employee checkins"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "support@phamos.eu"
app_license = "MIT"

after_install = "hr_addon.hr_addon.doctype.workday.workday.create_background_job_for_workday_generation_after_install"
after_migrate = "hr_addon.hr_addon.doctype.workday.workday.create_background_job_for_workday_generation_after_install"

fixtures = [
	{"dt": "Custom Field", "filters": [
		["module", "=", "HR Addon"]
	]}
]

doctype_js = {
	"HR Settings": "public/js/hr_settings.js",
	"Leave Application": "public/js/leave_application.js",
}

required_apps = ["hrms"]


permission_query_conditions = {
	"Employee Checkin": (
		"hr_addon.hr_addon.permissions."
		"self_service."
		"checkin_get_permission_query_conditions"
	),
	"Workday": (
		"hr_addon.hr_addon.permissions."
		"self_service."
		"workday_get_permission_query_conditions"
	),
	"Time Account Ledger Entry": (
		"hr_addon.hr_addon.permissions."
		"self_service."
		"ledger_get_permission_query_conditions"
	),
	"Checkin Correction Request": (
		"hr_addon.hr_addon.doctype."
		"checkin_correction_request."
		"checkin_correction_request_permissions."
		"get_permission_query_conditions"
	),
	"Employee Document": (
		"hr_addon.hr_addon.doctype."
		"employee_document."
		"employee_document_permissions."
		"get_permission_query_conditions"
	),
}


has_permission = {
	"Employee Checkin": (
		"hr_addon.hr_addon.permissions."
		"self_service."
		"checkin_has_permission"
	),
	"Workday": (
		"hr_addon.hr_addon.permissions."
		"self_service."
		"workday_has_permission"
	),
	"Time Account Ledger Entry": (
		"hr_addon.hr_addon.permissions."
		"self_service."
		"ledger_has_permission"
	),
	"Checkin Correction Request": (
		"hr_addon.hr_addon.doctype."
		"checkin_correction_request."
		"checkin_correction_request_permissions."
		"has_permission"
	),
	"Employee Document": (
		"hr_addon.hr_addon.doctype."
		"employee_document."
		"employee_document_permissions."
		"has_permission"
	),
}



CALENDAR_REFRESH_HOOK = (
    "hr_addon.hr_addon.company_calendar_updates."
    "schedule_refresh"
)

doc_events = {
	"Employee Checkin": {
		"before_insert": (
			"hr_addon.hr_addon.permissions."
			"self_service."
			"block_employee_direct_checkin_creation"
		)
	},
	"Leave Application": {
		"after_insert": (
			"hr_addon.hr_addon."
			"leave_application_integration."
			"handle_leave_after_insert"
		),
		"on_change": CALENDAR_REFRESH_HOOK,
        "on_trash": CALENDAR_REFRESH_HOOK,
        "on_submit": (
			"hr_addon.hr_addon."
			"leave_application_integration."
			"handle_leave_submit"
		),
		"on_cancel": (
			"hr_addon.hr_addon."
			"leave_application_integration."
			"handle_leave_cancel"
		),
	},

    "Employee": {
        "on_change": CALENDAR_REFRESH_HOOK,
        "on_trash": CALENDAR_REFRESH_HOOK,
    },
    "Company Calendar Event": {
        "on_change": CALENDAR_REFRESH_HOOK,
        "on_trash": CALENDAR_REFRESH_HOOK,
    },
    "Holiday List": {
        "on_change": CALENDAR_REFRESH_HOOK,
        "on_trash": CALENDAR_REFRESH_HOOK,
    },
	"Checkin Correction Request": {
		"validate": (
			"hr_addon.hr_addon.doctype."
			"checkin_correction_request."
			"checkin_correction_request_permissions."
			"validate_self_service_employee"
		)
	}
}


scheduler_events = {
	"daily": [
		"hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings.send_work_anniversary_notification",
		"hr_addon.hr_addon.doctype.employee_document.employee_document.auto_archive_old_employee_documents",
        "hr_addon.hr_addon.company_calendar_updates.daily_reconcile",
	],
	"cron": {
		"50 2 2-31 * *": [
			"hr_addon.hr_addon.time_account_monthly_reset.reconcile_previous_month_time_account_resets",
		],
		"0 3 3 * *": [
			"hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report_scheduler.generate_previous_month_reports",
		],
		"15 3 * * *": [
			"hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report_scheduler.reconcile_previous_month_reports",
		],
		"30 3 * * *": [
			"hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report_scheduler.finalize_due_month_reports",
		],
	},
}
