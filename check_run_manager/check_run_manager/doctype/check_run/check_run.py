import frappe
from frappe.model.document import Document


class CheckRun(Document):
    def validate(self):
        self.calculate_totals()

        if self.start_check_number is not None and self.start_check_number < 2:
            frappe.throw("Starting Check Number must be 2 or greater.")

    def calculate_totals(self):
        total_amount = 0
        total_checks = 0
        end_check_number = None

        for row in self.items or []:
            if row.amount:
                total_amount += float(row.amount)

            if row.check_number:
                total_checks += 1
                end_check_number = row.check_number

        self.total_amount = total_amount
        self.total_checks = total_checks
        self.end_check_number = end_check_number
        self.next_check_number = (end_check_number + 1) if end_check_number else self.start_check_number