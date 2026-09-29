// Copyright (c) 2026, RieckMedia and contributors
// For license information, please see license.txt

const EMPLOYEE_DOCUMENT_METHOD =
	"hr_addon.hr_addon.doctype.employee_document.";

frappe.ui.form.on("Employee Document", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		const is_management_user = [
			"System Manager",
			"HR Manager",
		].some(
			(role) => frappe.user_roles.includes(role)
		);

		if (
			!is_management_user
			&& frm.doc.read_status === "New"
		) {
			frappe.call({
				method:
					EMPLOYEE_DOCUMENT_METHOD
					+ "employee_document.mark_seen",
				args: {
					name: frm.doc.name,
				},
			}).then((response) => {
				if (
					response.message
					&& response.message.changed
				) {
					frm.doc.read_status =
						response.message.read_status;

					frm.doc.seen_at =
						response.message.seen_at;

					frm.refresh_field(
						"read_status"
					);

					frm.refresh_field(
						"seen_at"
					);
				}
			});
		}

		if (frm.doc.document_file) {
			frm.add_custom_button(
				__(
					"Send to Personal Email"
				),
				() => {
					frappe.confirm(
						__(
							"Send this document "
							+ "to the personal email "
							+ "address stored for "
							+ "this employee?"
						),
						() => {
							frappe.call({
								method:
									EMPLOYEE_DOCUMENT_METHOD
									+ "employee_document_mail."
									+ "send_to_personal_email",
								args: {
									name:
										frm.doc.name,
								},
								freeze: true,
								freeze_message:
									__(
										"Sending document..."
									),
							}).then(
								(response) => {
									if (
										response.message
										&& response.message.sent
									) {
										frappe.show_alert({
											message:
												__(
													"Document sent "
													+ "successfully."
												),
											indicator:
												"green",
										});

										frm.reload_doc();
									}
								}
							);
						}
					);
				}
			);
		}

		if (
			frm.doc.folder === "Inbox"
		) {
			frm.add_custom_button(
				__("Archive"),
				() => {
					frappe.confirm(
						__(
							"Move this document "
							+ "to the archive?"
						),
						() => {
							frappe.call({
								method:
									EMPLOYEE_DOCUMENT_METHOD
									+ "employee_document."
									+ "archive_document",
								args: {
									name:
										frm.doc.name,
								},
								freeze: true,
								freeze_message:
									__(
										"Archiving document..."
									),
							}).then(
								(response) => {
									if (
										response.message
										&& response.message.changed
									) {
										frappe.show_alert({
											message:
												__(
													"Document archived."
												),
											indicator:
												"green",
										});
									}

									frm.reload_doc();
								}
							);
						}
					);
				}
			);
		}
	},
});
