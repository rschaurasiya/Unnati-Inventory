/**
 * Demand Forecasting & AI Intelligence Module
 * Upgraded with Interactive KPI Cards, Clean Action Bar, Sensible Rounding,
 * Single-Row Pagination (10, 20, 30 rows), Real-Time Stock Reorder Modal,
 * and Cross-System Global Synchronization.
 */

(function(window) {
    'use strict';

    // Module State
    let _allForecastProducts = [];
    let _urgentProducts = [];
    let _activeKpiFilter = null; // 'reorder', 'low-stock', 'enough-stock', 'units-to-buy', or null
    let _fcCurrentPage = 1;
    let _fcPageSize = 10;
    let _urgentCurrentPage = 1;
    const _urgentPageSize = 10;
    let _currentForecastProductId = null;
    let _currentReorderProduct = null;
    let _fcSelectedProductId = null;
    let _fcSelectedHorizon = 7;

    /**
     * Sensibly rounds restock & suggested purchase quantities:
     * Discrete units (packet, piece, bottle, box, pkt, pcs, unit) -> Math.ceil
     * Weight/volume (kg, litre, gm) -> clean integer or 0.5 increments
     */
    function formatRestockQuantity(qty, unit) {
        if (!qty || qty <= 0) {
            return { num: 0, text: '0', unit: unit || '', full: `0 ${unit || ''}`.trim() };
        }

        const rawUnit = (unit || '').toLowerCase().trim();
        const isDiscrete = ['packet', 'packets', 'pkt', 'piece', 'pieces', 'pcs', 'bottle', 'bottles', 'box', 'boxes', 'unit', 'units', 'can', 'cans', 'tin', 'tins', 'item', 'items', 'pouch', 'pouches'].some(d => rawUnit.includes(d));

        let cleanNum;
        if (isDiscrete || !rawUnit) {
            cleanNum = Math.ceil(qty);
        } else if (rawUnit.includes('kg') || rawUnit.includes('kilo') || rawUnit.includes('litre') || rawUnit.includes('liter') || rawUnit.includes('ltr') || rawUnit.includes('gm') || rawUnit.includes('gram')) {
            cleanNum = Math.ceil(qty * 2) / 2;
            if (Number.isInteger(cleanNum)) {
                cleanNum = Math.round(cleanNum);
            }
        } else {
            cleanNum = Math.ceil(qty);
        }

        // Friendly pluralization
        let displayUnit = unit || '';
        if (cleanNum > 1) {
            if (rawUnit === 'packet' || rawUnit === 'pkt') displayUnit = 'packets';
            else if (rawUnit === 'piece' || rawUnit === 'pc') displayUnit = 'pieces';
            else if (rawUnit === 'bottle') displayUnit = 'bottles';
            else if (rawUnit === 'box') displayUnit = 'boxes';
            else if (rawUnit === 'unit') displayUnit = 'units';
            else if (rawUnit === 'can') displayUnit = 'cans';
            else if (rawUnit === 'pouch') displayUnit = 'pouches';
        } else if (cleanNum === 1) {
            if (rawUnit === 'packets') displayUnit = 'packet';
            else if (rawUnit === 'pieces') displayUnit = 'piece';
            else if (rawUnit === 'bottles') displayUnit = 'bottle';
            else if (rawUnit === 'boxes') displayUnit = 'box';
            else if (rawUnit === 'units') displayUnit = 'unit';
        }

        const formattedText = cleanNum.toLocaleString('en-IN');
        return {
            num: cleanNum,
            text: formattedText,
            unit: displayUnit,
            full: `${formattedText} ${displayUnit}`.trim()
        };
    }

    /**
     * Clean stock quantity formatting
     */
    function formatStockQuantity(qty, unit) {
        const val = Number(qty) || 0;
        const rawUnit = (unit || '').toLowerCase().trim();
        const isDiscrete = ['packet', 'packets', 'pkt', 'piece', 'pieces', 'pcs', 'bottle', 'bottles', 'box', 'boxes', 'unit', 'units', 'can', 'cans', 'tin', 'tins', 'item', 'items', 'pouch', 'pouches'].some(d => rawUnit.includes(d));

        let cleanText;
        if (isDiscrete || !rawUnit) {
            cleanText = Math.round(val).toLocaleString('en-IN');
        } else {
            cleanText = Number.isInteger(val) ? val.toLocaleString('en-IN') : val.toFixed(1);
        }

        let displayUnit = unit || '';
        if (val > 1) {
            if (rawUnit === 'packet' || rawUnit === 'pkt') displayUnit = 'packets';
            else if (rawUnit === 'piece' || rawUnit === 'pc') displayUnit = 'pieces';
            else if (rawUnit === 'bottle') displayUnit = 'bottles';
            else if (rawUnit === 'box') displayUnit = 'boxes';
            else if (rawUnit === 'unit') displayUnit = 'units';
        }

        return {
            num: val,
            text: cleanText,
            unit: displayUnit,
            full: `${cleanText} ${displayUnit}`.trim()
        };
    }

    /**
     * AI Voice Briefing Action
     */
    async function toggleAiVoiceBriefing() {
        const briefingBtn = document.getElementById("btn-voice-briefing");
        const iconEl = document.getElementById("voice-briefing-icon");
        const labelEl = document.getElementById("voice-briefing-label");

        // If already speaking, clicking toggles and stops playback
        if (window.ElevenLabsVoice && window.ElevenLabsVoice.isPlaying()) {
            window.ElevenLabsVoice.stop();
            resetBriefingButtonUI();
            return;
        }

        // Set visual "Speaking..." wave/spinner state
        if (briefingBtn) {
            briefingBtn.classList.add("speaking");
        }
        if (labelEl) labelEl.textContent = "Speaking Briefing...";

        // Ensure live forecast data is loaded
        if (!_allForecastProducts || _allForecastProducts.length === 0) {
            try {
                await loadForecastingDashboard(false);
            } catch (loadErr) {
                console.warn("Forecast load before briefing warning:", loadErr);
            }
        }

        // Calculate live metrics
        let reorderCount = 0;
        let lowStockCount = 0;
        if (_allForecastProducts && _allForecastProducts.length > 0) {
            _allForecastProducts.forEach(p => {
                const rq = getProductReorderQty(p);
                if (p.risk_level === "IMMEDIATE_ATTENTION" || p.risk_level === "POTENTIAL_STOCKOUT" || rq > 0) {
                    reorderCount++;
                }
                if (p.risk_level === "LOW_STOCK" || p.risk_level === "IMMEDIATE_ATTENTION") {
                    lowStockCount++;
                }
            });
        }

        // Determine top priority products to buy today
        const priorityList = (_urgentProducts && _urgentProducts.length > 0)
            ? _urgentProducts
            : (_allForecastProducts || []).filter(p => getProductReorderQty(p) > 0);

        const topNames = priorityList
            .map(p => (p.product_name || p.name || "").trim())
            .filter(Boolean)
            .slice(0, 2);

        let briefingSentence2 = "All staple inventory items have sufficient stock.";
        if (topNames.length === 2) {
            briefingSentence2 = `Top priority items to buy today are ${topNames[0]} and ${topNames[1]}.`;
        } else if (topNames.length === 1) {
            briefingSentence2 = `Top priority item to buy today is ${topNames[0]}.`;
        }

        const speechText = `Namaste! Currently, ${reorderCount} products need immediate reorder and ${lowStockCount} products are low in stock. ${briefingSentence2}`;

        // Play via ElevenLabs with force: true (plays even if global audio toggle is muted)
        if (typeof window.speakWithElevenLabs === "function") {
            const played = await window.speakWithElevenLabs(speechText, { force: true });
            if (!played) {
                resetBriefingButtonUI();
            }
        } else {
            resetBriefingButtonUI();
        }
    }

    function resetBriefingButtonUI() {
        const briefingBtn = document.getElementById("btn-voice-briefing");
        const iconEl = document.getElementById("voice-briefing-icon");
        const labelEl = document.getElementById("voice-briefing-label");

        if (briefingBtn) briefingBtn.classList.remove("speaking");
        if (labelEl) labelEl.textContent = "AI Voice Briefing";
    }

    /**
     * Initialize Module Events & Listeners
     */
    function initForecastingModule() {
        // AI Voice Briefing Action Button
        const briefingBtn = document.getElementById("btn-voice-briefing");
        if (briefingBtn) {
            briefingBtn.addEventListener("click", toggleAiVoiceBriefing);
        }

        // Listen for speech stopped to restore button UI automatically
        window.addEventListener("elevenlabs-speech-stopped", () => {
            resetBriefingButtonUI();
        });

        // Recalculate Forecasts Action Button
        const refreshBtn = document.getElementById("btn-refresh-forecasts") || document.getElementById("btn-refresh-forecast");
        if (refreshBtn) {
            refreshBtn.addEventListener("click", () => {
                loadForecastingDashboard(true);
            });
        }

        // Filter Controls
        const statusFilter = document.getElementById("fc-filter-status");
        if (statusFilter) {
            statusFilter.addEventListener("change", () => {
                _fcCurrentPage = 1;
                filterForecastProductsTable();
            });
        }

        const categoryFilter = document.getElementById("fc-filter-category");
        if (categoryFilter) {
            categoryFilter.addEventListener("change", () => {
                _fcCurrentPage = 1;
                filterForecastProductsTable();
            });
        }

        const searchInput = document.getElementById("fc-search-input");
        if (searchInput) {
            searchInput.addEventListener("input", () => {
                _fcCurrentPage = 1;
                filterForecastProductsTable();
            });
        }

        // Setup 4 KPI Summary Cards Click Listeners
        setupInteractiveKpiCards();

        // Setup Reset KPI Filter Button
        const btnResetKpi = document.getElementById("btn-fc-reset-kpi-filter");
        if (btnResetKpi) {
            btnResetKpi.addEventListener("click", () => {
                clearKpiCardFilter();
            });
        }

        // Setup Horizon Selector Pills (Phase 3)
        const horizonPills = document.querySelectorAll("#fc-horizon-pills .time-pill");
        horizonPills.forEach(pill => {
            pill.addEventListener("click", () => {
                const h = parseInt(pill.getAttribute("data-horizon"), 10) || 7;
                _fcSelectedHorizon = h;
                loadForecastingCharts(_fcSelectedProductId, _fcSelectedHorizon);
            });
        });

        // Setup Product Selector Dropdown (Phase 3)
        const chartProdSelect = document.getElementById("fc-chart-product-select");
        if (chartProdSelect) {
            chartProdSelect.addEventListener("change", (e) => {
                _fcSelectedProductId = parseInt(e.target.value, 10);
                loadForecastingCharts(_fcSelectedProductId, _fcSelectedHorizon);
            });
        }

        // Setup Main Table Pagination Controls
        const pageSizeSelect = document.getElementById("fc-page-size-select");
        if (pageSizeSelect) {
            pageSizeSelect.addEventListener("change", (e) => {
                _fcPageSize = parseInt(e.target.value, 10) || 10;
                _fcCurrentPage = 1;
                filterForecastProductsTable();
            });
        }

        const btnPrev = document.getElementById("btn-fc-prev");
        if (btnPrev) {
            btnPrev.addEventListener("click", () => {
                if (_fcCurrentPage > 1) {
                    _fcCurrentPage--;
                    filterForecastProductsTable();
                }
            });
        }

        const btnNext = document.getElementById("btn-fc-next");
        if (btnNext) {
            btnNext.addEventListener("click", () => {
                _fcCurrentPage++;
                filterForecastProductsTable();
            });
        }

        // Setup Urgent Section Pagination Controls
        const btnUrgentPrev = document.getElementById("btn-fc-urgent-prev");
        if (btnUrgentPrev) {
            btnUrgentPrev.addEventListener("click", () => {
                if (_urgentCurrentPage > 1) {
                    _urgentCurrentPage--;
                    renderUrgentAttentionTable();
                }
            });
        }

        const btnUrgentNext = document.getElementById("btn-fc-urgent-next");
        if (btnUrgentNext) {
            btnUrgentNext.addEventListener("click", () => {
                _urgentCurrentPage++;
                renderUrgentAttentionTable();
            });
        }

        // Setup Event Delegation for Action Buttons (Buy & Inspect) on both tables
        setupTableActionDelegation(document.getElementById("fc-urgent-tbody"));
        setupTableActionDelegation(document.getElementById("fc-products-tbody"));

        // Setup Inspect Modal Restock Button
        const modalRestockBtn = document.getElementById("modal-fc-btn-restock");
        if (modalRestockBtn) {
            modalRestockBtn.addEventListener("click", () => {
                if (_currentForecastProductId) {
                    const prodId = _currentForecastProductId;
                    closeForecastInspectModal();
                    openForecastReorderModal(prodId);
                }
            });
        }

        // Real-Time Event Sync from other modules
        function onExternalDataUpdated() {
            const forecastTab = document.getElementById("tab-forecasting") || document.getElementById("tab-forecast");
            if (forecastTab && forecastTab.classList.contains("active")) {
                loadForecastingDashboard(false);
            }
        }

        window.addEventListener("products-updated", onExternalDataUpdated);
        window.addEventListener("inventory-updated", onExternalDataUpdated);
        window.addEventListener("sales-updated", () => {
            const forecastTab = document.getElementById("tab-forecasting") || document.getElementById("tab-forecast");
            if (forecastTab && forecastTab.classList.contains("active")) {
                loadForecastingDashboard(true);
            }
        });
    }

    /**
     * Setup Interactive 4 KPI Summary Cards
     */
    function setupInteractiveKpiCards() {
        const cardConfigs = [
            { id: "fc-kpi-card-reorder", filter: "reorder" },
            { id: "fc-kpi-card-low-stock", filter: "low-stock" },
            { id: "fc-kpi-card-enough-stock", filter: "enough-stock" },
            { id: "fc-kpi-card-units-to-buy", filter: "units-to-buy" }
        ];

        cardConfigs.forEach(({ id, filter }) => {
            const cardEl = document.getElementById(id);
            if (!cardEl) return;

            cardEl.addEventListener("click", () => {
                if (_activeKpiFilter === filter) {
                    // Toggle off if already active
                    clearKpiCardFilter();
                } else {
                    applyKpiCardFilter(filter, id);
                }
            });

            cardEl.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    cardEl.click();
                }
            });
        });
    }

    /**
     * Apply KPI Card Filter & Update Plain-Language Explanation Banner
     */
    function applyKpiCardFilter(filterType, activeCardId) {
        _activeKpiFilter = filterType;
        _fcCurrentPage = 1;

        // Highlight active card
        document.querySelectorAll(".fc-interactive-kpi").forEach(card => {
            card.classList.remove("active-kpi-card");
        });
        const activeCard = document.getElementById(activeCardId);
        if (activeCard) {
            activeCard.classList.add("active-kpi-card");
        }

        // Count matching items
        const matchingItems = _allForecastProducts.filter(p => matchesKpiFilter(p, filterType));
        const count = matchingItems.length;

        // Update plain-language explanation banner
        const banner = document.getElementById("fc-filter-explanation-banner");
        const bannerText = document.getElementById("fc-filter-explanation-text");

        let explanationMsg = "";
        if (filterType === "reorder") {
            explanationMsg = `Showing ${count} Products Needing Reorder — These items are selling fast and will run out within a few days. Click 'Buy' on any item to restock it immediately.`;
        } else if (filterType === "low-stock") {
            explanationMsg = `Showing ${count} Products Low in Stock — Items currently below safe minimum stock levels. Plan to order soon to prevent stockouts.`;
        } else if (filterType === "enough-stock") {
            explanationMsg = `Showing ${count} Products With Enough Stock — Healthy inventory levels covering current sales demand. No immediate purchase required.`;
        } else if (filterType === "units-to-buy") {
            explanationMsg = `Showing ${count} Products With Recommended Purchases — Items with suggested purchase quantities to meet upcoming customer demand.`;
        }

        if (bannerText) bannerText.textContent = explanationMsg;
        if (banner) {
            banner.style.display = "flex";
            banner.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }

        // Re-render main table with this filter
        filterForecastProductsTable();
    }

    /**
     * Reset KPI Card Filter
     */
    function clearKpiCardFilter() {
        _activeKpiFilter = null;
        _fcCurrentPage = 1;

        document.querySelectorAll(".fc-interactive-kpi").forEach(card => {
            card.classList.remove("active-kpi-card");
        });

        const banner = document.getElementById("fc-filter-explanation-banner");
        if (banner) banner.style.display = "none";

        filterForecastProductsTable();
    }

    /**
     * Check if product matches active KPI card filter
     */
    function matchesKpiFilter(p, filterType) {
        if (!filterType) return true;

        const reorderQty = getProductReorderQty(p);

        if (filterType === "reorder") {
            return (
                p.risk_level === "IMMEDIATE_ATTENTION" ||
                p.risk_level === "POTENTIAL_STOCKOUT" ||
                reorderQty > 0
            );
        }
        if (filterType === "low-stock") {
            return (
                p.risk_level === "LOW_STOCK" ||
                p.risk_level === "IMMEDIATE_ATTENTION"
            );
        }
        if (filterType === "enough-stock") {
            return p.risk_level === "SUFFICIENT";
        }
        if (filterType === "units-to-buy") {
            return reorderQty > 0;
        }

        return true;
    }

    /**
     * Extract reorder qty safely
     */
    function getProductReorderQty(p) {
        if (p.suggested_reorder_qty !== undefined && p.suggested_reorder_qty !== null && p.suggested_reorder_qty > 0) {
            return p.suggested_reorder_qty;
        }
        if (p.stockout_risk && p.stockout_risk.recommended_reorder_quantity > 0) {
            return p.stockout_risk.recommended_reorder_quantity;
        }
        return 0;
    }

    /**
     * Load Forecasting Dashboard Data
     */
    async function loadForecastingDashboard(forceRefresh = false) {
        const refreshBtn = document.getElementById("btn-refresh-forecasts") || document.getElementById("btn-refresh-forecast");
        const tbody = document.getElementById("fc-products-tbody");
        const lastUpdatedEl = document.getElementById("fc-last-updated");
        const spinnerIcon = refreshBtn ? refreshBtn.querySelector(".refresh-spinner-icon") : null;
        const btnTextEl = refreshBtn ? refreshBtn.querySelector(".btn-text") : null;

        if (refreshBtn) {
            refreshBtn.disabled = true;
            if (spinnerIcon) spinnerIcon.classList.add("spinning");
            if (btnTextEl) btnTextEl.textContent = "Recalculating...";
            else refreshBtn.textContent = "Recalculating...";
        }

        if (tbody && (!tbody.children || tbody.children.length === 0 || tbody.textContent.includes("Loading"))) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted" style="padding: 25px;">Calculating demand forecasts & stockout risks...</td></tr>`;
        }

        try {
            const url = forceRefresh ? "/api/v1/forecast/products?force_refresh=true" : "/api/v1/forecast/products";
            const res = await fetch(url);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            const overview = data.overview || {};
            _allForecastProducts = data.products || [];

            // Update KPI summary cards
            updateKpiCardValues(overview, _allForecastProducts);

            // Populate category filter options
            populateCategoryFilter(_allForecastProducts);

            // Populate urgent attention section
            renderUrgentAttentionSection(_allForecastProducts);

            // Populate main products table with pagination
            filterForecastProductsTable();

            // Load Demand Forecasting & Restocking Visualizations (Phase 3)
            loadForecastingCharts(_fcSelectedProductId, _fcSelectedHorizon);

            // Update timestamp
            if (lastUpdatedEl) {
                const now = new Date();
                lastUpdatedEl.textContent = `Last updated: ${now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
            }

            if (forceRefresh && typeof window.showToast === 'function') {
                window.showToast("Forecasts recalculation completed successfully!", "success");
            }

        } catch (err) {
            console.error("Forecasting load error:", err);
            if (tbody) {
                tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger" style="padding: 25px;">Failed to load demand forecast data (${err.message}).</td></tr>`;
            }
            if (forceRefresh && typeof window.showToast === 'function') {
                window.showToast(`Forecast calculation error: ${err.message}`, "error");
            }
        } finally {
            if (refreshBtn) {
                refreshBtn.disabled = false;
                if (spinnerIcon) spinnerIcon.classList.remove("spinning");
                if (btnTextEl) btnTextEl.textContent = "Recalculate Forecasts";
                else refreshBtn.textContent = "Recalculate Forecasts";
            }
        }
    }

    /**
     * Update 4 Top KPI Cards
     */
    function updateKpiCardValues(overview, products) {
        const kpiReorder = document.getElementById("fc-kpi-reorder-count");
        const kpiLowStock = document.getElementById("fc-kpi-low-stock");
        const kpiEnoughStock = document.getElementById("fc-kpi-enough-stock");
        const kpiUnitsToBuy = document.getElementById("fc-kpi-units-to-buy");

        let reorderCount = 0;
        let lowStockCount = 0;
        let enoughStockCount = 0;
        let totalUnitsToBuy = 0;

        if (products && products.length > 0) {
            products.forEach(p => {
                const rq = getProductReorderQty(p);
                if (p.risk_level === "IMMEDIATE_ATTENTION" || p.risk_level === "POTENTIAL_STOCKOUT" || rq > 0) {
                    reorderCount++;
                }
                if (p.risk_level === "LOW_STOCK" || p.risk_level === "IMMEDIATE_ATTENTION") {
                    lowStockCount++;
                }
                if (p.risk_level === "SUFFICIENT") {
                    enoughStockCount++;
                }
                if (rq > 0) {
                    const clean = formatRestockQuantity(rq, p.unit);
                    totalUnitsToBuy += clean.num;
                }
            });
        } else {
            reorderCount = (overview.immediate_attention_count || 0) + (overview.potential_stockout_count || 0);
            lowStockCount = (overview.low_stock_count || 0) + (overview.immediate_attention_count || 0);
            enoughStockCount = overview.sufficient_stock_count || 0;
            totalUnitsToBuy = Math.round(overview.total_reorder_units_needed || 0);
        }

        if (kpiReorder) kpiReorder.textContent = `${reorderCount}`;
        if (kpiLowStock) kpiLowStock.textContent = `${lowStockCount}`;
        if (kpiEnoughStock) kpiEnoughStock.textContent = `${enoughStockCount}`;
        if (kpiUnitsToBuy) kpiUnitsToBuy.textContent = `${totalUnitsToBuy.toLocaleString('en-IN')}`;
    }

    /**
     * Populate Category Dropdown
     */
    function populateCategoryFilter(products) {
        const catSelect = document.getElementById("fc-filter-category");
        if (!catSelect) return;

        const cats = [...new Set((products || []).map(p => p.category).filter(Boolean))].sort();
        const curVal = catSelect.value;
        catSelect.innerHTML = `<option value="">All Categories (${cats.length})</option>`;
        cats.forEach(c => {
            const opt = document.createElement("option");
            opt.value = c.toLowerCase();
            opt.textContent = c;
            catSelect.appendChild(opt);
        });
        catSelect.value = curVal;
    }

    /**
     * Populate Urgent Attention Callout Section
     */
    function renderUrgentAttentionSection(products) {
        const urgentSection = document.getElementById("fc-urgent-section");
        const urgentBadge = document.getElementById("fc-urgent-count-badge");

        if (!urgentSection) return;

        _urgentProducts = (products || []).filter(p =>
            p.status === "ELIGIBLE" && (
                p.risk_level === "IMMEDIATE_ATTENTION" ||
                p.risk_level === "LOW_STOCK" ||
                p.risk_level === "POTENTIAL_STOCKOUT" ||
                getProductReorderQty(p) > 0
            )
        );

        _urgentProducts.sort(compareForecastUrgency);

        if (_urgentProducts.length === 0) {
            urgentSection.style.display = "none";
            if (urgentBadge) urgentBadge.textContent = "0 items";
        } else {
            urgentSection.style.display = "block";
            if (urgentBadge) urgentBadge.textContent = `${_urgentProducts.length} items`;
            _urgentCurrentPage = 1;
            renderUrgentAttentionTable();
        }
    }

    /**
     * Render Paginated Urgent Attention Table
     */
    function renderUrgentAttentionTable() {
        const urgentTbody = document.getElementById("fc-urgent-tbody");
        const pagContainer = document.getElementById("fc-urgent-pagination-container");
        const infoEl = document.getElementById("fc-urgent-pagination-info");
        const indEl = document.getElementById("fc-urgent-page-indicator");
        const btnPrev = document.getElementById("btn-fc-urgent-prev");
        const btnNext = document.getElementById("btn-fc-urgent-next");

        if (!urgentTbody) return;

        const totalItems = _urgentProducts.length;
        if (totalItems <= 10) {
            if (pagContainer) pagContainer.style.display = "none";
            urgentTbody.innerHTML = _urgentProducts.map(p => renderForecastRow(p)).join("");
            return;
        }

        // Show urgent pagination if > 10 items
        if (pagContainer) pagContainer.style.display = "flex";
        const totalPages = Math.ceil(totalItems / _urgentPageSize);
        if (_urgentCurrentPage > totalPages) _urgentCurrentPage = totalPages;
        if (_urgentCurrentPage < 1) _urgentCurrentPage = 1;

        const startIdx = (_urgentCurrentPage - 1) * _urgentPageSize;
        const endIdx = Math.min(startIdx + _urgentPageSize, totalItems);
        const pageItems = _urgentProducts.slice(startIdx, endIdx);

        urgentTbody.innerHTML = pageItems.map(p => renderForecastRow(p)).join("");

        if (infoEl) infoEl.textContent = `Showing ${startIdx + 1}–${endIdx} of ${totalItems} items`;
        if (indEl) indEl.textContent = `Page ${_urgentCurrentPage} of ${totalPages}`;
        if (btnPrev) btnPrev.disabled = (_urgentCurrentPage <= 1);
        if (btnNext) btnNext.disabled = (_urgentCurrentPage >= totalPages);
    }

    /**
     * Filter & Paginate Main Store Products Table
     */
    function filterForecastProductsTable() {
        const elStatus = document.getElementById("fc-filter-status");
        const statusFilter = (elStatus ? elStatus.value : "").trim();
        const elCat = document.getElementById("fc-filter-category");
        const catFilter = (elCat ? elCat.value : "").toLowerCase().trim();
        const elSearch = document.getElementById("fc-search-input");
        const searchVal = (elSearch ? elSearch.value : "").toLowerCase().trim();

        let filtered = _allForecastProducts.filter(p => {
            const pName = (p.product_name || p.name || "").toLowerCase();
            if (searchVal && !pName.includes(searchVal)) {
                return false;
            }

            if (statusFilter) {
                if (statusFilter === "LOW" && p.risk_level !== "LOW_STOCK" && p.risk_level !== "IMMEDIATE_ATTENTION") return false;
                if (statusFilter === "REORDER_SOON" && p.risk_level !== "POTENTIAL_STOCKOUT") return false;
                if (statusFilter === "ENOUGH" && p.risk_level !== "SUFFICIENT") return false;
                if (statusFilter === "INSUFFICIENT" && p.status === "ELIGIBLE" && p.risk_level !== "INSUFFICIENT_DATA") return false;
            }

            if (catFilter && (p.category || '').toLowerCase() !== catFilter) {
                return false;
            }

            // Check active KPI card filter
            if (_activeKpiFilter && !matchesKpiFilter(p, _activeKpiFilter)) {
                return false;
            }

            return true;
        });

        // Sort strictly by urgency: Low Stock (Red) -> Reorder Soon (Amber) -> Enough Stock (Green) -> Not Enough History (Gray)
        filtered.sort(compareForecastUrgency);

        const tbody = document.getElementById("fc-products-tbody");
        if (!tbody) return;

        const totalItems = filtered.length;
        const totalPages = Math.max(1, Math.ceil(totalItems / _fcPageSize));

        if (_fcCurrentPage > totalPages) _fcCurrentPage = totalPages;
        if (_fcCurrentPage < 1) _fcCurrentPage = 1;

        const startIdx = (totalItems === 0) ? 0 : (_fcCurrentPage - 1) * _fcPageSize;
        const endIdx = (totalItems === 0) ? 0 : Math.min(startIdx + _fcPageSize, totalItems);
        const pageItems = (totalItems === 0) ? [] : filtered.slice(startIdx, endIdx);

        if (pageItems.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted" style="padding: 25px;">No products match current filters.</td></tr>`;
        } else {
            tbody.innerHTML = pageItems.map(p => renderForecastRow(p)).join("");
        }

        // Update pagination UI controls
        const paginationInfo = document.getElementById("fc-pagination-info");
        const pageIndicator = document.getElementById("fc-page-indicator");
        const btnPrev = document.getElementById("btn-fc-prev");
        const btnNext = document.getElementById("btn-fc-next");

        if (paginationInfo) {
            if (totalItems === 0) {
                paginationInfo.textContent = "Showing 0–0 of 0 products";
            } else {
                paginationInfo.textContent = `Showing ${startIdx + 1}–${endIdx} of ${totalItems} products`;
            }
        }

        if (pageIndicator) {
            pageIndicator.textContent = `Page ${_fcCurrentPage} of ${totalPages}`;
        }

        if (btnPrev) {
            btnPrev.disabled = (_fcCurrentPage <= 1 || totalItems === 0);
        }

        if (btnNext) {
            btnNext.disabled = (_fcCurrentPage >= totalPages || totalItems === 0);
        }
    }

    /**
     * Sorting priority following strict chronological urgency:
     * 1. Low Stock (Red): IMMEDIATE_ATTENTION / LOW_STOCK (<= 3 days or critical threshold)
     * 2. Reorder Soon (Amber): POTENTIAL_STOCKOUT (> 3 days and <= 7 days or below buffer)
     * 3. Enough Stock (Green): SUFFICIENT (> 7 days)
     * 4. Not Enough Sales History (Gray): INSUFFICIENT_DATA
     */
    function getProductPriority(p) {
        if (p.status !== "ELIGIBLE" || p.risk_level === "INSUFFICIENT_DATA") return 4;
        if (p.risk_level === "IMMEDIATE_ATTENTION" || p.risk_level === "LOW_STOCK") return 1;
        if (p.risk_level === "POTENTIAL_STOCKOUT") return 2;
        if (p.risk_level === "SUFFICIENT") return 3;
        return 4;
    }

    /**
     * Strict urgency comparator:
     * Priority 1 (Low Stock) -> Priority 2 (Reorder Soon) -> Priority 3 (Enough Stock) -> Priority 4 (Insufficient)
     * Within same priority, sorted by lowest days_inventory_remaining ascending.
     */
    function compareForecastUrgency(a, b) {
        const pA = getProductPriority(a);
        const pB = getProductPriority(b);
        if (pA !== pB) return pA - pB;

        const daysA = (a.days_inventory_remaining !== undefined && a.days_inventory_remaining !== null)
            ? a.days_inventory_remaining
            : (a.stockout_risk && a.stockout_risk.days_inventory_remaining !== null ? a.stockout_risk.days_inventory_remaining : 9999);
        const daysB = (b.days_inventory_remaining !== undefined && b.days_inventory_remaining !== null)
            ? b.days_inventory_remaining
            : (b.stockout_risk && b.stockout_risk.days_inventory_remaining !== null ? b.stockout_risk.days_inventory_remaining : 9999);

        if (daysA !== daysB) return daysA - daysB;

        const reorderA = getProductReorderQty(a);
        const reorderB = getProductReorderQty(b);
        if (reorderA !== reorderB) return reorderB - reorderA;

        return (a.product_name || a.name || '').localeCompare(b.product_name || b.name || '');
    }

    /**
     * Render a Single Forecast Product Row with 7 Clean Columns:
     * 1. Product & Category
     * 2. Current Stock
     * 3. Weekly Demand (7 Days)
     * 4. Stock Lasts For
     * 5. Status
     * 6. Suggested Order
     * 7. Action
     */
    function renderForecastRow(p) {
        const escape = window.escapeHtml || (s => s ? String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]) : '');
        const prodId = p.product_id || p.id;
        const prodName = p.product_name || p.name || `Product #${prodId}`;

        // 1. Product & Category
        const productCell = `
            <td>
                <div style="font-weight: 700; color: var(--text-primary); font-size: 0.95rem;">${escape(prodName)}</div>
                <div style="font-size: 0.78rem; color: var(--text-secondary); margin-top: 2px;">
                    ${escape(p.category || 'General')} &bull; ₹${(p.unit_price || 0).toFixed(2)} / ${escape(p.unit || 'unit')}
                </div>
            </td>
        `;

        // 2. Current Stock (Bold white with clean quantity)
        const currentStockFmt = formatStockQuantity(p.current_stock, p.unit);
        const currentStockCell = `
            <td class="cell-nowrap">
                <strong style="color: #ffffff; font-size: 0.95rem;">${currentStockFmt.full}</strong>
            </td>
        `;

        // 3. Weekly Demand (7 Days)
        let weeklyDemandText = `<span class="text-muted">--</span>`;
        if (p.status === "ELIGIBLE") {
            const rawDemand = p.total_7d_demand || 0;
            const demandFmt = formatStockQuantity(rawDemand, p.unit);
            weeklyDemandText = `<span style="font-weight: 600; color: var(--text-primary);">~${demandFmt.text} ${escape(demandFmt.unit)} / week</span>`;
        }
        const weeklyDemandCell = `
            <td class="cell-nowrap" style="padding-left: 18px !important; padding-right: 18px !important;">
                ${weeklyDemandText}
            </td>
        `;

        // 4. Stock Lasts For (Badge)
        const stockLastsBadge = renderStockLastsBadge(p);
        const stockLastsCell = `
            <td class="cell-nowrap">
                ${stockLastsBadge}
            </td>
        `;

        // 5. Status Pill
        const statusPill = renderStatusPill(p);
        const statusCell = `
            <td class="cell-nowrap">
                ${statusPill}
            </td>
        `;

        // 6. Suggested Order (Clean rounded quantity in bold cyan or none needed)
        const rawReorderQty = getProductReorderQty(p);
        const reorderFmt = formatRestockQuantity(rawReorderQty, p.unit);
        let suggestedOrderDisplay = `<span class="text-muted">None needed</span>`;
        if (reorderFmt.num > 0) {
            suggestedOrderDisplay = `<strong style="color: var(--accent); font-size: 0.95rem;">+${reorderFmt.full}</strong>`;
        }
        const suggestedOrderCell = `
            <td class="cell-nowrap">
                ${suggestedOrderDisplay}
            </td>
        `;

        // 7. Action Button: Buy [Quantity] [Unit] or Inspect
        let actionButton = '';
        if (reorderFmt.num > 0) {
            actionButton = `
                <button type="button" class="btn btn-primary btn-sm btn-fc-buy"
                    data-product-id="${prodId}"
                    data-qty="${reorderFmt.num}"
                    data-unit="${escape(p.unit || '')}"
                    title="Click to quickly reorder ${reorderFmt.full}">
                    Buy ${reorderFmt.text} ${escape(reorderFmt.unit)}
                </button>
            `;
        } else {
            actionButton = `
                <button type="button" class="btn btn-secondary btn-sm btn-fc-inspect"
                    data-product-id="${prodId}"
                    title="Inspect product forecast details">
                    Inspect
                </button>
            `;
        }
        const actionCell = `
            <td class="cell-nowrap">
                ${actionButton}
            </td>
        `;

        return `
            <tr data-product-id="${prodId}">
                ${productCell}
                ${currentStockCell}
                ${weeklyDemandCell}
                ${stockLastsCell}
                ${statusCell}
                ${suggestedOrderCell}
                ${actionCell}
            </tr>
        `;
    }

    /**
     * Render Stock Lasts For Badge
     * Strict integer formatting with '> 30 days left' cap for >30 days or zero demand
     */
    function renderStockLastsBadge(p) {
        const days = (p.days_inventory_remaining !== undefined && p.days_inventory_remaining !== null)
            ? p.days_inventory_remaining
            : (p.stockout_risk && p.stockout_risk.days_inventory_remaining !== null ? p.stockout_risk.days_inventory_remaining : null);

        const currentStock = Number(p.current_stock !== undefined ? p.current_stock : (p.stockout_risk ? p.stockout_risk.current_stock : 0)) || 0;
        const avgDemand = Number(p.avg_daily_demand !== undefined ? p.avg_daily_demand : (p.stockout_risk ? p.stockout_risk.avg_daily_demand : 0)) || 0;

        if (currentStock <= 0) {
            return `<span class="forecast-coverage-badge forecast-coverage-urgent">0 days left</span>`;
        }

        if (days === null || days === undefined || days > 30 || avgDemand <= 0) {
            if (p.status === "ELIGIBLE" || days > 30 || avgDemand <= 0) {
                return `<span class="forecast-coverage-badge forecast-coverage-healthy">&gt; 30 days left</span>`;
            }
            return `<span class="text-muted">--</span>`;
        }

        if (days < 1) {
            return `<span class="forecast-coverage-badge forecast-coverage-urgent">&lt; 1 day left</span>`;
        }

        const intDays = Math.round(days);
        if (intDays <= 0) {
            return `<span class="forecast-coverage-badge forecast-coverage-urgent">&lt; 1 day left</span>`;
        } else if (intDays === 1) {
            return `<span class="forecast-coverage-badge forecast-coverage-urgent">1 day left</span>`;
        } else if (intDays <= 3) {
            return `<span class="forecast-coverage-badge forecast-coverage-urgent">${intDays} days left</span>`;
        } else if (intDays <= 7) {
            return `<span class="forecast-coverage-badge forecast-coverage-warning">${intDays} days left</span>`;
        } else if (intDays <= 30) {
            return `<span class="forecast-coverage-badge forecast-coverage-healthy">${intDays} days left</span>`;
        } else {
            return `<span class="forecast-coverage-badge forecast-coverage-healthy">&gt; 30 days left</span>`;
        }
    }

    /**
     * Render Status Pill
     */
    function renderStatusPill(p) {
        if (p.status !== "ELIGIBLE") {
            return `<span class="badge" style="background:rgba(148,163,184,0.15);color:#94a3b8;border:1px solid rgba(148,163,184,0.3);font-size:0.78rem;">Not Enough Sales History</span>`;
        }
        if (p.risk_level === "IMMEDIATE_ATTENTION" || p.risk_level === "LOW_STOCK") {
            return `<span class="badge badge-danger" style="background:rgba(239,68,68,0.15);color:#ef4444;border:1px solid rgba(239,68,68,0.3);font-size:0.78rem;">Low Stock</span>`;
        } else if (p.risk_level === "POTENTIAL_STOCKOUT") {
            return `<span class="badge badge-warning" style="background:rgba(245,158,11,0.15);color:#f59e0b;border:1px solid rgba(245,158,11,0.3);font-size:0.78rem;">Reorder Soon</span>`;
        } else if (p.risk_level === "SUFFICIENT") {
            return `<span class="badge badge-success" style="background:rgba(34,197,94,0.15);color:#22c55e;border:1px solid rgba(34,197,94,0.3);font-size:0.78rem;">Enough Stock</span>`;
        }
        return `<span class="badge badge-neutral" style="font-size:0.78rem;">Optimal</span>`;
    }

    /**
     * Setup Event Delegation for Action Buttons (Buy & Inspect)
     */
    function setupTableActionDelegation(tbody) {
        if (!tbody) return;

        tbody.addEventListener("click", (e) => {
            const buyBtn = e.target.closest(".btn-fc-buy");
            if (buyBtn) {
                e.preventDefault();
                e.stopPropagation();
                const prodId = parseInt(buyBtn.getAttribute("data-product-id"), 10);
                const suggestedQty = parseFloat(buyBtn.getAttribute("data-qty"));
                openForecastReorderModal(prodId, suggestedQty);
                return;
            }

            const inspectBtn = e.target.closest(".btn-fc-inspect");
            if (inspectBtn) {
                e.preventDefault();
                e.stopPropagation();
                const prodId = parseInt(inspectBtn.getAttribute("data-product-id"), 10);
                inspectForecastProduct(prodId);
                return;
            }
        });
    }

    /**
     * Open Quick Confirm Stock Reorder Modal
     */
    function openForecastReorderModal(productId, suggestedQty) {
        const product = _allForecastProducts.find(p => (p.product_id || p.id) === productId);
        _currentReorderProduct = product || { id: productId, product_id: productId, name: `Product #${productId}`, current_stock: 0, unit: 'units' };

        const modal = document.getElementById("forecast-reorder-modal");
        const idInput = document.getElementById("fc-reorder-product-id");
        const nameEl = document.getElementById("fc-reorder-product-name");
        const metaEl = document.getElementById("fc-reorder-product-meta");
        const curStockEl = document.getElementById("fc-reorder-current-stock");
        const newStockEl = document.getElementById("fc-reorder-new-stock");
        const unitLabel = document.getElementById("fc-reorder-unit-label");
        const qtyInput = document.getElementById("fc-reorder-quantity-input");
        const hintEl = document.getElementById("fc-reorder-suggested-hint");

        if (!modal) return;

        const escape = window.escapeHtml || (s => s);
        const prodName = _currentReorderProduct.product_name || _currentReorderProduct.name || `Product #${productId}`;
        const unit = _currentReorderProduct.unit || 'units';

        if (idInput) idInput.value = productId;
        if (nameEl) nameEl.textContent = prodName;
        if (metaEl) metaEl.innerHTML = `${escape(_currentReorderProduct.category || 'General')} &bull; ₹${(_currentReorderProduct.unit_price || 0).toFixed(2)} / ${escape(unit)}`;

        const curStockFmt = formatStockQuantity(_currentReorderProduct.current_stock, unit);
        if (curStockEl) curStockEl.textContent = curStockFmt.full;
        if (unitLabel) unitLabel.textContent = unit;

        // Default restock quantity
        let rawSuggested = suggestedQty;
        if (!rawSuggested || rawSuggested <= 0) {
            rawSuggested = getProductReorderQty(_currentReorderProduct);
        }
        if (!rawSuggested || rawSuggested <= 0) {
            rawSuggested = 10;
        }

        const cleanSuggested = formatRestockQuantity(rawSuggested, unit);
        if (hintEl) hintEl.textContent = cleanSuggested.full;

        if (qtyInput) {
            qtyInput.value = cleanSuggested.num;
            qtyInput.min = "1";
            qtyInput.step = "any";

            // Live update new total stock
            const updateNewStockTotal = () => {
                const added = parseFloat(qtyInput.value) || 0;
                const total = Number(_currentReorderProduct.current_stock || 0) + added;
                const totalFmt = formatStockQuantity(total, unit);
                if (newStockEl) newStockEl.textContent = totalFmt.full;
            };

            qtyInput.oninput = updateNewStockTotal;
            updateNewStockTotal();
        }

        modal.style.display = "flex";
        setTimeout(() => {
            if (qtyInput) {
                qtyInput.focus();
                qtyInput.select();
            }
        }, 50);
    }

    /**
     * Close Confirm Stock Reorder Modal
     */
    function closeForecastReorderModal() {
        const modal = document.getElementById("forecast-reorder-modal");
        if (modal) modal.style.display = "none";
        _currentReorderProduct = null;
    }

    /**
     * Submit Stock Reorder to Backend API
     */
    async function submitForecastReorder() {
        const idInput = document.getElementById("fc-reorder-product-id");
        const qtyInput = document.getElementById("fc-reorder-quantity-input");
        const btnSubmit = document.getElementById("btn-confirm-fc-reorder");
        const btnText = btnSubmit ? btnSubmit.querySelector(".btn-text") : null;
        const btnSpinner = btnSubmit ? btnSubmit.querySelector(".btn-spinner") : null;

        const prodId = parseInt(idInput ? idInput.value : 0, 10);
        const quantityDelta = parseFloat(qtyInput ? qtyInput.value : 0);

        if (!prodId || isNaN(quantityDelta) || quantityDelta <= 0) {
            if (typeof window.showToast === 'function') {
                window.showToast("Please enter a valid restock quantity greater than 0.", "warning");
            }
            return;
        }

        if (btnSubmit) {
            btnSubmit.disabled = true;
            if (btnText) btnText.style.display = "none";
            if (btnSpinner) btnSpinner.style.display = "inline";
        }

        try {
            const res = await fetch("/api/v1/inventory/restock", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    product_id: prodId,
                    quantity_delta: quantityDelta,
                    notes: "Restocked via Forecast Module"
                })
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || `HTTP ${res.status}`);
            }

            const data = await res.json();
            const newStock = (data.new_stock !== undefined) ? data.new_stock : (Number(_currentReorderProduct ? _currentReorderProduct.current_stock : 0) + quantityDelta);

            // Close modal
            closeForecastReorderModal();

            // 1. Immediate Local UI Update
            const p = _allForecastProducts.find(item => (item.product_id || item.id) === prodId);
            if (p) {
                p.current_stock = newStock;

                // Recalculate local forecast metrics following chronological urgency
                const dailyRate = (p.total_7d_demand || 0) / 7;
                p.days_inventory_remaining = dailyRate > 0 ? (newStock / dailyRate) : 999;
                const safetyStock = (p.reorder_recommendation && p.reorder_recommendation.safety_stock) || Math.max(10, dailyRate * 2);
                const minThreshold = (p.min_stock_threshold !== undefined) ? p.min_stock_threshold : 10;

                if (newStock <= 0 || p.days_inventory_remaining <= 3.0 || newStock <= minThreshold) {
                    p.risk_level = (newStock <= 0 || p.days_inventory_remaining <= 1.0) ? "IMMEDIATE_ATTENTION" : "LOW_STOCK";
                    p.suggested_reorder_qty = Math.max(0, (p.total_7d_demand || 0) + safetyStock - newStock);
                } else if (p.days_inventory_remaining <= 7.0 || newStock < ((p.total_7d_demand || 0) + safetyStock)) {
                    p.risk_level = "POTENTIAL_STOCKOUT";
                    p.suggested_reorder_qty = Math.max(0, (p.total_7d_demand || 0) + safetyStock - newStock);
                } else {
                    p.risk_level = "SUFFICIENT";
                    p.suggested_reorder_qty = 0;
                }
                if (p.stockout_risk) {
                    p.stockout_risk.risk_level = p.risk_level;
                    p.stockout_risk.days_inventory_remaining = p.days_inventory_remaining;
                    p.stockout_risk.recommended_reorder_quantity = p.suggested_reorder_qty;
                }
                if (p.reorder_recommendation) {
                    p.reorder_recommendation.suggested_reorder_quantity = p.suggested_reorder_qty;
                }
            }

            // Update KPI cards values instantly
            updateKpiCardValues({}, _allForecastProducts);

            // Re-render urgent attention list (item will be automatically removed if now sufficient)
            renderUrgentAttentionSection(_allForecastProducts);

            // Re-render main products table
            filterForecastProductsTable();

            // Success Toast
            const unitName = (data.unit || (p ? p.unit : '') || 'units');
            const pName = (p ? (p.product_name || p.name) : 'Product');
            if (typeof window.showToast === 'function') {
                window.showToast(`Restocked ${quantityDelta} ${unitName} for ${pName}. New stock: ${newStock} ${unitName}.`, "success");
            }

            // 2. Immediate Cross-System Database & State Synchronization
            window.dispatchEvent(new CustomEvent("inventory-updated", {
                detail: { productId: prodId, newStock: newStock }
            }));
            window.dispatchEvent(new CustomEvent("products-updated", {
                detail: _allForecastProducts
            }));
            if (window.AppEvents) {
                window.AppEvents.emit("inventory-updated", { productId: prodId, newStock: newStock });
                window.AppEvents.emit("products-updated", _allForecastProducts);
            }

            if (typeof window.loadInventorySummary === "function") {
                window.loadInventorySummary();
            }
            if (typeof window.loadDashboardMetrics === "function") {
                window.loadDashboardMetrics();
            }

        } catch (err) {
            console.error("Reorder submission error:", err);
            if (typeof window.showToast === 'function') {
                window.showToast(`Failed to complete restock: ${err.message}`, "error");
            }
        } finally {
            if (btnSubmit) {
                btnSubmit.disabled = false;
                if (btnText) btnText.style.display = "inline";
                if (btnSpinner) btnSpinner.style.display = "none";
            }
        }
    }

    /**
     * Inspect Product Forecast Summary Modal
     */
    async function inspectForecastProduct(productId) {
        _currentForecastProductId = productId;
        _fcSelectedProductId = productId;

        // Synchronize main visualizer product selector if available
        const chartProdSelect = document.getElementById("fc-chart-product-select");
        if (chartProdSelect) {
            chartProdSelect.value = productId;
        }
        loadForecastingCharts(productId, _fcSelectedHorizon);

        const modal = document.getElementById("forecast-inspect-modal");
        const titleEl = document.getElementById("modal-fc-title");
        const subEl = document.getElementById("modal-fc-subtitle");
        const stockEl = document.getElementById("modal-fc-stock");
        const d7El = document.getElementById("modal-fc-demand7d");
        const covEl = document.getElementById("modal-fc-coverage");
        const statusEl = document.getElementById("modal-fc-status");
        const reorderEl = document.getElementById("modal-fc-reorder");
        const reasonEl = document.getElementById("modal-fc-reason");
        const restockBtn = document.getElementById("modal-fc-btn-restock");

        if (modal) modal.style.display = "flex";

        try {
            const res = await fetch(`/api/v1/forecast/product/${productId}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const p = await res.json();

            const escape = window.escapeHtml || (s => s);
            const prodName = p.product_name || p.name || `Product #${productId}`;

            if (titleEl) titleEl.textContent = prodName;
            if (subEl) subEl.textContent = `${p.category || 'General'} • ₹${(p.unit_price || 0).toFixed(2)} / ${escape(p.unit || '')}`;

            const curStockFmt = formatStockQuantity(p.current_stock, p.unit);
            if (stockEl) stockEl.textContent = curStockFmt.full;

            if (d7El) {
                if (p.status === "ELIGIBLE") {
                    const dFmt = formatStockQuantity(p.total_7d_demand || 0, p.unit);
                    d7El.textContent = `${dFmt.full} / 7 days`;
                } else {
                    d7El.textContent = "--";
                }
            }

            const daysRemaining = (p.stockout_risk && p.stockout_risk.days_inventory_remaining !== null)
                ? p.stockout_risk.days_inventory_remaining
                : (p.days_inventory_remaining !== undefined ? p.days_inventory_remaining : null);
            const curStockVal = Number(p.current_stock !== undefined ? p.current_stock : (p.stockout_risk ? p.stockout_risk.current_stock : 0)) || 0;
            const avgDemVal = Number(p.avg_daily_demand !== undefined ? p.avg_daily_demand : (p.stockout_risk ? p.stockout_risk.avg_daily_demand : 0)) || 0;

            if (covEl) {
                if (curStockVal <= 0) {
                    covEl.textContent = "0 days left";
                } else if (daysRemaining === null || daysRemaining === undefined || daysRemaining > 30 || avgDemVal <= 0) {
                    covEl.textContent = "> 30 days left";
                } else if (daysRemaining < 1) {
                    covEl.textContent = "< 1 day left";
                } else {
                    const intDays = Math.round(daysRemaining);
                    covEl.textContent = intDays === 1 ? "1 day left" : (intDays > 30 ? "> 30 days left" : `${intDays} days left`);
                }
            }

            if (statusEl) {
                statusEl.innerHTML = renderStatusPill(p);
            }

            const rawReorder = (p.reorder_recommendation && p.reorder_recommendation.suggested_reorder_quantity) ||
                (p.stockout_risk && p.stockout_risk.recommended_reorder_quantity) || 0;
            const reorderFmt = formatRestockQuantity(rawReorder, p.unit);

            if (reorderEl) {
                if (reorderFmt.num > 0) {
                    reorderEl.textContent = `+${reorderFmt.full} (Purchase Advice)`;
                    reorderEl.style.color = "var(--accent)";
                } else {
                    reorderEl.textContent = `0 ${escape(p.unit || '')} (Stock is sufficient)`;
                    reorderEl.style.color = "#22c55e";
                }
            }

            if (reasonEl) {
                if (p.reorder_recommendation && p.reorder_recommendation.formula_breakdown) {
                    reasonEl.textContent = p.reorder_recommendation.formula_breakdown;
                } else if (p.explanation) {
                    reasonEl.textContent = p.explanation;
                } else if (p.stockout_risk && p.stockout_risk.stockout_reason) {
                    reasonEl.textContent = p.stockout_risk.stockout_reason;
                } else if (p.status === "ELIGIBLE") {
                    reasonEl.textContent = `Current stock of ${curStockFmt.full} comfortably covers expected 7-day sales.`;
                } else {
                    reasonEl.textContent = "This item has fewer than 7 recorded sales days. Please record more bills or import past spreadsheets.";
                }
            }

            if (restockBtn) {
                restockBtn.textContent = reorderFmt.num > 0 ? `Buy ${reorderFmt.text} ${reorderFmt.unit}` : "Add Stock / Manual Restock";
            }

            // Render chart visualizer
            renderDemandForecastChart(p);

        } catch (err) {
            console.error("Forecast product detail error:", err);
        }
    }

    /**
     * Close Inspect Modal
     */
    function closeForecastInspectModal() {
        const modal = document.getElementById("forecast-inspect-modal");
        if (modal) modal.style.display = "none";
    }

    /**
     * Render Demand Forecast Canvas Chart
     */
    function renderDemandForecastChart(productData) {
        const canvas = document.getElementById("fc-demand-canvas");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        const width = canvas.width;
        const height = canvas.height;

        ctx.clearRect(0, 0, width, height);

        if (productData.status !== "ELIGIBLE" || !productData.forecast_7d || productData.forecast_7d.length === 0) {
            ctx.fillStyle = "#94a3b8";
            ctx.font = "13px sans-serif";
            ctx.textAlign = "center";
            ctx.fillText("Demand visualization requires 7+ days of sales records.", width / 2, height / 2);
            return;
        }

        const hist = productData.recent_history || productData.historical_sales_series || [];
        const fc7 = productData.forecast_7d || [];

        const points = [];
        hist.forEach((h, i) => points.push({ label: `H${i+1}`, val: h.quantity || h.units || 0, isFc: false }));
        fc7.forEach((f, i) => points.push({ label: `D${i+1}`, val: f.predicted_demand || f.expected_units || 0, isFc: true }));

        if (points.length === 0) return;

        const maxVal = Math.max(...points.map(p => p.val), 5) * 1.25;
        const padding = 35;
        const graphW = width - (padding * 2);
        const graphH = height - (padding * 2);

        // Draw axes
        ctx.strokeStyle = "rgba(148, 163, 184, 0.25)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padding, height - padding);
        ctx.lineTo(width - padding, height - padding);
        ctx.stroke();

        // Draw Historical line (blue)
        ctx.strokeStyle = "#38bdf8";
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        let started = false;
        points.forEach((p, idx) => {
            if (p.isFc) return;
            const x = padding + (idx / Math.max(points.length - 1, 1)) * graphW;
            const y = height - padding - (p.val / maxVal) * graphH;
            if (!started) {
                ctx.moveTo(x, y);
                started = true;
            } else {
                ctx.lineTo(x, y);
            }
        });
        ctx.stroke();

        // Draw Forecast line (green dashed)
        ctx.strokeStyle = "#22c55e";
        ctx.lineWidth = 2.5;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        started = false;
        points.forEach((p, idx) => {
            if (!p.isFc && idx !== hist.length - 1) return;
            const x = padding + (idx / Math.max(points.length - 1, 1)) * graphW;
            const y = height - padding - (p.val / maxVal) * graphH;
            if (!started) {
                ctx.moveTo(x, y);
                started = true;
            } else {
                ctx.lineTo(x, y);
            }
        });
        ctx.stroke();
        ctx.setLineDash([]);
    }

    /**
     * Load Demand Forecasting & Restocking Charts (Phase 3)
     */
    async function loadForecastingCharts(productId = null, horizon = null) {
        if (horizon) _fcSelectedHorizon = parseInt(horizon, 10) || 7;
        if (productId !== null && productId !== undefined) {
            _fcSelectedProductId = parseInt(productId, 10);
        }

        const productSelect = document.getElementById("fc-chart-product-select");
        const horizonPills = document.querySelectorAll("#fc-horizon-pills .time-pill");
        horizonPills.forEach(pill => {
            const h = parseInt(pill.getAttribute("data-horizon"), 10);
            pill.classList.toggle("active", h === _fcSelectedHorizon);
        });

        const queryParams = new URLSearchParams();
        if (_fcSelectedProductId) queryParams.append("product_id", _fcSelectedProductId);
        queryParams.append("horizon", _fcSelectedHorizon);

        try {
            const res = await fetch(`/api/v1/forecast/charts?${queryParams.toString()}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            // Populate product select if empty or needed
            if (productSelect && data.products && data.products.length > 0) {
                const optionsHtml = data.products.map(p =>
                    `<option value="${p.id}" ${p.is_selected ? 'selected' : ''}>${(p.name || '').substring(0, 32)} (${p.unit || 'units'})</option>`
                ).join("");
                if (!productSelect.options || productSelect.options.length <= 1) {
                    productSelect.innerHTML = optionsHtml;
                }
                if (data.selected_product) {
                    _fcSelectedProductId = data.selected_product.id;
                    productSelect.value = data.selected_product.id;
                }
            }

            // Render Chart: Actual vs Forecast Demand
            renderDemandComparisonChart(data);

        } catch (err) {
            console.error("Failed to load demand forecasting charts:", err);
            const demandCanvas = document.getElementById("chart-forecast-demand");
            if (window.ApnaCharts && demandCanvas) {
                window.ApnaCharts.showEmptyState(demandCanvas.parentElement, "Failed to load forecast", err.message);
            }
        }
    }

    function renderDemandComparisonChart(data) {
        const canvas = document.getElementById("chart-forecast-demand");
        if (!canvas) return;

        const demand = data.demand_chart || {};
        const splitDateLabel = document.getElementById("fc-split-date-label");
        const statusBadge = document.getElementById("fc-demand-status-badge");

        if (splitDateLabel) {
            splitDateLabel.textContent = demand.split_date ? `Forecast starting: ${demand.split_date}` : '';
        }

        if (statusBadge) {
            if (demand.is_forecast_available) {
                statusBadge.textContent = `${data.horizon}-Day Projected Demand`;
                statusBadge.style.color = "#22c55e";
                statusBadge.style.borderColor = "rgba(34, 197, 94, 0.3)";
                statusBadge.style.background = "rgba(34, 197, 94, 0.15)";
            } else {
                statusBadge.textContent = "Insufficient Data";
                statusBadge.style.color = "#f59e0b";
                statusBadge.style.borderColor = "rgba(245, 158, 11, 0.3)";
                statusBadge.style.background = "rgba(245, 158, 11, 0.15)";
            }
        }

        if (!demand.labels || demand.labels.length === 0) {
            if (window.ApnaCharts) {
                window.ApnaCharts.showEmptyState(canvas.parentElement, "No Sales History", "Product has zero recorded sales records.");
            }
            return;
        }

        if (!demand.is_forecast_available) {
            if (window.ApnaCharts) {
                window.ApnaCharts.createChart("chart-forecast-demand", {
                    type: "line",
                    data: {
                        labels: demand.labels,
                        datasets: [
                            {
                                label: `Recorded Sales (${data.selected_product.unit})`,
                                data: demand.historical_series,
                                borderColor: "#38bdf8",
                                backgroundColor: "rgba(56, 189, 248, 0.12)",
                                fill: true,
                                tension: 0.2,
                                pointRadius: 3,
                                pointHoverRadius: 6
                            }
                        ]
                    },
                    options: {
                        ...window.ApnaCharts.getBaseOptions(),
                        scales: {
                            x: { grid: { color: "rgba(148, 163, 184, 0.1)" }, ticks: { color: "#94a3b8", maxRotation: 45, autoSkip: true, maxTicksLimit: 10 } },
                            y: { beginAtZero: true, grid: { color: "rgba(148, 163, 184, 0.1)" }, ticks: { color: "#94a3b8" } }
                        }
                    }
                });
            }
            return;
        }

        if (window.ApnaCharts) {
            window.ApnaCharts.createChart("chart-forecast-demand", {
                type: "line",
                data: {
                    labels: demand.labels,
                    datasets: [
                        {
                            label: `Actual Sales (${data.selected_product.unit})`,
                            data: demand.historical_series,
                            borderColor: "#38bdf8",
                            backgroundColor: "rgba(56, 189, 248, 0.12)",
                            fill: true,
                            tension: 0.2,
                            pointRadius: 3,
                            pointHoverRadius: 5
                        },
                        {
                            label: `Predicted Demand (${data.selected_product.unit})`,
                            data: demand.forecast_series,
                            borderColor: "#22c55e",
                            borderDash: [5, 4],
                            backgroundColor: "rgba(34, 197, 94, 0.12)",
                            fill: true,
                            tension: 0.2,
                            pointRadius: 3,
                            pointHoverRadius: 5
                        }
                    ]
                },
                options: {
                    ...window.ApnaCharts.getBaseOptions(),
                    scales: {
                        x: {
                            grid: { color: "rgba(148, 163, 184, 0.1)" },
                            ticks: { color: "#94a3b8", maxRotation: 45, autoSkip: true, maxTicksLimit: 12 }
                        },
                        y: {
                            beginAtZero: true,
                            grid: { color: "rgba(148, 163, 184, 0.1)" },
                            ticks: { color: "#94a3b8" }
                        }
                    }
                }
            });
        }
    }

    function renderRestockingComparisonChart(data) {
        // Removed per Update 3
    }

    function updateModelEvaluationCard(evalData) {
        // Removed per Update 3
    }

    // Module Exports
    const ForecastingModule = {
        init: initForecastingModule,
        loadForecastingDashboard,
        loadForecastingCharts,
        filterForecastProductsTable,
        formatRestockQuantity,
        formatStockQuantity,
        openForecastReorderModal,
        closeForecastReorderModal,
        submitForecastReorder,
        inspectForecastProduct,
        closeForecastInspectModal,
        applyKpiCardFilter,
        clearKpiCardFilter,
        renderDemandForecastChart,
        toggleAiVoiceBriefing
    };

    window.ForecastingModule = ForecastingModule;
    window.initForecasting = initForecastingModule;
    window.initForecastingModule = initForecastingModule;
    window.loadForecastingDashboard = loadForecastingDashboard;
    window.loadForecastingCharts = loadForecastingCharts;
    window.openForecastReorderModal = openForecastReorderModal;
    window.closeForecastReorderModal = closeForecastReorderModal;
    window.submitForecastReorder = submitForecastReorder;
    window.triggerRestockFromForecast = openForecastReorderModal;
    window.inspectForecastProduct = inspectForecastProduct;
    window.closeForecastInspectModal = closeForecastInspectModal;
    window.toggleAiVoiceBriefing = toggleAiVoiceBriefing;

})(window);

