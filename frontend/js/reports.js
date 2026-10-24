/**
 * Apna Kirana OS — Export & Reports Center Module
 * Manages UI interactions, date range presets, report-specific filters,
 * authenticated binary stream downloads (CSV / PDF), and generation feedback.
 */

(function(window) {
    'use strict';

    let allCustomersCache = [];

    // ==============================================================================
    // 1. MODULE INITIALIZATION & DATE PRESETS
    // ==============================================================================

    function initReportsModule() {
        // Set default date range to "This Month"
        setReportDatePreset("month");

        // Populate customer dropdown for Report 7
        loadCustomersForReportDropdown();

        // Populate store profile badge
        updateShopBadgeInReports();

        // Wire live search input
        const searchInput = document.getElementById("reports-search-input");
        if (searchInput) {
            searchInput.addEventListener("input", () => {
                const query = searchInput.value.trim().toLowerCase();
                filterReportsBySearch(query);
            });
        }

        // Wire custom date change listeners
        const startDateInput = document.getElementById("reports-start-date");
        const endDateInput = document.getElementById("reports-end-date");

        if (startDateInput && endDateInput) {
            const onCustomDateChange = () => {
                // Clear preset active states when user touches custom date pickers
                document.querySelectorAll(".reports-pill-btn").forEach(btn => btn.classList.remove("active"));
                const customBtn = document.querySelector(".reports-pill-btn[data-preset='custom']");
                if (customBtn) customBtn.classList.add("active");
            };
            startDateInput.addEventListener("change", onCustomDateChange);
            endDateInput.addEventListener("change", onCustomDateChange);
        }
    }

    function updateShopBadgeInReports() {
        const badge = document.getElementById("reports-shop-name-badge");
        if (!badge) return;

        try {
            const userStr = localStorage.getItem("shopkeeper_user") || localStorage.getItem("pos_auth_user");
            if (userStr) {
                const u = JSON.parse(userStr);
                const shopName = (u.shop_profile && u.shop_profile.shop_name) || u.shop_name || "Apna Kirana Store";
                badge.textContent = shopName;
            }
        } catch (_) {}
    }

    function setReportDatePreset(preset) {
        const startDateInput = document.getElementById("reports-start-date");
        const endDateInput = document.getElementById("reports-end-date");
        if (!startDateInput || !endDateInput) return;

        const now = new Date();
        const formatDate = (d) => {
            const y = d.getFullYear();
            const m = String(d.getMonth() + 1).padStart(2, "0");
            const day = String(d.getDate()).padStart(2, "0");
            return `${y}-${m}-${day}`;
        };

        const todayStr = formatDate(now);
        let startStr = todayStr;
        let endStr = todayStr;

        if (preset === "today") {
            startStr = todayStr;
            endStr = todayStr;
        } else if (preset === "week") {
            const weekAgo = new Date(now.getTime() - (6 * 24 * 60 * 60 * 1000));
            startStr = formatDate(weekAgo);
            endStr = todayStr;
        } else if (preset === "month") {
            const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
            startStr = formatDate(firstDay);
            endStr = todayStr;
        } else if (preset === "all") {
            // Default 365 days window for "all" records
            const yearAgo = new Date(now.getTime() - (365 * 24 * 60 * 60 * 1000));
            startStr = formatDate(yearAgo);
            endStr = todayStr;
        }

        startDateInput.value = startStr;
        endDateInput.value = endStr;

        // Update active pill UI
        document.querySelectorAll(".reports-pill-btn").forEach(btn => {
            if (btn.getAttribute("data-preset") === preset) {
                btn.classList.add("active");
            } else {
                btn.classList.remove("active");
            }
        });
    }

    function filterReportCategory(category, clickedBtn) {
        document.querySelectorAll(".reports-cat-btn").forEach(b => b.classList.remove("active"));
        if (clickedBtn) clickedBtn.classList.add("active");

        const cards = document.querySelectorAll(".report-card");
        cards.forEach(card => {
            const cardCat = (card.getAttribute("data-category") || "").toLowerCase();
            if (category === "all" || cardCat.includes(category.toLowerCase())) {
                card.style.display = "flex";
            } else {
                card.style.display = "none";
            }
        });
    }

    function filterReportsBySearch(query) {
        const cards = document.querySelectorAll(".report-card");
        cards.forEach(card => {
            const text = card.textContent.toLowerCase();
            if (!query || text.includes(query)) {
                card.style.display = "flex";
            } else {
                card.style.display = "none";
            }
        });
    }

    // ==============================================================================
    // 2. DROPDOWN POPULATORS
    // ==============================================================================

    async function loadCustomersForReportDropdown() {
        const select = document.getElementById("filter-report-customer-id");
        if (!select) return;

        try {
            const res = await fetch("/api/v1/customers?active_only=true");
            if (res.ok) {
                const list = await res.json();
                allCustomersCache = Array.isArray(list) ? list : (list.customers || []);

                let optionsHtml = '<option value="">-- Select Customer Account --</option>';
                allCustomersCache.forEach(c => {
                    const code = c.customer_code || `C-${String(c.id).padStart(6, '0')}`;
                    const bal = Number(c.current_udhaar_balance || 0).toFixed(2);
                    optionsHtml += `<option value="${c.id}">${code} • ${c.full_name} (₹${bal})</option>`;
                });
                select.innerHTML = optionsHtml;
            }
        } catch (e) {
            console.warn("[Reports] Failed to preload customer list:", e);
        }
    }

    // ==============================================================================
    // 3. SECURE END-TO-END DOWNLOAD CONTROLLER
    // ==============================================================================

    async function downloadReport(reportKey, format) {
        const card = document.getElementById(`report-card-${reportKey}`);
        const statusBox = document.getElementById(`status-${reportKey}`);
        const csvBtn = card ? card.querySelector(".btn-report-csv") : null;
        const pdfBtn = card ? card.querySelector(".btn-report-pdf") : null;

        // Reset status box
        if (statusBox) {
            statusBox.className = "report-card-status status-loading";
            statusBox.style.display = "flex";
            statusBox.innerHTML = `
                <span class="spinner" style="display:inline-block;width:12px;height:12px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;"></span>
                <span>Generating ${format.toUpperCase()} report...</span>
            `;
        }

        if (csvBtn) csvBtn.disabled = true;
        if (pdfBtn) pdfBtn.disabled = true;

        try {
            // Build query params
            const startDateInput = document.getElementById("reports-start-date");
            const endDateInput = document.getElementById("reports-end-date");
            const startDate = startDateInput ? startDateInput.value : "";
            const endDate = endDateInput ? endDateInput.value : "";

            if (startDate && endDate && startDate > endDate) {
                throw new Error("Start date cannot be after end date. Please check the period.");
            }

            let endpoint = `/api/v1/exports/${reportKey}?format=${encodeURIComponent(format)}`;

            // Report-specific parameters
            if (reportKey === "sales-summary" || reportKey === "sales-history" || reportKey === "supplier-purchases") {
                if (startDate) endpoint += `&start_date=${encodeURIComponent(startDate)}`;
                if (endDate) endpoint += `&end_date=${encodeURIComponent(endDate)}`;

                if (reportKey === "sales-history") {
                    const modeSelect = document.getElementById("filter-history-payment-mode");
                    if (modeSelect && modeSelect.value) {
                        endpoint += `&payment_mode=${encodeURIComponent(modeSelect.value)}`;
                    }
                }
            } else if (reportKey === "invoice") {
                const billInput = document.getElementById("filter-invoice-bill-number");
                const billVal = billInput ? billInput.value.trim() : "";
                if (!billVal) {
                    throw new Error("Please enter an Invoice / Bill Number to download.");
                }
                endpoint += `&bill_number=${encodeURIComponent(billVal)}`;
            } else if (reportKey === "inventory" || reportKey === "low-stock" || reportKey === "inventory-valuation") {
                const catSelect = document.getElementById(`filter-${reportKey}-category`);
                if (catSelect && catSelect.value && catSelect.value !== "ALL") {
                    endpoint += `&category=${encodeURIComponent(catSelect.value)}`;
                }
                if (reportKey === "inventory") {
                    const statusSelect = document.getElementById("filter-inventory-status");
                    if (statusSelect && statusSelect.value) {
                        endpoint += `&status=${encodeURIComponent(statusSelect.value)}`;
                    }
                }
            } else if (reportKey === "customer-ledger") {
                const custSelect = document.getElementById("filter-report-customer-id");
                const custId = custSelect ? custSelect.value : "";
                if (!custId) {
                    throw new Error("Please select a customer account to export their ledger statement.");
                }
                endpoint += `&customer_id=${encodeURIComponent(custId)}`;
                if (startDate) endpoint += `&start_date=${encodeURIComponent(startDate)}`;
                if (endDate) endpoint += `&end_date=${encodeURIComponent(endDate)}`;
            } else if (reportKey === "outstanding-udhaar") {
                const minBalInput = document.getElementById("filter-outstanding-min-balance");
                if (minBalInput && minBalInput.value) {
                    endpoint += `&min_balance=${encodeURIComponent(minBalInput.value)}`;
                }
            } else if (reportKey === "demand-forecast") {
                const horizonSelect = document.getElementById("filter-forecast-horizon");
                const riskSelect = document.getElementById("filter-forecast-risk");
                if (horizonSelect && horizonSelect.value) {
                    endpoint += `&horizon=${encodeURIComponent(horizonSelect.value)}`;
                }
                if (riskSelect && riskSelect.value && riskSelect.value !== "ALL") {
                    endpoint += `&risk_level=${encodeURIComponent(riskSelect.value)}`;
                }
            }

            // Execute secure authenticated request
            const res = await fetch(endpoint, {
                method: "GET"
            });

            if (!res.ok) {
                let errorMsg = `Server error (${res.status})`;
                try {
                    const errData = await res.json();
                    if (errData && errData.detail) errorMsg = errData.detail;
                } catch (_) {}
                throw new Error(errorMsg);
            }

            // Extract filename from Content-Disposition header
            let filename = `${reportKey}_${format === 'pdf' ? 'report.pdf' : 'report.csv'}`;
            const disposition = res.headers.get("content-disposition");
            if (disposition && disposition.indexOf("filename=") !== -1) {
                const filenameMatch = disposition.match(/filename=["']?([^"';]+)["']?/);
                if (filenameMatch && filenameMatch[1]) {
                    filename = filenameMatch[1];
                }
            }

            // Convert to blob and trigger real browser download
            const blob = await res.blob();
            const blobUrl = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.style.display = "none";
            a.href = blobUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(blobUrl);
            document.body.removeChild(a);

            // Update UI status to Success
            if (statusBox) {
                statusBox.className = "report-card-status status-success";
                statusBox.innerHTML = `✓ Downloaded ${filename}`;
                setTimeout(() => {
                    statusBox.style.display = "none";
                }, 4000);
            }

            if (window.showToast) {
                window.showToast(`Report downloaded: ${filename}`, "success");
            }

        } catch (err) {
            console.error(`[Reports] Error downloading ${reportKey}:`, err);
            if (statusBox) {
                statusBox.className = "report-card-status status-error";
                statusBox.innerHTML = `✕ ${err.message || 'Generation failed'}`;
            }
            if (window.showToast) {
                window.showToast(err.message || "Failed to generate report", "error");
            }
        } finally {
            if (csvBtn) csvBtn.disabled = false;
            if (pdfBtn) pdfBtn.disabled = false;
        }
    }

    // Export module functions onto window object
    window.initReports = initReportsModule;
    window.initReportsModule = initReportsModule;
    window.downloadReport = downloadReport;
    window.setReportDatePreset = setReportDatePreset;
    window.filterReportCategory = filterReportCategory;
    window.filterReportsBySearch = filterReportsBySearch;
    window.loadCustomersForReportDropdown = loadCustomersForReportDropdown;

})(window);
