frappe.pages["check-run-manager"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "Check Run Manager",
        single_column: true
    });

    const body = $('<div style="padding:20px; max-width:1400px;"></div>').appendTo(page.body);

    const filters_row = $('<div style="display:grid; grid-template-columns:repeat(5, 1fr); gap:12px; margin-bottom:16px;"></div>').appendTo(body);
    const actions_row = $('<div style="display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap;"></div>').appendTo(body);
    const table_wrap = $('<div style="margin-top:16px;"></div>').appendTo(body);

    function makeControl(parent, df) {
        const w = $('<div></div>').appendTo(parent);
        const c = frappe.ui.form.make_control({
            parent: w,
            df,
            render_input: true
        });
        c.refresh();
        return c;
    }

    const company = makeControl(filters_row, {
        fieldtype: "Link",
        fieldname: "company",
        label: "Company",
        options: "Company",
        reqd: 1
    });

    const supplier = makeControl(filters_row, {
        fieldtype: "Link",
        fieldname: "supplier",
        label: "Supplier",
        options: "Supplier"
    });

    const paid_from_account = makeControl(filters_row, {
        fieldtype: "Link",
        fieldname: "paid_from_account",
        label: "Paid From Account",
        options: "Account"
    });

    const payment_date = makeControl(filters_row, {
        fieldtype: "Date",
        fieldname: "payment_date",
        label: "Payment Date",
        reqd: 1,
        default: frappe.datetime.get_today()
    });

    const starting_number = makeControl(filters_row, {
        fieldtype: "Int",
        fieldname: "starting_number",
        label: "Starting Check Number",
        reqd: 1,
        default: 2
    });

    const check_run_name = makeControl(filters_row, {
        fieldtype: "Data",
        fieldname: "check_run_name",
        label: "Check Run Name",
        read_only: 1
    });

    const create_btn = $('<button class="btn btn-primary">Create Check Run</button>').appendTo(actions_row);
    const load_btn = $('<button class="btn btn-secondary">Load Eligible Invoices</button>').appendTo(actions_row);
    const assign_btn = $('<button class="btn btn-primary">Assign Check Numbers</button>').appendTo(actions_row);
    const printed_btn = $('<button class="btn btn-success">Mark Printed</button>').appendTo(actions_row);

    const table = $(`
        <table class="table table-bordered">
            <thead>
                <tr>
                    <th>Select</th>
                    <th>Supplier</th>
                    <th>Invoice</th>
                    <th>Due Date</th>
                    <th>Outstanding</th>
                    <th>Check #</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody id="crm-body"></tbody>
        </table>
    `).appendTo(table_wrap);

    function getVal(ctrl) {
        return ctrl.get_value();
    }

    function formatMoney(v) {
        return format_currency(v || 0);
    }

    function formatCheckNumber(v) {
        return v ? String(v).padStart(6, "0") : "";
    }

    function renderInvoices(invoices) {
        const html = (invoices || []).map(inv => `
            <tr>
                <td><input type="checkbox" class="crm-select" value="${frappe.utils.escape_html(inv.name)}"></td>
                <td>${frappe.utils.escape_html(inv.supplier_name || inv.supplier || "")}</td>
                <td>${frappe.utils.escape_html(inv.name)}</td>
                <td>${frappe.utils.escape_html(inv.due_date || "")}</td>
                <td>${formatMoney(inv.outstanding_amount || inv.amount || 0)}</td>
                <td>${formatCheckNumber(inv.check_number)}</td>
                <td>${frappe.utils.escape_html(inv.print_status || "Pending")}</td>
            </tr>
        `).join("");

        $("#crm-body").html(html);
    }

    function renderRun(doc) {
        const html = (doc.items || []).map(row => `
            <tr>
                <td></td>
                <td>${frappe.utils.escape_html(row.supplier_name || row.supplier || "")}</td>
                <td>${frappe.utils.escape_html(row.invoice_reference || "")}</td>
                <td></td>
                <td>${formatMoney(row.amount || 0)}</td>
                <td>${formatCheckNumber(row.check_number)}</td>
                <td>${frappe.utils.escape_html(row.print_status || "")}</td>
            </tr>
        `).join("");

        $("#crm-body").html(html);
    }

    create_btn.on("click", async () => {
        const r = await frappe.call({
            method: "check_run_manager.api.check_run.create_check_run",
            args: {
                company: getVal(company),
                payment_date: getVal(payment_date),
                paid_from_account: getVal(paid_from_account)
            }
        });

        check_run_name.set_value(r.message.name);
        frappe.show_alert({ message: `Created ${r.message.name}`, indicator: "green" });
    });

    load_btn.on("click", async () => {
        if (!getVal(company)) {
            frappe.msgprint("Company is required.");
            return;
        }

        const r = await frappe.call({
            method: "check_run_manager.api.check_run.load_eligible_invoices",
            args: {
                company: getVal(company),
                supplier: getVal(supplier)
            }
        });

        renderInvoices(r.message || []);
        frappe.show_alert({ message: `Loaded ${(r.message || []).length} invoice(s)`, indicator: "blue" });
    });

    assign_btn.on("click", async () => {
        if (!getVal(check_run_name)) {
            frappe.msgprint("Create a Check Run first.");
            return;
        }

        const selected = $(".crm-select:checked").map(function () {
            return $(this).val();
        }).get();

        if (!selected.length) {
            frappe.msgprint("Select at least one invoice.");
            return;
        }

        await frappe.call({
            method: "check_run_manager.api.check_run.add_invoices_to_run",
            args: {
                check_run_name: getVal(check_run_name),
                invoice_names: selected
            }
        });

        const r = await frappe.call({
            method: "check_run_manager.api.check_run.assign_check_numbers_and_create_payments",
            args: {
                check_run_name: getVal(check_run_name),
                starting_number: getVal(starting_number),
                paid_from_account: getVal(paid_from_account)
            }
        });

        renderRun(r.message.doc);
        frappe.show_alert({ message: r.message.message, indicator: "green" });
    });

    printed_btn.on("click", async () => {
        if (!getVal(check_run_name)) {
            frappe.msgprint("Create a Check Run first.");
            return;
        }

        const r = await frappe.call({
            method: "check_run_manager.api.check_run.mark_printed",
            args: {
                check_run_name: getVal(check_run_name)
            }
        });

        renderRun(r.message.doc);
        frappe.show_alert({ message: r.message.message, indicator: "green" });
    });
};
