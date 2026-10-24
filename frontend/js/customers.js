/**
 * Udhaar (Credit) & Customer Management Module
 * Manages customer directory, family member credit lines,
 * ledger transaction histories, credit limit updates, and debt settlements.
 */

(function(window) {
    'use strict';

// ==============================================================================
// STEP 9: UDHAAR (CREDIT) & FAMILY ACCOUNT MANAGEMENT MODULE
// ==============================================================================

let allUdhaarCustomers = [];
let selectedUdhaarCustomerId = null;

function initUdhaarModule() {
    // Toolbar buttons
    const createBtn = document.getElementById("btn-open-create-customer");
    if (createBtn) createBtn.addEventListener("click", openCreateCustomerModal);

    const importBtn = document.getElementById("btn-open-import-customers");
    if (importBtn) importBtn.addEventListener("click", openImportCustomersModal);

    const refreshBtn = document.getElementById("btn-refresh-customers");
    if (refreshBtn) refreshBtn.addEventListener("click", () => loadUdhaarDashboard());

    // Search input
    const searchInput = document.getElementById("udhaar-search-input");
    if (searchInput) {
        let debounceTimer = null;
        searchInput.addEventListener("input", () => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                loadUdhaarDashboard(searchInput.value.trim());
            }, 300);
        });
    }

    // Customer Detail Action Buttons
    const settleBtn = document.getElementById("btn-open-settle-modal");
    if (settleBtn) settleBtn.addEventListener("click", openSettleModal);

    const editProfileBtn = document.getElementById("btn-open-edit-profile-modal") || document.getElementById("btn-open-edit-limit-modal");
    if (editProfileBtn) editProfileBtn.addEventListener("click", openEditProfileModal);

    const addMemberBtn = document.getElementById("btn-open-add-member-modal");
    if (addMemberBtn) addMemberBtn.addEventListener("click", openAddMemberModal);

    // Modal Cancel Buttons
    const cancelCreate = document.getElementById("cancel-create-cust-btn");
    if (cancelCreate) cancelCreate.addEventListener("click", () => closeModal("create-customer-modal"));

    const cancelMember = document.getElementById("cancel-add-member-btn");
    if (cancelMember) cancelMember.addEventListener("click", () => closeModal("add-member-modal"));

    const cancelSettle = document.getElementById("cancel-settle-btn");
    if (cancelSettle) cancelSettle.addEventListener("click", () => closeModal("settle-udhaar-modal"));

    const cancelEditLimit = document.getElementById("cancel-edit-limit-btn");
    if (cancelEditLimit) cancelEditLimit.addEventListener("click", () => {
        closeModal("edit-customer-modal");
        closeModal("edit-limit-modal");
    });
    const cancelEditProfile = document.getElementById("cancel-edit-cust-btn");
    if (cancelEditProfile) cancelEditProfile.addEventListener("click", () => {
        closeModal("edit-customer-modal");
        closeModal("edit-limit-modal");
    });

    // Modal Submit Buttons
    const submitCreate = document.getElementById("submit-create-cust-btn");
    if (submitCreate) submitCreate.addEventListener("click", submitCreateCustomer);

    const submitMember = document.getElementById("submit-add-member-btn");
    if (submitMember) submitMember.addEventListener("click", submitAddMember);

    const submitSettle = document.getElementById("submit-settle-btn");
    if (submitSettle) submitSettle.addEventListener("click", submitSettleUdhaar);

    const submitEditLimitBtn = document.getElementById("submit-edit-limit-btn");
    if (submitEditLimitBtn) submitEditLimitBtn.addEventListener("click", submitEditProfile);

    const submitEditProfileBtn = document.getElementById("submit-edit-cust-btn");
    if (submitEditProfileBtn) submitEditProfileBtn.addEventListener("click", submitEditProfile);

    // Mode options in Settle Modal
    const settleModes = document.querySelectorAll("#settle-udhaar-modal .mode-option");
    settleModes.forEach(opt => {
        opt.addEventListener("click", () => {
            settleModes.forEach(o => o.classList.remove("active"));
            opt.classList.add("active");
            const r = opt.querySelector("input[type='radio']");
            if (r) r.checked = true;
        });
    });

    // Import Udhaar Customers Modal Listeners
    const cancelImport = document.getElementById("btn-cancel-import-cust");
    if (cancelImport) cancelImport.addEventListener("click", closeImportCustomersModal);

    const closeImportX = document.getElementById("btn-close-import-cust-x");
    if (closeImportX) closeImportX.addEventListener("click", closeImportCustomersModal);

    const submitImport = document.getElementById("btn-submit-import-cust");
    if (submitImport) submitImport.addEventListener("click", submitImportCustomers);

    const removeFile = document.getElementById("btn-remove-selected-cust-file");
    if (removeFile) removeFile.addEventListener("click", clearSelectedCustFile);

    const custFileInput = document.getElementById("import-cust-file-input");
    if (custFileInput) {
        custFileInput.addEventListener("change", (e) => {
            if (e.target.files && e.target.files.length > 0) {
                handleCustFileSelected(e.target.files[0]);
            }
        });
    }

    const custDropzone = document.getElementById("import-cust-dropzone");
    if (custDropzone) {
        custDropzone.addEventListener("click", () => {
            if (custFileInput) custFileInput.click();
        });

        ["dragenter", "dragover"].forEach(evt => {
            custDropzone.addEventListener(evt, (e) => {
                e.preventDefault();
                e.stopPropagation();
                custDropzone.style.borderColor = "var(--accent, #3b82f6)";
                custDropzone.style.backgroundColor = "rgba(59, 130, 246, 0.08)";
            });
        });

        ["dragleave", "drop"].forEach(evt => {
            custDropzone.addEventListener(evt, (e) => {
                e.preventDefault();
                e.stopPropagation();
                custDropzone.style.borderColor = "var(--border-color, rgba(255, 255, 255, 0.15))";
                custDropzone.style.backgroundColor = "rgba(255, 255, 255, 0.02)";
            });
        });

        custDropzone.addEventListener("drop", (e) => {
            if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                handleCustFileSelected(e.dataTransfer.files[0]);
            }
        });
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.style.display = "none";
}

async function loadUdhaarDashboard(searchQuery = "") {
    const listContainer = document.getElementById("udhaar-customers-list");
    const totalUdhaarEl = document.getElementById("metric-total-udhaar");
    const availCreditEl = document.getElementById("metric-available-credit");
    const activeCountEl = document.getElementById("metric-active-customers");
    const listCountEl = document.getElementById("customer-list-count");

    if (listContainer) {
        listContainer.innerHTML = `<div class="loading-cell">Loading customer accounts...</div>`;
    }

    try {
        const url = searchQuery ? `/api/v1/customers?query=${encodeURIComponent(searchQuery)}` : "/api/v1/customers";
        const res = await fetch(url);
        if (!res.ok) throw new Error("Failed to fetch customer accounts");
        allUdhaarCustomers = await res.json();

        // Update Overview Metrics
        let totalOutstanding = 0;
        let totalAvailable = 0;
        let activeAccounts = 0;

        allUdhaarCustomers.forEach(c => {
            totalOutstanding += c.current_udhaar_balance;
            totalAvailable += c.available_credit;
            if (c.is_active) activeAccounts += 1;
        });

        if (totalUdhaarEl) totalUdhaarEl.textContent = `₹${totalOutstanding.toFixed(2)}`;
        if (availCreditEl) availCreditEl.textContent = `₹${totalAvailable.toFixed(2)}`;
        if (activeCountEl) activeCountEl.textContent = activeAccounts;
        if (listCountEl) listCountEl.textContent = allUdhaarCustomers.length;

        renderUdhaarCustomerCards(allUdhaarCustomers);

        // Auto-select previously selected customer or first in list
        if (allUdhaarCustomers.length > 0) {
            const targetId = selectedUdhaarCustomerId && allUdhaarCustomers.some(c => c.id === selectedUdhaarCustomerId)
                ? selectedUdhaarCustomerId
                : allUdhaarCustomers[0].id;
            selectUdhaarCustomer(targetId);
        } else {
            selectedUdhaarCustomerId = null;
            const emptyState = document.getElementById("udhaar-empty-state");
            const detailContent = document.getElementById("udhaar-customer-detail-content");
            if (emptyState) emptyState.style.display = "block";
            if (detailContent) detailContent.style.display = "none";
        }

        // Load Udhaar Analytics Charts (Phase 2)
        await loadUdhaarCharts();

    } catch (err) {
        console.error("Error loading Udhaar dashboard:", err);
        if (listContainer) {
            listContainer.innerHTML = `<div class="error-msg" style="padding: 1rem;">Failed to load accounts: ${escapeHtml(err.message)}</div>`;
        }
    }
}

function renderUdhaarCustomerCards(customers) {
    const listContainer = document.getElementById("udhaar-customers-list");
    if (!listContainer) return;

    if (!customers || customers.length === 0) {
        listContainer.innerHTML = `<div class="loading-cell">No customers found matching search.</div>`;
        return;
    }

    listContainer.innerHTML = customers.map(c => {
        const isActive = c.id === selectedUdhaarCustomerId;
        const activeClass = isActive ? "active" : "";
        const pctUsed = c.credit_limit > 0 ? Math.min(100, Math.round((c.current_udhaar_balance / c.credit_limit) * 100)) : 0;
        const memberCount = c.family_members ? c.family_members.length : 0;

        return `
            <div class="customer-card ${activeClass}" onclick="selectUdhaarCustomer(${c.id})">
                <div class="cust-card-top">
                    <div>
                        <span class="cust-card-name">${escapeHtml(c.full_name)}</span>
                        <span class="badge" style="font-size: 0.7rem; background: rgba(59, 130, 246, 0.15); color: var(--accent-light); border: 1px solid rgba(59, 130, 246, 0.3); margin-left: 0.35rem;">${c.customer_code || `C-${String(c.id).padStart(6, '0')}`}</span>
                    </div>
                    <span class="count-badge">${memberCount} ${memberCount === 1 ? 'member' : 'members'}</span>
                </div>
                <div class="cust-card-phone">${escapeHtml(c.phone)}</div>
                <div class="cust-card-metrics">
                    <span>Udhaar: <strong class="${c.current_udhaar_balance > 0 ? 'text-danger' : ''}">₹${c.current_udhaar_balance.toFixed(2)}</strong></span>
                    <span>Avail: <strong class="text-success">₹${c.available_credit.toFixed(2)}</strong></span>
                </div>
                <div class="cust-mini-bar">
                    <div class="cust-mini-bar-fill" style="width: ${pctUsed}%;"></div>
                </div>
            </div>
        `;
    }).join("");
}

async function selectUdhaarCustomer(customerId) {
    selectedUdhaarCustomerId = customerId;

    // Highlight card in list
    const cards = document.querySelectorAll(".customer-card");
    cards.forEach(card => card.classList.remove("active"));
    const activeCards = document.querySelectorAll(`.customer-card[onclick="selectUdhaarCustomer(${customerId})"]`);
    activeCards.forEach(c => c.classList.add("active"));

    const emptyState = document.getElementById("udhaar-empty-state");
    const detailContent = document.getElementById("udhaar-customer-detail-content");

    try {
        const res = await fetch(`/api/v1/customers/${customerId}`);
        if (!res.ok) throw new Error("Failed to load customer profile");
        const cust = await res.json();

        if (emptyState) emptyState.style.display = "none";
        if (detailContent) detailContent.style.display = "block";

        // Profile Information
        const nameEl = document.getElementById("detail-customer-name");
        const codeEl = document.getElementById("detail-customer-code");
        const phoneEl = document.getElementById("detail-customer-phone");
        const addrEl = document.getElementById("detail-customer-address");
        const curBalEl = document.getElementById("detail-current-balance");
        const availEl = document.getElementById("detail-available-credit");
        const limitEl = document.getElementById("detail-credit-limit");
        const barFill = document.getElementById("detail-credit-bar-fill");

        if (nameEl) nameEl.textContent = cust.full_name;
        if (codeEl) codeEl.textContent = cust.customer_code || `C-${String(cust.id).padStart(6, '0')}`;
        if (phoneEl) phoneEl.textContent = cust.phone;
        if (addrEl) {
            if (cust.address_line) {
                addrEl.textContent = `${cust.address_line}, ${cust.city}, ${cust.state} - ${cust.pincode}, ${cust.country}`;
            } else {
                addrEl.textContent = cust.address || "Local Kirana Customer";
            }
        }
        if (curBalEl) curBalEl.textContent = `₹${cust.current_udhaar_balance.toFixed(2)}`;
        if (availEl) availEl.textContent = `₹${cust.available_credit.toFixed(2)}`;
        if (limitEl) limitEl.textContent = `₹${cust.credit_limit.toFixed(2)}`;

        // Phone Verification Status Badge
        const verifBadge = document.getElementById("detail-customer-verif-badge");
        if (verifBadge) {
            if (cust.is_phone_verified) {
                verifBadge.className = "badge badge-in-stock";
                verifBadge.textContent = "Verified";
            } else {
                verifBadge.className = "badge badge-out-stock";
                verifBadge.innerHTML = `Unverified <button type="button" class="btn btn-secondary btn-sm" style="margin-left: 0.35rem; padding: 2px 6px; font-size: 0.7rem;" onclick="handleCustomerPhoneOTP(${cust.id})">Verify Phone (Demo OTP)</button>`;
            }
        }

        const pctUsed = cust.credit_limit > 0
            ? Math.min(100, Math.round((cust.current_udhaar_balance / cust.credit_limit) * 100))
            : 0;
        if (barFill) barFill.style.width = `${pctUsed}%`;

        // Render Family Members
        renderFamilyMembers(cust.family_members || []);

        // Render Immutable Ledger History
        renderLedgerHistory(cust.transactions || []);

    } catch (err) {
        console.error("Error selecting customer:", err);
        alert(`Failed to load details for customer: ${err.message}`);
    }
};

function renderFamilyMembers(members) {
    const container = document.getElementById("detail-family-members-list");
    if (!container) return;

    if (!members || members.length === 0) {
        container.innerHTML = `
            <div style="grid-column: 1 / -1; color: var(--text-secondary); font-size: 0.88rem; padding: 0.5rem 0;">
                No family members added yet. Click <strong>Add Member</strong> to link family members who can purchase on this account.
            </div>
        `;
        return;
    }

    container.innerHTML = members.map(m => {
        let verifTag = "";
        if (m.phone) {
            if (m.is_phone_verified) {
                verifTag = `<span class="badge badge-in-stock" style="font-size: 0.68rem; margin-left: 0.35rem;">Verified</span>`;
            } else {
                verifTag = `<span class="badge badge-low-stock" style="font-size: 0.68rem; margin-left: 0.35rem;">Unverified</span> <button type="button" class="btn btn-secondary btn-sm" style="padding: 1px 5px; font-size: 0.68rem;" onclick="handleMemberPhoneOTP(${m.primary_customer_id}, ${m.id})">Verify</button>`;
            }
        } else if (m.is_phone_verified) {
            verifTag = `<span class="badge badge-in-stock" style="font-size: 0.68rem; margin-left: 0.35rem;">Inherited Primary</span>`;
        }

        const isActive = m.is_active !== false;
        const statusBadge = isActive
            ? `<span class="badge badge-in-stock badge-active" style="font-size: 0.68rem; margin-left: 0.35rem;">Active</span>`
            : `<span class="badge badge-out-stock badge-inactive" style="font-size: 0.68rem; margin-left: 0.35rem;">Inactive</span>`;

        const removeBtn = isActive
            ? `<button type="button" class="btn btn-secondary btn-sm" style="color: var(--danger); border-color: rgba(239, 68, 68, 0.4); padding: 2px 7px; font-size: 0.7rem; margin-top: 0.35rem;" onclick="handleRemoveFamilyMember(${m.primary_customer_id}, ${m.id}, '${escapeHtml(m.full_name)}')">Remove Member</button>`
            : `<span style="font-size: 0.72rem; color: var(--text-secondary); margin-top: 0.35rem; display: block;">Deactivated</span>`;

        return `
            <div class="family-member-card" style="${!isActive ? 'opacity: 0.65; border-style: dashed;' : ''}">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div>
                        <span class="member-name">${escapeHtml(m.full_name)}</span>
                        ${statusBadge}
                    </div>
                    <span class="member-relation-badge">${escapeHtml(m.relation_type)}</span>
                </div>
                ${m.phone ? `<div style="font-size: 0.78rem; color: var(--text-secondary); margin-top: 0.25rem;">${escapeHtml(m.phone)} ${verifTag}</div>` : (verifTag ? `<div style="margin-top: 0.25rem;">${verifTag}</div>` : "")}
                <div class="member-limit-tag">
                    ${m.allowed_spending_limit ? `Per-bill cap: <strong>₹${m.allowed_spending_limit.toFixed(2)}</strong>` : "Cap: <em>No individual limit</em>"}
                </div>
                <div>
                    ${removeBtn}
                </div>
            </div>
        `;
    }).join("");
}

async function handleRemoveFamilyMember(primaryCustomerId, memberId, memberName) {
    const confirmed = confirm("Are you sure you want to remove this family member?");
    if (!confirmed) return;

    try {
        const res = await fetch(`/api/v1/customers/${primaryCustomerId}/family-members/${memberId}`, {
            method: "DELETE"
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "Failed to remove family member");
        }
        alert(data.message || `Family member '${memberName}' removed.`);
        selectUdhaarCustomer(primaryCustomerId);
    } catch (err) {
        console.error("Remove family member error:", err);
        alert(`Error removing family member: ${err.message}`);
    }
};

function toggleTxItems(txId) {
    const row = document.getElementById(`tx-items-row-${txId}`);
    if (row) {
        row.style.display = row.style.display === "none" ? "table-row" : "none";
    }
};

let currentCustomerLedgerTransactions = [];
let currentLedgerPage = 1;
const LEDGER_PAGE_SIZE = 10;

function renderLedgerHistory(transactions) {
    currentCustomerLedgerTransactions = transactions || [];
    currentLedgerPage = 1; // Always reset to Page 1 when loading or switching customer
    renderLedgerHistoryPage();
}

function renderLedgerHistoryPage() {
    const tbody = document.getElementById("detail-ledger-tbody");
    const paginationInfo = document.getElementById("ledger-pagination-info");
    const paginationControls = document.getElementById("ledger-pagination-controls");
    if (!tbody) return;

    const total = currentCustomerLedgerTransactions.length;

    if (total === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="loading-cell">No ledger transactions recorded yet.</td>
            </tr>
        `;
        if (paginationInfo) paginationInfo.textContent = "Showing 0–0 of 0 transactions";
        if (paginationControls) paginationControls.innerHTML = "";
        return;
    }

    const totalPages = Math.ceil(total / LEDGER_PAGE_SIZE);
    if (currentLedgerPage > totalPages) currentLedgerPage = totalPages;
    if (currentLedgerPage < 1) currentLedgerPage = 1;

    const startIdx = (currentLedgerPage - 1) * LEDGER_PAGE_SIZE;
    const endIdx = Math.min(startIdx + LEDGER_PAGE_SIZE, total);
    const pageItems = currentCustomerLedgerTransactions.slice(startIdx, endIdx);

    tbody.innerHTML = pageItems.map(t => {
        const dateStr = new Date(t.created_at).toLocaleString("en-IN", {
            day: "2-digit",
            month: "short",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit"
        });

        const isDebit = t.transaction_type === "DEBIT_PURCHASE";
        const badgeClass = isDebit ? "badge-debit" : "badge-credit";
        const typeLabel = isDebit ? "Udhaar Purchase" : "Debt Settlement";
        const buyerLabel = t.family_member_name ? `${escapeHtml(t.family_member_name)} (Family)` : (escapeHtml(t.primary_customer_name) || "Account Holder");

        const hasItems = t.items && t.items.length > 0;
        const itemsBtn = hasItems
            ? `<button type="button" class="tx-items-btn" onclick="toggleTxItems(${t.id})">Items (${t.items.length})</button>`
            : `<span style="font-size: 0.78rem; color: var(--text-secondary);">—</span>`;

        let itemsSubRow = "";
        if (hasItems) {
            itemsSubRow = `
                <tr id="tx-items-row-${t.id}" class="tx-items-expanded-row" style="display: none;">
                    <td colspan="9" style="padding: 0.6rem 1rem; background: rgba(30, 41, 59, 0.5); border-left: 3px solid var(--accent);">
                        <div style="font-size: 0.8rem; font-weight: 600; margin-bottom: 0.4rem; color: var(--accent-light);">
                            Purchased Items for Bill ${t.bill_number ? escapeHtml(t.bill_number) : ''}:
                        </div>
                        <table class="tx-items-table" style="width: 100%; font-size: 0.8rem; border-collapse: collapse;">
                            <thead>
                                <tr style="color: var(--text-secondary); border-bottom: 1px solid var(--border-color);">
                                    <th style="text-align: left; padding: 4px;">Product</th>
                                    <th style="text-align: center; padding: 4px;">Qty</th>
                                    <th style="text-align: center; padding: 4px;">Unit</th>
                                    <th style="text-align: right; padding: 4px;">Rate</th>
                                    <th style="text-align: right; padding: 4px;">Line Total</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${t.items.map(it => `
                                    <tr style="border-bottom: 1px dashed rgba(148, 163, 184, 0.15);">
                                        <td style="padding: 4px; font-weight: 500;">${escapeHtml(it.product_name)}</td>
                                        <td style="padding: 4px; text-align: center;">${it.quantity}</td>
                                        <td style="padding: 4px; text-align: center;">${escapeHtml(it.unit)}</td>
                                        <td style="padding: 4px; text-align: right;">₹${it.unit_price.toFixed(2)}</td>
                                        <td style="padding: 4px; text-align: right; font-weight: 600; color: var(--accent-light);">₹${it.line_total.toFixed(2)}</td>
                                    </tr>
                                `).join("")}
                            </tbody>
                        </table>
                    </td>
                </tr>
            `;
        }

        const billText = t.bill_number ? escapeHtml(t.bill_number) : "—";
        const notesText = t.notes ? escapeHtml(t.notes) : "—";

        return `
            <tr>
                <td class="cell-date">${dateStr}</td>
                <td><span class="badge ${badgeClass}">${typeLabel}</span></td>
                <td class="cell-buyer" title="${escapeHtml(buyerLabel)}"><strong>${buyerLabel}</strong></td>
                <td class="cell-bill" title="${billText}"><code>${billText}</code></td>
                <td>${itemsBtn}</td>
                <td style="white-space: nowrap;"><strong class="${isDebit ? 'text-danger' : 'text-success'}">${isDebit ? '+' : '-'}₹${t.amount.toFixed(2)}</strong></td>
                <td style="white-space: nowrap;"><strong>₹${t.balance_after.toFixed(2)}</strong></td>
                <td style="white-space: nowrap;"><span style="font-size: 0.75rem; color: var(--text-secondary);">${escapeHtml(t.verified_by)}</span></td>
                <td class="cell-notes" title="${notesText}"><span>${notesText}</span></td>
            </tr>
            ${itemsSubRow}
        `;
    }).join("");

    // Update Pagination Info
    if (paginationInfo) {
        paginationInfo.textContent = `Showing ${startIdx + 1}–${endIdx} of ${total} transactions`;
    }

    // Render Pagination Controls
    if (paginationControls) {
        let controlsHtml = `
            <button type="button" class="btn btn-secondary btn-sm" ${currentLedgerPage === 1 ? 'disabled' : ''} onclick="goToLedgerPage(${currentLedgerPage - 1})">
                &larr; Previous
            </button>
            <span class="page-indicator-badge" style="padding: 4px 10px; background: rgba(255,255,255,0.06); border-radius: 6px; font-size: 0.82rem; color: #94a3b8; border: 1px solid rgba(255,255,255,0.1); font-weight: 500;">
                Page ${currentLedgerPage} of ${totalPages}
            </span>
            <button type="button" class="btn btn-secondary btn-sm" ${currentLedgerPage === totalPages ? 'disabled' : ''} onclick="goToLedgerPage(${currentLedgerPage + 1})">
                Next &rarr;
            </button>
        `;

        paginationControls.innerHTML = controlsHtml;
    }
}

function goToLedgerPage(page) {
    currentLedgerPage = page;
    renderLedgerHistoryPage();
}

// ==============================================================================
// IMPORT UDHAAR CUSTOMERS PIPELINE (CSV / EXCEL)
// ==============================================================================

let selectedImportCustFile = null;

function openImportCustomersModal() {
    const modal = document.getElementById("import-customers-modal");
    if (!modal) {
        console.error("[Customers] #import-customers-modal element not found");
        return;
    }
    clearSelectedCustFile();
    const resultBox = document.getElementById("import-cust-result-box");
    if (resultBox) {
        resultBox.style.display = "none";
        resultBox.innerHTML = "";
    }
    const err = document.getElementById("import-cust-error");
    if (err) {
        err.style.display = "none";
        err.textContent = "";
    }
    const loading = document.getElementById("import-cust-loading");
    if (loading) loading.style.display = "none";

    const submitBtn = document.getElementById("btn-submit-import-cust");
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = 'Upload &amp; Import';
    }

    modal.style.display = "flex";
}

function closeImportCustomersModal() {
    const modal = document.getElementById("import-customers-modal");
    if (modal) {
        modal.style.display = "none";
    }
    clearSelectedCustFile();
}

function clearSelectedCustFile() {
    selectedImportCustFile = null;
    const fileInput = document.getElementById("import-cust-file-input");
    if (fileInput) fileInput.value = "";

    const preview = document.getElementById("import-cust-file-preview");
    if (preview) preview.style.display = "none";

    const dropzone = document.getElementById("import-cust-dropzone");
    if (dropzone) dropzone.style.display = "block";

    const submitBtn = document.getElementById("btn-submit-import-cust");
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = 'Upload &amp; Import';
    }
}

function handleCustFileSelected(file) {
    if (!file) return;

    const err = document.getElementById("import-cust-error");
    if (err) err.style.display = "none";

    const name = file.name.toLowerCase();
    const validExts = [".csv", ".xlsx", ".xls"];
    const isValid = validExts.some(ext => name.endsWith(ext));

    if (!isValid) {
        if (err) {
            err.textContent = `Invalid file format for "${file.name}". Please upload a .csv, .xlsx, or .xls file.`;
            err.style.display = "block";
        }
        if (window.showToast) window.showToast("Unsupported file format. Please upload .csv or .xlsx.", "error");
        clearSelectedCustFile();
        return;
    }

    if (file.size > 10 * 1024 * 1024) {
        if (err) {
            err.textContent = `File size (${(file.size / (1024 * 1024)).toFixed(2)} MB) exceeds maximum limit of 10 MB.`;
            err.style.display = "block";
        }
        if (window.showToast) window.showToast("File exceeds 10 MB limit.", "error");
        clearSelectedCustFile();
        return;
    }

    selectedImportCustFile = file;

    // Update preview
    const nameEl = document.getElementById("import-cust-file-name");
    const metaEl = document.getElementById("import-cust-file-meta");
    const preview = document.getElementById("import-cust-file-preview");
    const dropzone = document.getElementById("import-cust-dropzone");
    const submitBtn = document.getElementById("btn-submit-import-cust");

    if (nameEl) nameEl.textContent = file.name;
    if (metaEl) {
        const sizeKb = (file.size / 1024).toFixed(1);
        const typeStr = name.endsWith(".csv") ? "CSV Spreadsheet" : "Excel Spreadsheet";
        metaEl.textContent = `${sizeKb} KB • ${typeStr}`;
    }

    if (dropzone) dropzone.style.display = "none";
    if (preview) preview.style.display = "flex";
    if (submitBtn) submitBtn.disabled = false;
}

async function submitImportCustomers() {
    if (!selectedImportCustFile) {
        const err = document.getElementById("import-cust-error");
        if (err) {
            err.textContent = "Please select a CSV or Excel file to upload.";
            err.style.display = "block";
        }
        return;
    }

    const submitBtn = document.getElementById("btn-submit-import-cust");
    const cancelBtn = document.getElementById("btn-cancel-import-cust");
    const loading = document.getElementById("import-cust-loading");
    const err = document.getElementById("import-cust-error");
    const resultBox = document.getElementById("import-cust-result-box");
    const preview = document.getElementById("import-cust-file-preview");

    if (err) err.style.display = "none";
    if (resultBox) resultBox.style.display = "none";
    if (loading) loading.style.display = "block";
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner" style="display:inline-block;width:14px;height:14px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;margin-right:6px;vertical-align:middle;"></span> Importing...';
    }
    if (cancelBtn) cancelBtn.disabled = true;

    try {
        const formData = new FormData();
        formData.append("file", selectedImportCustFile);

        // Fetch request: auth token and tenant ID are automatically attached by api.js fetch interceptor
        const res = await fetch("/api/v1/customers/import", {
            method: "POST",
            body: formData
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "Failed to import customers.");
        }

        // Render success summary
        if (resultBox) {
            const escape = (window.escapeHtml || (s => String(s || "").replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])));
            const hasErrors = data.errors && data.errors.length > 0;
            let errorsHtml = "";
            if (hasErrors) {
                const errorItems = data.errors.slice(0, 10).map(e => `<li style="margin-bottom: 2px;">${escape(e)}</li>`).join("");
                const extraNote = data.errors.length > 10 ? `<li style="font-style: italic; color: var(--text-secondary);">...and ${data.errors.length - 10} more notes</li>` : "";
                errorsHtml = `
                    <div style="margin-top: 10px; padding: 8px 10px; background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 6px;">
                        <div style="font-weight: 600; font-size: 0.8rem; color: #f59e0b; margin-bottom: 4px;">Validation Notes &amp; Skipped Items:</div>
                        <ul style="margin: 0; padding-left: 18px; font-size: 0.78rem; color: var(--text-secondary); max-height: 120px; overflow-y: auto;">
                            ${errorItems}
                            ${extraNote}
                        </ul>
                    </div>
                `;
            }

            resultBox.innerHTML = `
                <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 8px; padding: 12px;">
                    <div style="display: flex; align-items: center; gap: 8px; font-weight: 600; color: #10b981; font-size: 0.95rem; margin-bottom: 8px;">
                        <span>✓</span> Import Successful!
                    </div>
                    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; text-align: center; margin-bottom: 6px;">
                        <div style="background: rgba(255, 255, 255, 0.04); padding: 8px 4px; border-radius: 6px;">
                            <div style="font-size: 1.1rem; font-weight: 700; color: var(--text-primary);">${data.total_processed}</div>
                            <div style="font-size: 0.72rem; color: var(--text-secondary);">Total Processed</div>
                        </div>
                        <div style="background: rgba(16, 185, 129, 0.08); padding: 8px 4px; border-radius: 6px;">
                            <div style="font-size: 1.1rem; font-weight: 700; color: #10b981;">+${data.successfully_added}</div>
                            <div style="font-size: 0.72rem; color: var(--text-secondary);">Added to Store</div>
                        </div>
                        <div style="background: rgba(245, 158, 11, 0.08); padding: 8px 4px; border-radius: 6px;">
                            <div style="font-size: 1.1rem; font-weight: 700; color: #f59e0b;">${data.skipped_duplicates}</div>
                            <div style="font-size: 0.72rem; color: var(--text-secondary);">Duplicates Skipped</div>
                        </div>
                    </div>
                    ${errorsHtml}
                </div>
            `;
            resultBox.style.display = "block";
        }

        if (preview) preview.style.display = "none";
        selectedImportCustFile = null;

        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = "Import Completed";
        }

        if (window.showToast) {
            window.showToast(`Import completed! ${data.successfully_added} new customers added.`, "success");
        }

        // Refresh customers dashboard
        await loadUdhaarDashboard();

        // Dispatch customer updated event
        try { window.dispatchEvent(new CustomEvent("customers-updated", { detail: data })); } catch (_) {}

    } catch (e) {
        if (err) {
            err.textContent = e.message || "Failed to import customers.";
            err.style.display = "block";
        }
        if (window.showToast) {
            window.showToast(e.message || "Customer import failed", "error");
        }
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = 'Upload &amp; Import';
        }
    } finally {
        if (loading) loading.style.display = "none";
        if (cancelBtn) cancelBtn.disabled = false;
    }
}

function openCreateCustomerModal() {
    const modal = document.getElementById("create-customer-modal");
    const nameInput = document.getElementById("create-cust-name");
    const phoneInput = document.getElementById("create-cust-phone");
    const limitInput = document.getElementById("create-cust-limit");
    const addrLineInput = document.getElementById("create-cust-address-line");
    const cityInput = document.getElementById("create-cust-city");
    const stateInput = document.getElementById("create-cust-state");
    const pinInput = document.getElementById("create-cust-pincode");
    const countryInput = document.getElementById("create-cust-country");
    const err = document.getElementById("create-cust-error");

    if (nameInput) nameInput.value = "";
    if (phoneInput) phoneInput.value = "";
    if (limitInput) limitInput.value = "3000";
    if (addrLineInput) addrLineInput.value = "";
    if (cityInput) cityInput.value = "";
    if (stateInput) stateInput.value = "";
    if (pinInput) pinInput.value = "";
    if (countryInput) countryInput.value = "India";
    if (err) err.style.display = "none";

    if (modal) modal.style.display = "flex";
}

async function submitCreateCustomer() {
    const nameInput = document.getElementById("create-cust-name");
    const phoneInput = document.getElementById("create-cust-phone");
    const limitInput = document.getElementById("create-cust-limit");
    const addrLineInput = document.getElementById("create-cust-address-line");
    const cityInput = document.getElementById("create-cust-city");
    const stateInput = document.getElementById("create-cust-state");
    const pinInput = document.getElementById("create-cust-pincode");
    const countryInput = document.getElementById("create-cust-country");
    const err = document.getElementById("create-cust-error");
    const modal = document.getElementById("create-customer-modal");

    const name = nameInput ? nameInput.value.trim() : "";
    const phone = phoneInput ? phoneInput.value.trim() : "";
    const limit = limitInput ? parseFloat(limitInput.value) : 2000;
    const addressLine = addrLineInput ? addrLineInput.value.trim() : "";
    const city = cityInput ? cityInput.value.trim() : "";
    const state = stateInput ? stateInput.value.trim() : "";
    const pincode = pinInput ? pinInput.value.trim() : "";
    const country = countryInput && countryInput.value.trim() ? countryInput.value.trim() : "India";

    if (!name || name.length < 2) {
        showModalError(err, "Please enter a valid customer name (at least 2 characters).");
        return;
    }
    if (!phone || !/^\d{10}$/.test(phone)) {
        showModalError(err, "Please enter a valid 10-digit mobile phone number (exactly 10 digits, numbers only).");
        return;
    }
    if (isNaN(limit) || limit < 0) {
        showModalError(err, "Please enter a valid positive credit limit.");
        return;
    }
    if (!addressLine) {
        showModalError(err, "Address Line is mandatory for Udhaar customer accounts.");
        return;
    }
    if (!city) {
        showModalError(err, "City is mandatory.");
        return;
    }
    if (!state) {
        showModalError(err, "State is mandatory.");
        return;
    }
    if (country.toLowerCase() === "india") {
        if (!pincode || !/^\d{6}$/.test(pincode)) {
            showModalError(err, "PIN code must contain exactly 6 digits (numbers only, no alphabets). Example: 160017.");
            return;
        }
    } else {
        const alphanumericCount = (pincode.match(/[A-Za-z0-9]/g) || []).length;
        if (!pincode || !/^[A-Za-z0-9\s\-]{3,10}$/.test(pincode) || alphanumericCount < 3) {
            showModalError(err, `Postal code for ${country} must be 4 to 10 alphanumeric characters. Example: 90210.`);
            return;
        }
    }

    try {
        const res = await fetch("/api/v1/customers", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                full_name: name,
                phone: phone,
                credit_limit: limit,
                address_line: addressLine,
                city: city,
                state: state,
                pincode: pincode,
                country: country
            })
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "Failed to create customer account");
        }

        if (modal) modal.style.display = "none";
        selectedUdhaarCustomerId = data.id;
        await loadUdhaarDashboard();
        selectUdhaarCustomer(data.id);

        // Reactive system-wide event dispatch for customer mutation
        try { window.dispatchEvent(new CustomEvent("customers-updated", { detail: data })); } catch(e){}

    } catch (e) {
        showModalError(err, e.message);
    }
}

function openAddMemberModal() {
    if (!selectedUdhaarCustomerId) return;
    const cust = allUdhaarCustomers.find(c => c.id === selectedUdhaarCustomerId);
    const parentNameEl = document.getElementById("add-member-parent-name");
    const nameInput = document.getElementById("member-name");
    const phoneInput = document.getElementById("member-phone");
    const limitInput = document.getElementById("member-spending-limit");
    const err = document.getElementById("add-member-error");
    const modal = document.getElementById("add-member-modal");

    if (parentNameEl && cust) parentNameEl.textContent = cust.full_name;
    if (nameInput) nameInput.value = "";
    if (phoneInput) phoneInput.value = "";
    if (limitInput) limitInput.value = "";
    if (err) err.style.display = "none";

    if (modal) modal.style.display = "flex";
}

async function submitAddMember() {
    if (!selectedUdhaarCustomerId) return;
    const nameInput = document.getElementById("member-name");
    const relationSelect = document.getElementById("member-relation");
    const phoneInput = document.getElementById("member-phone");
    const limitInput = document.getElementById("member-spending-limit");
    const err = document.getElementById("add-member-error");
    const modal = document.getElementById("add-member-modal");

    const name = nameInput ? nameInput.value.trim() : "";
    const relation = relationSelect ? relationSelect.value : "Son";
    const phone = phoneInput ? phoneInput.value.trim() : null;
    const spendingLimit = limitInput && limitInput.value ? parseFloat(limitInput.value) : null;

    if (!name || name.length < 2) {
        showModalError(err, "Please enter family member's full name.");
        return;
    }

    if (phone && !/^\d{10}$/.test(phone)) {
        showModalError(err, "Family member phone number must be exactly 10 digits (digits only). Example: 9876543210.");
        return;
    }

    try {
        const res = await fetch(`/api/v1/customers/${selectedUdhaarCustomerId}/family-members`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                full_name: name,
                relation_type: relation,
                phone: phone,
                allowed_spending_limit: spendingLimit
            })
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "Failed to add family member");
        }

        if (modal) modal.style.display = "none";
        selectUdhaarCustomer(selectedUdhaarCustomerId);

    } catch (e) {
        showModalError(err, e.message);
    }
}

async function handleDeleteCustomer() {
    if (!selectedUdhaarCustomerId) return;
    const cust = allUdhaarCustomers.find(c => c.id === selectedUdhaarCustomerId);
    if (!cust) return;

    if (cust.current_udhaar_balance > 0) {
        alert(
            `Account cannot be deleted because outstanding Udhaar remains.\n\n` +
            `Customer: ${cust.full_name}\n` +
            `Outstanding Balance: ₹${cust.current_udhaar_balance.toFixed(2)}\n\n` +
            `Deletion is blocked by store policy until balance is settled to ₹0.00.`
        );
        return;
    }

    const code = cust.customer_code || `C-${String(cust.id).padStart(6, '0')}`;
    const confirmed = confirm(
        `Are you sure you want to delete account '${cust.full_name}' (${code})?\n\n` +
        `• Current Outstanding Balance: ₹0.00.\n` +
        `• Historical financial records and ledger transactions will be safely preserved.\n` +
        `• Remaining customer accounts will be automatically re-sequenced gaplessly.`
    );
    if (!confirmed) return;

    try {
        const res = await fetch(`/api/v1/customers/${cust.id}`, {
            method: "DELETE"
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "Failed to delete account");
        }
        alert(data.message || "Account successfully deleted.");
        selectedUdhaarCustomerId = null;
        await loadUdhaarDashboard();

        // Reactive system-wide event dispatch for customer deletion
        try { 
            window.dispatchEvent(new CustomEvent("customers-updated", { detail: data })); 
            if (window.AppEvents) window.AppEvents.emit("customers-updated", data);
        } catch(e){}
    } catch (err) {
        console.error("Delete customer error:", err);
        alert(`Deletion Failed:\n${err.message}`);
    }
};

async function handleCustomerPhoneOTP(customerId) {
    try {
        const reqRes = await fetch(`/api/v1/customers/${customerId}/request-phone-otp`, { method: "POST" });
        const reqData = await reqRes.json();
        if (!reqRes.ok) throw new Error(reqData.detail || "Failed to request OTP");

        const otpCode = prompt(`${reqData.message}\n\n[DEMO/TEST ENVIRONMENT]: Enter the 6-digit OTP code (Demo code: ${reqData.demo_otp || "------"}):`);
        if (!otpCode) return;

        const verifyRes = await fetch(`/api/v1/customers/${customerId}/verify-phone-otp`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ otp_code: otpCode.trim() })
        });
        const verifyData = await verifyRes.json();
        if (!verifyRes.ok) throw new Error(verifyData.detail || "OTP verification failed");

        alert(verifyData.message);
        await loadUdhaarDashboard();
        selectUdhaarCustomer(customerId);
    } catch (e) {
        alert(`OTP Verification Error: ${e.message}`);
    }
};

async function handleMemberPhoneOTP(customerId, memberId) {
    try {
        const reqRes = await fetch(`/api/v1/customers/${customerId}/family-members/${memberId}/request-phone-otp`, { method: "POST" });
        const reqData = await reqRes.json();
        if (!reqRes.ok) throw new Error(reqData.detail || "Failed to request OTP");

        const otpCode = prompt(`${reqData.message}\n\n[DEMO/TEST ENVIRONMENT]: Enter the 6-digit OTP code (Demo code: ${reqData.demo_otp || "------"}):`);
        if (!otpCode) return;

        const verifyRes = await fetch(`/api/v1/customers/${customerId}/family-members/${memberId}/verify-phone-otp`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ otp_code: otpCode.trim() })
        });
        const verifyData = await verifyRes.json();
        if (!verifyRes.ok) throw new Error(verifyData.detail || "OTP verification failed");

        alert(verifyData.message);
        selectUdhaarCustomer(customerId);
    } catch (e) {
        alert(`OTP Verification Error: ${e.message}`);
    }
};

function openSettleModal() {
    if (!selectedUdhaarCustomerId) return;
    const cust = allUdhaarCustomers.find(c => c.id === selectedUdhaarCustomerId);
    if (!cust) return;

    if (cust.current_udhaar_balance <= 0) {
        alert(`${cust.full_name} has zero outstanding Udhaar balance.`);
        return;
    }

    const custNameEl = document.getElementById("settle-customer-name");
    const balEl = document.getElementById("settle-modal-balance");
    const amountInput = document.getElementById("settle-amount");
    const notesInput = document.getElementById("settle-notes");
    const err = document.getElementById("settle-error-msg");
    const modal = document.getElementById("settle-udhaar-modal");

    if (custNameEl) custNameEl.textContent = cust.full_name;
    if (balEl) balEl.textContent = `₹${cust.current_udhaar_balance.toFixed(2)}`;
    if (amountInput) {
        amountInput.value = cust.current_udhaar_balance.toFixed(2);
        amountInput.max = cust.current_udhaar_balance;
    }
    if (notesInput) notesInput.value = "";
    if (err) err.style.display = "none";

    if (modal) modal.style.display = "flex";
}

async function submitSettleUdhaar() {
    if (!selectedUdhaarCustomerId) return;
    const amountInput = document.getElementById("settle-amount");
    const modeEl = document.querySelector("#settle-udhaar-modal input[name='settle-mode']:checked");
    const notesInput = document.getElementById("settle-notes");
    const err = document.getElementById("settle-error-msg");
    const modal = document.getElementById("settle-udhaar-modal");

    const amount = amountInput ? parseFloat(amountInput.value) : 0;
    const paymentMode = modeEl ? modeEl.value : "CASH";
    const notes = notesInput ? notesInput.value.trim() : "";

    if (isNaN(amount) || amount <= 0) {
        showModalError(err, "Please enter a valid repayment amount greater than 0.");
        return;
    }

    try {
        const res = await fetch(`/api/v1/customers/${selectedUdhaarCustomerId}/settle`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                amount: amount,
                payment_mode: paymentMode,
                notes: notes
            })
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "Settlement failed");
        }

        if (modal) modal.style.display = "none";

        // Counter Settlement Voice Announcement via ElevenLabs
        try {
            const cust = (allUdhaarCustomers || []).find(c => c.id === selectedUdhaarCustomerId);
            const customerName = (cust && (cust.full_name || cust.name)) || "Customer";
            const remainingBalance = (data.new_balance !== undefined && data.new_balance !== null)
                ? Number(data.new_balance).toFixed(2)
                : "0.00";
            const announceText = `Received ₹${amount.toFixed(2)} from ${customerName}. Remaining Udhaar balance is ₹${remainingBalance}.`;
            if (typeof window.speakWithElevenLabs === "function") {
                window.speakWithElevenLabs(announceText);
            }
        } catch (voiceErr) {
            console.warn("Counter settlement announcement notice:", voiceErr);
        }

        alert(`Payment Recorded!\nSuccessfully settled ₹${amount.toFixed(2)} via ${paymentMode}.\nNew Balance: ₹${data.new_balance.toFixed(2)}`);
        await loadUdhaarDashboard();
        selectUdhaarCustomer(selectedUdhaarCustomerId);

        // Reactive system-wide event dispatch for repayment settlement
        try { 
            window.dispatchEvent(new CustomEvent("customers-updated", { detail: data })); 
            if (window.AppEvents) window.AppEvents.emit("customers-updated", data);
        } catch(e){}

    } catch (e) {
        showModalError(err, e.message);
    }
}

function openEditProfileModal() {
    if (!selectedUdhaarCustomerId) return;
    const cust = allUdhaarCustomers.find(c => c.id === selectedUdhaarCustomerId);
    if (!cust) return;

    const nameInput = document.getElementById("edit-cust-name");
    const phoneInput = document.getElementById("edit-cust-phone");
    const limitInput = document.getElementById("edit-cust-limit") || document.getElementById("edit-limit-input");
    const addrLineInput = document.getElementById("edit-cust-address-line");
    const cityInput = document.getElementById("edit-cust-city");
    const stateInput = document.getElementById("edit-cust-state");
    const pinInput = document.getElementById("edit-cust-pincode");
    const countryInput = document.getElementById("edit-cust-country");
    const codeBadge = document.getElementById("edit-cust-code-badge");
    const nameHeader = document.getElementById("edit-cust-name-header");
    const limitCustName = document.getElementById("edit-limit-cust-name");
    const err = document.getElementById("edit-cust-error") || document.getElementById("edit-limit-error");
    const modal = document.getElementById("edit-customer-modal") || document.getElementById("edit-limit-modal");

    const code = cust.customer_code || `C-${String(cust.id).padStart(6, '0')}`;
    if (codeBadge) codeBadge.textContent = code;
    if (nameHeader) nameHeader.textContent = cust.full_name;
    if (limitCustName) limitCustName.textContent = cust.full_name;
    if (nameInput) nameInput.value = cust.full_name || "";
    if (phoneInput) phoneInput.value = cust.phone || "";
    if (limitInput) limitInput.value = cust.credit_limit !== undefined ? cust.credit_limit : 2000;
    if (addrLineInput) addrLineInput.value = cust.address_line || "";
    if (cityInput) cityInput.value = cust.city || "";
    if (stateInput) stateInput.value = cust.state || "";
    if (pinInput) pinInput.value = cust.pincode || "";
    if (countryInput) countryInput.value = cust.country || "India";
    if (err) err.style.display = "none";

    if (modal) modal.style.display = "flex";
}

function openEditLimitModal() {
    openEditProfileModal();
}

async function submitEditProfile() {
    if (!selectedUdhaarCustomerId) return;
    const nameInput = document.getElementById("edit-cust-name");
    const phoneInput = document.getElementById("edit-cust-phone");
    const limitInput = document.getElementById("edit-cust-limit") || document.getElementById("edit-limit-input");
    const addrLineInput = document.getElementById("edit-cust-address-line");
    const cityInput = document.getElementById("edit-cust-city");
    const stateInput = document.getElementById("edit-cust-state");
    const pinInput = document.getElementById("edit-cust-pincode");
    const countryInput = document.getElementById("edit-cust-country");
    const err = document.getElementById("edit-cust-error") || document.getElementById("edit-limit-error");

    const name = nameInput ? nameInput.value.trim() : "";
    const phone = phoneInput ? phoneInput.value.trim() : "";
    const limit = limitInput ? parseFloat(limitInput.value) : -1;
    const addressLine = addrLineInput ? addrLineInput.value.trim() : "";
    const city = cityInput ? cityInput.value.trim() : "";
    const state = stateInput ? stateInput.value.trim() : "";
    const pincode = pinInput ? pinInput.value.trim() : "";
    const country = countryInput && countryInput.value.trim() ? countryInput.value.trim() : "India";

    if (!name || name.length < 2) {
        showModalError(err, "Please enter a valid customer name (at least 2 characters).");
        return;
    }
    if (!phone || !/^\d{10}$/.test(phone)) {
        showModalError(err, "Please enter a valid 10-digit mobile phone number (exactly 10 digits, numbers only).");
        return;
    }
    if (isNaN(limit) || limit < 0) {
        showModalError(err, "Credit limit must be a non-negative number.");
        return;
    }
    if (!addressLine) {
        showModalError(err, "Address Line / Street / House is mandatory.");
        return;
    }
    if (!city) {
        showModalError(err, "City is mandatory.");
        return;
    }
    if (!state) {
        showModalError(err, "State is mandatory.");
        return;
    }
    if (country.toLowerCase() === "india") {
        if (!pincode || !/^\d{6}$/.test(pincode)) {
            showModalError(err, "PIN code must contain exactly 6 digits (numbers only, no alphabets). Example: 160017.");
            return;
        }
    } else {
        const alphanumericCount = (pincode.match(/[A-Za-z0-9]/g) || []).length;
        if (!pincode || !/^[A-Za-z0-9\s\-]{3,10}$/.test(pincode) || alphanumericCount < 3) {
            showModalError(err, `Postal code for ${country} must be 4 to 10 alphanumeric characters. Example: 90210.`);
            return;
        }
    }

    try {
        const payload = {
            full_name: name,
            phone: phone,
            credit_limit: limit,
            address_line: addressLine,
            city: city,
            state: state,
            pincode: pincode,
            country: country
        };

        const res = await fetch(`/api/v1/customers/${selectedUdhaarCustomerId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const updatedCust = await res.json();
        if (!res.ok) throw new Error(updatedCust.detail || "Failed to update customer profile");

        // Close Modals
        closeModal("edit-customer-modal");
        closeModal("edit-limit-modal");

        // 1. In-place update in local allUdhaarCustomers cache
        const idx = allUdhaarCustomers.findIndex(c => c.id === selectedUdhaarCustomerId);
        if (idx !== -1) {
            allUdhaarCustomers[idx] = { ...allUdhaarCustomers[idx], ...updatedCust };
        }

        // 2. Real-time in-place update of customer header
        const nameEl = document.getElementById("detail-customer-name");
        const phoneEl = document.getElementById("detail-customer-phone");
        const addrEl = document.getElementById("detail-customer-address");
        if (nameEl) nameEl.textContent = updatedCust.full_name;
        if (phoneEl) phoneEl.textContent = updatedCust.phone;
        if (addrEl) {
            if (updatedCust.address_line) {
                addrEl.textContent = `${updatedCust.address_line}, ${updatedCust.city}, ${updatedCust.state} - ${updatedCust.pincode}, ${updatedCust.country || 'India'}`;
            } else {
                addrEl.textContent = updatedCust.address || "Local Kirana Customer";
            }
        }

        // 3. Real-time update of credit bar metrics
        const curBalEl = document.getElementById("detail-current-balance");
        const availEl = document.getElementById("detail-available-credit");
        const limitEl = document.getElementById("detail-credit-limit");
        const barFill = document.getElementById("detail-credit-bar-fill");
        if (curBalEl) curBalEl.textContent = `₹${updatedCust.current_udhaar_balance.toFixed(2)}`;
        if (availEl) availEl.textContent = `₹${updatedCust.available_credit.toFixed(2)}`;
        if (limitEl) limitEl.textContent = `₹${updatedCust.credit_limit.toFixed(2)}`;
        const pctUsed = updatedCust.credit_limit > 0
            ? Math.min(100, Math.round((updatedCust.current_udhaar_balance / updatedCust.credit_limit) * 100))
            : 0;
        if (barFill) barFill.style.width = `${pctUsed}%`;

        // 4. Update the Customer's card in the left Customer Accounts sidebar
        renderUdhaarCustomerCards(allUdhaarCustomers);

        // 5. Update top KPI summary cards (Total Udhaar & Available Store Credit)
        const availCreditEl = document.getElementById("metric-available-credit");
        const totalUdhaarEl = document.getElementById("metric-total-udhaar");
        let totalOutstanding = 0;
        let totalAvailable = 0;
        allUdhaarCustomers.forEach(c => {
            totalOutstanding += c.current_udhaar_balance;
            totalAvailable += c.available_credit;
        });
        if (availCreditEl) availCreditEl.textContent = `₹${totalAvailable.toFixed(2)}`;
        if (totalUdhaarEl) totalUdhaarEl.textContent = `₹${totalOutstanding.toFixed(2)}`;

        // 6. Reactive system-wide event dispatch for customer update
        try { 
            window.dispatchEvent(new CustomEvent("customers-updated", { detail: updatedCust })); 
            if (window.AppEvents) window.AppEvents.emit("customers-updated", updatedCust);
        } catch(e){}

    } catch (e) {
        showModalError(err, e.message);
    }
}

async function submitEditLimit() {
    await submitEditProfile();
}

function showModalError(element, message) {
    if (element) {
        element.textContent = message;
        element.style.display = "block";
    }
}

/* ============================================================
   DUPLICATE CUSTOMER CLEANUP MODULE
   ============================================================ */

/** @type {{ groups: any[], safe_to_delete_count: number } | null} */
let _dupScanResult = null;

function openDuplicateCleanupModal() {
    const modal = document.getElementById("duplicate-cleanup-modal");
    if (!modal) {
        _injectDuplicateCleanupModal();
        return;
    }
    modal.style.display = "flex";
    _renderDupScanState("idle");
}

function closeDuplicateCleanupModal() {
    const modal = document.getElementById("duplicate-cleanup-modal");
    if (modal) modal.style.display = "none";
    _dupScanResult = null;
}

function _injectDuplicateCleanupModal() {
    // Build the modal HTML and append to body, then open
    const overlay = document.createElement("div");
    overlay.id = "duplicate-cleanup-modal";
    overlay.className = "modal-overlay";
    overlay.style.cssText = "display:flex;z-index:10000;";
    overlay.innerHTML = `
        <div class="modal-box" id="dup-cleanup-box" style="max-width:780px;width:95%;max-height:90vh;display:flex;flex-direction:column;">
            <!-- Header -->
            <div class="modal-header" style="display:flex;align-items:center;justify-content:space-between;">
                <h3 style="margin:0;font-size:1.1rem;display:flex;align-items:center;gap:0.5rem;">
                    Duplicate Customer Cleanup
                </h3>
                <button type="button" onclick="closeDuplicateCleanupModal()"
                    style="background:none;border:none;color:var(--text-secondary);font-size:1.4rem;cursor:pointer;line-height:1;">×</button>
            </div>

            <!-- Body -->
            <div id="dup-cleanup-body" style="overflow-y:auto;flex:1;padding:1rem 1.25rem;">
                <!-- Filled dynamically -->
            </div>

            <!-- Footer -->
            <div class="modal-footer" id="dup-cleanup-footer"
                style="display:flex;gap:0.75rem;justify-content:flex-end;padding:0.85rem 1.25rem;border-top:1px solid var(--border-color);flex-wrap:wrap;">
                <!-- Filled dynamically -->
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    _renderDupScanState("idle");
}

function _renderDupScanState(state, data) {
    const body = document.getElementById("dup-cleanup-body");
    const footer = document.getElementById("dup-cleanup-footer");
    if (!body || !footer) return;

    if (state === "idle") {
        body.innerHTML = `
            <div style="text-align:center;padding:2rem 1rem;">
                <p style="color:var(--text-secondary);max-width:480px;margin:0 auto 1.5rem;">
                    Scan all customer accounts for duplicate names. Accounts with
                    <strong>no outstanding balance, no bills, and no Udhaar history</strong>
                    are safe to delete permanently.
                </p>
                <div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.3);border-radius:8px;padding:0.75rem 1rem;font-size:0.82rem;color:#fca5a5;max-width:480px;margin:0 auto;">
                    <strong>Hard Delete:</strong> Clean duplicates will be permanently removed.
                    The oldest account in each group is always kept.
                </div>
            </div>`;
        footer.innerHTML = `
            <button type="button" onclick="closeDuplicateCleanupModal()"
                class="btn btn-secondary" style="padding:0.5rem 1.25rem;">Cancel</button>
            <button type="button" id="dup-scan-btn" onclick="runDuplicateScan()"
                class="btn btn-primary" style="padding:0.5rem 1.4rem;background:linear-gradient(135deg,#6366f1,#8b5cf6);">
                Scan for Duplicates
            </button>`;
    } else if (state === "scanning") {
        body.innerHTML = `
            <div style="text-align:center;padding:3rem 1rem;">
                <div class="spinner" style="width:40px;height:40px;border:3px solid rgba(99,102,241,0.2);
                    border-top-color:#6366f1;border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 1rem;"></div>
                <p style="color:var(--text-secondary);">Scanning customer database…</p>
            </div>`;
        footer.innerHTML = ``;
    } else if (state === "results") {
        _renderDupResults(data);
    } else if (state === "executing") {
        body.innerHTML = `
            <div style="text-align:center;padding:3rem 1rem;">
                <div class="spinner" style="width:40px;height:40px;border:3px solid rgba(239,68,68,0.2);
                    border-top-color:#ef4444;border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 1rem;"></div>
                <p style="color:var(--text-secondary);">Deleting duplicates…</p>
            </div>`;
        footer.innerHTML = ``;
    } else if (state === "done") {
        _renderDupDoneState(data);
    }
}

function _renderDupResults(scanData) {
    const body = document.getElementById("dup-cleanup-body");
    const footer = document.getElementById("dup-cleanup-footer");
    if (!body || !footer) return;

    const { total_duplicate_groups, total_duplicate_accounts, safe_to_delete_count, groups } = scanData;

    if (total_duplicate_groups === 0) {
        body.innerHTML = `
            <div style="text-align:center;padding:2.5rem 1rem;">
                <h4 style="color:#4ade80;margin:0 0 0.4rem;">No Duplicates Found!</h4>
                <p style="color:var(--text-secondary);margin:0;">All customer accounts have unique names.</p>
            </div>`;
        footer.innerHTML = `
            <button type="button" onclick="closeDuplicateCleanupModal()"
                class="btn btn-primary" style="padding:0.5rem 1.4rem;">Close</button>`;
        return;
    }

    // Summary bar
    let html = `
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.75rem;margin-bottom:1.25rem;">
            <div style="background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.3);border-radius:8px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.6rem;font-weight:700;color:#a5b4fc;">${total_duplicate_groups}</div>
                <div style="font-size:0.75rem;color:var(--text-secondary);">Duplicate Groups</div>
            </div>
            <div style="background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.3);border-radius:8px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.6rem;font-weight:700;color:#fcd34d;">${total_duplicate_accounts}</div>
                <div style="font-size:0.75rem;color:var(--text-secondary);">Total Duplicate Accounts</div>
            </div>
            <div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);border-radius:8px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.6rem;font-weight:700;color:#fca5a5;">${safe_to_delete_count}</div>
                <div style="font-size:0.75rem;color:var(--text-secondary);">Safe to Delete</div>
            </div>
        </div>`;

    // Groups
    html += `<div style="display:flex;flex-direction:column;gap:1rem;">`;
    groups.forEach(group => {
        html += `
            <div style="border:1px solid var(--border-color);border-radius:10px;overflow:hidden;">
                <div style="background:rgba(30,41,59,0.7);padding:0.65rem 1rem;display:flex;align-items:center;justify-content:space-between;">
                    <div style="display:flex;align-items:center;gap:0.6rem;">
                        <span style="font-weight:600;font-size:0.95rem;">${escapeHtml(group.duplicate_name)}</span>
                        <span style="background:rgba(99,102,241,0.2);color:#a5b4fc;border-radius:4px;font-size:0.72rem;padding:2px 7px;">
                            ${group.count} accounts
                        </span>
                        ${group.safe_to_delete_ids.length > 0
                            ? `<span style="background:rgba(239,68,68,0.15);color:#fca5a5;border-radius:4px;font-size:0.72rem;padding:2px 7px;">
                                ${group.safe_to_delete_ids.length} deletable
                               </span>`
                            : `<span style="background:rgba(74,222,128,0.12);color:#4ade80;border-radius:4px;font-size:0.72rem;padding:2px 7px;">All have history</span>`}
                    </div>
                </div>
                <div style="padding:0.5rem;display:flex;flex-direction:column;gap:0.4rem;">
                    ${group.members.map(m => {
                        const isKeep  = m.id === group.keep_id;
                        const isSafe  = group.safe_to_delete_ids.includes(m.id);
                        const hasData = m.has_bills || m.has_udhaar_transactions || m.current_udhaar_balance > 0;

                        const statusTag = isKeep
                            ? `<span style="background:rgba(74,222,128,0.15);color:#4ade80;border-radius:4px;font-size:0.7rem;padding:2px 6px;">Keep (Oldest)</span>`
                            : isSafe
                                ? `<span style="background:rgba(239,68,68,0.15);color:#fca5a5;border-radius:4px;font-size:0.7rem;padding:2px 6px;">Safe to Delete</span>`
                                : `<span style="background:rgba(245,158,11,0.15);color:#fcd34d;border-radius:4px;font-size:0.7rem;padding:2px 6px;">Has History</span>`;

                        return `
                            <div style="display:flex;align-items:center;justify-content:space-between;
                                background:${isKeep ? 'rgba(74,222,128,0.05)' : isSafe ? 'rgba(239,68,68,0.05)' : 'rgba(245,158,11,0.05)'};
                                border-radius:7px;padding:0.5rem 0.75rem;gap:0.5rem;">
                                <div style="display:flex;flex-direction:column;gap:0.1rem;flex:1;min-width:0;">
                                    <div style="display:flex;align-items:center;gap:0.4rem;flex-wrap:wrap;">
                                        <span style="font-size:0.82rem;font-weight:600;">${
                                            m.customer_code || ('C-' + String(m.id).padStart(6,'0'))
                                        }</span>
                                        ${statusTag}
                                        ${!m.is_active ? '<span style="font-size:0.7rem;color:var(--text-secondary);">Inactive</span>' : ''}
                                    </div>
                                    <div style="font-size:0.77rem;color:var(--text-secondary);display:flex;gap:1rem;flex-wrap:wrap;">
                                        <span>${escapeHtml(m.phone)}</span>
                                        <span>Balance: <strong style="color:${m.current_udhaar_balance>0?'#fca5a5':'#94a3b8'};">₹${m.current_udhaar_balance.toFixed(2)}</strong></span>
                                        ${m.has_bills ? '<span style="color:#fcd34d;">Bills</span>' : ''}
                                        ${m.has_udhaar_transactions ? '<span style="color:#fcd34d;">Udhaar Ledger</span>' : ''}
                                    </div>
                                </div>
                                ${isSafe ? `
                                    <label style="display:flex;align-items:center;gap:0.35rem;cursor:pointer;white-space:nowrap;">
                                        <input type="checkbox" class="dup-delete-checkbox"
                                            data-id="${m.id}" checked
                                            style="width:16px;height:16px;cursor:pointer;accent-color:#ef4444;">
                                        <span style="font-size:0.78rem;color:var(--text-secondary);">Delete</span>
                                    </label>` : ''}
                            </div>`;
                    }).join('')}
                </div>
            </div>`;
    });
    html += `</div>`;

    body.innerHTML = html;

    // Footer buttons
    footer.innerHTML = `
        <button type="button" onclick="_renderDupScanState('idle')" class="btn btn-secondary"
            style="padding:0.5rem 1.1rem;">← Back</button>
        <button type="button" onclick="closeDuplicateCleanupModal()" class="btn btn-secondary"
            style="padding:0.5rem 1.1rem;">Cancel</button>
        <button type="button" id="dup-dryrun-btn" onclick="runDuplicateDelete(true)" class="btn btn-secondary"
            style="padding:0.5rem 1.2rem;border-color:rgba(99,102,241,0.5);color:#a5b4fc;"
            ${safe_to_delete_count === 0 ? 'disabled' : ''}>
            Dry Run
        </button>
        <button type="button" id="dup-delete-btn" onclick="runDuplicateDelete(false)"
            class="btn btn-primary"
            style="padding:0.5rem 1.35rem;background:linear-gradient(135deg,#ef4444,#dc2626);border:none;"
            ${safe_to_delete_count === 0 ? 'disabled' : ''}>
            Delete Selected
        </button>`;
}

function _renderDupDoneState(result) {
    const body = document.getElementById("dup-cleanup-body");
    const footer = document.getElementById("dup-cleanup-footer");
    if (!body || !footer) return;

    const isDryRun = result.dry_run;
    const color = isDryRun ? "#a5b4fc" : (result.deleted_count > 0 ? "#4ade80" : "#94a3b8");

    let html = `
        <div style="text-align:center;padding:1.25rem 0.5rem 0.75rem;">
            <h4 style="color:${color};margin:0 0 0.3rem;font-size:1rem;">
                ${isDryRun ? 'Dry Run Complete' : 'Cleanup Complete'}
            </h4>
            <p style="color:var(--text-secondary);font-size:0.85rem;margin:0;">${escapeHtml(result.message)}</p>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin:1rem 0;">
            <div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.25);border-radius:8px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.5rem;font-weight:700;color:#fca5a5;">${result.deleted_count}</div>
                <div style="font-size:0.75rem;color:var(--text-secondary);">${isDryRun ? 'Would Delete' : 'Deleted'}</div>
            </div>
            <div style="background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.25);border-radius:8px;padding:0.75rem;text-align:center;">
                <div style="font-size:1.5rem;font-weight:700;color:#fcd34d;">${result.skipped_count}</div>
                <div style="font-size:0.75rem;color:var(--text-secondary);">Skipped</div>
            </div>
        </div>`;

    if (result.skipped_ids.length > 0) {
        html += `<div style="background:rgba(30,41,59,0.6);border-radius:8px;padding:0.75rem;">
            <div style="font-size:0.8rem;font-weight:600;color:var(--text-secondary);margin-bottom:0.5rem;">Skipped Accounts:</div>
            <div style="display:flex;flex-direction:column;gap:0.35rem;">`;
        result.skipped_ids.forEach(id => {
            const reason = result.skipped_reasons[String(id)] || "Unknown reason";
            html += `<div style="font-size:0.78rem;display:flex;gap:0.5rem;">
                <span style="color:#94a3b8;white-space:nowrap;">ID #${id}:</span>
                <span style="color:#fcd34d;">${escapeHtml(reason)}</span>
            </div>`;
        });
        html += `</div></div>`;
    }

    body.innerHTML = html;
    footer.innerHTML = `
        <button type="button" onclick="runDuplicateScan()" class="btn btn-secondary"
            style="padding:0.5rem 1.1rem;">Re-Scan</button>
        <button type="button" onclick="closeDuplicateCleanupModal()" class="btn btn-primary"
            style="padding:0.5rem 1.4rem;">Close</button>`;

    // Refresh main customer list silently
    loadUdhaarDashboard();
}

async function runDuplicateScan() {
    _renderDupScanState("scanning");
    try {
        const res = await fetch("/api/v1/customers/duplicates");
        if (!res.ok) throw new Error(`Scan failed (HTTP ${res.status})`);
        _dupScanResult = await res.json();
        _renderDupScanState("results", _dupScanResult);
    } catch (e) {
        const body = document.getElementById("dup-cleanup-body");
        if (body) body.innerHTML = `<div style="color:#fca5a5;padding:1rem;text-align:center;">
            Scan error: ${escapeHtml(e.message)}</div>`;
        const footer = document.getElementById("dup-cleanup-footer");
        if (footer) footer.innerHTML = `<button type="button" onclick="_renderDupScanState('idle')" class="btn btn-secondary">← Back</button>`;
    }
}

async function runDuplicateDelete(isDryRun) {
    // Collect checked IDs
    const checkboxes = document.querySelectorAll(".dup-delete-checkbox:checked");
    const ids = Array.from(checkboxes).map(cb => parseInt(cb.dataset.id, 10));

    if (!isDryRun && ids.length === 0) {
        alert("No accounts selected for deletion. Check at least one.");
        return;
    }

    if (!isDryRun) {
        const confirmed = confirm(
            `You are about to permanently delete ${ids.length} duplicate account(s).\n` +
            `This action cannot be undone.\n\nProceed?`
        );
        if (!confirmed) return;
    }

    _renderDupScanState("executing");

    try {
        const payload = ids.length > 0 ? { customer_ids: ids, dry_run: isDryRun } : { dry_run: isDryRun };
        const res = await fetch("/api/v1/customers/bulk-delete-duplicates", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Cleanup request failed");
        _renderDupScanState("done", data);
    } catch (e) {
        const body = document.getElementById("dup-cleanup-body");
        if (body) body.innerHTML = `<div style="color:#fca5a5;padding:1rem;text-align:center;">
            Cleanup error: ${escapeHtml(e.message)}</div>`;
        const footer = document.getElementById("dup-cleanup-footer");
        if (footer) footer.innerHTML = `<button type="button" onclick="runDuplicateScan()" class="btn btn-secondary">← Back</button>`;
    }
}

/* ============================================================
   STEP 10: SALES HISTORY & AGGREGATION MODULE
   ============================================================ */

let currentSalesPreset = "30days";



    // Reactive sync listeners
    window.addEventListener('bills-updated', () => {
        const udhaarTab = document.getElementById('tab-udhaar');
        if (udhaarTab && udhaarTab.classList.contains('active')) {
            loadUdhaarDashboard();
        }
    });

    const CustomersModule = {
        init: initUdhaarModule,
        loadUdhaarDashboard,
        selectUdhaarCustomer,
        handleRemoveFamilyMember,
        toggleTxItems,
        openCreateCustomerModal,
        submitCreateCustomer,
        openAddMemberModal,
        submitAddMember,
        handleDeleteCustomer,
        handleCustomerPhoneOTP,
        handleMemberPhoneOTP,
        openSettleModal,
        submitSettleUdhaar,
        openEditLimitModal,
        submitEditLimit,
        openEditProfileModal,
        submitEditProfile,
        closeModal,
        goToLedgerPage,
        // Duplicate cleanup
        openDuplicateCleanupModal,
        closeDuplicateCleanupModal,
        runDuplicateScan,
        runDuplicateDelete,
        // Import customers
        openImportCustomersModal,
        closeImportCustomersModal,
        submitImportCustomers,
        clearSelectedCustFile,
        handleCustFileSelected,
    };

    window.CustomersModule = CustomersModule;
    window.initCustomers = initUdhaarModule;
    window.initUdhaarModule = initUdhaarModule;
    window.loadUdhaarDashboard = loadUdhaarDashboard;
    window.selectUdhaarCustomer = selectUdhaarCustomer;
    window.goToLedgerPage = goToLedgerPage;
    window.handleRemoveFamilyMember = handleRemoveFamilyMember;
    window.toggleTxItems = toggleTxItems;
    window.openCreateCustomerModal = openCreateCustomerModal;
    window.submitCreateCustomer = submitCreateCustomer;
    window.openAddMemberModal = openAddMemberModal;
    window.submitAddMember = submitAddMember;
    window.handleDeleteCustomer = handleDeleteCustomer;
    window.handleCustomerPhoneOTP = handleCustomerPhoneOTP;
    window.handleMemberPhoneOTP = handleMemberPhoneOTP;
    window.openSettleModal = openSettleModal;
    window.submitSettleUdhaar = submitSettleUdhaar;
    window.openEditLimitModal = openEditLimitModal;
    window.submitEditLimit = submitEditLimit;
    window.openEditProfileModal = openEditProfileModal;
    window.submitEditProfile = submitEditProfile;
    window.closeModal = closeModal;
    // Duplicate cleanup
    window.openDuplicateCleanupModal = openDuplicateCleanupModal;
    window.closeDuplicateCleanupModal = closeDuplicateCleanupModal;
    window.runDuplicateScan = runDuplicateScan;
    window.runDuplicateDelete = runDuplicateDelete;
    window._renderDupScanState = _renderDupScanState;
    // Import customers
    window.openImportCustomersModal = openImportCustomersModal;
    window.closeImportCustomersModal = closeImportCustomersModal;
    window.submitImportCustomers = submitImportCustomers;
    window.clearSelectedCustFile = clearSelectedCustFile;
    window.handleCustFileSelected = handleCustFileSelected;

    // ==============================================================================
    // Udhaar & Customer Visualizations (Phase 2)
    // ==============================================================================

    let currentUdhaarHorizon = 30;
    let cachedUdhaarChartsData = null;

    function switchUdhaarHorizon(days) {
        currentUdhaarHorizon = parseInt(days) || 30;
        const btn30 = document.getElementById("btn-udhaar-horizon-30d");
        const btn90 = document.getElementById("btn-udhaar-horizon-90d");

        if (btn30) btn30.classList.toggle("active", currentUdhaarHorizon === 30);
        if (btn90) btn90.classList.toggle("active", currentUdhaarHorizon === 90);

        loadUdhaarCharts(currentUdhaarHorizon);
    }

    async function loadUdhaarCharts(days = currentUdhaarHorizon) {
        if (!window.ApnaCharts) return;

        try {
            const res = await fetch(`/api/v1/customers/charts?days=${days}`);
            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || `Server returned ${res.status}`);
            }
            const data = await res.json();
            cachedUdhaarChartsData = data;

            // Summary Badges
            const collectedBadge = document.getElementById("udhaar-chart-collected-badge");
            if (collectedBadge) {
                collectedBadge.textContent = `${window.ApnaCharts.formatRupees(data.period_collections || 0)} collected`;
            }

            // Chart 11: Highest Outstanding Balances
            renderHighestOutstandingChart(data);

            // Chart 12: Credit vs Collections
            renderCreditVsCollectionsChart(data);

        } catch (err) {
            console.error("Failed to load Udhaar charts:", err);
            const wrap = document.getElementById("udhaar-outstanding-wrap");
            if (wrap) window.ApnaCharts.showEmptyState(wrap, "Udhaar Visualizations Unavailable", err.message);
        }
    }

    function renderHighestOutstandingChart(data) {
        const wrap = document.getElementById("udhaar-outstanding-wrap");
        const items = data.highest_outstanding || [];

        if (items.length === 0) {
            window.ApnaCharts.showEmptyState(wrap, "Zero Outstanding Udhaar", "No customer accounts have positive outstanding balances.");
            return;
        }

        const labels = items.map(c => c.name.length > 18 ? c.name.slice(0, 16) + "…" : c.name);
        const balances = items.map(c => c.balance);

        const chart = window.ApnaCharts.createChart("udhaar-outstanding-canvas", {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: "Outstanding Balance",
                    data: balances,
                    backgroundColor: "#ef4444",
                    borderRadius: 4,
                    maxBarThickness: 22
                }]
            },
            options: {
                ...window.ApnaCharts.getBaseOptions(),
                indexAxis: "y",
                onClick: (event, elements) => {
                    if (elements && elements.length > 0) {
                        const idx = elements[0].index;
                        const targetCust = items[idx];
                        if (targetCust && typeof selectUdhaarCustomer === "function") {
                            selectUdhaarCustomer(targetCust.id);
                        }
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        grid: { color: "rgba(255, 255, 255, 0.05)" },
                        ticks: {
                            color: "#94a3b8",
                            font: { size: 10 },
                            callback: val => window.ApnaCharts.formatCompactRupees(val)
                        }
                    },
                    y: {
                        grid: { display: false },
                        ticks: { color: "#f8fafc", font: { size: 11 } }
                    }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: ctx => {
                                const it = items[ctx.dataIndex];
                                return [
                                    `Debt: ${window.ApnaCharts.formatRupees(it.balance)}`,
                                    `Credit Limit: ${window.ApnaCharts.formatRupees(it.credit_limit)}`,
                                    `Phone: ${it.phone_masked} (Click to open ledger)`
                                ];
                            }
                        }
                    }
                }
            }
        });
    }

    function renderCreditVsCollectionsChart(data) {
        const wrap = document.getElementById("udhaar-collections-wrap");
        const list = data.credit_vs_collections || [];

        if (list.length === 0) {
            window.ApnaCharts.showEmptyState(wrap, "No Ledger Activity", "No credit purchases or settlements recorded in period.");
            return;
        }

        const labels = list.map(d => d.label);
        const creditData = list.map(d => d.credit_added);
        const collData = list.map(d => d.collections);

        window.ApnaCharts.createChart("udhaar-collections-canvas", {
            type: "bar",
            data: {
                labels: labels,
                datasets: [
                    {
                        label: "Credit Added (Udhaar Purchases)",
                        data: creditData,
                        backgroundColor: "#f59e0b",
                        borderRadius: 3,
                        maxBarThickness: 16
                    },
                    {
                        label: "Collections (Debt Payments)",
                        data: collData,
                        backgroundColor: "#22c55e",
                        borderRadius: 3,
                        maxBarThickness: 16
                    }
                ]
            },
            options: {
                ...window.ApnaCharts.getBaseOptions(),
                scales: {
                    x: {
                        grid: { color: "rgba(255, 255, 255, 0.05)" },
                        ticks: { color: "#94a3b8", font: { size: 10 } }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: "rgba(255, 255, 255, 0.05)" },
                        ticks: {
                            color: "#94a3b8",
                            font: { size: 10 },
                            callback: val => window.ApnaCharts.formatCompactRupees(val)
                        }
                    }
                },
                plugins: {
                    legend: {
                        position: "top",
                        labels: { color: "#94a3b8", font: { size: 10 }, boxWidth: 10, padding: 6 }
                    },
                    tooltip: {
                        callbacks: {
                            label: ctx => {
                                const mode = ctx.datasetIndex === 0 ? "Credit Added" : "Collections Received";
                                return `${mode}: ${window.ApnaCharts.formatRupees(ctx.raw)}`;
                            }
                        }
                    }
                }
            }
        });
    }

    window.switchUdhaarHorizon = switchUdhaarHorizon;
    window.loadUdhaarCharts = loadUdhaarCharts;

})(window);
