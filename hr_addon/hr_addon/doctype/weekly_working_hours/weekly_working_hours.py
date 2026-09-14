# Copyright (c) 2022, phamos.eu and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate
from frappe.model.naming import make_autoname
from frappe import _

class WeeklyWorkingHours(Document):
	def autoname(self):
		Company = frappe.qb.DocType('Company')
		query = (
			frappe.qb.from_(Company)
			.select(Company.abbr)
			.where(Company.name == self.company)
		).run()

		coy = query[0][0] if query else None
		e_name = self.employee
		name_key = coy+'-.YYYY.-'+e_name+'-.####'
		self.name = make_autoname(name_key)
		self.title_hour= self.name

	def validate(self):
		self.validate_if_employee_is_active()
		self.validate_overlapping_records_in_specific_interval()

	def validate_if_employee_is_active(self):
		if self.employee and frappe.get_value('Employee', self.employee, 'status') != "Active":
			frappe.throw(_("{0} is not active").format(frappe.get_desk_link('Employee', self.employee)))

	def validate_overlapping_records_in_specific_interval(self):
		if not self.valid_from:
			frappe.throw(_("From Date is required."))

		if not self.employee:
			frappe.throw(_("Employee required."))

		valid_from = getdate(self.valid_from)
		valid_to = getdate(self.valid_to) if self.valid_to else None

		if valid_to and valid_from > valid_to:
			frappe.throw(_("From Date cannot be after To Date."))

		wwh = frappe.qb.DocType("Weekly Working Hours")

		overlapping_records = (
			frappe.qb.from_(wwh)
			.select(wwh.name)
			.where(wwh.employee == self.employee)
			.where(wwh.docstatus == 1)
			.where(
				wwh.valid_to.isnull()
				| (wwh.valid_to >= valid_from)
			)
		)

		if valid_to:
			overlapping_records = overlapping_records.where(
				wwh.valid_from <= valid_to
			)

		if not self.is_new():
			overlapping_records = overlapping_records.where(
				wwh.name != self.name
			)

		results = overlapping_records.run(as_dict=True)

		if results:
			overlapping_links = "<br> ".join(
				[
					frappe.get_desk_link("Weekly Working Hours", d.name)
					for d in results
				]
			)

			frappe.throw(
				_(
					"Following Weekly Working Hours record already exists for {0} "
					"for the specified date range:<br> {1}"
				).format(
					frappe.get_desk_link("Employee", self.employee),
					overlapping_links,
				)
			)
