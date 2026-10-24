/**
 * Inventory Management Module
 * Manages product catalog, stock adjustments, low stock alerts,
 * product CRUD modals, price updates, unified KPI filter tabs,
 * client-side pagination, and safe archiving.
 */

(function(window) {
    'use strict';

    // State Variables
    let rawCatalogProducts = [];   // Authoritative raw products fetched for current query/category
    let filteredProducts = [];     // Filtered & sorted products ready for pagination
    let activeRestockProduct = null;
    let selectedProductIds = new Set();

    // Active KPI filter: 'all' (default), 'valuation', 'low_stock', 'out_of_stock'
    let activeKpiFilter = 'all';

    // Pagination State
    let currentPage = 1;
    let pageSize = 10; // Default to 10 products per page

    // Architecture Helpers
    const fetchApi = (window.ShopApi && typeof window.ShopApi.authFetch === "function")
        ? window.ShopApi.authFetch
        : window.fetch.bind(window);

    const escapeHtml = (window.AppUtils && typeof window.AppUtils.escapeHtml === "function")
        ? window.AppUtils.escapeHtml
        : (window.escapeHtml || (str => (str || "").replace(/[&<>'"]/g, t => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[t] || t))));

    function triggerAudio(type) {
        if (window.AppUtils && typeof window.AppUtils.playAudioTone === "function") {
            window.AppUtils.playAudioTone(type);
        } else if (typeof window.playAudioTone === "function") {
            window.playAudioTone(type);
        }
    }

    // --- Initialization ---
    function initInventory() {
        const searchInput = document.getElementById("product-search-input");
        const categorySelect = document.getElementById("category-filter");
        const refreshBtn = document.getElementById("refresh-inventory-btn");

        // Legacy checkbox guards (kept hidden for test compatibility)
        const lowStockCheckbox = document.getElementById("low-stock-filter");
        const outStockCheckbox = document.getElementById("out-of-stock-filter");

        if (searchInput) {
            let debounceTimer;
            searchInput.addEventListener("input", () => {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    currentPage = 1;
                    loadProducts();
                }, 250);
            });
        }

        if (categorySelect) {
            categorySelect.addEventListener("change", () => {
                currentPage = 1;
                loadProducts();
            });
        }

        if (lowStockCheckbox) {
            lowStockCheckbox.addEventListener("change", () => {
                if (lowStockCheckbox.checked) {
                    selectKpiFilter("low_stock");
                } else if (activeKpiFilter === "low_stock") {
                    selectKpiFilter("all");
                }
            });
        }

        if (outStockCheckbox) {
            outStockCheckbox.addEventListener("change", () => {
                if (outStockCheckbox.checked) {
                    selectKpiFilter("out_of_stock");
                } else if (activeKpiFilter === "out_of_stock") {
                    selectKpiFilter("all");
                }
            });
        }

        if (refreshBtn) {
            refreshBtn.addEventListener("click", () => {
                currentPage = 1;
                loadInventorySummary();
                loadCategories();
                loadProducts();
            });
        }

        // Table Pagination Controls
        const prevBtn = document.getElementById("btn-pagination-prev");
        if (prevBtn) {
            prevBtn.addEventListener("click", (e) => {
                e.preventDefault();
                prevPage();
            });
        }

        const nextBtn = document.getElementById("btn-pagination-next");
        if (nextBtn) {
            nextBtn.addEventListener("click", (e) => {
                e.preventDefault();
                nextPage();
            });
        }

        const pageSizeSelect = document.getElementById("inventory-page-size-select");
        if (pageSizeSelect) {
            pageSizeSelect.addEventListener("change", (e) => {
                setPageSize(parseInt(e.target.value, 10));
            });
        }

        initRestockModal();
        loadCategories();
        loadInventorySummary();
        syncFilterCardsUI();
        loadProducts();

        // Reactive updates when bills finalized or external events occur
        window.addEventListener("bills-updated", () => {
            loadInventorySummary();
            loadProducts({ preservePage: true });
        });
        window.addEventListener("shop-profile-updated", () => {
            loadInventorySummary();
        });
    }

    // --- Inventory Summary Metrics ---
    async function loadInventorySummary() {
        try {
            const res = await fetchApi("/api/v1/inventory/summary");
            if (!res.ok) return;
            const data = await res.json();

            const totalProdEl = document.getElementById("metric-total-products");
            const totalValEl = document.getElementById("metric-total-valuation");
            const lowStockEl = document.getElementById("metric-low-stock");
            const outStockEl = document.getElementById("metric-out-stock");
            const banner = document.getElementById("low-stock-banner");
            const bannerText = document.getElementById("low-stock-banner-text");

            if (totalProdEl) totalProdEl.textContent = data.total_products;
            if (totalValEl) totalValEl.textContent = `₹${data.total_inventory_value.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
            if (lowStockEl) lowStockEl.textContent = data.low_stock_count;
            if (outStockEl) outStockEl.textContent = data.out_of_stock_count;

            if (banner) {
                if (data.low_stock_count > 0) {
                    banner.style.display = "flex";
                    if (bannerText) bannerText.textContent = `${data.low_stock_count} item(s) are below their minimum threshold and need restocking!`;
                } else {
                    banner.style.display = "none";
                }
            }

            // Load Inventory Analytics Charts (Phase 2)
            await loadInventoryCharts();

        } catch (e) {
            console.error("Failed to load inventory summary", e);
        }
    }

    // --- Load Categories ---
    async function loadCategories() {
        const select = document.getElementById("category-filter");
        if (!select) return;
        try {
            const res = await fetchApi("/api/v1/products/categories");
            if (!res.ok) return;
            const categories = await res.json();

            const currentVal = select.value;
            select.innerHTML = `<option value="">All Categories (${categories.length})</option>`;
            categories.forEach(cat => {
                const opt = document.createElement("option");
                opt.value = cat;
                opt.textContent = cat;
                select.appendChild(opt);
            });
            select.value = currentVal;
        } catch (e) {
            console.error("Failed to load categories", e);
        }
    }

    // --- Fetch Products from Backend ---
    async function loadProducts(options = {}) {
        const tableBody = document.getElementById("inventory-table-body");
        const searchInput = document.getElementById("product-search-input");
        const categorySelect = document.getElementById("category-filter");

        if (!tableBody) return;

        const preservePage = !!(options && options.preservePage);
        if (!preservePage) {
            currentPage = 1;
        }

        const params = new URLSearchParams();
        if (searchInput && searchInput.value.trim()) {
            params.append("query", searchInput.value.trim());
        }
        if (categorySelect && categorySelect.value) {
            params.append("category", categorySelect.value);
        }

        try {
            tableBody.innerHTML = `<tr><td colspan="7" class="loading-cell">Loading products...</td></tr>`;
            const res = await fetchApi(`/api/v1/products?${params.toString()}`);
            if (!res.ok) throw new Error("Failed to fetch products");
            rawCatalogProducts = await res.json();

            // Synchronize with AppState and window globals
            window.currentProducts = rawCatalogProducts;
            if (window.AppState && typeof window.AppState.setProducts === "function") {
                window.AppState.setProducts(rawCatalogProducts);
            }

            // Apply active KPI card filter, sort, and render paginated slice
            applyFiltersAndRender(preservePage);

        } catch (e) {
            tableBody.innerHTML = `<tr><td colspan="7" class="loading-cell error-msg">Error loading catalog: ${escapeHtml(e.message)}</td></tr>`;
        }
    }

    // --- Filter & Sort Engine ---
    function applyFiltersAndRender(preservePage = false) {
        let result = [];

        if (activeKpiFilter === 'low_stock') {
            // Show only items where stock_quantity <= min_stock_threshold and stock_quantity > 0
            result = rawCatalogProducts.filter(p => (p.stock_quantity <= p.min_stock_threshold && p.stock_quantity > 0) || (p.is_low_stock && p.stock_quantity > 0));
            // Sorted alphabetically
            result.sort((a, b) => (a.name || "").localeCompare(b.name || "", undefined, { sensitivity: 'base' }));
        } else if (activeKpiFilter === 'out_of_stock') {
            // Show only items where stock_quantity <= 0
            result = rawCatalogProducts.filter(p => p.stock_quantity <= 0);
            // Sorted alphabetically
            result.sort((a, b) => (a.name || "").localeCompare(b.name || "", undefined, { sensitivity: 'base' }));
        } else if (activeKpiFilter === 'in_stock') {
            // Show only items where stock_quantity > min_stock_threshold
            result = rawCatalogProducts.filter(p => p.stock_quantity > p.min_stock_threshold && !p.is_low_stock);
            // Sorted alphabetically
            result.sort((a, b) => (a.name || "").localeCompare(b.name || "", undefined, { sensitivity: 'base' }));
        } else if (activeKpiFilter === 'valuation') {
            // Show all active products sorted by highest total stock valuation descending
            result = [...rawCatalogProducts];
            result.sort((a, b) => {
                const valA = (a.stock_quantity || 0) * (a.unit_price || 0);
                const valB = (b.stock_quantity || 0) * (b.unit_price || 0);
                if (valB !== valA) return valB - valA;
                return (a.name || "").localeCompare(b.name || "", undefined, { sensitivity: 'base' });
            });
        } else {
            // 'all' / Total Products (Default): Show all active products sorted alphabetically
            result = [...rawCatalogProducts];
            result.sort((a, b) => (a.name || "").localeCompare(b.name || "", undefined, { sensitivity: 'base' }));
        }

        filteredProducts = result;

        const totalItems = filteredProducts.length;
        const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));

        if (!preservePage) {
            currentPage = 1;
        } else {
            if (currentPage > totalPages) currentPage = totalPages;
            if (currentPage < 1) currentPage = 1;
        }

        renderTableSlice();
        renderPaginationControls(totalItems, totalPages);
    }

    // --- Render Paginated Table Slice ---
    function renderTableSlice() {
        const tableBody = document.getElementById("inventory-table-body");
        if (!tableBody) return;

        const totalItems = filteredProducts.length;
        if (totalItems === 0) {
            tableBody.innerHTML = `<tr><td colspan="7" class="loading-cell">No products found matching filters.</td></tr>`;
            return;
        }

        const startIndex = (currentPage - 1) * pageSize;
        const endIndex = Math.min(startIndex + pageSize, totalItems);
        const pageItems = filteredProducts.slice(startIndex, endIndex);

        tableBody.innerHTML = pageItems.map(p => {
            let statusBadge = `<span class="badge badge-in-stock">In Stock</span>`;
            if (p.stock_quantity <= 0) {
                statusBadge = `<span class="badge badge-out-stock">Out of Stock</span>`;
            } else if (p.is_low_stock || p.stock_quantity <= p.min_stock_threshold) {
                statusBadge = `<span class="badge badge-low-stock">Low Stock</span>`;
            }

            const aliasesText = p.aliases ? `Keywords: ${p.aliases}` : "";

            return `
                <tr id="prod-row-${p.id}">
                    <td>
                        <strong class="product-name-title">${escapeHtml(p.name)}</strong>
                        ${p.hindi_name ? `<div class="product-subtext hindi-name">${escapeHtml(p.hindi_name)}</div>` : ""}
                        ${aliasesText ? `<div class="product-subtext alias-tags">${escapeHtml(aliasesText)}</div>` : ""}
                    </td>
                    <td><span class="category-badge">${escapeHtml(p.category || "General")}</span></td>
                    <td><strong>₹${(p.unit_price || 0).toFixed(2)}</strong></td>
                    <td>
                        <strong class="${p.stock_quantity <= 0 ? 'text-danger' : (p.is_low_stock ? 'text-warning' : '')}">
                            ${formatQuantity(p.stock_quantity, p.unit)}
                        </strong> ${escapeHtml(p.unit || "")}
                    </td>
                    <td>${formatQuantity(p.min_stock_threshold, p.unit)} ${escapeHtml(p.unit || "")}</td>
                    <td>${statusBadge}</td>
                    <td class="action-cell">
                        <div class="product-action-btns">
                            <button type="button" class="btn-table-action" onclick="openEditProductModalById(${p.id})" title="Edit Product Details">Edit</button>
                            <button type="button" class="btn-table-action" onclick="openProductPriceModal(${p.id}, '${escapeHtml(p.name)}', ${p.unit_price})" title="Update Price">Price</button>
                            <button type="button" class="btn-table-action" onclick="openRestockModal(${p.id})" title="Adjust / Restock Stock">Restock</button>
                            <button type="button" class="btn-table-action danger" onclick="openProductArchiveModal(${p.id})" title="Archive or Delete Product">Archive</button>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");
    }

    function formatQuantity(qty, unit = "") {
        const num = parseFloat(qty);
        if (isNaN(num)) return "0";
        const u = (unit || "").toLowerCase();
        const isDiscrete = ["packet", "packets", "piece", "pieces", "bottle", "bottles", "box", "boxes", "tin", "tins", "can", "cans", "pouch", "pouches", "unit", "units"].some(d => u.includes(d));
        if (isDiscrete) {
            return Math.round(num).toString();
        }
        return (num % 1 === 0) ? num.toFixed(0) : num.toFixed(2);
    }

    // --- Render Pagination Bar & Controls ---
    function renderPaginationControls(totalItems, totalPages) {
        const infoEl = document.getElementById("inventory-pagination-info");
        const prevBtn = document.getElementById("btn-pagination-prev");
        const nextBtn = document.getElementById("btn-pagination-next");
        const pageBadge = document.getElementById("inventory-pagination-page-badge");
        const sizeSelect = document.getElementById("inventory-page-size-select");

        if (sizeSelect && sizeSelect.value !== String(pageSize)) {
            sizeSelect.value = String(pageSize);
        }

        // Range counter: "Showing 1–10 of 146 items"
        if (infoEl) {
            if (totalItems === 0) {
                infoEl.textContent = "Showing 0–0 of 0 items";
            } else {
                const startIndex = (currentPage - 1) * pageSize + 1;
                const endIndex = Math.min(currentPage * pageSize, totalItems);
                infoEl.textContent = `Showing ${startIndex}–${endIndex} of ${totalItems} items`;
            }
        }

        if (pageBadge) {
            pageBadge.textContent = `Page ${currentPage} of ${totalPages}`;
        }

        if (prevBtn) {
            prevBtn.disabled = (currentPage <= 1);
        }
        if (nextBtn) {
            nextBtn.disabled = (currentPage >= totalPages);
        }
        window.currentPage = currentPage;
    }

    function handleStockStatusFilter(val) {
        currentPage = 1;
        if (!val) {
            selectKpiFilter('all');
        } else if (val === 'low_stock') {
            selectKpiFilter('low_stock');
        } else if (val === 'out_of_stock') {
            selectKpiFilter('out_of_stock');
        } else if (val === 'in_stock') {
            selectKpiFilter('in_stock');
        } else {
            selectKpiFilter('all');
        }
    }

    function generatePaginationTokens(totalPages, current) {
        if (totalPages <= 7) {
            return Array.from({ length: totalPages }, (_, i) => i + 1);
        }
        if (current <= 4) {
            return [1, 2, 3, 4, 5, "...", totalPages];
        }
        if (current >= totalPages - 3) {
            return [1, "...", totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages];
        }
        return [1, "...", current - 1, current, current + 1, "...", totalPages];
    }

    // --- Pagination Navigation & Page Size Scaling ---
    function goToPage(page) {
        const totalPages = Math.max(1, Math.ceil(filteredProducts.length / pageSize));
        if (page < 1 || page > totalPages) return;
        currentPage = page;
        window.currentPage = currentPage;
        renderTableSlice();
        renderPaginationControls(filteredProducts.length, totalPages);
    }

    function prevPage() {
        if (currentPage > 1) {
            goToPage(currentPage - 1);
        }
    }

    function nextPage() {
        const totalPages = Math.max(1, Math.ceil(filteredProducts.length / pageSize));
        if (currentPage < totalPages) {
            goToPage(currentPage + 1);
        }
    }

    function setPageSize(size) {
        const parsed = parseInt(size, 10);
        if (isNaN(parsed) || parsed <= 0) return;
        pageSize = parsed;
        currentPage = 1;

        // Update active pill button state
        const pills = document.querySelectorAll("#page-size-pill-group .btn-page-pill");
        pills.forEach(p => {
            const pillSize = parseInt(p.getAttribute("data-size"), 10);
            if (pillSize === pageSize) {
                p.classList.add("active");
            } else {
                p.classList.remove("active");
            }
        });

        applyFiltersAndRender(false);
    }

    // --- KPI Cards Interactive Selection ---
    function selectKpiFilter(filterKey) {
        activeKpiFilter = filterKey || 'all';
        currentPage = 1;

        syncFilterCardsUI();
        applyFiltersAndRender(false);
    }

    function syncFilterCardsUI() {
        const cardTotal = document.getElementById("inv-card-total-products");
        const cardVal = document.getElementById("inv-card-total-valuation");
        const cardLow = document.getElementById("inv-card-low-stock");
        const cardOut = document.getElementById("inv-card-out-stock");

        const badgeTotal = document.getElementById("badge-kpi-total-products");
        const badgeVal = document.getElementById("badge-kpi-total-valuation");
        const badgeLow = document.getElementById("badge-kpi-low-stock");
        const badgeOut = document.getElementById("badge-kpi-out-stock");

        const filterPill = document.getElementById("active-filter-indicator");
        const filterText = document.getElementById("active-filter-text");

        // Clear all card active states first
        [cardTotal, cardVal, cardLow, cardOut].forEach(c => {
            if (c) c.classList.remove("active-filter");
        });
        [badgeTotal, badgeVal, badgeLow, badgeOut].forEach(b => {
            if (b) b.style.display = "none";
        });

        // Set active state on currently selected card
        if (activeKpiFilter === 'valuation') {
            if (cardVal) cardVal.classList.add("active-filter");
            if (badgeVal) badgeVal.style.display = "inline-block";
            if (filterPill) filterPill.style.display = "inline-flex";
            if (filterText) filterText.textContent = "Showing: Highest Stock Valuation";
        } else if (activeKpiFilter === 'low_stock') {
            if (cardLow) cardLow.classList.add("active-filter");
            if (badgeLow) badgeLow.style.display = "inline-block";
            if (filterPill) filterPill.style.display = "inline-flex";
            if (filterText) filterText.textContent = "Showing: Low Stock Only (Stock ≤ Threshold)";
        } else if (activeKpiFilter === 'out_of_stock') {
            if (cardOut) cardOut.classList.add("active-filter");
            if (badgeOut) badgeOut.style.display = "inline-block";
            if (filterPill) filterPill.style.display = "inline-flex";
            if (filterText) filterText.textContent = "Showing: Out of Stock Only (Stock ≤ 0)";
        } else if (activeKpiFilter === 'in_stock') {
            if (filterPill) filterPill.style.display = "inline-flex";
            if (filterText) filterText.textContent = "Showing: In Stock (Stock > Threshold)";
        } else {
            // 'all' / Total Products (Default)
            if (cardTotal) cardTotal.classList.add("active-filter");
            if (badgeTotal) badgeTotal.style.display = "inline-block";
            if (filterPill) filterPill.style.display = "none";
            if (filterText) filterText.textContent = "Showing: All Products (A–Z)";
        }

        // Sync dropdown if present in DOM
        const statusSelect = document.getElementById("inv-filter-status");
        if (statusSelect) {
            if (activeKpiFilter === 'low_stock') statusSelect.value = 'low_stock';
            else if (activeKpiFilter === 'out_of_stock') statusSelect.value = 'out_of_stock';
            else if (activeKpiFilter === 'in_stock') statusSelect.value = 'in_stock';
            else statusSelect.value = '';
        }

        // Sync legacy checkboxes if present in DOM
        const lowStockCb = document.getElementById("low-stock-filter");
        const outStockCb = document.getElementById("out-of-stock-filter");
        if (lowStockCb) lowStockCb.checked = (activeKpiFilter === "low_stock");
        if (outStockCb) outStockCb.checked = (activeKpiFilter === "out_of_stock");
    }

    function handleStockStatusFilter(status) {
        if (!status || status === 'all') {
            selectKpiFilter('all');
        } else if (status === 'low_stock') {
            selectKpiFilter('low_stock');
        } else if (status === 'out_of_stock') {
            selectKpiFilter('out_of_stock');
        } else if (status === 'in_stock') {
            activeKpiFilter = 'in_stock';
            currentPage = 1;
            syncFilterCardsUI();
            applyFiltersAndRender(false);
        }
    }

    // Backward compatibility filter aliases
    function toggleStockFilter(type) {
        if (activeKpiFilter === type) {
            selectKpiFilter("all");
        } else {
            selectKpiFilter(type);
        }
    }

    function setStockFilter(type) {
        selectKpiFilter(type || "all");
    }

    function clearStockFilters() {
        selectKpiFilter("all");
    }

    function navigateToInventoryWithFilter(type) {
        if (typeof window.switchTab === "function") {
            window.switchTab("inventory");
        } else {
            const invTabBtn = document.querySelector('[data-tab="inventory"]');
            if (invTabBtn) invTabBtn.click();
        }
        setTimeout(() => {
            selectKpiFilter(type);
        }, 50);
    }

    // --- Restock Modal ---
    function initRestockModal() {
        const modal = document.getElementById("restock-modal");
        const cancelBtn = document.getElementById("cancel-restock-btn");
        const confirmBtn = document.getElementById("confirm-restock-btn");

        if (cancelBtn) cancelBtn.addEventListener("click", () => {
            if (modal) modal.style.display = "none";
        });

        if (confirmBtn) confirmBtn.addEventListener("click", submitRestock);
    }

    function openRestockModal(productId) {
        const product = (rawCatalogProducts || []).find(p => p.id === productId) ||
                        (window.currentProducts || []).find(p => p.id === productId);
        if (!product) return;

        activeRestockProduct = product;
        const modal = document.getElementById("restock-modal");
        const title = document.getElementById("restock-modal-title");
        const desc = document.getElementById("restock-modal-desc");
        const qtyInput = document.getElementById("restock-quantity");
        const notesInput = document.getElementById("restock-notes");
        const hint = document.getElementById("restock-unit-hint");
        const err = document.getElementById("restock-error-msg");

        if (title) title.textContent = `Restock: ${product.name}`;
        if (desc) desc.textContent = `Current Stock: ${product.stock_quantity} ${product.unit} (Threshold: ${product.min_stock_threshold} ${product.unit})`;
        if (hint) hint.textContent = `Unit: ${product.unit}`;
        if (qtyInput) qtyInput.value = "";
        if (notesInput) notesInput.value = "";
        if (err) err.style.display = "none";

        if (modal) modal.style.display = "flex";
    }

    async function submitRestock() {
        if (!activeRestockProduct) return;
        const qtyInput = document.getElementById("restock-quantity");
        const notesInput = document.getElementById("restock-notes");
        const err = document.getElementById("restock-error-msg");
        const modal = document.getElementById("restock-modal");

        const qty = parseFloat(qtyInput ? qtyInput.value : "0");
        if (isNaN(qty) || qty === 0) {
            if (err) {
                err.textContent = "Please enter a valid non-zero quantity change.";
                err.style.display = "block";
            }
            return;
        }

        try {
            const res = await fetchApi("/api/v1/inventory/restock", {
                method: "POST",
                body: JSON.stringify({
                    product_id: activeRestockProduct.id,
                    quantity_delta: qty,
                    notes: notesInput ? notesInput.value : ""
                })
            });

            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.detail || "Failed to adjust stock");
            }

            if (modal) modal.style.display = "none";
            triggerAudio("success");
            loadInventorySummary();
            await loadProducts({ preservePage: true });
            window.dispatchEvent(new CustomEvent("products-updated", { detail: rawCatalogProducts }));
        } catch (e) {
            if (err) {
                err.textContent = e.message;
                err.style.display = "block";
            }
        }
    }

    // --- Product CRUD Modals ---
    function openAddProductModal() {
        const modal = document.getElementById("product-crud-modal");
        const title = document.getElementById("product-crud-title");
        const subtitle = document.getElementById("product-crud-subtitle");
        const form = document.getElementById("product-crud-form");
        const stockRow = document.getElementById("product-crud-stock-row");
        const errEl = document.getElementById("product-crud-error");

        if (form) form.reset();
        const idEl = document.getElementById("product-crud-id");
        if (idEl) idEl.value = "";

        if (window.currentShopProfile) {
            if (window.currentShopProfile.default_measurement_unit) {
                const unitEl = document.getElementById("product-crud-unit");
                if (unitEl) unitEl.value = window.currentShopProfile.default_measurement_unit;
            }
            if (window.currentShopProfile.default_min_stock_threshold !== undefined) {
                const minStockEl = document.getElementById("product-crud-min-threshold") || document.getElementById("product-crud-min-stock");
                if (minStockEl) minStockEl.value = window.currentShopProfile.default_min_stock_threshold;
            }
        }
        if (title) title.textContent = "Add New Product";
        if (subtitle) subtitle.textContent = "Add catalog item with authoritative price and opening stock";
        if (stockRow) stockRow.style.display = "grid";
        if (errEl) errEl.style.display = "none";
        if (modal) modal.style.display = "flex";
    }

    function openEditProductModalById(productId) {
        const prod = (rawCatalogProducts || []).find(p => p.id === productId) ||
                     (window.currentProducts || []).find(p => p.id === productId);
        if (!prod) return;

        const modal = document.getElementById("product-crud-modal");
        const title = document.getElementById("product-crud-title");
        const subtitle = document.getElementById("product-crud-subtitle");
        const stockRow = document.getElementById("product-crud-stock-row");
        const errEl = document.getElementById("product-crud-error");

        const idEl = document.getElementById("product-crud-id");
        const nameEl = document.getElementById("product-crud-name");
        const hindiEl = document.getElementById("product-crud-hindi");
        const aliasEl = document.getElementById("product-crud-aliases");
        const catEl = document.getElementById("product-crud-category");
        const unitEl = document.getElementById("product-crud-unit");
        const priceEl = document.getElementById("product-crud-price");
        const minStockEl = document.getElementById("product-crud-min-stock");

        if (idEl) idEl.value = prod.id;
        if (nameEl) nameEl.value = prod.name;
        if (hindiEl) hindiEl.value = prod.hindi_name || "";
        if (aliasEl) aliasEl.value = prod.aliases || "";
        if (catEl) catEl.value = prod.category;
        if (unitEl) unitEl.value = prod.unit;
        if (priceEl) priceEl.value = prod.unit_price;
        if (minStockEl) minStockEl.value = prod.min_stock_threshold;

        if (title) title.textContent = `Edit Product: ${prod.name}`;
        if (subtitle) subtitle.textContent = "Modify product details and future billing rate";
        if (stockRow) stockRow.style.display = "none";
        if (errEl) errEl.style.display = "none";
        if (modal) modal.style.display = "flex";
    }

    function closeProductCrudModal() {
        const modal = document.getElementById("product-crud-modal");
        if (modal) modal.style.display = "none";
    }

    async function handleProductCrudSubmit(event) {
        if (event) event.preventDefault();
        const id = document.getElementById("product-crud-id").value;
        const name = document.getElementById("product-crud-name").value.trim();
        const hindi = document.getElementById("product-crud-hindi").value.trim();
        const aliases = document.getElementById("product-crud-aliases").value.trim();
        const category = document.getElementById("product-crud-category").value.trim();
        const unit = document.getElementById("product-crud-unit").value;
        const rawPrice = parseFloat(document.getElementById("product-crud-price").value);
        const stock = parseFloat(document.getElementById("product-crud-stock").value || "0");
        const minStock = parseFloat(document.getElementById("product-crud-min-stock").value || "10");
        const errEl = document.getElementById("product-crud-error");
        const btnSave = document.getElementById("btn-save-product-crud");

        if (isNaN(rawPrice) || rawPrice <= 0) {
            if (errEl) {
                errEl.textContent = "Please enter a valid positive price (e.g. ₹50.00).";
                errEl.style.display = "block";
            }
            return;
        }

        const price = Math.round(rawPrice * 100) / 100;

        if (errEl) errEl.style.display = "none";
        if (btnSave) {
            btnSave.disabled = true;
            btnSave.textContent = "Saving...";
        }

        try {
            let res;
            if (!id) {
                res = await fetchApi("/api/v1/products", {
                    method: "POST",
                    body: JSON.stringify({
                        name: name,
                        hindi_name: hindi || null,
                        aliases: aliases || "",
                        category: category,
                        unit: unit,
                        unit_price: price,
                        stock_quantity: stock >= 0 ? stock : 0,
                        min_stock_threshold: minStock >= 0 ? minStock : 10
                    })
                });
            } else {
                res = await fetchApi(`/api/v1/products/${id}`, {
                    method: "PUT",
                    body: JSON.stringify({
                        name: name,
                        hindi_name: hindi || null,
                        aliases: aliases || "",
                        category: category,
                        unit: unit,
                        unit_price: price,
                        min_stock_threshold: minStock >= 0 ? minStock : 10
                    })
                });
            }

            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.detail || `Server returned error (${res.status})`);
            }

            closeProductCrudModal();
            triggerAudio("success");
            await loadProducts({ preservePage: true });
            loadCategories();
            loadInventorySummary();
            if (typeof window.loadMainDashboard === "function") window.loadMainDashboard();

        } catch (err) {
            console.error("Product CRUD error:", err);
            if (errEl) {
                errEl.textContent = err.message;
                errEl.style.display = "block";
            }
        } finally {
            if (btnSave) {
                btnSave.disabled = false;
                btnSave.textContent = "Save Product";
            }
        }
    }

    // --- Quick Price Update Modal ---
    function openProductPriceModal(productId, productName, currentPrice) {
        const modal = document.getElementById("product-price-modal");
        const idEl = document.getElementById("price-modal-product-id");
        const nameEl = document.getElementById("price-modal-product-name");
        const curEl = document.getElementById("price-modal-current-price");
        const newInp = document.getElementById("price-modal-new-price");
        const errEl = document.getElementById("price-modal-error");

        if (idEl) idEl.value = productId;
        if (nameEl) nameEl.textContent = productName;
        if (curEl) curEl.textContent = `₹${parseFloat(currentPrice || 0).toFixed(2)}`;
        if (newInp) newInp.value = currentPrice;
        if (errEl) errEl.style.display = "none";
        if (modal) modal.style.display = "flex";
    }

    function closeProductPriceModal() {
        const modal = document.getElementById("product-price-modal");
        if (modal) modal.style.display = "none";
    }

    async function submitProductPriceUpdate() {
        const id = document.getElementById("price-modal-product-id").value;
        const newPriceInput = document.getElementById("price-modal-new-price");
        const errEl = document.getElementById("price-modal-error");

        const rawPrice = parseFloat(newPriceInput ? newPriceInput.value : "NaN");
        if (isNaN(rawPrice) || rawPrice <= 0) {
            if (errEl) {
                errEl.textContent = "Please enter a valid positive price (e.g. ₹50.00).";
                errEl.style.display = "block";
            }
            return;
        }

        const newPrice = Math.round(rawPrice * 100) / 100;

        try {
            const res = await fetchApi(`/api/v1/products/${id}/price`, {
                method: "PATCH",
                body: JSON.stringify({ unit_price: newPrice })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Failed to update price.");

            closeProductPriceModal();
            triggerAudio("success");
            await loadProducts({ preservePage: true });
            loadInventorySummary();
            if (typeof window.loadMainDashboard === "function") window.loadMainDashboard();

            // Real-time synchronization event
            window.dispatchEvent(new CustomEvent("products-updated", { detail: rawCatalogProducts }));

        } catch (err) {
            if (errEl) {
                errEl.textContent = err.message;
                errEl.style.display = "block";
            }
        }
    }

    // --- Safe Product Archive / Delete Modal ---
    function openProductArchiveModal(productId, productName) {
        const modal = document.getElementById("product-archive-confirm-modal");
        const idEl = document.getElementById("archive-modal-product-id");
        const nameEl = document.getElementById("archive-modal-product-name");
        const errEl = document.getElementById("archive-modal-error");

        const p = rawCatalogProducts.find(x => x.id === productId);
        const resolvedName = (p && p.name) ? p.name : (productName || `Product #${productId}`);

        if (idEl) idEl.value = productId;
        if (nameEl) nameEl.textContent = resolvedName;
        if (errEl) errEl.style.display = "none";
        if (modal) modal.style.display = "flex";
    }

    function closeProductArchiveModal() {
        const modal = document.getElementById("product-archive-confirm-modal");
        if (modal) modal.style.display = "none";
    }

    async function confirmProductArchive(hardDelete = false) {
        const id = document.getElementById("archive-modal-product-id").value;
        const errEl = document.getElementById("archive-modal-error");

        try {
            const url = hardDelete ? `/api/v1/products/${id}?hard_delete=true` : `/api/v1/products/${id}`;
            const res = await fetchApi(url, { method: "DELETE" });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Failed to remove product.");

            closeProductArchiveModal();
            triggerAudio("success");
            await loadProducts({ preservePage: true });
            loadInventorySummary();
            loadCategories();
            if (typeof window.loadMainDashboard === "function") window.loadMainDashboard();
            window.dispatchEvent(new CustomEvent("products-updated", { detail: rawCatalogProducts }));
        } catch (err) {
            if (errEl) {
                errEl.textContent = err.message;
                errEl.style.display = "block";
            }
        }
    }

    // --- Bulk Action Handlers (Kept for automated test suite compatibility) ---
    function handleProductCheckboxChange(cb) {
        if (!cb) return;
        const id = parseInt(cb.getAttribute("data-id"), 10);
        if (cb.checked) {
            selectedProductIds.add(id);
            const row = document.getElementById(`prod-row-${id}`);
            if (row) row.classList.add("row-selected");
        } else {
            selectedProductIds.delete(id);
            const row = document.getElementById(`prod-row-${id}`);
            if (row) row.classList.remove("row-selected");
        }
        updateBulkToolbar();
    }

    function toggleSelectAllProducts(checked) {
        const checkboxes = document.querySelectorAll(".product-select-checkbox");
        checkboxes.forEach(cb => {
            cb.checked = checked;
            const id = parseInt(cb.getAttribute("data-id"), 10);
            if (checked) {
                selectedProductIds.add(id);
                const row = document.getElementById(`prod-row-${id}`);
                if (row) row.classList.add("row-selected");
            } else {
                selectedProductIds.delete(id);
                const row = document.getElementById(`prod-row-${id}`);
                if (row) row.classList.remove("row-selected");
            }
        });
        updateBulkToolbar();
    }

    function clearProductSelections() {
        selectedProductIds.clear();
        const checkboxes = document.querySelectorAll(".product-select-checkbox");
        checkboxes.forEach(cb => {
            cb.checked = false;
            const id = parseInt(cb.getAttribute("data-id"), 10);
            const row = document.getElementById(`prod-row-${id}`);
            if (row) row.classList.remove("row-selected");
        });
        const selectAllCb = document.getElementById("select-all-products-checkbox");
        if (selectAllCb) selectAllCb.checked = false;
        updateBulkToolbar();
    }

    function updateBulkToolbar() {
        const toolbar = document.getElementById("inventory-bulk-toolbar");
        const countBadge = document.getElementById("bulk-selected-count");
        if (!toolbar) return;

        const count = selectedProductIds.size;
        if (count > 0) {
            toolbar.style.display = "flex";
            if (countBadge) countBadge.textContent = `${count} Selected`;
        } else {
            toolbar.style.display = "none";
        }
    }

    function selectTestProducts() {
        const testPattern = /test/i;
        let matched = 0;
        rawCatalogProducts.forEach(p => {
            if (testPattern.test(p.name) || testPattern.test(p.category || "") || testPattern.test(p.aliases || "")) {
                selectedProductIds.add(p.id);
                matched++;
            }
        });

        const checkboxes = document.querySelectorAll(".product-select-checkbox");
        checkboxes.forEach(cb => {
            const id = parseInt(cb.getAttribute("data-id"), 10);
            if (selectedProductIds.has(id)) {
                cb.checked = true;
                const row = document.getElementById(`prod-row-${id}`);
                if (row) row.classList.add("row-selected");
            }
        });

        updateBulkToolbar();
        if (matched === 0) {
            alert("No test products found in the current list.");
        }
    }

    async function handleBulkDeleteSelected() {
        const count = selectedProductIds.size;
        if (count === 0) return;

        const confirmMsg = `Are you sure you want to permanently delete ${count} selected product(s) from the database?`;
        if (!confirm(confirmMsg)) return;

        try {
            const res = await fetchApi("/api/v1/products/bulk-delete", {
                method: "POST",
                body: JSON.stringify({
                    product_ids: Array.from(selectedProductIds),
                    hard_delete: true
                })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Failed to delete selected products.");

            selectedProductIds.clear();
            updateBulkToolbar();
            triggerAudio("success");
            await loadProducts({ preservePage: true });
            loadInventorySummary();
            loadCategories();
            if (typeof window.loadMainDashboard === "function") window.loadMainDashboard();
            window.dispatchEvent(new CustomEvent("products-updated", { detail: rawCatalogProducts }));
        } catch (err) {
            alert(`Error deleting products: ${err.message}`);
        }
    }

    async function purgeAllTestItems() {
        const confirmMsg = "Are you sure you want to clean and delete ALL test products from the database?";
        if (!confirm(confirmMsg)) return;

        try {
            const res = await fetchApi("/api/v1/products/bulk-delete", {
                method: "POST",
                body: JSON.stringify({
                    delete_all_test_items: true,
                    hard_delete: true
                })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Failed to purge test products.");

            selectedProductIds.clear();
            updateBulkToolbar();
            triggerAudio("success");
            await loadProducts({ preservePage: true });
            loadInventorySummary();
            loadCategories();
            if (typeof window.loadMainDashboard === "function") window.loadMainDashboard();
            window.dispatchEvent(new CustomEvent("products-updated", { detail: rawCatalogProducts }));
            alert(data.message || `Deleted ${data.deleted_count} test items.`);
        } catch (err) {
            alert(`Error purging test products: ${err.message}`);
        }
    }

    // --- Module Export ---
    const InventoryModule = {
        init: initInventory,
        loadProducts,
        loadCategories,
        loadInventorySummary,
        openRestockModal,
        openAddProductModal,
        openEditProductModalById,
        closeProductCrudModal,
        handleProductCrudSubmit,
        openProductPriceModal,
        closeProductPriceModal,
        submitProductPriceUpdate,
        openProductArchiveModal,
        closeProductArchiveModal,
        confirmProductArchive,
        selectKpiFilter,
        setPageSize,
        goToPage,
        toggleStockFilter,
        setStockFilter,
        clearStockFilters,
        handleStockStatusFilter,
        navigateToInventoryWithFilter,
        handleProductCheckboxChange,
        toggleSelectAllProducts,
        clearProductSelections,
        selectTestProducts,
        handleBulkDeleteSelected,
        purgeAllTestItems
    };

    // Global Window Bindings
    window.InventoryModule = InventoryModule;
    window.initInventory = initInventory;
    window.loadProducts = loadProducts;
    window.loadCategories = loadCategories;
    window.loadInventorySummary = loadInventorySummary;
    window.openRestockModal = openRestockModal;
    window.openAddProductModal = openAddProductModal;
    window.openEditProductModalById = openEditProductModalById;
    window.closeProductCrudModal = closeProductCrudModal;
    window.handleProductCrudSubmit = handleProductCrudSubmit;
    window.openProductPriceModal = openProductPriceModal;
    window.closeProductPriceModal = closeProductPriceModal;
    window.submitProductPriceUpdate = submitProductPriceUpdate;
    window.openProductArchiveModal = openProductArchiveModal;
    window.closeProductArchiveModal = closeProductArchiveModal;
    window.confirmProductArchive = confirmProductArchive;
    window.selectKpiFilter = selectKpiFilter;
    window.setPageSize = setPageSize;
    window.goToPage = goToPage;
    window.prevPage = prevPage;
    window.nextPage = nextPage;
    window.currentPage = currentPage;
    window.toggleStockFilter = toggleStockFilter;
    window.setStockFilter = setStockFilter;
    window.clearStockFilters = clearStockFilters;
    window.handleStockStatusFilter = handleStockStatusFilter;
    window.navigateToInventoryWithFilter = navigateToInventoryWithFilter;
    window.handleProductCheckboxChange = handleProductCheckboxChange;
    window.toggleSelectAllProducts = toggleSelectAllProducts;
    window.clearProductSelections = clearProductSelections;
    window.selectTestProducts = selectTestProducts;
    window.handleBulkDeleteSelected = handleBulkDeleteSelected;
    window.purgeAllTestItems = purgeAllTestItems;

    // ==============================================================================
    // Inventory Analytics & Visualizations (Phase 2)
    // ==============================================================================

    let cachedInventoryChartsData = null;

    function toggleInvCategoryMetric(metric) {
        // Locked to product counts; retained for backwards compatibility
        if (cachedInventoryChartsData) {
            renderInvCategoryChart(cachedInventoryChartsData);
        }
    }

    async function loadInventoryCharts() {
        if (!window.ApnaCharts) return;

        try {
            const res = await fetchApi("/api/v1/inventory/charts");
            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || `Server returned ${res.status}`);
            }
            const data = await res.json();
            cachedInventoryChartsData = data;

            // Summary Badges
            const lowCountEl = document.getElementById("inv-chart-low-count");
            if (lowCountEl && data.low_stock_comparison) {
                const belowCount = data.low_stock_comparison.filter(p => p.is_below_threshold).length;
                lowCountEl.textContent = `${belowCount} items below threshold`;
            }

            // Chart 8: Low-Stock Comparison
            renderLowStockComparisonChart(data);

            // Chart 9: Stock by Category (Product counts only)
            renderInvCategoryChart(data);

        } catch (err) {
            console.error("Failed to load inventory charts:", err);
            const wrap = document.getElementById("inv-low-stock-wrap");
            if (wrap) window.ApnaCharts.showEmptyState(wrap, "Inventory Visualizations Unavailable", err.message);
        }
    }

    function renderLowStockComparisonChart(data) {
        const wrap = document.getElementById("inv-low-stock-wrap");
        const items = data.low_stock_comparison || [];

        if (items.length === 0) {
            window.ApnaCharts.showEmptyState(wrap, "No Low Stock Items", "All products currently maintain comfortable stock buffers.");
            return;
        }

        const labels = items.map(p => p.name.length > 18 ? p.name.slice(0, 16) + "…" : p.name);
        const currentStock = items.map(p => p.stock_quantity);
        const thresholds = items.map(p => p.min_stock_threshold);
        const barColors = items.map(p => p.is_below_threshold ? "#ef4444" : "#22c55e");

        window.ApnaCharts.createChart("inv-low-stock-canvas", {
            type: "bar",
            data: {
                labels: labels,
                datasets: [
                    {
                        label: "Current Stock",
                        data: currentStock,
                        backgroundColor: barColors,
                        borderRadius: 3,
                        maxBarThickness: 16
                    },
                    {
                        label: "Min Threshold",
                        data: thresholds,
                        backgroundColor: "rgba(148, 163, 184, 0.4)",
                        borderColor: "#94a3b8",
                        borderWidth: 1,
                        borderRadius: 3,
                        maxBarThickness: 16
                    }
                ]
            },
            options: {
                ...window.ApnaCharts.getBaseOptions(),
                indexAxis: "y",
                scales: {
                    x: {
                        beginAtZero: true,
                        grid: { color: "rgba(255, 255, 255, 0.05)" },
                        ticks: { color: "#94a3b8", font: { size: 10 } }
                    },
                    y: {
                        grid: { display: false },
                        ticks: { color: "#f8fafc", font: { size: 11 } }
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
                                const it = items[ctx.dataIndex];
                                if (ctx.datasetIndex === 0) {
                                    return `Current: ${ctx.raw} ${it.unit} (${it.is_below_threshold ? 'BELOW THRESHOLD' : 'STOCKED'})`;
                                }
                                return `Min Buffer: ${ctx.raw} ${it.unit}`;
                            }
                        }
                    }
                }
            }
        });
    }

    function renderInvCategoryChart(data) {
        const wrap = document.getElementById("inv-category-wrap");
        const categories = data.stock_by_category || [];

        if (categories.length === 0) {
            window.ApnaCharts.showEmptyState(wrap, "No Category Data", "Add products to view category stock distribution.");
            return;
        }

        const labels = categories.map(c => c.category);
        const values = categories.map(c => c.product_count);

        window.ApnaCharts.createChart("inv-category-canvas", {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: "Product Count",
                    data: values,
                    backgroundColor: "#818cf8",
                    borderRadius: 4,
                    maxBarThickness: 24
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
                        ticks: { color: "#94a3b8", font: { size: 10 }, precision: 0 },
                        title: {
                            display: true,
                            text: "Distinct Products",
                            color: "#94a3b8",
                            font: { size: 10 }
                        }
                    }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: ctx => `Products: ${ctx.raw} items`
                        }
                    }
                }
            }
        });
    }

    window.toggleInvCategoryMetric = toggleInvCategoryMetric;
    window.loadInventoryCharts = loadInventoryCharts;

})(window);
