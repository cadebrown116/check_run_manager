frappe.pages["check-run-manager"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "Check Run Manager",
        single_column: true
    });

    const $body = $(`
        <div style="padding: 20px; max-width: 1200px;">
            <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px;">
                <div>
                    <label>Company</label>
                    <input id="crm-company" class="form-control" />
                </div>
                <div>
                    <label>Bank Account</label>
                    <input id="crm-bank-account" class="form-control" />
                </div>
                <div>
                    <label>Payment Date</label>
                    <input id="crm-payment-date" type="date" class="form-control" />
                </div>
                <div style="display:flex; align-items:end;">
                    <button id="crm-create-run" class="btn btn-primary" style="width:100%;">Create Check Run</button>
                </div>
            </div>

            <div style="display:grid; grid-template-columns: 1fr auto auto auto; gap: 12px; margin-bottom: 16px;">
                <input id="crm-check-run-name" class="form-control" placeholder="Check Run Name" />
                <input id="crm-start-number" class="form-control" type="number" value="2" min="2" />
                <button id="crm-load-payments" class="btn btn-secondary">Load Eligible Payments</button>
                <button id="crm-assign-numbers" class="btn btn-primary">Assign Check Numbers</button>
            </div>

            <div style="margin-bottom: 16px;">
                <button id="crm-mark-printed" class="btn btn-success">Mark Printed</button>
            </div>

            <table class="table table-bordered">
                <thead>
                    <tr>
                        <th>Select</th>
                        <th>Supplier</th>
                        <th>Payment Entry</th>
                        <th>Amount</th>
                        <th>Check #</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody id="crm-payments-body"></tbody>
            </table>
        </div>
    `);

    $(page.body).append($body);

    async function createRun() {
        const company = $("#crm-company").val().trim();
        const bank_account = $("#crm-bank-account").val().trim();
        const payment_date = $("#crm-payment-date").val();

        const r = await frappe.call({
            method: "check_run_manager.api.check_run.create_check_run",
            args: { company, bank_account, payment_date }
        });

        $("#crm-check-run-name").val(r.message.name);
        frappe.show_alert({ message: `Created ${r.message.name}`, indicator: "green" });
    }

    async function loadPayments() {
        const company = $("#crm-company").val().trim();
        const bank_account = $("#crm-bank-account").val().trim();

        const paymentsResp = await frappe.call({
            method: "check_run_manager.api.check_run.load_eligible_payments",
            args: { company, bank_account }
        });

        const payments = paymentsResp.message || [];
        const rowsHtml = payments.map(p => `
            <tr>
                <td><input type="checkbox" class="crm-select-payment" value="${p.name}"></td>
                <td>${frappe.utils.escape_html(p.party_name || p.party || "")}</td>
                <td>${frappe.utils.escape_html(p.name)}</td>
                <td style="text-align:right;">${Number(p.paid_amount || 0).toFixed(2)}</td>
                <td></td>
                <td>Pending</td>
            </tr>
        `).join("");

        $("#crm-payments-body").html(rowsHtml);
    }

    async function assignNumbers() {
        const check_run_name = $("#crm-check-run-name").val().trim();
        const starting_number = parseInt($("#crm-start-number").val() || "2", 10);

        const selected = $(".crm-select-payment:checked").map(function () {
            return $(this).val();
        }).get();

        if (selected.length) {
            await frappe.call({
                method: "check_run_manager.api.check_run.add_payments_to_run",
                args: {
                    check_run_name,
                    payment_entry_names: selected
                }
            });
        }

        const r = await frappe.call({
            method: "check_run_manager.api.check_run.assign_check_numbers",
            args: { check_run_name, starting_number }
        });

        renderRun(r.message.doc);
        frappe.show_alert({ message: r.message.message, indicator: "green" });
    }

    async function markPrinted() {
        const check_run_name = $("#crm-check-run-name").val().trim();

        const r = await frappe.call({
            method: "check_run_manager.api.check_run.mark_printed",
            args: { check_run_name }
        });

        renderRun(r.message.doc);
        frappe.show_alert({ message: r.message.message, indicator: "green" });
    }

    function renderRun(doc) {
        const rowsHtml = (doc.items || []).map(row => `
            <tr>
                <td></td>
                <td>${frappe.utils.escape_html(row.supplier_name || row.supplier || "")}</td>
                <td>${frappe.utils.escape_html(row.payment_entry || "")}</td>
                <td style="text-align:right;">${Number(row.amount || 0).toFixed(2)}</td>
                <td>${String(row.check_number || "").padStart(6, "0")}</td>
                <td>${frappe.utils.escape_html(row.print_status || "")}</td>
            </tr>
        `).join("");

        $("#crm-payments-body").html(rowsHtml);
    }

    $("#crm-create-run").on("click", createRun);
    $("#crm-load-payments").on("click", loadPayments);
    $("#crm-assign-numbers").on("click", assignNumbers);
    $("#crm-mark-printed").on("click", markPrinted);
};