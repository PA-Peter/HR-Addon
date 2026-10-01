from . import __version__ as app_version

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
	"HR Settings": "public/js/hr_settings.js"
}

required_apps = ["hrms"]


permission_query_conditions = {
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


doc_events = {
	"Leave Application": {
		"on_change": "hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings.export_calendar",
		"on_cancel": "hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings.export_calendar"
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
	],
	"cron": {
		"0 3 3 * *": [
			"hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report_scheduler.generate_previous_month_reports",
		],
	},
}
