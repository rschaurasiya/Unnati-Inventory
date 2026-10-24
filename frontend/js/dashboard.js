/**
 * Shop Command Center Dashboard Module
 * Manages store overview metrics, interactive clickable KPI cards with real-time drill-down panels,
 * Quick Action launchers, independent collapsible operational sections with state persistence,
 * and real-time cross-module synchronization.
 */

(function(window) {
    'use strict';

    // State Variables
    let isLowStockExpanded = false;
    let isRecentSalesExpanded = false;
    let dashboardDebounceTimer = null;
    let currentActiveKpi = null;
    let latestLowStockCount = 0;
    let latestRecentSalesCount = 0;

    /**
     * Helper to get authenticated fetch
     */
    function authFetch(url, options = {}) {
        if (window.ShopApi && typeof window.ShopApi.authFetch === "function") {
            return window.ShopApi.authFetch(url, options);
        }
        if (typeof window.authFetch === "function") {
            return window.authFetch(url, options);
        }
        return fetch(url, options);
    }

    /**
     * Helper for currency formatting
     */
    function formatCurrency(val) {
        if (window.AppUtils && typeof window.AppUtils.formatCurrency === "function") {
            return window.AppUtils.formatCurrency(val);
        }
        if (typeof window.formatCurrency === "function") {
            return window.formatCurrency(val);
        }
        const num = parseFloat(val);
        return isNaN(num) ? "₹0.00" : `₹${num.toFixed(2)}`;
    }

    /**
     * Helper for HTML escaping
     */
    function escapeHtml(str) {
        if (window.AppUtils && typeof window.AppUtils.escapeHtml === "function") {
            return window.AppUtils.escapeHtml(str);
        }
        if (typeof window.escapeHtml === "function") {
            return window.escapeHtml(str);
        }
        if (!str) return "";
        return String(str).replace(/[&<>'"]/g, tag => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            "'": "&#39;",
            '"': "&quot;"
        }[tag] || tag));
    }

    /**
     * Debounced loader to coalesce rapid successive events
     */
    function debouncedLoadMainDashboard(delay = 60) {
        clearTimeout(dashboardDebounceTimer);
        dashboardDebounceTimer = setTimeout(() => {
            loadMainDashboard();
            if (currentActiveKpi) {
                refreshActiveDrillDown();
            }
        }, delay);
    }

    /**
     * Initialize Dashboard Module, event bindings, and default collapsed states
     */
    function initDashboard() {
        const refreshBtn = document.getElementById("refresh-dashboard-btn");
        if (refreshBtn) {
            refreshBtn.addEventListener("click", () => {
                loadMainDashboard();
                if (currentActiveKpi) {
                    refreshActiveDrillDown();
                }
            });
        }

        // Restore persisted collapse preferences from localStorage
        const alertsCollapsed = localStorage.getItem("pos_dash_alerts_collapsed");
        const txnsCollapsed = localStorage.getItem("pos_dash_txns_collapsed");

        setLowStockSectionExpanded(alertsCollapsed === "false");
        setRecentSalesSectionExpanded(txnsCollapsed === "false");
        updateToggleAllButton();

        // Reactive real-time updates when shop profile, inventory, sales, or customers mutate
        if (window.AppEvents) {
            window.AppEvents.on("sales-updated", () => debouncedLoadMainDashboard());
            window.AppEvents.on("inventory-updated", () => debouncedLoadMainDashboard());
            window.AppEvents.on("products-updated", () => debouncedLoadMainDashboard());
            window.AppEvents.on("customers-updated", () => debouncedLoadMainDashboard());
            window.AppEvents.on("profile-updated", () => debouncedLoadMainDashboard());
            window.AppEvents.on("bills-updated", () => debouncedLoadMainDashboard());
        }
        window.addEventListener("shop-profile-updated", () => debouncedLoadMainDashboard());
        window.addEventListener("profile-updated", () => debouncedLoadMainDashboard());
        window.addEventListener("products-updated", () => debouncedLoadMainDashboard());
        window.addEventListener("bills-updated", () => debouncedLoadMainDashboard());
        window.addEventListener("sales-updated", () => debouncedLoadMainDashboard());
        window.addEventListener("customers-updated", () => debouncedLoadMainDashboard());
        window.addEventListener("inventory-updated", () => debouncedLoadMainDashboard());
    }

    // ==============================================================================
    // Independent Collapsible Section Controls & Persistence
    // ==============================================================================

    function updateCollapsibleBadges() {
        const lowBadge = document.getElementById("dash-low-stock-badge");
        if (lowBadge) {
            if (isLowStockExpanded) {
                lowBadge.textContent = latestLowStockCount === 0 ? "Healthy" : `${latestLowStockCount} ${latestLowStockCount === 1 ? 'alert' : 'alerts'}`;
                lowBadge.className = "collapse-status-pill expanded";
            } else {
                lowBadge.textContent = latestLowStockCount === 0 ? "Healthy" : `${latestLowStockCount} ${latestLowStockCount === 1 ? 'alert' : 'alerts'}`;
                lowBadge.className = "collapse-status-pill collapsed";
            }
        }

        const salesBadge = document.getElementById("dash-recent-sales-badge");
        if (salesBadge) {
            const countText = `${latestRecentSalesCount} ${latestRecentSalesCount === 1 ? 'recent bill' : 'recent bills'}`;
            if (isRecentSalesExpanded) {
                salesBadge.textContent = countText;
                salesBadge.className = "collapse-status-pill expanded";
            } else {
                salesBadge.textContent = countText;
                salesBadge.className = "collapse-status-pill collapsed";
            }
        }
    }

    function updateToggleAllButton() {
        const toggleAllBtn = document.getElementById("dash-toggle-all-panels-btn");
        if (toggleAllBtn) {
            if (isLowStockExpanded && isRecentSalesExpanded) {
                toggleAllBtn.textContent = "Collapse All";
            } else {
                toggleAllBtn.textContent = "Expand All";
            }
        }
    }

    function toggleAllDashboardPanels() {
        if (isLowStockExpanded && isRecentSalesExpanded) {
            setLowStockSectionExpanded(false);
            setRecentSalesSectionExpanded(false);
            localStorage.setItem("pos_dash_alerts_collapsed", "true");
            localStorage.setItem("pos_dash_txns_collapsed", "true");
        } else {
            setLowStockSectionExpanded(true);
            setRecentSalesSectionExpanded(true);
            localStorage.setItem("pos_dash_alerts_collapsed", "false");
            localStorage.setItem("pos_dash_txns_collapsed", "false");
        }
        updateToggleAllButton();
    }

    function setLowStockSectionExpanded(expanded, scrollIntoView = false) {
        isLowStockExpanded = !!expanded;
        const content = document.getElementById("dash-low-stock-collapsible");
        const chevron = document.getElementById("dash-low-stock-chevron");
        const header = document.getElementById("dash-low-stock-header");

        if (content) {
            if (isLowStockExpanded) {
                content.classList.remove("collapsed");
                content.setAttribute("aria-hidden", "false");
            } else {
                content.classList.add("collapsed");
                content.setAttribute("aria-hidden", "true");
            }
        }

        if (chevron) {
            if (isLowStockExpanded) {
                chevron.classList.add("expanded");
            } else {
                chevron.classList.remove("expanded");
            }
        }

        if (header) {
            header.setAttribute("aria-expanded", isLowStockExpanded ? "true" : "false");
        }

        updateCollapsibleBadges();
        updateToggleAllButton();

        if (isLowStockExpanded && scrollIntoView) {
            const cardEl = document.getElementById("dash-section-low-stock") || header;
            if (cardEl && typeof cardEl.scrollIntoView === "function") {
                cardEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }
        }
    }

    function setRecentSalesSectionExpanded(expanded, scrollIntoView = false) {
        isRecentSalesExpanded = !!expanded;
        const content = document.getElementById("dash-recent-sales-collapsible");
        const chevron = document.getElementById("dash-recent-sales-chevron");
        const header = document.getElementById("dash-recent-sales-header");

        if (content) {
            if (isRecentSalesExpanded) {
                content.classList.remove("collapsed");
                content.setAttribute("aria-hidden", "false");
            } else {
                content.classList.add("collapsed");
                content.setAttribute("aria-hidden", "true");
            }
        }

        if (chevron) {
            if (isRecentSalesExpanded) {
                chevron.classList.add("expanded");
            } else {
                chevron.classList.remove("expanded");
            }
        }

        if (header) {
            header.setAttribute("aria-expanded", isRecentSalesExpanded ? "true" : "false");
        }

        updateCollapsibleBadges();
        updateToggleAllButton();

        if (isRecentSalesExpanded && scrollIntoView) {
            const cardEl = document.getElementById("dash-section-recent-sales") || header;
            if (cardEl && typeof cardEl.scrollIntoView === "function") {
                cardEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }
        }
    }

    function toggleLowStockSection() {
        setLowStockSectionExpanded(!isLowStockExpanded);
        localStorage.setItem("pos_dash_alerts_collapsed", isLowStockExpanded ? "false" : "true");
    }

    function toggleRecentSalesSection() {
        setRecentSalesSectionExpanded(!isRecentSalesExpanded);
        localStorage.setItem("pos_dash_txns_collapsed", isRecentSalesExpanded ? "false" : "true");
    }

    function handleCollapsibleKeyDown(event, section) {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            if (section === "low-stock") {
                toggleLowStockSection();
            } else if (section === "recent-sales") {
                toggleRecentSalesSection();
            }
        }
    }

    // ==============================================================================
    // Interactive KPI Drill-Down Panel Manager
    // ==============================================================================

    function updateActiveKpiCardHighlight() {
        const cardIds = [
            "kpi-card-today-sales",
            "kpi-card-inventory-val",
            "kpi-card-low-stock",
            "kpi-card-total-udhaar",
            "kpi-card-forecast-ready"
        ];

        cardIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.classList.remove("active-kpi-card");
            }
        });

        if (currentActiveKpi) {
            const activeEl = document.getElementById(`kpi-card-${currentActiveKpi}`);
            if (activeEl) {
                activeEl.classList.add("active-kpi-card");
            }
        }
    }

    function closeKpiDrillDown() {
        currentActiveKpi = null;
        updateActiveKpiCardHighlight();
        const panel = document.getElementById("kpi-drilldown-panel");
        if (panel) {
            panel.style.display = "none";
        }
    }

    async function openKpiDrillDown(kpiType) {
        if (currentActiveKpi === kpiType) {
            closeKpiDrillDown();
            return;
        }

        currentActiveKpi = kpiType;
        updateActiveKpiCardHighlight();

        const panel = document.getElementById("kpi-drilldown-panel");
        const body = document.getElementById("drilldown-body");
        const titleEl = document.getElementById("drilldown-title");
        const subtitleEl = document.getElementById("drilldown-subtitle");
        const iconEl = document.getElementById("drilldown-icon");
        const fullModuleBtn = document.getElementById("drilldown-full-module-btn");
        const moduleLabelEl = document.getElementById("drilldown-module-label");

        if (!panel || !body) return;

        panel.style.display = "block";
        body.innerHTML = `
            <div class="text-center text-muted" style="padding: 2.5rem 1rem;">
                <div style="font-size: 1.5rem; margin-bottom: 0.5rem;">⏳</div>
                <div>Fetching real-time ${kpiType.replace('-', ' ')} details...</div>
            </div>
        `;

        if (typeof panel.scrollIntoView === "function") {
            panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }

        switch (kpiType) {
            case "today-sales":
                await renderDrillDownTodaySales(titleEl, subtitleEl, iconEl, fullModuleBtn, moduleLabelEl, body);
                break;
            case "inventory-val":
                await renderDrillDownInventoryVal(titleEl, subtitleEl, iconEl, fullModuleBtn, moduleLabelEl, body);
                break;
            case "low-stock":
                await renderDrillDownLowStock(titleEl, subtitleEl, iconEl, fullModuleBtn, moduleLabelEl, body);
                break;
            case "total-udhaar":
                await renderDrillDownTotalUdhaar(titleEl, subtitleEl, iconEl, fullModuleBtn, moduleLabelEl, body);
                break;
            case "forecast-ready":
                await renderDrillDownForecastReady(titleEl, subtitleEl, iconEl, fullModuleBtn, moduleLabelEl, body);
                break;
        }
    }

    function refreshActiveDrillDown() {
        if (currentActiveKpi) {
            const active = currentActiveKpi;
            currentActiveKpi = null;
            openKpiDrillDown(active);
        }
    }

    // Handlers mapped to KPI cards - Directly navigate to corresponding filtered views
    function onKpiTodaySalesClick() {
        if (typeof window.switchTab === "function") {
            window.switchTab("analytics");
        } else if (typeof window.navigateTo === "function") {
            window.navigateTo("/sales/history");
        }
        setTimeout(() => {
            if (typeof window.filterSalesToToday === "function") {
                window.filterSalesToToday();
            } else if (typeof window.applySalesPreset === "function") {
                window.applySalesPreset("today");
            }
        }, 50);
    }

    function onKpiInventoryValClick() {
        if (typeof window.switchTab === "function") {
            window.switchTab("inventory");
        } else if (typeof window.navigateTo === "function") {
            window.navigateTo("/inventory");
        }
    }

    function onKpiLowStockClick() {
        if (typeof window.switchTab === "function") {
            window.switchTab("inventory");
        } else if (typeof window.navigateTo === "function") {
            window.navigateTo("/inventory");
        }
        setTimeout(() => {
            if (typeof window.selectKpiFilter === "function") {
                window.selectKpiFilter("low_stock");
            }
        }, 50);
    }

    function onKpiTotalUdhaarClick() {
        if (typeof window.switchTab === "function") {
            window.switchTab("udhaar");
        } else if (typeof window.navigateTo === "function") {
            window.navigateTo("/customers");
        }
    }

    function onKpiForecastReadyClick() {
        if (typeof window.switchTab === "function") {
            window.switchTab("forecasting");
        } else if (typeof window.navigateTo === "function") {
            window.navigateTo("/forecast");
        }
    }

    async function playDailyVoiceBriefing() {
        const todaySales = document.getElementById("dash-today-sales")?.textContent || "₹0.00";
        const todayOrdersText = document.getElementById("dash-today-orders")?.textContent || "0 bills";
        const lowStockCount = document.getElementById("dash-low-stock-count")?.textContent || "0";
        const totalUdhaar = document.getElementById("dash-total-udhaar")?.textContent || "₹0.00";
        const reorderUnits = document.getElementById("dash-reorder-units")?.textContent || "0 units";

        const briefingText = `Good day! Today's revenue is ${todaySales} across ${todayOrdersText}. You have ${lowStockCount} items needing attention, and ${totalUdhaar} in outstanding udhaar. AI recommends ${reorderUnits}.`;

        if (typeof window.speakWithElevenLabs === "function") {
            window.speakWithElevenLabs(briefingText, { force: true });
        }
        if (typeof window.showToast === "function") {
            window.showToast("Playing Daily AI Voice Briefing...", "info");
        }
    }

    function handleKpiCardKeyDown(event, type) {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            switch (type) {
                case "today-sales":
                    onKpiTodaySalesClick();
                    break;
                case "inventory-val":
                    onKpiInventoryValClick();
                    break;
                case "low-stock":
                    onKpiLowStockClick();
                    break;
                case "total-udhaar":
                    onKpiTotalUdhaarClick();
                    break;
                case "forecast-ready":
                    onKpiForecastReadyClick();
                    break;
            }
        }
    }

    // ==============================================================================
    // Drill-Down Renderers
    // ==============================================================================

    /**
     * 1. TODAY'S SALES Drill-Down
     */
    async function renderDrillDownTodaySales(titleEl, subtitleEl, iconEl, fullModuleBtn, moduleLabelEl, body) {
        titleEl.textContent = "Today's Sales Breakdown";
        subtitleEl.textContent = "Real-time itemized transactions, line totals, and payment modes for today";
        iconEl.innerHTML = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>`;
        moduleLabelEl.textContent = "Go to Sales History";

        fullModuleBtn.onclick = () => {
            if (typeof window.switchTab === "function") {
                window.switchTab("analytics");
            } else if (typeof window.navigateTo === "function") {
                window.navigateTo("/sales/history");
            }
            setTimeout(() => {
                if (typeof window.filterSalesToToday === "function") {
                    window.filterSalesToToday();
                } else if (typeof window.applySalesPreset === "function") {
                    window.applySalesPreset("today");
                }
            }, 50);
        };

        const todayStr = new Date().toISOString().slice(0, 10);

        try {
            const [dailyRes, itemsRes] = await Promise.allSettled([
                authFetch(`/api/v1/analytics/sales/daily?date=${todayStr}`).then(r => r.ok ? r.json() : null),
                authFetch(`/api/v1/analytics/sales/items?start_date=${todayStr}&end_date=${todayStr}&limit=500`).then(r => r.ok ? r.json() : [])
            ]);

            const daily = dailyRes.status === "fulfilled" ? dailyRes.value : null;
            const items = itemsRes.status === "fulfilled" && Array.isArray(itemsRes.value) ? itemsRes.value : [];

            const totalRev = daily ? (daily.total_revenue || 0) : 0;
            const txnCount = daily ? (daily.transaction_count || 0) : 0;
            const totalQty = daily ? (daily.total_quantity_sold || 0) : items.reduce((s, it) => s + (it.quantity || 0), 0);

            // Calculate payment breakdown
            let cashTotal = 0;
            let upiTotal = 0;
            let udhaarTotal = 0;
            items.forEach(it => {
                const mode = (it.payment_mode || "").toUpperCase();
                const amt = it.line_total || 0;
                if (mode === "CASH") cashTotal += amt;
                else if (mode === "UPI") upiTotal += amt;
                else if (mode === "UDHAAR") udhaarTotal += amt;
            });

            body.innerHTML = `
                <div class="drilldown-summary-grid">
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Total Revenue</span>
                        <span class="drilldown-stat-val" style="color: #22c55e;">${formatCurrency(totalRev)}</span>
                        <span class="drilldown-stat-sub">Aggregated for ${todayStr}</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Completed Bills</span>
                        <span class="drilldown-stat-val">${txnCount}</span>
                        <span class="drilldown-stat-sub">${txnCount === 1 ? 'Customer transaction' : 'Customer transactions'}</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Units Sold</span>
                        <span class="drilldown-stat-val">${totalQty.toFixed(1)}</span>
                        <span class="drilldown-stat-sub">Across all line items</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Payment Modes</span>
                        <div style="font-size: 0.85rem; margin-top: 0.2rem; display: flex; flex-direction: column; gap: 0.15rem;">
                            <span>Cash: <strong style="color: #22c55e;">${formatCurrency(cashTotal)}</strong></span>
                            <span>UPI: <strong style="color: #38bdf8;">${formatCurrency(upiTotal)}</strong></span>
                            <span>Udhaar: <strong style="color: #f59e0b;">${formatCurrency(udhaarTotal)}</strong></span>
                        </div>
                    </div>
                </div>

                <div style="margin-top: 0.5rem;">
                    <h4 style="font-size: 0.95rem; margin-bottom: 0.6rem; color: var(--text-primary);">Today's Itemized Sales</h4>
                    ${items.length === 0 ? `
                        <div class="drilldown-empty">
                            <div class="drilldown-empty-title">No Sales Recorded Today Yet</div>
                            <p style="font-size: 0.85rem; margin: 0.25rem 0 0.75rem 0;">Transactions captured via Voice Billing POS or Manual Billing will appear here immediately.</p>
                            <button type="button" class="btn btn-primary btn-sm" onclick="navigateTo('/billing')">Open Voice Billing POS</button>
                        </div>
                    ` : `
                        <div class="drilldown-table-wrap">
                            <table class="drilldown-table">
                                <thead>
                                    <tr>
                                        <th>Bill / Source</th>
                                        <th>Product Name</th>
                                        <th>Category</th>
                                        <th>Quantity</th>
                                        <th>Unit Price</th>
                                        <th>Payment Mode</th>
                                        <th style="text-align: right;">Line Total</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${items.map(it => {
                                        const mode = (it.payment_mode || "CASH").toUpperCase();
                                        const badgeClass = mode === "CASH" ? "badge-in-stock" : (mode === "UPI" ? "badge-ready" : "badge-low-stock");
                                        return `
                                            <tr>
                                                <td style="font-family: monospace; font-weight: 600; color: var(--accent);">${escapeHtml(it.bill_number || `Bill #${it.bill_id}`)}</td>
                                                <td><strong>${escapeHtml(it.product_name)}</strong></td>
                                                <td><span class="badge" style="background: rgba(255,255,255,0.06); font-size: 0.75rem;">${escapeHtml(it.category || 'General')}</span></td>
                                                <td>${it.quantity} ${escapeHtml(it.unit || 'unit')}</td>
                                                <td>${formatCurrency(it.unit_price)}</td>
                                                <td><span class="badge ${badgeClass}" style="font-size: 0.72rem;">${mode}</span></td>
                                                <td style="text-align: right; font-weight: 700; color: #22c55e;">${formatCurrency(it.line_total)}</td>
                                            </tr>
                                        `;
                                    }).join('')}
                                </tbody>
                            </table>
                        </div>
                    `}
                </div>
            `;
        } catch (err) {
            console.error("Error loading today's sales drill-down:", err);
            body.innerHTML = `<div class="drilldown-empty" style="color: #ef4444;">Error loading sales drill-down: ${escapeHtml(err.message)}</div>`;
        }
    }

    /**
     * 2. INVENTORY VALUATION Drill-Down
     */
    async function renderDrillDownInventoryVal(titleEl, subtitleEl, iconEl, fullModuleBtn, moduleLabelEl, body) {
        titleEl.textContent = "Inventory Valuation & Catalog Details";
        subtitleEl.textContent = "Category-wise stock distribution, unit pricing, and top-value merchandise";
        iconEl.innerHTML = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2"><path d="m7.5 4.27 9 5.15M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5M12 22V12"/></svg>`;
        moduleLabelEl.textContent = "Go to Inventory Catalog";

        fullModuleBtn.onclick = () => {
            if (typeof window.clearStockFilters === "function") {
                window.clearStockFilters();
            }
            if (typeof window.navigateTo === "function") {
                window.navigateTo("/inventory");
            } else if (typeof window.switchTab === "function") {
                window.switchTab("inventory");
            }
        };

        try {
            const [summaryRes, productsRes] = await Promise.allSettled([
                authFetch("/api/v1/inventory/summary").then(r => r.ok ? r.json() : null),
                authFetch("/api/v1/products").then(r => r.ok ? r.json() : [])
            ]);

            const summary = summaryRes.status === "fulfilled" ? summaryRes.value : null;
            const products = productsRes.status === "fulfilled" && Array.isArray(productsRes.value) ? productsRes.value : [];

            // Compute category-wise breakdown & product valuation
            const categoryMap = {};
            const enrichedProducts = products.map(p => {
                const stockVal = (p.stock_quantity || 0) * (p.unit_price || 0);
                const cat = p.category || "Uncategorized";
                if (!categoryMap[cat]) {
                    categoryMap[cat] = { count: 0, totalVal: 0 };
                }
                categoryMap[cat].count += 1;
                categoryMap[cat].totalVal += stockVal;

                return {
                    ...p,
                    stockVal
                };
            });

            // Sort products by highest stock valuation descending
            enrichedProducts.sort((a, b) => b.stockVal - a.stockVal);

            const totalVal = summary ? (summary.total_inventory_value || 0) : enrichedProducts.reduce((s, p) => s + p.stockVal, 0);
            const totalProds = summary ? (summary.total_products || 0) : enrichedProducts.length;
            const lowCount = summary ? (summary.low_stock_count || 0) : enrichedProducts.filter(p => p.stock_quantity <= p.min_stock_threshold).length;
            const outCount = summary ? (summary.out_of_stock_count || 0) : enrichedProducts.filter(p => p.stock_quantity <= 0).length;

            body.innerHTML = `
                <div class="drilldown-summary-grid">
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Total Inventory Valuation</span>
                        <span class="drilldown-stat-val" style="color: #38bdf8;">${formatCurrency(totalVal)}</span>
                        <span class="drilldown-stat-sub">${totalProds} active catalog products</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Catalog Products</span>
                        <span class="drilldown-stat-val">${totalProds}</span>
                        <span class="drilldown-stat-sub">Across ${Object.keys(categoryMap).length} categories</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Stock Status</span>
                        <span class="drilldown-stat-val" style="color: ${lowCount > 0 ? '#f59e0b' : '#22c55e'};">${lowCount} Low / ${outCount} Out</span>
                        <span class="drilldown-stat-sub">${totalProds - lowCount} items well-stocked</span>
                    </div>
                </div>

                <div>
                    <h4 style="font-size: 0.95rem; margin-bottom: 0.6rem; color: var(--text-primary);">Category Valuation Distribution</h4>
                    <div class="drilldown-pills-row">
                        ${Object.entries(categoryMap).map(([cat, data]) => `
                            <div class="drilldown-cat-pill">
                                <span>${escapeHtml(cat)} (${data.count}):</span>
                                <strong>${formatCurrency(data.totalVal)}</strong>
                            </div>
                        `).join('')}
                    </div>
                </div>

                <div style="margin-top: 0.5rem;">
                    <h4 style="font-size: 0.95rem; margin-bottom: 0.6rem; color: var(--text-primary);">Top-Value Catalog Items (Sorted by Valuation)</h4>
                    <div class="drilldown-table-wrap">
                        <table class="drilldown-table">
                            <thead>
                                <tr>
                                    <th>Product Name</th>
                                    <th>Category</th>
                                    <th>Current Stock</th>
                                    <th>Unit Price</th>
                                    <th>Status</th>
                                    <th style="text-align: right;">Total Stock Value</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${enrichedProducts.slice(0, 50).map(p => {
                                    const isOut = p.stock_quantity <= 0;
                                    const isLow = !isOut && p.stock_quantity <= p.min_stock_threshold;
                                    const statusBadge = isOut
                                        ? `<span class="badge badge-out-stock" style="font-size: 0.72rem;">OUT OF STOCK</span>`
                                        : (isLow
                                            ? `<span class="badge badge-low-stock" style="font-size: 0.72rem;">LOW STOCK</span>`
                                            : `<span class="badge badge-in-stock" style="font-size: 0.72rem;">HEALTHY</span>`);
                                    return `
                                        <tr>
                                            <td>
                                                <strong>${escapeHtml(p.name)}</strong>
                                                ${p.hindi_name ? `<small style="color: var(--text-secondary); margin-left: 0.35rem;">(${escapeHtml(p.hindi_name)})</small>` : ''}
                                            </td>
                                            <td><span class="badge" style="background: rgba(255,255,255,0.06); font-size: 0.75rem;">${escapeHtml(p.category || 'General')}</span></td>
                                            <td style="font-weight: 600; color: ${isOut ? '#ef4444' : (isLow ? '#f59e0b' : 'inherit')};">${p.stock_quantity} ${escapeHtml(p.unit || '')}</td>
                                            <td>${formatCurrency(p.unit_price)}</td>
                                            <td>${statusBadge}</td>
                                            <td style="text-align: right; font-weight: 700; color: #38bdf8;">${formatCurrency(p.stockVal)}</td>
                                        </tr>
                                    `;
                                }).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        } catch (err) {
            console.error("Error loading inventory valuation drill-down:", err);
            body.innerHTML = `<div class="drilldown-empty" style="color: #ef4444;">Error loading inventory valuation: ${escapeHtml(err.message)}</div>`;
        }
    }

    /**
     * 3. LOW STOCK ALERTS Drill-Down
     */
    async function renderDrillDownLowStock(titleEl, subtitleEl, iconEl, fullModuleBtn, moduleLabelEl, body) {
        titleEl.textContent = "Low Stock & Reorder Intelligence";
        subtitleEl.textContent = "Products at or below minimum threshold requiring replenishment";
        iconEl.innerHTML = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;
        moduleLabelEl.textContent = "Go to Inventory";

        fullModuleBtn.onclick = () => {
            if (typeof window.navigateTo === "function") {
                window.navigateTo("/inventory");
            } else if (typeof window.switchTab === "function") {
                window.switchTab("inventory");
            }
        };

        try {
            const res = await authFetch("/api/v1/inventory/low-stock");
            const items = res.ok ? await res.json() : [];

            const outOfStockCount = items.filter(it => it.stock_quantity <= 0).length;
            const lowStockCount = items.filter(it => it.stock_quantity > 0).length;
            const totalDeficit = items.reduce((s, it) => s + Math.max(0, (it.min_stock_threshold || 0) - (it.stock_quantity || 0)), 0);

            body.innerHTML = `
                <div class="drilldown-summary-grid">
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Total Low Stock Alerts</span>
                        <span class="drilldown-stat-val" style="color: #ef4444;">${items.length}</span>
                        <span class="drilldown-stat-sub">Products requiring restock</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Completely Out of Stock</span>
                        <span class="drilldown-stat-val" style="color: #ef4444;">${outOfStockCount}</span>
                        <span class="drilldown-stat-sub">Immediate stockout risk</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Below Threshold</span>
                        <span class="drilldown-stat-val" style="color: #f59e0b;">${lowStockCount}</span>
                        <span class="drilldown-stat-sub">Buffer stock remaining</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Total Deficit Units</span>
                        <span class="drilldown-stat-val">${totalDeficit.toFixed(1)}</span>
                        <span class="drilldown-stat-sub">Recommended replenishment</span>
                    </div>
                </div>

                <div style="margin-top: 0.5rem;">
                    <h4 style="font-size: 0.95rem; margin-bottom: 0.6rem; color: var(--text-primary);">Products Requiring Restock</h4>
                    ${items.length === 0 ? `
                        <div class="drilldown-empty">
                            <div class="drilldown-empty-title" style="color: #22c55e;">Inventory Healthy!</div>
                            <p style="font-size: 0.85rem; margin: 0.25rem 0 0 0;">All catalog products are currently stocked above their minimum reorder thresholds.</p>
                        </div>
                    ` : `
                        <div class="drilldown-table-wrap">
                            <table class="drilldown-table">
                                <thead>
                                    <tr>
                                        <th>Product Name</th>
                                        <th>Current Stock</th>
                                        <th>Min Threshold</th>
                                        <th>Deficit Qty</th>
                                        <th>Status</th>
                                        <th style="text-align: right;">Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${items.map(it => {
                                        const isOut = it.stock_quantity <= 0;
                                        const deficit = Math.max(0, (it.min_stock_threshold || 0) - (it.stock_quantity || 0));
                                        return `
                                            <tr>
                                                <td>
                                                    <strong>${escapeHtml(it.name)}</strong>
                                                    ${it.hindi_name ? `<small style="color: var(--text-secondary); margin-left: 0.35rem;">(${escapeHtml(it.hindi_name)})</small>` : ''}
                                                </td>
                                                <td style="font-weight: 700; color: ${isOut ? '#ef4444' : '#f59e0b'};">
                                                    ${it.stock_quantity} ${escapeHtml(it.unit || '')}
                                                </td>
                                                <td>${it.min_stock_threshold} ${escapeHtml(it.unit || '')}</td>
                                                <td style="font-weight: 600; color: #ef4444;">+${deficit.toFixed(1)} ${escapeHtml(it.unit || '')}</td>
                                                <td>
                                                    <span class="badge ${isOut ? 'badge-out-stock' : 'badge-low-stock'}" style="font-size: 0.72rem;">
                                                        ${isOut ? 'OUT OF STOCK' : 'LOW STOCK'}
                                                    </span>
                                                </td>
                                                <td style="text-align: right;">
                                                    <button type="button" class="btn btn-secondary btn-sm" onclick="openRestockFromDashboard(${it.id}, '${escapeHtml(it.name)}', ${it.stock_quantity}, '${escapeHtml(it.unit || '')}')" style="padding: 0.25rem 0.65rem; font-size: 0.78rem;">
                                                        Restock
                                                    </button>
                                                </td>
                                            </tr>
                                        `;
                                    }).join('')}
                                </tbody>
                            </table>
                        </div>
                    `}
                </div>
            `;
        } catch (err) {
            console.error("Error loading low stock drill-down:", err);
            body.innerHTML = `<div class="drilldown-empty" style="color: #ef4444;">Error loading low stock alerts: ${escapeHtml(err.message)}</div>`;
        }
    }

    /**
     * 4. OUTSTANDING UDHAAR Drill-Down
     */
    async function renderDrillDownTotalUdhaar(titleEl, subtitleEl, iconEl, fullModuleBtn, moduleLabelEl, body) {
        titleEl.textContent = "Outstanding Udhaar & Customer Credit";
        subtitleEl.textContent = "Customer credit balances, limit utilization, and settlement accounts";
        iconEl.innerHTML = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`;
        moduleLabelEl.textContent = "Go to Udhaar & Customers";

        fullModuleBtn.onclick = () => {
            if (typeof window.navigateTo === "function") {
                window.navigateTo("/customers");
            } else if (typeof window.switchTab === "function") {
                window.switchTab("udhaar");
            }
        };

        try {
            const res = await authFetch("/api/v1/customers");
            const allCustomers = res.ok ? await res.json() : [];

            // Filter to customers with current_udhaar_balance > 0, sorted by highest balance descending
            const activeUdhaarCustomers = allCustomers
                .filter(c => (c.current_udhaar_balance || 0) > 0)
                .sort((a, b) => (b.current_udhaar_balance || 0) - (a.current_udhaar_balance || 0));

            const totalUdhaar = activeUdhaarCustomers.reduce((s, c) => s + (c.current_udhaar_balance || 0), 0);
            const totalCreditLimit = allCustomers.reduce((s, c) => s + (c.credit_limit || 0), 0);
            const totalAvailCredit = Math.max(0, totalCreditLimit - totalUdhaar);

            body.innerHTML = `
                <div class="drilldown-summary-grid">
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Total Outstanding Udhaar</span>
                        <span class="drilldown-stat-val" style="color: #f59e0b;">${formatCurrency(totalUdhaar)}</span>
                        <span class="drilldown-stat-sub">${activeUdhaarCustomers.length} active customer debtors</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Active Customer Accounts</span>
                        <span class="drilldown-stat-val">${allCustomers.length}</span>
                        <span class="drilldown-stat-sub">${activeUdhaarCustomers.length} have outstanding balance</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Total Extended Limit</span>
                        <span class="drilldown-stat-val">${formatCurrency(totalCreditLimit)}</span>
                        <span class="drilldown-stat-sub">Store credit exposure</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Available Store Credit</span>
                        <span class="drilldown-stat-val" style="color: #22c55e;">${formatCurrency(totalAvailCredit)}</span>
                        <span class="drilldown-stat-sub">Remaining buffer across accounts</span>
                    </div>
                </div>

                <div style="margin-top: 0.5rem;">
                    <h4 style="font-size: 0.95rem; margin-bottom: 0.6rem; color: var(--text-primary);">Customer Outstanding Balances (Sorted by Balance)</h4>
                    ${activeUdhaarCustomers.length === 0 ? `
                        <div class="drilldown-empty">
                            <div class="drilldown-empty-title" style="color: #22c55e;">No Outstanding Udhaar!</div>
                            <p style="font-size: 0.85rem; margin: 0.25rem 0 0 0;">All customer accounts are fully settled with zero active debt.</p>
                        </div>
                    ` : `
                        <div class="drilldown-table-wrap">
                            <table class="drilldown-table">
                                <thead>
                                    <tr>
                                        <th>Customer Name</th>
                                        <th>Customer Code</th>
                                        <th>Phone Verification</th>
                                        <th>Credit Limit</th>
                                        <th>Available Credit</th>
                                        <th>Current Udhaar Balance</th>
                                        <th style="text-align: right;">Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${activeUdhaarCustomers.map(c => {
                                        const avail = Math.max(0, (c.credit_limit || 0) - (c.current_udhaar_balance || 0));
                                        const hasPhone = !!c.phone;
                                        const phoneBadge = hasPhone
                                            ? `<span class="badge badge-ready" style="font-size: 0.72rem;">Verified (${escapeHtml(c.phone.slice(-4))})</span>`
                                            : `<span class="badge" style="background: rgba(148,163,184,0.15); font-size: 0.72rem;">Unverified</span>`;
                                        return `
                                            <tr>
                                                <td>
                                                    <strong>${escapeHtml(c.full_name)}</strong>
                                                    ${c.address_line ? `<br><small style="color: var(--text-secondary);">${escapeHtml(c.address_line)}</small>` : ''}
                                                </td>
                                                <td style="font-family: monospace; color: var(--accent); font-weight: 600;">${escapeHtml(c.customer_code || `CUST-${c.id}`)}</td>
                                                <td>${phoneBadge}</td>
                                                <td>${formatCurrency(c.credit_limit)}</td>
                                                <td style="color: #22c55e;">${formatCurrency(avail)}</td>
                                                <td style="font-weight: 700; color: #f59e0b;">${formatCurrency(c.current_udhaar_balance)}</td>
                                                <td style="text-align: right;">
                                                    <button type="button" class="btn btn-secondary btn-sm" onclick="jumpToCustomerLedger(${c.id})" style="padding: 0.25rem 0.65rem; font-size: 0.78rem;">
                                                        View Ledger &rarr;
                                                    </button>
                                                </td>
                                            </tr>
                                        `;
                                    }).join('')}
                                </tbody>
                            </table>
                        </div>
                    `}
                </div>
            `;
        } catch (err) {
            console.error("Error loading udhaar drill-down:", err);
            body.innerHTML = `<div class="drilldown-empty" style="color: #ef4444;">Error loading customer credit: ${escapeHtml(err.message)}</div>`;
        }
    }

    /**
     * 5. AI FORECAST READINESS Drill-Down
     */
    async function renderDrillDownForecastReady(titleEl, subtitleEl, iconEl, fullModuleBtn, moduleLabelEl, body) {
        titleEl.textContent = "AI Demand Forecasting & Predictive Stockout Intelligence";
        subtitleEl.textContent = "Projected 7-day and 30-day demand, reorder recommendations, and stockout risk ranking";
        iconEl.innerHTML = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#a855f7" stroke-width="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>`;
        moduleLabelEl.textContent = "Go to Demand Forecasting";

        fullModuleBtn.onclick = () => {
            if (typeof window.navigateTo === "function") {
                window.navigateTo("/forecast");
            } else if (typeof window.switchTab === "function") {
                window.switchTab("forecasting");
            }
        };

        try {
            // Support both /api/v1/forecasting and /api/v1/forecast routes
            const [overviewRes, productsRes] = await Promise.allSettled([
                authFetch("/api/v1/forecasting/summary")
                    .then(r => r.ok ? r.json() : authFetch("/api/v1/forecast/overview").then(r2 => r2.ok ? r2.json() : null)),
                authFetch("/api/v1/forecasting/all")
                    .then(r => r.ok ? r.json() : authFetch("/api/v1/forecast/products").then(r2 => r2.ok ? r2.json() : null))
            ]);

            const overview = overviewRes.status === "fulfilled" ? overviewRes.value : null;
            const fcData = productsRes.status === "fulfilled" ? productsRes.value : null;
            const products = fcData && Array.isArray(fcData.products) ? fcData.products : [];

            const totalProds = overview ? (overview.total_products || 0) : products.length;
            const eligibleProds = overview ? (overview.eligible_products_count || 0) : products.filter(p => p.status === "ELIGIBLE").length;
            const insufficientProds = overview ? (overview.insufficient_products_count || 0) : (totalProds - eligibleProds);
            const totalReorder = overview ? (overview.total_reorder_units_needed || 0) : products.reduce((s, p) => s + (p.suggested_reorder_qty || 0), 0);

            // Risk priority sorting
            const riskWeight = {
                "IMMEDIATE_ATTENTION": 1,
                "POTENTIAL_STOCKOUT": 2,
                "LOW_STOCK": 3,
                "SUFFICIENT": 4,
                "INSUFFICIENT_DATA": 5
            };

            const prioritizedProducts = [...products].sort((a, b) => {
                const wA = riskWeight[a.risk_level] || 99;
                const wB = riskWeight[b.risk_level] || 99;
                if (wA !== wB) return wA - wB;
                return (b.suggested_reorder_qty || 0) - (a.suggested_reorder_qty || 0);
            });

            const isEligible = eligibleProds > 0;
            const statusBadge = isEligible
                ? `<span class="badge badge-in-stock" style="font-size: 0.8rem; padding: 0.25rem 0.65rem;">ELIGIBLE</span>`
                : `<span class="badge badge-low-stock" style="font-size: 0.8rem; padding: 0.25rem 0.65rem;">INSUFFICIENT_DATA</span>`;

            body.innerHTML = `
                <div class="drilldown-summary-grid">
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Model Usability Status</span>
                        <div style="margin-top: 0.25rem;">${statusBadge}</div>
                        <span class="drilldown-stat-sub">${eligibleProds} of ${totalProds} products eligible</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Eligible vs Insufficient</span>
                        <span class="drilldown-stat-val" style="color: #a855f7;">${eligibleProds} / ${insufficientProds}</span>
                        <span class="drilldown-stat-sub">Requires &ge; 7 sales history days</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Stockout Attention Alerts</span>
                        <span class="drilldown-stat-val" style="color: ${((overview && overview.immediate_attention_count) || 0) > 0 ? '#ef4444' : '#22c55e'};">
                            ${((overview && overview.immediate_attention_count) || 0) + ((overview && overview.potential_stockout_count) || 0)}
                        </span>
                        <span class="drilldown-stat-sub">${(overview && overview.immediate_attention_count) || 0} immediate, ${(overview && overview.potential_stockout_count) || 0} potential</span>
                    </div>
                    <div class="drilldown-stat-card">
                        <span class="drilldown-stat-label">Recommended Reorder Units</span>
                        <span class="drilldown-stat-val" style="color: #38bdf8;">${totalReorder.toFixed(1)}</span>
                        <span class="drilldown-stat-sub">Optimal replenishment buffer</span>
                    </div>
                </div>

                <div style="margin-top: 0.5rem;">
                    <h4 style="font-size: 0.95rem; margin-bottom: 0.6rem; color: var(--text-primary);">Products Needing Reorder &amp; Risk Hierarchy</h4>
                    ${prioritizedProducts.length === 0 ? `
                        <div class="drilldown-empty">
                            <div class="drilldown-empty-title">No Forecast Data Available</div>
                            <p style="font-size: 0.85rem; margin: 0.25rem 0 0.75rem 0;">Historical sales records are required to generate demand predictions.</p>
                            <button type="button" class="btn btn-secondary btn-sm" onclick="navigateTo('/sales/import')">Import Historical Sales</button>
                        </div>
                    ` : `
                        <div class="drilldown-table-wrap">
                            <table class="drilldown-table">
                                <thead>
                                    <tr>
                                        <th>Product Name</th>
                                        <th>Current Stock</th>
                                        <th>7-Day Demand</th>
                                        <th>30-Day Demand</th>
                                        <th>Days Left</th>
                                        <th>Suggested Reorder</th>
                                        <th>Risk Level</th>
                                        <th style="text-align: right;">Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${prioritizedProducts.map(p => {
                                        let riskBadge = '';
                                        if (p.risk_level === "IMMEDIATE_ATTENTION") {
                                            riskBadge = `<span class="badge badge-out-stock" style="font-size: 0.72rem;">IMMEDIATE ATTENTION</span>`;
                                        } else if (p.risk_level === "POTENTIAL_STOCKOUT") {
                                            riskBadge = `<span class="badge" style="background: rgba(249, 115, 22, 0.2); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.35); font-size: 0.72rem;">POTENTIAL STOCKOUT</span>`;
                                        } else if (p.risk_level === "LOW_STOCK") {
                                            riskBadge = `<span class="badge badge-low-stock" style="font-size: 0.72rem;">LOW STOCK</span>`;
                                        } else if (p.risk_level === "SUFFICIENT") {
                                            riskBadge = `<span class="badge badge-in-stock" style="font-size: 0.72rem;">SUFFICIENT</span>`;
                                        } else {
                                            riskBadge = `<span class="badge" style="background: rgba(148,163,184,0.15); color: #94a3b8; font-size: 0.72rem;">INSUFFICIENT DATA</span>`;
                                        }

                                        const daysLeft = p.days_inventory_remaining !== null && p.days_inventory_remaining !== undefined
                                            ? `${p.days_inventory_remaining.toFixed(1)} days`
                                            : "N/A";

                                        return `
                                            <tr>
                                                <td>
                                                    <strong>${escapeHtml(p.product_name)}</strong>
                                                    <br><small style="color: var(--text-secondary);">${escapeHtml(p.category || 'General')}</small>
                                                </td>
                                                <td style="font-weight: 600;">${p.current_stock} ${escapeHtml(p.unit || '')}</td>
                                                <td>${(p.total_7d_demand || 0).toFixed(1)}</td>
                                                <td>${(p.total_30d_demand || 0).toFixed(1)}</td>
                                                <td style="font-weight: 600; color: ${(p.days_inventory_remaining || 99) <= 3 ? '#ef4444' : 'inherit'};">${daysLeft}</td>
                                                <td style="font-weight: 700; color: ${(p.suggested_reorder_qty || 0) > 0 ? '#38bdf8' : 'inherit'};">
                                                    ${(p.suggested_reorder_qty || 0) > 0 ? `+${(p.suggested_reorder_qty || 0).toFixed(1)} ${escapeHtml(p.unit || '')}` : '—'}
                                                </td>
                                                <td>${riskBadge}</td>
                                                <td style="text-align: right;">
                                                    <button type="button" class="btn btn-secondary btn-sm" onclick="openRestockFromDashboard(${p.product_id}, '${escapeHtml(p.product_name)}', ${p.current_stock}, '${escapeHtml(p.unit || '')}')" style="padding: 0.25rem 0.65rem; font-size: 0.78rem;">
                                                        Restock
                                                    </button>
                                                </td>
                                            </tr>
                                        `;
                                    }).join('')}
                                </tbody>
                            </table>
                        </div>
                    `}
                </div>
            `;
        } catch (err) {
            console.error("Error loading forecast readiness drill-down:", err);
            body.innerHTML = `<div class="drilldown-empty" style="color: #ef4444;">Error loading forecasting readiness: ${escapeHtml(err.message)}</div>`;
        }
    }

    function jumpToCustomerLedger(customerId) {
        if (typeof window.switchTab === "function") {
            window.switchTab("udhaar");
        } else if (typeof window.navigateTo === "function") {
            window.navigateTo("/customers");
        }
        setTimeout(() => {
            if (typeof window.selectUdhaarCustomer === "function") {
                window.selectUdhaarCustomer(customerId);
            }
        }, 80);
    }

    // ==============================================================================
    // Main Dashboard Data Loading & Rendering
    // ==============================================================================

    async function loadMainDashboard() {
        const lastUpdatedEl = document.getElementById("dash-last-updated");
        if (lastUpdatedEl) {
            lastUpdatedEl.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
        }

        try {
            const [invRes, lowStockRes, billsRes, custRes, forecastRes, dailyRes, forecastProdsRes] = await Promise.allSettled([
                authFetch("/api/v1/inventory/summary").then(r => r.ok ? r.json() : null),
                authFetch("/api/v1/inventory/low-stock").then(r => r.ok ? r.json() : []),
                authFetch("/api/v1/billing/bills?limit=8").then(r => r.ok ? r.json() : []),
                authFetch("/api/v1/customers").then(r => r.ok ? r.json() : []),
                authFetch("/api/v1/forecast/overview").then(r => r.ok ? r.json() : null),
                authFetch("/api/v1/analytics/sales/daily").then(r => r.ok ? r.json() : null),
                authFetch("/api/v1/forecast/products").then(r => r.ok ? r.json() : authFetch("/api/v1/forecasting/all").then(r2 => r2.ok ? r2.json() : null))
            ]);

            // Build forecast coverage lookup map
            const forecastMap = {};
            if (forecastProdsRes.status === "fulfilled" && forecastProdsRes.value) {
                const prods = forecastProdsRes.value.products || forecastProdsRes.value || [];
                if (Array.isArray(prods)) {
                    prods.forEach(p => {
                        forecastMap[p.product_id || p.id] = p;
                    });
                }
            }

            // 1. Inventory Valuation & Product Counts
            if (invRes.status === "fulfilled" && invRes.value) {
                const inv = invRes.value;
                const valEl = document.getElementById("dash-inventory-val");
                const itemsEl = document.getElementById("dash-inventory-items");
                const lowCountEl = document.getElementById("dash-low-stock-count");
                const outCountEl = document.getElementById("dash-out-stock-count");

                if (valEl) valEl.textContent = formatCurrency(inv.total_inventory_value || 0);
                if (itemsEl) itemsEl.textContent = `${inv.total_products || 0} catalog items`;
                if (lowCountEl) lowCountEl.textContent = inv.low_stock_count || 0;
                if (outCountEl) outCountEl.textContent = `${inv.out_of_stock_count || 0} items out of stock`;
            }

            // 2. Today's Completed Sales & Order Counts
            let todayRevenue = 0;
            let todayOrders = 0;

            if (dailyRes.status === "fulfilled" && dailyRes.value) {
                todayRevenue = dailyRes.value.total_revenue || 0;
                todayOrders = dailyRes.value.transaction_count || 0;
            } else if (billsRes.status === "fulfilled" && billsRes.value) {
                const bills = billsRes.value || [];
                const todayStr = new Date().toISOString().slice(0, 10);
                bills.forEach(b => {
                    if (b.created_at && b.created_at.startsWith(todayStr)) {
                        todayRevenue += (b.total_amount || 0);
                        todayOrders += 1;
                    }
                });
            }

            const salesEl = document.getElementById("dash-today-sales");
            const ordersEl = document.getElementById("dash-today-orders");
            if (salesEl) salesEl.textContent = formatCurrency(todayRevenue);
            if (ordersEl) ordersEl.textContent = `${todayOrders} completed ${todayOrders === 1 ? 'bill' : 'bills'} today`;

            // 3. Render Top 5 Recent Transactions
            if (billsRes.status === "fulfilled" && billsRes.value) {
                latestRecentSalesCount = billsRes.value.length;
                renderDashboardRecentSales(billsRes.value || []);
            }

            // 4. Outstanding Udhaar & Customer Ledger
            if (custRes.status === "fulfilled" && custRes.value) {
                const customers = custRes.value || [];
                let totalUdhaar = 0;
                let activeUdhaarCusts = 0;

                customers.forEach(c => {
                    const bal = c.current_udhaar_balance || 0;
                    totalUdhaar += bal;
                    if (bal > 0) activeUdhaarCusts += 1;
                });

                const udhaarEl = document.getElementById("dash-total-udhaar");
                const custCountEl = document.getElementById("dash-udhaar-cust-count");
                if (udhaarEl) udhaarEl.textContent = formatCurrency(totalUdhaar);
                if (custCountEl) custCountEl.textContent = `${activeUdhaarCusts} with active balance (${customers.length} total)`;
            }

            // 5. AI Demand Forecasting Readiness
            if (forecastRes.status === "fulfilled" && forecastRes.value) {
                const fc = forecastRes.value;
                const readyEl = document.getElementById("dash-forecast-ready");
                const reorderEl = document.getElementById("dash-reorder-units");

                if (readyEl) readyEl.textContent = `${fc.eligible_products_count || 0} / ${fc.total_products || 0}`;
                if (reorderEl) reorderEl.textContent = `${(fc.total_reorder_units_needed || 0).toFixed(1)} units recommended reorder`;
            }

            // 6. Render Top 5 Low Stock Items with Plain-English Coverage Badges & 1-Click Buy
            if (lowStockRes.status === "fulfilled") {
                const lowItems = lowStockRes.value || [];
                latestLowStockCount = lowItems.length;
                renderDashboardLowStock(lowItems, forecastMap);
            }

            // 7. Load Dashboard Analytics & Visualizations (Sales trend, Top 5 products, Payment breakdown, Stock health)
            await loadDashboardCharts();

            updateCollapsibleBadges();

        } catch (err) {
            console.error("Dashboard metric loading error:", err);
        }
    }

    function renderDashboardLowStock(items, forecastMap = {}) {
        const container = document.getElementById("dash-low-stock-container");
        if (!container) return;

        if (!items || items.length === 0) {
            container.innerHTML = `
                <div class="empty-state-card" style="text-align: center; padding: 2rem 1rem; color: var(--text-secondary);">
                    <strong style="color: #22c55e;">Inventory Healthy</strong>
                    <p style="font-size: 0.85rem; margin-top: 0.25rem;">All products are currently stocked above their minimum thresholds.</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="dash-feed-list">
                ${items.slice(0, 5).map(it => {
                    const fc = forecastMap[it.id];
                    let coverageBadge = '';
                    if (it.stock_quantity <= 0) {
                        coverageBadge = `<span class="badge badge-out-stock" style="font-size: 0.72rem;">Out of stock</span>`;
                    } else if (fc && fc.days_inventory_remaining !== undefined && fc.days_inventory_remaining !== null) {
                        const days = Number(fc.days_inventory_remaining);
                        coverageBadge = `<span class="badge badge-low-stock" style="font-size: 0.72rem;">${days.toFixed(1)} days left</span>`;
                    } else {
                        coverageBadge = `<span class="badge badge-low-stock" style="font-size: 0.72rem;">Low Stock</span>`;
                    }

                    const buyQty = Math.max(1, Math.ceil(it.shortage_quantity || 10));

                    return `
                        <div class="dash-feed-item">
                            <div class="dash-feed-left">
                                <span class="dash-feed-title">${escapeHtml(it.name)} ${it.hindi_name ? `<small style="color: var(--text-secondary); font-weight: normal;">(${escapeHtml(it.hindi_name)})</small>` : ''}</span>
                                <span class="dash-feed-sub">
                                    Stock: <strong style="color: ${it.stock_quantity <= 0 ? '#ef4444' : '#f59e0b'};">${it.stock_quantity} ${escapeHtml(it.unit || '')}</strong> 
                                    &bull; Min: ${it.min_stock_threshold}
                                </span>
                            </div>
                            <div class="dash-feed-right" style="display: flex; align-items: center; gap: 8px;">
                                ${coverageBadge}
                                <button type="button" class="btn btn-primary btn-sm" style="padding: 0.25rem 0.65rem; font-size: 0.78rem; font-weight: 600; white-space: nowrap;" onclick="quickRestockFromDashboard(${it.id}, ${buyQty}, '${escapeHtml(it.unit || '')}')">
                                    Buy +${buyQty} ${escapeHtml(it.unit || '')}
                                </button>
                            </div>
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    }

    function renderDashboardRecentSales(bills) {
        const container = document.getElementById("dash-recent-sales-container");
        if (!container) return;

        if (!bills || bills.length === 0) {
            container.innerHTML = `
                <div class="dash-recent-sales-shortcuts" style="display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap;">
                    <button type="button" class="btn btn-primary btn-sm" onclick="navigateTo('/billing')" style="font-size: 0.78rem; padding: 4px 10px;">
                        + New Voice Bill
                    </button>
                    <button type="button" class="btn btn-secondary btn-sm" onclick="openAddProductFromDashboard()" style="font-size: 0.78rem; padding: 4px 10px;">
                        + Add Inventory Item
                    </button>
                    <button type="button" class="btn btn-secondary btn-sm" onclick="navigateTo('/customers')" style="font-size: 0.78rem; padding: 4px 10px;">
                        + Settle Udhaar
                    </button>
                </div>
                <div class="empty-state-card" style="text-align: center; padding: 1.5rem 1rem; color: var(--text-secondary);">
                    <strong style="color: var(--text-primary);">No Recent Sales</strong>
                    <p style="font-size: 0.85rem; margin-top: 0.25rem;">Completed transactions will appear here automatically.</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="dash-recent-sales-shortcuts" style="display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap;">
                <button type="button" class="btn btn-primary btn-sm" onclick="navigateTo('/billing')" style="font-size: 0.78rem; padding: 4px 10px;">
                    + New Voice Bill
                </button>
                <button type="button" class="btn btn-secondary btn-sm" onclick="openAddProductFromDashboard()" style="font-size: 0.78rem; padding: 4px 10px;">
                    + Add Inventory Item
                </button>
                <button type="button" class="btn btn-secondary btn-sm" onclick="navigateTo('/customers')" style="font-size: 0.78rem; padding: 4px 10px;">
                    + Settle Udhaar
                </button>
            </div>
            <div class="dash-feed-list">
                ${bills.slice(0, 5).map(b => {
                    const dateObj = new Date(b.created_at);
                    const timeStr = !isNaN(dateObj.getTime()) ? dateObj.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : '';
                    const rawMode = (b.payment_mode || 'CASH').toUpperCase();
                    const payBadgeClass = rawMode === 'CASH' ? 'badge-in-stock' : (rawMode === 'UPI' ? 'badge-ready' : 'badge-low-stock');
                    const custName = b.customer_name ? ` &bull; ${escapeHtml(b.customer_name)}` : '';
                    const itemCount = b.items ? b.items.length : 0;
                    
                    return `
                        <div class="dash-feed-item">
                            <div class="dash-feed-left">
                                <span class="dash-feed-title">${escapeHtml(b.bill_number)}</span>
                                <span class="dash-feed-sub">
                                    ${timeStr} &bull; ${itemCount} ${itemCount === 1 ? 'item' : 'items'}${custName}
                                </span>
                            </div>
                            <div class="dash-feed-right">
                                <span class="badge ${payBadgeClass}" style="font-size: 0.72rem;">${rawMode}</span>
                                <span class="dash-feed-amount">${formatCurrency(b.total_amount || 0)}</span>
                            </div>
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    }

    async function quickRestockFromDashboard(productId, quantity, unit = "") {
        try {
            const res = await authFetch("/api/v1/inventory/restock", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    product_id: productId,
                    quantity_delta: quantity,
                    notes: "1-Click Dashboard Quick Restock"
                })
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || "Restock failed");
            }
            const data = await res.json();
            const msg = `Restocked +${quantity} ${unit} for ${data.name || 'product'}!`;
            if (typeof window.showToast === "function") {
                window.showToast(msg, "success");
            }
            if (window.AppEvents) {
                window.AppEvents.emit("inventory-updated", data);
                window.AppEvents.emit("products-updated", data);
            }
            window.dispatchEvent(new CustomEvent("inventory-updated", { detail: data }));
            window.dispatchEvent(new CustomEvent("products-updated", { detail: data }));
            debouncedLoadMainDashboard();
        } catch (err) {
            console.error("Dashboard quick restock error:", err);
            if (typeof window.showToast === "function") {
                window.showToast(`Restock error: ${err.message}`, "error");
            } else {
                alert(`Restock error: ${err.message}`);
            }
        }
    }

    function openAddProductFromDashboard() {
        if (typeof window.switchTab === "function") {
            window.switchTab("inventory");
        } else if (typeof window.navigateTo === "function") {
            window.navigateTo("/inventory");
        }
        setTimeout(() => {
            if (typeof window.openAddProductModal === "function") {
                window.openAddProductModal();
            }
        }, 80);
    }

    async function openRestockFromDashboard(productId, productName, currentStock, unit) {
        if (typeof window.switchTab === "function") {
            window.switchTab('inventory');
        }
        if (!window.currentProducts || window.currentProducts.length === 0) {
            if (typeof window.loadProducts === "function") {
                await window.loadProducts();
            }
        }
        if (typeof window.openRestockModal === 'function') {
            window.openRestockModal(productId);
        }
    }

    async function checkHealth() {
        const statusBadge = document.getElementById("system-status");
        const statusText = document.getElementById("status-text");
        const avatarDot = document.getElementById("avatar-status-dot");
        const dropdownDot = document.getElementById("dropdown-status-dot");
        const dropdownText = document.getElementById("dropdown-status-text");
        const versionEl = document.getElementById("backend-version");
        const envEl = document.getElementById("backend-env");
        const dbEl = document.getElementById("backend-db");

        try {
            const response = await fetch("/api/v1/health");
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            const isHealthy = data.status === "healthy";

            if (isHealthy) {
                // Online state: Avatar dot green, dropdown dot green, header warning badge hidden
                if (avatarDot) {
                    avatarDot.className = "avatar-status-dot dot-online";
                    avatarDot.title = "System Online: API & Database Connected";
                }
                if (dropdownDot) {
                    dropdownDot.className = "status-dot-mini dot-online";
                }
                if (dropdownText) {
                    dropdownText.textContent = "System & DB Online";
                }
                if (statusBadge) {
                    statusBadge.style.display = "none";
                    statusBadge.className = "status-badge status-healthy compact-warning-badge";
                }
                if (statusText) {
                    statusText.textContent = "API & DB Connected";
                }
            } else {
                // Degraded state: Avatar dot red, dropdown dot red, reveal compact warning badge
                if (avatarDot) {
                    avatarDot.className = "avatar-status-dot dot-offline";
                    avatarDot.title = `System Degraded: ${data.database || "Database Issue"}`;
                }
                if (dropdownDot) {
                    dropdownDot.className = "status-dot-mini dot-offline";
                }
                if (dropdownText) {
                    dropdownText.textContent = `Degraded (${data.database || "DB Issue"})`;
                }
                if (statusBadge) {
                    statusBadge.style.display = "inline-flex";
                    statusBadge.className = "status-badge status-checking compact-warning-badge";
                }
                if (statusText) {
                    statusText.textContent = `Degraded (${data.database || "DB"})`;
                }
            }

            if (versionEl) versionEl.textContent = `v${data.version}`;
            if (envEl) envEl.textContent = data.environment;
            if (dbEl) dbEl.textContent = data.database;
        } catch (err) {
            // Disconnected / Offline state: Avatar dot red, dropdown dot red, reveal compact warning badge
            if (avatarDot) {
                avatarDot.className = "avatar-status-dot dot-offline";
                avatarDot.title = "System Offline: Disconnected";
            }
            if (dropdownDot) {
                dropdownDot.className = "status-dot-mini dot-offline";
            }
            if (dropdownText) {
                dropdownText.textContent = "Offline / Reconnecting...";
            }
            if (statusBadge) {
                statusBadge.style.display = "inline-flex";
                statusBadge.className = "status-badge status-error compact-warning-badge";
            }
            if (statusText) {
                statusText.textContent = "Offline / Reconnecting...";
            }
            if (versionEl) versionEl.textContent = "Offline";
            if (envEl) envEl.textContent = "Offline";
            if (dbEl) dbEl.textContent = "Disconnected";
        }
    }

    const DashboardModule = {
        init: initDashboard,
        loadMainDashboard,
        debouncedLoadMainDashboard,
        renderDashboardLowStock,
        renderDashboardRecentSales,
        openRestockFromDashboard,
        quickRestockFromDashboard,
        openAddProductFromDashboard,
        playDailyVoiceBriefing,
        checkHealth,
        // Collapsible Section State & Handlers
        isLowStockExpanded: () => isLowStockExpanded,
        isRecentSalesExpanded: () => isRecentSalesExpanded,
        setLowStockSectionExpanded,
        setRecentSalesSectionExpanded,
        toggleLowStockSection,
        toggleRecentSalesSection,
        handleCollapsibleKeyDown,
        toggleAllDashboardPanels,
        // Interactive KPI Drill-Down Handlers
        openKpiDrillDown,
        closeKpiDrillDown,
        onKpiTodaySalesClick,
        onKpiInventoryValClick,
        onKpiLowStockClick,
        onKpiTotalUdhaarClick,
        onKpiForecastReadyClick,
        handleKpiCardKeyDown,
        jumpToCustomerLedger,
        // Dashboard Charts
        loadDashboardCharts,
        switchDashboardHorizon,
        toggleTopProductsMetric
    };

    // ==============================================================================
    // Dashboard Analytics & Business Visualizations (Phase 1)
    // ==============================================================================

    let currentDashboardHorizon = 7;
    let topProductsMetric = 'units';
    let cachedDashboardData = null;

    function switchDashboardHorizon(days) {
        currentDashboardHorizon = parseInt(days) || 7;
        const btn7 = document.getElementById("btn-dash-horizon-7d");
        const btn30 = document.getElementById("btn-dash-horizon-30d");
        const subEl = document.getElementById("dash-sales-trend-sub");

        if (btn7) btn7.classList.toggle("active", currentDashboardHorizon === 7);
        if (btn30) btn30.classList.toggle("active", currentDashboardHorizon === 30);
        if (subEl) subEl.textContent = `Daily revenue over last ${currentDashboardHorizon} days`;

        loadDashboardCharts(currentDashboardHorizon);
    }

    function toggleTopProductsMetric(metric) {
        topProductsMetric = metric === 'revenue' ? 'revenue' : 'units';
        const btnU = document.getElementById("btn-top-by-units");
        const btnR = document.getElementById("btn-top-by-revenue");
        if (btnU) btnU.classList.toggle("active", topProductsMetric === 'units');
        if (btnR) btnR.classList.toggle("active", topProductsMetric === 'revenue');

        if (cachedDashboardData) {
            renderTopProductsChart(cachedDashboardData);
        }
    }

    async function loadDashboardCharts(days = currentDashboardHorizon) {
        if (!window.ApnaCharts) return;

        try {
            const res = await authFetch(`/api/v1/analytics/dashboard/charts?days=${days}`);
            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || `Server returned ${res.status}`);
            }
            const data = await res.json();
            cachedDashboardData = data;

            // Summary Badges
            const trendTotal = document.getElementById("dash-trend-total");
            if (trendTotal) trendTotal.textContent = window.ApnaCharts.formatRupees(data.total_revenue || 0);

            const payCount = document.getElementById("dash-payment-count");
            if (payCount) payCount.textContent = `${data.total_transactions || 0} bills`;

            const stockBadge = document.getElementById("dash-stock-total-badge");
            if (stockBadge && data.stock_overview) {
                stockBadge.textContent = `${data.stock_overview.total_products || 0} items`;
            }

            // 1. Sales Trend Line Chart
            renderSalesTrendChart(data);

            // 2. Top-Selling Products Horizontal Bar Chart
            renderTopProductsChart(data);

            // 3. Payment Breakdown Donut Chart
            renderPaymentBreakdownChart(data);

            // 4. Stock Health Donut Chart
            renderStockHealthChart(data);

        } catch (err) {
            console.error("Failed to load dashboard charts:", err);
            const trendWrap = document.getElementById("dash-sales-trend-wrap");
            if (trendWrap) window.ApnaCharts.showEmptyState(trendWrap, "Sales Analytics Unavailable", err.message);
        }
    }

    function renderSalesTrendChart(data) {
        const wrap = document.getElementById("dash-sales-trend-wrap");
        const trend = data.sales_trend || [];
        if (trend.length === 0) {
            window.ApnaCharts.showEmptyState(wrap, "No Sales Data", "No sales records recorded in this timeframe.");
            return;
        }

        const labels = trend.map(d => d.label);
        const revenues = trend.map(d => d.revenue);

        window.ApnaCharts.createChart("dash-sales-trend-canvas", {
            type: "line",
            data: {
                labels: labels,
                datasets: [{
                    label: "Daily Revenue",
                    data: revenues,
                    borderColor: "#38bdf8",
                    backgroundColor: "rgba(56, 189, 248, 0.12)",
                    fill: true,
                    tension: 0.35,
                    borderWidth: 2.5,
                    pointBackgroundColor: "#0284c7",
                    pointBorderColor: "#ffffff",
                    pointRadius: trend.length > 15 ? 2 : 4,
                    pointHoverRadius: 6
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

    function renderTopProductsChart(data) {
        const wrap = document.getElementById("dash-top-products-wrap");
        const isUnits = topProductsMetric === "units";
        const items = isUnits ? (data.top_by_units || []) : (data.top_by_revenue || []);

        if (items.length === 0) {
            window.ApnaCharts.showEmptyState(wrap, "No Completed Sales", "Start billing to generate top product rankings.");
            return;
        }

        const labels = items.map(p => p.name.length > 20 ? p.name.slice(0, 18) + "…" : p.name);
        const values = items.map(p => isUnits ? p.units_sold : p.revenue);

        window.ApnaCharts.createChart("dash-top-products-canvas", {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: isUnits ? "Units Sold" : "Revenue",
                    data: values,
                    backgroundColor: isUnits ? "#22c55e" : "#38bdf8",
                    borderRadius: 4,
                    maxBarThickness: 24
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

    function renderPaymentBreakdownChart(data) {
        const wrap = document.getElementById("dash-payment-wrap");
        const list = data.payment_breakdown || [];
        const nonZero = list.filter(item => item.total > 0 || item.count > 0);

        if (nonZero.length === 0) {
            window.ApnaCharts.showEmptyState(wrap, "No Payments Recorded", "Completed sales will populate payment distribution.");
            return;
        }

        const labels = nonZero.map(p => p.label);
        const amounts = nonZero.map(p => p.total);
        const colors = nonZero.map(p => {
            if (p.mode === "CASH") return "#22c55e";
            if (p.mode === "UPI") return "#38bdf8";
            if (p.mode === "UDHAAR") return "#f59e0b";
            return "#94a3b8";
        });

        window.ApnaCharts.createChart("dash-payment-breakdown-canvas", {
            type: "doughnut",
            data: {
                labels: labels,
                datasets: [{
                    data: amounts,
                    backgroundColor: colors,
                    borderColor: "#334155",
                    borderWidth: 2,
                    hoverOffset: 4
                }]
            },
            options: {
                ...window.ApnaCharts.getBaseOptions(),
                cutout: "62%",
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { color: "#94a3b8", font: { size: 11 }, padding: 8, boxWidth: 10 }
                    },
                    tooltip: {
                        callbacks: {
                            label: ctx => {
                                const item = nonZero[ctx.dataIndex];
                                return `${item.label}: ${window.ApnaCharts.formatRupees(item.total)} (${item.percentage}%)`;
                            }
                        }
                    }
                }
            }
        });
    }

    function renderStockHealthChart(data) {
        const wrap = document.getElementById("dash-stock-health-wrap");
        const stock = data.stock_overview;
        if (!stock || stock.total_products === 0) {
            window.ApnaCharts.showEmptyState(wrap, "No Products in Catalog", "Add catalog items to view stock distribution.");
            return;
        }

        const labels = ["Healthy Stock", "Low Stock Alert", "Out of Stock"];
        const counts = [stock.healthy, stock.low_stock, stock.out_of_stock];
        const colors = ["#10b981", "#f59e0b", "#ef4444"];

        window.ApnaCharts.createChart("dash-stock-health-canvas", {
            type: "doughnut",
            data: {
                labels: labels,
                datasets: [{
                    data: counts,
                    backgroundColor: colors,
                    borderColor: "#334155",
                    borderWidth: 2,
                    hoverOffset: 4
                }]
            },
            options: {
                ...window.ApnaCharts.getBaseOptions(),
                cutout: "62%",
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { color: "#94a3b8", font: { size: 11 }, padding: 8, boxWidth: 10 }
                    },
                    tooltip: {
                        callbacks: {
                            label: ctx => `${labels[ctx.dataIndex]}: ${ctx.raw} items`
                        }
                    }
                }
            }
        });
    }

    // Global exports for inline HTML event handlers & cross-module interoperability
    window.DashboardModule = DashboardModule;
    window.initMainDashboard = initDashboard;
    window.initDashboard = initDashboard;
    window.loadMainDashboard = loadMainDashboard;
    window.debouncedLoadMainDashboard = debouncedLoadMainDashboard;
    window.openRestockFromDashboard = openRestockFromDashboard;
    window.quickRestockFromDashboard = quickRestockFromDashboard;
    window.openAddProductFromDashboard = openAddProductFromDashboard;
    window.playDailyVoiceBriefing = playDailyVoiceBriefing;
    window.checkHealth = checkHealth;

    window.toggleLowStockSection = toggleLowStockSection;
    window.toggleRecentSalesSection = toggleRecentSalesSection;
    window.setLowStockSectionExpanded = setLowStockSectionExpanded;
    window.setRecentSalesSectionExpanded = setRecentSalesSectionExpanded;
    window.handleCollapsibleKeyDown = handleCollapsibleKeyDown;
    window.toggleAllDashboardPanels = toggleAllDashboardPanels;

    window.openKpiDrillDown = openKpiDrillDown;
    window.closeKpiDrillDown = closeKpiDrillDown;
    window.onKpiTodaySalesClick = onKpiTodaySalesClick;
    window.onKpiInventoryValClick = onKpiInventoryValClick;
    window.onKpiLowStockClick = onKpiLowStockClick;
    window.onKpiTotalUdhaarClick = onKpiTotalUdhaarClick;
    window.onKpiForecastReadyClick = onKpiForecastReadyClick;
    window.handleKpiCardKeyDown = handleKpiCardKeyDown;
    window.jumpToCustomerLedger = jumpToCustomerLedger;

    window.switchDashboardHorizon = switchDashboardHorizon;
    window.toggleTopProductsMetric = toggleTopProductsMetric;
    window.loadDashboardCharts = loadDashboardCharts;

})(window);
