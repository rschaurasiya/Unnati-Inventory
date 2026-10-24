/**
 * Sales History, Analytics & Historical Import Module
 * Manages completed sales ledger, date-range presets, sales metrics,
 * daily summaries, and CSV/Excel batch historical sales import workflow.
 */

(function(window) {
    'use strict';

function switchSalesView(viewName, updateHistory = true) {
    const importViewBtn = document.getElementById("btn-show-import-view");
    const historyViewBtn = document.getElementById("btn-show-history-view");
    const importSection = document.getElementById("section-sales-import");
    const historySection = document.getElementById("section-sales-history");

    if (viewName === "import") {
        if (importViewBtn) importViewBtn.classList.add("active");
        if (historyViewBtn) historyViewBtn.classList.remove("active");
        if (importSection) importSection.style.display = "block";
        if (historySection) historySection.style.display = "none";
        loadImportBatchesList();
        if (updateHistory && window.history && window.history.pushState) {
            if (window.location.pathname !== "/sales/import") {
                window.history.pushState({ path: "/sales/import" }, "", "/sales/import");
            }
        }
    } else {
        if (historyViewBtn) historyViewBtn.classList.add("active");
        if (importViewBtn) importViewBtn.classList.remove("active");
        if (historySection) historySection.style.display = "block";
        if (importSection) importSection.style.display = "none";
        loadSalesHistoryDashboard();
        if (updateHistory && window.history && window.history.pushState) {
            if (window.location.pathname !== "/sales/history") {
                window.history.pushState({ path: "/sales/history" }, "", "/sales/history");
            }
        }
    }
}

function filterSalesToToday() {
    switchSalesView("history");
    const presetButtons = document.querySelectorAll(".preset-btn");
    presetButtons.forEach(b => b.classList.remove("active"));
    const todayBtn = document.querySelector('.preset-btn[data-preset="today"]');
    if (todayBtn) todayBtn.classList.add("active");
    currentSalesPreset = "today";
    applySalesPreset("today");
    loadSalesHistoryDashboard();
}

function initSalesHistoryModule() {
    // Primary Action Switching (Import Sales Data vs Sales History)
    const importViewBtn = document.getElementById("btn-show-import-view");
    const historyViewBtn = document.getElementById("btn-show-history-view");

    if (importViewBtn) {
        importViewBtn.addEventListener("click", () => switchSalesView("import"));
    }
    if (historyViewBtn) {
        historyViewBtn.addEventListener("click", () => switchSalesView("history"));
    }

    const viewHistoryAfterImportBtn = document.getElementById("btn-view-imported-history");
    if (viewHistoryAfterImportBtn) {
        viewHistoryAfterImportBtn.addEventListener("click", () => switchSalesView("history"));
    }

    // Preset buttons
    const presetButtons = document.querySelectorAll(".preset-btn");
    presetButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            presetButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentSalesPreset = btn.dataset.preset;
            applySalesPreset(currentSalesPreset);
            loadSalesHistoryDashboard();
        });
    });

    initHistoricalImportModule();

    // Expand / Collapse Filter Toggle
    function toggleSalesFilters() {
        const filterCard = document.getElementById("sales-filter-card");
        const filterBody = document.getElementById("salesFilterBody") || document.getElementById("sales-detailed-filters");
        const toggleBtn = document.getElementById("toggleSalesFiltersBtn") || document.getElementById("btn-toggle-sales-filters");
        const filterCaret = document.getElementById("sales-filter-caret");

        if (!filterCard && !filterBody) return;

        const isCurrentlyCollapsed = filterCard ? filterCard.classList.contains("filters-collapsed") : (filterBody.style.display === "none");
        const willBeCollapsed = !isCurrentlyCollapsed;

        if (filterCard) {
            if (willBeCollapsed) {
                filterCard.classList.add("filters-collapsed");
            } else {
                filterCard.classList.remove("filters-collapsed");
            }
        }
        if (filterBody) {
            filterBody.style.display = willBeCollapsed ? "none" : "flex";
        }

        if (toggleBtn) {
            const label = toggleBtn.querySelector(".toggle-label");
            if (willBeCollapsed) {
                toggleBtn.classList.add("is-collapsed");
                toggleBtn.setAttribute("aria-expanded", "false");
                toggleBtn.title = "Show Filters";
                toggleBtn.setAttribute("aria-label", "Show Filters");
                if (label) label.textContent = "Show Filters";
                if (filterCaret) filterCaret.textContent = "⌄";
            } else {
                toggleBtn.classList.remove("is-collapsed");
                toggleBtn.setAttribute("aria-expanded", "true");
                toggleBtn.title = "Hide Filters";
                toggleBtn.setAttribute("aria-label", "Hide Filters");
                if (label) label.textContent = "Hide Filters";
                if (filterCaret) filterCaret.textContent = "‸";
            }
        }
    }

    const toggleFiltersBtn = document.getElementById("toggleSalesFiltersBtn") || document.getElementById("btn-toggle-sales-filters");
    if (toggleFiltersBtn && !toggleFiltersBtn.dataset.toggleInit) {
        toggleFiltersBtn.dataset.toggleInit = "true";
        toggleFiltersBtn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            toggleSalesFilters();
        });
    }

    if (!window._salesFilterToggleDelegated) {
        window._salesFilterToggleDelegated = true;
        document.addEventListener("click", (e) => {
            const btn = e.target.closest("#toggleSalesFiltersBtn, #btn-toggle-sales-filters");
            if (btn && !btn.dataset.toggleInit) {
                e.preventDefault();
                e.stopPropagation();
                toggleSalesFilters();
            }
        });
    }

    // Apply Filter Button
    const applyFilterBtn = document.getElementById("btn-apply-sales-filter");
    if (applyFilterBtn) {
        applyFilterBtn.addEventListener("click", () => {
            presetButtons.forEach(b => b.classList.remove("active"));
            currentSalesPage = 1;
            loadSalesHistoryDashboard();
        });
    }

    // Pagination Controls
    const pageSizeSelect = document.getElementById("sales-page-size-select");
    if (pageSizeSelect) {
        pageSizeSelect.addEventListener("change", (e) => {
            salesPageSize = parseInt(e.target.value) || 10;
            currentSalesPage = 1;
            renderSalesHistoryPage();
        });
    }

    const prevBtn = document.getElementById("btn-sales-prev");
    if (prevBtn) {
        prevBtn.addEventListener("click", () => {
            if (currentSalesPage > 1) {
                currentSalesPage--;
                renderSalesHistoryPage();
            }
        });
    }

    const nextBtn = document.getElementById("btn-sales-next");
    if (nextBtn) {
        nextBtn.addEventListener("click", () => {
            const totalPages = Math.ceil(allSalesItems.length / salesPageSize) || 1;
            if (currentSalesPage < totalPages) {
                currentSalesPage++;
                renderSalesHistoryPage();
            }
        });
    }

    // Rebuild Summaries Button
    const rebuildBtn = document.getElementById("btn-rebuild-history");
    if (rebuildBtn) {
        rebuildBtn.addEventListener("click", async () => {
            try {
                rebuildBtn.disabled = true;
                rebuildBtn.textContent = "Reconciling...";
                const res = await fetch("/api/v1/analytics/rebuild", { method: "POST" });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || "Failed to rebuild summaries");
                alert(data.message || "Daily sales summaries reconciled successfully!");
                await loadSalesHistoryDashboard();
            } catch (err) {
                alert(`Error reconciling summaries: ${err.message}`);
            } finally {
                rebuildBtn.disabled = false;
                rebuildBtn.textContent = "Reconcile Summaries";
            }
        });
    }

    // Seed Demo History Button
    const seedBtn = document.getElementById("btn-seed-demo-history");
    if (seedBtn) {
        seedBtn.addEventListener("click", async () => {
            const confirmSeed = confirm(
                "Generate ~60 days of realistic historical completed sales for demand analytics?\n\n" +
                "Note: Current store product inventory stock will NOT be changed."
            );
            if (!confirmSeed) return;

            try {
                seedBtn.disabled = true;
                seedBtn.textContent = "Seeding 60 Days...";
                const res = await fetch("/api/v1/analytics/seed-demo", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ days: 60, seed: 42 })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || "Failed to seed demo data");
                alert(
                    `Successfully seeded historical sales foundation!\n` +
                    `• Days covered: ${data.days_seeded}\n` +
                    `• Completed bills: ${data.bills_created}\n` +
                    `• Line items: ${data.items_created}\n` +
                    `• Inventory stock unaltered: ${data.inventory_unaltered}`
                );
                await loadSalesHistoryDashboard();
            } catch (err) {
                alert(`Error seeding demo sales history: ${err.message}`);
            } finally {
                seedBtn.disabled = false;
                seedBtn.textContent = "Seed 60-Day Demo History";
            }
        });
    }

    // Initialize default date range & filters
    applySalesPreset("30days");
    populateSalesFilters();
}

function applySalesPreset(preset) {
    const startInput = document.getElementById("sales-filter-start");
    const endInput = document.getElementById("sales-filter-end");
    if (!startInput || !endInput) return;

    const today = new Date();
    const formatDate = d => d.toISOString().split("T")[0];

    endInput.value = formatDate(today);

    if (preset === "today") {
        startInput.value = formatDate(today);
    } else if (preset === "7days") {
        const d = new Date(today);
        d.setDate(d.getDate() - 6);
        startInput.value = formatDate(d);
    } else if (preset === "30days") {
        const d = new Date(today);
        d.setDate(d.getDate() - 29);
        startInput.value = formatDate(d);
    } else if (preset === "60days") {
        const d = new Date(today);
        d.setDate(d.getDate() - 59);
        startInput.value = formatDate(d);
    } else if (preset === "all") {
        startInput.value = "2026-01-01";
    }
}

async function populateSalesFilters() {
    const prodSelect = document.getElementById("sales-filter-product");
    const catSelect = document.getElementById("sales-filter-category");

    try {
        const res = await fetch("/api/v1/products");
        if (!res.ok) return;
        const products = await res.json();

        if (prodSelect && prodSelect.options.length <= 1) {
            products.forEach(p => {
                const opt = document.createElement("option");
                opt.value = p.id;
                opt.textContent = `${p.name} (${p.category || 'General'})`;
                prodSelect.appendChild(opt);
            });
        }

        if (catSelect && catSelect.options.length <= 1) {
            const categories = [...new Set(products.map(p => p.category).filter(Boolean))].sort();
            categories.forEach(cat => {
                const opt = document.createElement("option");
                opt.value = cat;
                opt.textContent = cat;
                catSelect.appendChild(opt);
            });
        }
    } catch (e) {
        console.error("Failed to load products/categories for sales filters:", e);
    }
}

async function loadSalesHistoryDashboard() {
    const startInput = document.getElementById("sales-filter-start");
    const endInput = document.getElementById("sales-filter-end");
    const productSelect = document.getElementById("sales-filter-product");
    const categorySelect = document.getElementById("sales-filter-category");
    const paymentSelect = document.getElementById("sales-filter-payment");

    let startDate = startInput ? startInput.value : "";
    let endDate = endInput ? endInput.value : "";
    const productId = productSelect && productSelect.value ? productSelect.value : "";
    const category = categorySelect && categorySelect.value ? categorySelect.value : "";
    const paymentMode = paymentSelect && paymentSelect.value ? paymentSelect.value : "";

    // If dates are not set yet, apply the default 30-day preset
    if (!startDate || !endDate) {
        applySalesPreset("30days");
        if (startInput && startInput.value) startDate = startInput.value;
        if (endInput && endInput.value) endDate = endInput.value;
    }

    const tbody = document.getElementById("sales-history-tbody") || document.getElementById("sales-ledger-tbody");

    // 1. Load Sales Range Aggregation (updates the 4 top summary cards)
    if (startDate && endDate) {
        try {
            let rangeUrl = `/api/v1/analytics/sales/range?start_date=${startDate}&end_date=${endDate}`;
            if (productId) rangeUrl += `&product_id=${productId}`;

            const rangeRes = await fetch(rangeUrl);
            if (rangeRes.ok) {
                const rangeData = await rangeRes.json();
                updateMetricsUI(rangeData);
            }
        } catch (err) {
            console.error("Error loading sales range:", err);
        }

        // 2. Load Sales History Analytics Charts (Phase 1)
        loadSalesHistoryCharts(startDate, endDate, productId, category, paymentMode);

        // 3. Load Completed Sales History Items
        try {
            if (tbody && !tbody.querySelector("tr:not(.loading-row)")) {
                tbody.innerHTML = `<tr class="loading-row"><td colspan="7" class="text-center text-muted" style="padding: 20px;">Loading completed sales records...</td></tr>`;
            }

            let itemsUrl = `/api/v1/analytics/sales/items?start_date=${startDate}&end_date=${endDate}&limit=500`;
            if (productId) itemsUrl += `&product_id=${productId}`;
            if (category) itemsUrl += `&category=${encodeURIComponent(category)}`;
            if (paymentMode) itemsUrl += `&payment_mode=${encodeURIComponent(paymentMode)}`;

            const itemsRes = await fetch(itemsUrl);
            if (itemsRes.ok) {
                const itemsData = await itemsRes.json();
                renderSalesHistoryTable(itemsData || []);
            } else {
                if (tbody) {
                    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger" style="padding: 20px;">Failed to load sales records (Server HTTP ${itemsRes.status}).</td></tr>`;
                }
            }
        } catch (err) {
            console.error("Error loading sales items:", err);
            if (tbody) {
                tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger" style="padding: 20px;">Network error: Could not reach sales history service (${err.message || 'Connection failed'}).</td></tr>`;
            }
        }
    }
}

function updateSufficiencyUI(data) {
    const banner = document.getElementById("sales-sufficiency-banner");
    const badge = document.getElementById("sufficiency-badge");
    const daysEl = document.getElementById("sufficiency-days-count");
    const msgEl = document.getElementById("sufficiency-message-text");

    if (daysEl) daysEl.textContent = `${data.usable_days_count} / ${data.min_days_required} days`;
    if (msgEl) msgEl.textContent = data.message;

    if (banner && badge) {
        if (data.status === "SUFFICIENT_DATA") {
            banner.classList.remove("insufficient");
            banner.classList.add("sufficient");
            badge.className = "badge-status badge-success";
            badge.textContent = `SUFFICIENT DATA (${data.usable_days_count} Days)`;
        } else {
            banner.classList.remove("sufficient");
            banner.classList.add("insufficient");
            badge.className = "badge-status badge-warning";
            badge.textContent = `INSUFFICIENT DATA (${data.usable_days_count}/7 Days Required)`;
        }
    }
}

function updateMetricsUI(data) {
    const revEl = document.getElementById("metric-sales-revenue");
    const volEl = document.getElementById("metric-sales-volume");
    const txEl = document.getElementById("metric-sales-transactions");
    const prodEl = document.getElementById("metric-active-products");

    if (revEl) revEl.textContent = `₹${data.total_revenue.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (volEl) volEl.textContent = data.total_quantity_sold.toLocaleString('en-IN');
    if (txEl) txEl.textContent = data.total_transactions.toLocaleString('en-IN');
    if (prodEl) prodEl.textContent = data.distinct_products_count.toLocaleString('en-IN');
}

function renderDailySalesTable(dailySummaries) {
    const tbody = document.getElementById("daily-sales-tbody");
    if (!tbody) return;

    if (!dailySummaries || dailySummaries.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No completed sales recorded in selected date range.</td></tr>`;
        return;
    }

    let rowsHtml = "";
    const reversed = [...dailySummaries].reverse();

    reversed.forEach(day => {
        if (!day.items || day.items.length === 0) return;
        day.items.forEach(item => {
            rowsHtml += `
                <tr>
                    <td><strong>${day.sale_date}</strong></td>
                    <td>${escapeHtml(item.product_name)}</td>
                    <td><span class="badge-status badge-secondary">${escapeHtml(item.category || 'General')}</span></td>
                    <td>${item.total_quantity_sold}</td>
                    <td>${escapeHtml(item.unit)}</td>
                    <td><strong>₹${item.total_sales_amount.toFixed(2)}</strong></td>
                    <td>${item.transaction_count}</td>
                </tr>
            `;
        });
    });

    tbody.innerHTML = rowsHtml || `<tr><td colspan="7" class="text-center text-muted">No product items found.</td></tr>`;
}

let allSalesItems = [];
let currentSalesPage = 1;
let salesPageSize = 10;

function renderSalesHistoryTable(items) {
    allSalesItems = items || [];
    currentSalesPage = 1;
    renderSalesHistoryPage();
}

function renderSalesHistoryPage() {
    const tbody = document.getElementById("sales-history-tbody") || document.getElementById("sales-ledger-tbody");
    const paginationInfo = document.getElementById("sales-pagination-info");
    const pageIndicator = document.getElementById("sales-page-indicator");
    const prevBtn = document.getElementById("btn-sales-prev");
    const nextBtn = document.getElementById("btn-sales-next");
    if (!tbody) return;

    const total = allSalesItems.length;

    if (total === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted" style="padding: 20px;">No completed sales records found for selected filters.</td></tr>`;
        if (paginationInfo) paginationInfo.textContent = "Showing 0–0 of 0 items";
        if (pageIndicator) pageIndicator.textContent = "Page 1 of 1";
        if (prevBtn) prevBtn.disabled = true;
        if (nextBtn) nextBtn.disabled = true;
        return;
    }

    const totalPages = Math.ceil(total / salesPageSize) || 1;
    if (currentSalesPage > totalPages) currentSalesPage = totalPages;
    if (currentSalesPage < 1) currentSalesPage = 1;

    const startIdx = (currentSalesPage - 1) * salesPageSize;
    const endIdx = Math.min(startIdx + salesPageSize, total);
    const pageItems = allSalesItems.slice(startIdx, endIdx);

    tbody.innerHTML = pageItems.map(it => {
        const dt = new Date(it.created_at);
        const dateStr = dt.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
        const timeStr = dt.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });

        let payBadge = `<span class="badge badge-secondary">${escapeHtml(it.payment_mode || 'Cash')}</span>`;
        if (it.payment_mode === "CASH") payBadge = `<span class="badge badge-success">Cash</span>`;
        else if (it.payment_mode === "UPI") payBadge = `<span class="badge badge-info" style="background:#0284c7;color:#fff;">UPI</span>`;
        else if (it.payment_mode === "UDHAAR") payBadge = `<span class="badge badge-warning">Udhaar</span>`;
        else if (it.payment_mode === "IMPORTED") payBadge = `<span class="badge badge-info" style="background:#6366f1;color:#fff;">Imported</span>`;

        return `
            <tr>
                <td><strong>${dateStr}</strong> <span class="text-muted" style="font-size:0.8rem;">${timeStr}</span></td>
                <td><strong>${escapeHtml(it.product_name)}</strong> ${it.category ? `<br><small class="text-muted">${escapeHtml(it.category)}</small>` : ''}</td>
                <td><strong>${it.quantity}</strong> ${escapeHtml(it.unit || '')}</td>
                <td>₹${it.unit_price.toFixed(2)}</td>
                <td><strong>₹${it.line_total.toFixed(2)}</strong></td>
                <td>${payBadge}</td>
                <td><span class="badge badge-success" style="background:rgba(34,197,94,0.15);color:#22c55e;border:1px solid rgba(34,197,94,0.3);">Completed</span></td>
            </tr>
        `;
    }).join("");

    if (paginationInfo) paginationInfo.textContent = `Showing ${startIdx + 1}–${endIdx} of ${total} items`;
    if (pageIndicator) pageIndicator.textContent = `Page ${currentSalesPage} of ${totalPages}`;
    if (prevBtn) prevBtn.disabled = (currentSalesPage <= 1);
    if (nextBtn) nextBtn.disabled = (currentSalesPage >= totalPages);
}

// ============================================================
// Historical Sales Data Import & Normalization Controller
// ============================================================

let currentStagedImport = null;

function initHistoricalImportModule() {
    const dropzone = document.getElementById("import-dropzone");
    const fileInput = document.getElementById("import-file-input");
    const browseBtn = document.getElementById("btn-browse-file");
    const selectedDisplay = document.getElementById("selected-file-display");
    const selectedFilename = document.getElementById("selected-filename");
    const selectedFilesize = document.getElementById("selected-filesize");
    const analyzeBtn = document.getElementById("btn-analyze-upload");

    if (browseBtn && fileInput) {
        browseBtn.addEventListener("click", () => fileInput.click());
    }

    if (dropzone && fileInput) {
        ["dragenter", "dragover"].forEach(eventName => {
            dropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.add("dragover");
            }, false);
        });

        ["dragleave", "drop"].forEach(eventName => {
            dropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.remove("dragover");
            }, false);
        });

        dropzone.addEventListener("drop", (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files && files.length > 0) {
                fileInput.files = files;
                handleFileSelection(files[0]);
            }
        });

        fileInput.addEventListener("change", () => {
            if (fileInput.files && fileInput.files.length > 0) {
                handleFileSelection(fileInput.files[0]);
            }
        });
    }

    function handleFileSelection(file) {
        if (!file) return;
        if (selectedFilename) selectedFilename.textContent = file.name;
        if (selectedFilesize) selectedFilesize.textContent = `${(file.size / 1024).toFixed(1)} KB`;
        if (selectedDisplay) selectedDisplay.style.display = "inline-flex";
    }

    if (analyzeBtn && fileInput) {
        analyzeBtn.addEventListener("click", async () => {
            if (!fileInput.files || fileInput.files.length === 0) {
                alert("Please select a spreadsheet file first.");
                return;
            }
            await uploadAndAnalyzeFile(fileInput.files[0]);
        });
    }

    const cancelBtn = document.getElementById("btn-cancel-import");
    if (cancelBtn) {
        cancelBtn.addEventListener("click", resetImportWorkflow);
    }

    const confirmBtn = document.getElementById("btn-confirm-import");
    if (confirmBtn) {
        confirmBtn.addEventListener("click", executeConfirmImport);
    }

    const importAnotherBtn = document.getElementById("btn-import-another");
    if (importAnotherBtn) {
        importAnotherBtn.addEventListener("click", resetImportWorkflow);
    }

    const refreshBatchesBtn = document.getElementById("btn-refresh-batches");
    if (refreshBatchesBtn) {
        refreshBatchesBtn.addEventListener("click", loadImportBatchesList);
    }
}

async function uploadAndAnalyzeFile(file) {
    const analyzeBtn = document.getElementById("btn-analyze-upload");
    try {
        if (analyzeBtn) {
            analyzeBtn.disabled = true;
            analyzeBtn.textContent = "Analyzing File...";
        }

        const formData = new FormData();
        formData.append("file", file);

        const res = await fetch("/api/v1/analytics/import/upload", {
            method: "POST",
            body: formData
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "Failed to analyze historical sales file.");
        }

        currentStagedImport = data;
        renderAnalysisResults(data);

        // Update step badges
        updateWizardStep(4);
    } catch (err) {
        alert(`Error analyzing file: ${err.message}`);
    } finally {
        if (analyzeBtn) {
            analyzeBtn.disabled = false;
            analyzeBtn.textContent = "Analyze File";
        }
    }
}

function updateWizardStep(activeStepNumber) {
    for (let i = 1; i <= 5; i++) {
        const badge = document.getElementById(`step-badge-${i}`);
        if (!badge) continue;
        badge.classList.remove("active", "completed");
        if (i < activeStepNumber) {
            badge.classList.add("completed");
        } else if (i === activeStepNumber) {
            badge.classList.add("active");
        }
    }
}

function renderAnalysisResults(analysis) {
    const analysisCard = document.getElementById("import-analysis-card");
    const uploadCard = document.getElementById("import-upload-card");
    const resultCard = document.getElementById("import-result-card");

    if (uploadCard) uploadCard.style.display = "none";
    if (resultCard) resultCard.style.display = "none";
    if (analysisCard) analysisCard.style.display = "block";

    // Header stats
    const setElemText = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    };

    setElemText("stat-filename", analysis.filename);
    setElemText("stat-total-rows", analysis.total_rows.toLocaleString());
    setElemText("stat-total-cols", analysis.total_columns);
    setElemText("stat-file-type", analysis.file_type);

    const statusTag = document.getElementById("import-status-tag");
    if (statusTag) {
        statusTag.textContent = analysis.is_ready_for_import ? "Ready for Import" : analysis.status;
        statusTag.className = analysis.is_ready_for_import ? "badge badge-success" : "badge badge-warning";
    }

    // Column Mapping Table
    const mapTbody = document.getElementById("column-mapping-tbody");
    if (mapTbody) {
        const canonicalFields = [
            { key: "date", label: "Date", required: true },
            { key: "product", label: "Product / Item", required: true },
            { key: "quantity", label: "Quantity", required: true },
            { key: "price", label: "Unit Price", required: false },
            { key: "total", label: "Total Amount", required: false },
            { key: "unit", label: "Unit", required: false },
            { key: "transaction_id", label: "Invoice / Bill #", required: false }
        ];

        mapTbody.innerHTML = canonicalFields.map(f => {
            const detected = analysis.detected_mapping[f.key] || "";
            const isAmbiguous = analysis.ambiguous_columns && analysis.ambiguous_columns[f.key];
            const isMissing = analysis.missing_required_columns && analysis.missing_required_columns.includes(f.key);

            let statusHtml = `<span class="badge-status badge-success">Matched</span>`;
            if (isAmbiguous) {
                statusHtml = `<span class="badge-status badge-warning">Ambiguous</span>`;
            } else if (isMissing) {
                statusHtml = `<span class="badge-status badge-danger">Missing</span>`;
            } else if (!detected) {
                statusHtml = `<span class="badge-status badge-secondary">Optional (Empty)</span>`;
            }

            // Generate dropdown options
            const options = ['<option value="">-- Not Mapped --</option>']
                .concat(analysis.detected_columns.map(col => {
                    const sel = (col === detected) ? 'selected' : '';
                    return `<option value="${escapeHtml(col)}" ${sel}>${escapeHtml(col)}</option>`;
                })).join("");

            return `
                <tr>
                    <td><strong>${escapeHtml(f.label)}</strong></td>
                    <td>${f.required ? '<span class="badge badge-danger">Required</span>' : '<span class="badge badge-neutral">Optional</span>'}</td>
                    <td>
                        <select class="mapping-select" data-canonical="${f.key}">
                            ${options}
                        </select>
                    </td>
                    <td>${statusHtml}</td>
                </tr>
            `;
        }).join("");
    }

    // Ignored Columns
    const ignoredList = document.getElementById("ignored-columns-list");
    if (ignoredList) {
        if (analysis.ignored_columns && analysis.ignored_columns.length > 0) {
            ignoredList.textContent = analysis.ignored_columns.join(", ");
        } else {
            ignoredList.textContent = "None (all columns utilized)";
        }
    }

    // Validation Summary Cards
    const val = analysis.validation_summary;
    setElemText("val-valid-count", val.valid_rows.toLocaleString());
    setElemText("val-warning-count", val.warning_rows.toLocaleString());
    setElemText("val-invalid-count", val.invalid_rows.toLocaleString());
    setElemText("val-usable-days", val.usable_days_count.toLocaleString());

    if (val.earliest_date && val.latest_date) {
        setElemText("val-coverage-range", `${val.earliest_date} to ${val.latest_date}`);
    } else {
        setElemText("val-coverage-range", "--");
    }

    // Unmatched products
    const unmatchedAlert = document.getElementById("unmatched-products-alert");
    const unmatchedList = document.getElementById("unmatched-products-list");
    if (unmatchedAlert && unmatchedList) {
        if (analysis.unmatched_products && analysis.unmatched_products.length > 0) {
            unmatchedAlert.style.display = "block";
            unmatchedList.innerHTML = analysis.unmatched_products.map(p =>
                `<li><strong>"${escapeHtml(p.raw_name)}"</strong> (${p.occurrence_count} occurrences) — No catalog match</li>`
            ).join("");
        } else {
            unmatchedAlert.style.display = "none";
        }
    }

    // Diagnostics Accordion
    const issuesDetails = document.getElementById("issues-accordion");
    const issuesCount = document.getElementById("issues-total-count");
    const issuesList = document.getElementById("issues-list");
    const allIssues = (analysis.errors || []).concat(analysis.warnings || []);

    if (issuesDetails && issuesCount && issuesList) {
        if (allIssues.length > 0) {
            issuesDetails.style.display = "block";
            issuesCount.textContent = allIssues.length;
            issuesList.innerHTML = allIssues.slice(0, 50).map(issue => `
                <div class="issues-item ${issue.severity === 'ERROR' ? 'error' : 'warning'}">
                    Row ${issue.row}: [${escapeHtml(issue.field)}] ${escapeHtml(issue.message)}
                </div>
            `).join("");
        } else {
            issuesDetails.style.display = "none";
        }
    }

    // Sample Preview Table
    const previewTbody = document.getElementById("preview-tbody");
    if (previewTbody) {
        if (!analysis.sample_preview || analysis.sample_preview.length === 0) {
            previewTbody.innerHTML = `<tr><td colspan="9" class="text-center text-muted">No valid rows available for preview.</td></tr>`;
        } else {
            previewTbody.innerHTML = analysis.sample_preview.map(row => `
                <tr>
                    <td>${row.row}</td>
                    <td><code>${escapeHtml(row.sale_date)}</code></td>
                    <td>${escapeHtml(row.raw_product_name)}</td>
                    <td><strong>${escapeHtml(row.matched_product_name || '--')}</strong></td>
                    <td>${row.quantity}</td>
                    <td>${escapeHtml(row.unit)}</td>
                    <td>₹${row.unit_price.toFixed(2)}</td>
                    <td><strong>₹${row.total_amount.toFixed(2)}</strong></td>
                    <td><span class="badge badge-success">${row.match_type} (${Math.round(row.match_confidence * 100)}%)</span></td>
                </tr>
            `).join("");
        }
    }

    // Confirm button
    const confirmBadge = document.getElementById("confirm-valid-count-badge");
    const confirmBtn = document.getElementById("btn-confirm-import");
    if (confirmBadge) confirmBadge.textContent = val.valid_rows.toLocaleString();
    if (confirmBtn) confirmBtn.disabled = !analysis.is_ready_for_import;
}

async function executeConfirmImport() {
    if (!currentStagedImport) return;

    const confirmBtn = document.getElementById("btn-confirm-import");
    try {
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.textContent = "Importing Historical Sales...";
        }

        // Collect custom mapping if user changed dropdowns
        const customMapping = {};
        document.querySelectorAll(".mapping-select").forEach(sel => {
            const canonical = sel.dataset.canonical;
            if (sel.value) {
                customMapping[canonical] = sel.value;
            }
        });

        const payload = {
            import_id: currentStagedImport.import_id,
            column_mapping: customMapping,
            import_mode: "SKIP_INVALID"
        };

        const res = await fetch("/api/v1/analytics/import/confirm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "Failed to commit historical sales import.");
        }

        // Show result banner
        const analysisCard = document.getElementById("import-analysis-card");
        const resultCard = document.getElementById("import-result-card");
        if (analysisCard) analysisCard.style.display = "none";
        if (resultCard) resultCard.style.display = "block";

        const setElemText = (id, text) => {
            const el = document.getElementById(id);
            if (el) el.textContent = text;
        };

        setElemText("res-imported-count", data.imported_records_count.toLocaleString());
        setElemText("res-skipped-count", data.skipped_duplicate_count.toLocaleString());
        setElemText("res-usable-days", data.usable_days_count);
        setElemText("res-forecasting-status", data.forecasting_status);

        const statusBadge = document.getElementById("res-forecasting-status");
        if (statusBadge) {
            statusBadge.className = data.forecasting_status === "SUFFICIENT_DATA" ? "badge badge-success" : "badge badge-warning";
        }

        updateWizardStep(5);

        // Refresh analytics dashboard and audit batches
        await loadSalesHistoryDashboard();
        await loadImportBatchesList();

        // Reactive system-wide event dispatch
        window.dispatchEvent(new CustomEvent('bills-updated', { detail: data }));
        window.dispatchEvent(new CustomEvent('sales-updated', { detail: data }));

        alert(data.message || "Historical sales imported successfully!");
    } catch (err) {
        alert(`Import Error: ${err.message}`);
    } finally {
        if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.textContent = `Confirm & Import Valid Records`;
        }
    }
}

function resetImportWorkflow() {
    currentStagedImport = null;
    const fileInput = document.getElementById("import-file-input");
    if (fileInput) fileInput.value = "";

    const selectedDisplay = document.getElementById("selected-file-display");
    if (selectedDisplay) selectedDisplay.style.display = "none";

    const uploadCard = document.getElementById("import-upload-card");
    const analysisCard = document.getElementById("import-analysis-card");
    const resultCard = document.getElementById("import-result-card");

    if (uploadCard) uploadCard.style.display = "block";
    if (analysisCard) analysisCard.style.display = "none";
    if (resultCard) resultCard.style.display = "none";

    updateWizardStep(1);
}

async function loadImportBatchesList() {
    const tbody = document.getElementById("batches-tbody");
    if (!tbody) return;

    try {
        const res = await fetch("/api/v1/analytics/import/batches?limit=25");
        if (!res.ok) return;
        const batches = await res.json();

        if (!batches || batches.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" class="text-center text-muted">No historical imports recorded yet.</td></tr>`;
            return;
        }

        tbody.innerHTML = batches.map(b => {
            const dt = new Date(b.created_at);
            const dateStr = dt.toLocaleDateString("en-IN") + " " + dt.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });

            let statusClass = "badge-success";
            if (b.status === "ROLLED_BACK") statusClass = "badge-neutral";
            else if (b.status === "FAILED") statusClass = "badge-danger";

            const coverage = (b.earliest_date && b.latest_date) ? `${b.earliest_date} → ${b.latest_date}` : '--';

            const canRollback = (b.status === "COMPLETED" && b.imported_records > 0);
            const rollbackBtn = canRollback
                ? `<button class="btn btn-secondary btn-sm" onclick="rollbackImportBatch('${escapeHtml(b.import_id)}')">Rollback</button>`
                : `<span class="text-muted">--</span>`;

            return `
                <tr>
                    <td><code>${escapeHtml(b.import_id)}</code></td>
                    <td><strong>${escapeHtml(b.source_filename)}</strong></td>
                    <td><span class="badge badge-neutral">${escapeHtml(b.file_type)}</span></td>
                    <td><strong>${b.imported_records.toLocaleString()}</strong></td>
                    <td>${b.skipped_duplicates.toLocaleString()}</td>
                    <td>${coverage}</td>
                    <td>${b.usable_days_count} days</td>
                    <td><span class="badge-status ${statusClass}">${escapeHtml(b.status)}</span></td>
                    <td>${rollbackBtn}</td>
                </tr>
            `;
        }).join("");
    } catch (err) {
        console.error("Failed to load import batches:", err);
    }
}

async function rollbackImportBatch(importId) {
    if (!confirm(`Are you sure you want to rollback import '${importId}'?\nAll associated historical sales records will be deactivated and sales aggregates reconciled.`)) {
        return;
    }

    try {
        const res = await fetch(`/api/v1/analytics/import/rollback/${encodeURIComponent(importId)}`, {
            method: "POST"
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "Failed to rollback import batch.");
        }

        alert(data.message || `Batch '${importId}' rolled back successfully.`);
        await loadSalesHistoryDashboard();
        await loadImportBatchesList();

        // Reactive system-wide event dispatch for rollback
        window.dispatchEvent(new CustomEvent('bills-updated', { detail: data }));
        window.dispatchEvent(new CustomEvent('sales-updated', { detail: data }));
    } catch (err) {
        alert(`Rollback Error: ${err.message}`);
    }
}


/* ============================================================
   STEP 11: DEMAND FORECASTING & REORDER INTELLIGENCE MODULE
   ============================================================ */

let _forecastStoreData = null;


    function initSales() {
        if (typeof initSalesHistoryModule === 'function') initSalesHistoryModule();
        if (typeof initHistoricalImportModule === 'function') initHistoricalImportModule();
    }

    // Reactive sync listeners
    function onSalesOrBillsUpdated() {
        const salesTab = document.getElementById('tab-analytics') || document.getElementById('tab-sales');
        if (salesTab && salesTab.classList.contains('active')) {
            if (typeof loadSalesHistoryDashboard === 'function') {
                loadSalesHistoryDashboard();
            }
        }
    }
    window.addEventListener('bills-updated', onSalesOrBillsUpdated);
    window.addEventListener('sales-updated', onSalesOrBillsUpdated);

    // ==============================================================================
    // Sales History Visualizations (Phase 1)
    // ==============================================================================

    let salesChartMetric = 'units';
    let cachedSalesChartsData = null;

    function toggleSalesChartMetric(metric) {
        salesChartMetric = metric === 'revenue' ? 'revenue' : 'units';
        const btnU = document.getElementById("btn-sales-chart-units");
        const btnR = document.getElementById("btn-sales-chart-revenue");
        if (btnU) btnU.classList.toggle("active", salesChartMetric === 'units');
        if (btnR) btnR.classList.toggle("active", salesChartMetric === 'revenue');

        if (cachedSalesChartsData) {
            renderSalesBestProductsChart(cachedSalesChartsData);
        }
    }

    async function loadSalesHistoryCharts(startDate, endDate, productId = "", category = "", paymentMode = "") {
        if (!window.ApnaCharts) return;

        try {
            let url = `/api/v1/analytics/sales/charts?start_date=${startDate}&end_date=${endDate}`;
            if (productId) url += `&product_id=${productId}`;
            if (category) url += `&category=${encodeURIComponent(category)}`;
            if (paymentMode) url += `&payment_mode=${encodeURIComponent(paymentMode)}`;

            const res = await fetch(url);
            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || `Server returned ${res.status}`);
            }
            const data = await res.json();
            cachedSalesChartsData = data;

            // Summary Badges
            const revBadge = document.getElementById("sales-chart-rev-badge");
            if (revBadge) revBadge.textContent = window.ApnaCharts.formatRupees(data.total_revenue || 0);

            const txBadge = document.getElementById("sales-chart-tx-badge");
            if (txBadge) txBadge.textContent = `${data.total_transactions || 0} bills`;

            // Chart 4: Revenue Over Time Line Chart
            renderSalesRevenueTrendChart(data);

            // Chart 5: Daily Transactions Bar Chart
            renderSalesTransactionsChart(data);

            // Chart 6: Best-Selling Products Horizontal Bar Chart
            renderSalesBestProductsChart(data);

            // Chart 7: Category-wise Sales Bar Chart
            renderSalesCategoryChart(data);

        } catch (err) {
            console.error("Failed to load sales history charts:", err);
            const wrap = document.getElementById("sales-revenue-trend-wrap");
            if (wrap) window.ApnaCharts.showEmptyState(wrap, "Visualizations Unavailable", err.message);
        }
    }

    function renderSalesRevenueTrendChart(data) {
        const wrap = document.getElementById("sales-revenue-trend-wrap");
        const trend = data.revenue_trend || [];
        if (trend.length === 0) {
            window.ApnaCharts.showEmptyState(wrap, "No Revenue Recorded", "No completed sales found in this date range.");
            return;
        }

        const labels = trend.map(d => d.label);
        const revenues = trend.map(d => d.revenue);

        window.ApnaCharts.createChart("sales-revenue-trend-canvas", {
            type: "line",
            data: {
                labels: labels,
                datasets: [{
                    label: "Revenue",
                    data: revenues,
                    borderColor: "#38bdf8",
                    backgroundColor: "rgba(56, 189, 248, 0.12)",
                    fill: true,
                    tension: 0.35,
                    borderWidth: 2,
                    pointRadius: trend.length > 20 ? 1 : 3,
                    pointHoverRadius: 5
                }]
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
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: ctx => `Revenue: ${window.ApnaCharts.formatRupees(ctx.raw)}`
                        }
                    }
                }
            }
        });
    }

    function renderSalesTransactionsChart(data) {
        const wrap = document.getElementById("sales-tx-trend-wrap");
        const trend = data.transactions_trend || [];
        if (trend.length === 0) {
            window.ApnaCharts.showEmptyState(wrap, "No Transactions", "No completed invoices in selected period.");
            return;
        }

        const labels = trend.map(d => d.label);
        const counts = trend.map(d => d.count);

        window.ApnaCharts.createChart("sales-tx-trend-canvas", {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: "Bills",
                    data: counts,
                    backgroundColor: "#818cf8",
                    borderRadius: 3,
                    maxBarThickness: 18
                }]
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
                            stepSize: 1
                        }
                    }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: ctx => `Bills: ${ctx.raw}`
                        }
                    }
                }
            }
        });
    }

    function renderSalesBestProductsChart(data) {
        const wrap = document.getElementById("sales-best-products-wrap");
        const isUnits = salesChartMetric === "units";
        const items = isUnits ? (data.best_by_units || []) : (data.best_by_revenue || []);

        if (items.length === 0) {
            window.ApnaCharts.showEmptyState(wrap, "No Product Sales", "No items recorded in selected period.");
            return;
        }

        const labels = items.map(p => p.name.length > 20 ? p.name.slice(0, 18) + "…" : p.name);
        const values = items.map(p => isUnits ? p.units_sold : p.revenue);

        window.ApnaCharts.createChart("sales-best-products-canvas", {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: isUnits ? "Units Sold" : "Revenue",
                    data: values,
                    backgroundColor: isUnits ? "#22c55e" : "#38bdf8",
                    borderRadius: 4,
                    maxBarThickness: 22
                }]
            },
            options: {
                ...window.ApnaCharts.getBaseOptions(),
                indexAxis: "y",
                scales: {
                    x: {
                        beginAtZero: true,
                        grid: { color: "rgba(255, 255, 255, 0.05)" },
                        ticks: {
                            color: "#94a3b8",
                            font: { size: 10 },
                            callback: val => isUnits ? val : window.ApnaCharts.formatCompactRupees(val)
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
                                const idx = ctx.dataIndex;
                                const it = items[idx];
                                return isUnits 
                                    ? `Sold: ${ctx.raw} ${it.unit || 'units'}`
                                    : `Revenue: ${window.ApnaCharts.formatRupees(ctx.raw)}`;
                            }
                        }
                    }
                }
            }
        });
    }

    function renderSalesCategoryChart(data) {
        const wrap = document.getElementById("sales-category-wrap");
        const categories = data.category_sales || [];

        if (categories.length === 0) {
            window.ApnaCharts.showEmptyState(wrap, "No Category Data", "No category records in selected period.");
            return;
        }

        const labels = categories.map(c => c.category);
        const values = categories.map(c => c.revenue);

        window.ApnaCharts.createChart("sales-category-canvas", {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: "Category Revenue",
                    data: values,
                    backgroundColor: "#f59e0b",
                    borderRadius: 4,
                    maxBarThickness: 28
                }]
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
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: ctx => `Revenue: ${window.ApnaCharts.formatRupees(ctx.raw)}`
                        }
                    }
                }
            }
        });
    }

    const SalesModule = {
        init: initSales,
        initSalesHistory: initSalesHistoryModule,
        initHistoricalImport: initHistoricalImportModule,
        switchSalesView,
        applySalesPreset,
        filterSalesToToday,
        loadSalesHistoryDashboard,
        loadSalesHistoryCharts,
        toggleSalesChartMetric
    };

    window.SalesModule = SalesModule;
    window.initSales = initSales;
    window.initSalesHistoryModule = initSalesHistoryModule;
    window.initHistoricalImport = initHistoricalImportModule;
    window.initHistoricalImportModule = initHistoricalImportModule;
    window.switchSalesView = switchSalesView;
    window.applySalesPreset = applySalesPreset;
    window.filterSalesToToday = filterSalesToToday;
    window.loadSalesHistoryDashboard = loadSalesHistoryDashboard;
    window.loadSalesHistoryCharts = loadSalesHistoryCharts;
    window.toggleSalesChartMetric = toggleSalesChartMetric;

})(window);
