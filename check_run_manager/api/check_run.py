import json
import frappe
from frappe import _
from frappe.utils import nowdate, now_datetime
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry


def format_check_number(number: int) -> str:
    return str(int(number)).zfill(6)


def get_next_check_number() -> int:
    max_no = frappe.db.sql("""
        select max(check_number)
        from `tabCheck Run Item`
        where ifnull(check_number, 0) > 0
    """)[0][0]

    if not max_no:
        return 2

    return int(max_no) + 1


@frappe.whitelist()
def create_check_run(company: str, payment_date: str, paid_from_account: str | None = None):
    doc = frappe.get_doc({
        "doctype": "Check Run",
        "company": company,
        "payment_date": payment_date or nowdate(),
        "status": "Draft",
        "start_check_number": get_next_check_number(),
        "next_check_number": get_next_check_number(),
        "bank_account": paid_from_account or ""
    })
    doc.insert()
    return doc.as_dict()


@frappe.whitelist()
def load_eligible_invoices(company: str, supplier: str | None = None):
    filters = {
        "docstatus": 1,
        "company": company,
        "outstanding_amount": [">", 0]
    }

    if supplier:
        filters["supplier"] = supplier

    invoices = frappe.get_all(
        "Purchase Invoice",
        filters=filters,
        fields=[
            "name",
            "supplier",
            "supplier_name",
            "posting_date",
            "due_date",
            "grand_total",
            "outstanding_amount",
            "currency"
        ],
        order_by="due_date asc, posting_date asc"
    )

    return invoices


@frappe.whitelist()
def add_invoices_to_run(check_run_name: str, invoice_names):
    if isinstance(invoice_names, str):
        invoice_names = json.loads(invoice_names)

    if not isinstance(invoice_names, list):
        frappe.throw("invoice_names must be a list.")

    doc = frappe.get_doc("Check Run", check_run_name)
    existing = {row.invoice_reference for row in (doc.items or [])}

    for inv_name in invoice_names:
        if inv_name in existing:
            continue

        # Block duplicate checks across ALL runs unless voided
        duplicate = frappe.db.exists(
            "Check Run Item",
            {
                "invoice_reference": inv_name,
                "docstatus": ["<", 2],
                "print_status": ["!=", "Voided"]
            }
        )
        if duplicate:
            frappe.throw(
                _("Invoice {0} already exists in another Check Run Item.").format(inv_name)
            )

        inv = frappe.get_doc("Purchase Invoice", inv_name)

        doc.append("items", {
            "supplier": inv.supplier,
            "supplier_name": inv.supplier_name,
            "invoice_reference": inv.name,
            "payee_name": inv.supplier_name or inv.supplier,
            "amount": inv.outstanding_amount,
            "net_amount": inv.outstanding_amount,
            "memo": inv.name,
            "print_status": "Pending"
        })

    doc.save()
    return doc.as_dict()


def _create_payment_entry_for_invoice(invoice_name: str, paid_from_account: str, payment_date: str, check_number: int):
    pe = get_payment_entry("Purchase Invoice", invoice_name)

    pe.posting_date = payment_date
    pe.paid_from = paid_from_account
    pe.reference_no = format_check_number(check_number)
    pe.reference_date = payment_date
    pe.mode_of_payment = "Check"

    pe.insert()
    pe.submit()
    return pe


@frappe.whitelist()
def assign_check_numbers(check_run_name: str):
    try:
        doc = frappe.get_doc("Check Run", check_run_name)

        if not doc.bank_account:
            frappe.throw(_("Paid From Account is required."))

        next_number = get_next_check_number()
        sequence = 1

        for row in doc.items or []:
            if row.print_status == "Voided":
                continue

            # Skip rows already assigned
            if row.check_number or row.payment_entry:
                continue

            # Block duplicate Payment Entries too
            existing_pe = frappe.db.exists(
                "Payment Entry Reference",
                {
                    "reference_doctype": "Purchase Invoice",
                    "reference_name": row.invoice_reference,
                    "docstatus": 1
                }
            )
            if existing_pe:
                frappe.throw(
                    _("Invoice {0} already has a submitted Payment Entry.").format(row.invoice_reference)
                )

            row.sequence_no = sequence
            row.check_number = next_number

            pe = _create_payment_entry_for_invoice(
                invoice_name=row.invoice_reference,
                paid_from_account=doc.bank_account,
                payment_date=doc.payment_date,
                check_number=next_number
            )

            row.payment_entry = pe.name
            row.print_status = "Pending"

            sequence += 1
            next_number += 1

        doc.end_check_number = next_number - 1 if next_number > 2 else 0
        doc.next_check_number = next_number
        doc.status = "Ready to Print"
        doc.save()

        return {
            "ok": True,
            "message": f"Assigned checks through {format_check_number(next_number - 1)}",
            "doc": doc.as_dict(),
        }
    except Exception:
        frappe.log_error(
            title="Assign Check Numbers Failed",
            message=frappe.get_traceback()
        )
        raise


@frappe.whitelist()
def mark_printed(check_run_name: str):
    try:
        doc = frappe.get_doc("Check Run", check_run_name)
        changed = False

        for row in doc.items or []:
            if row.check_number and row.print_status == "Pending":
                row.print_status = "Printed"
                row.printed_on = now_datetime()
                row.printed_by = frappe.session.user
                changed = True

        if changed:
            doc.status = "Printed"
            doc.printed_on = now_datetime()
            doc.printed_by = frappe.session.user
            doc.save()

        return {
            "ok": True,
            "message": f"Marked Check Run {doc.name} as printed.",
            "doc": doc.as_dict(),
        }
    except Exception:
        frappe.log_error(
            title="Mark Printed Failed",
            message=frappe.get_traceback()
        )
        raise