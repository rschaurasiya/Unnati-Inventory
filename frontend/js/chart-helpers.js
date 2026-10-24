/**
 * Apna Kirana OS — Charting Utility & Visualizations Helper (ApnaCharts)
 * Provides centralized Chart.js configuration, Indian currency formatting,
 * canvas lifecycle management (safe destroy & re-create), dark-mode styling,
 * and empty-state handlers.
 */
(function(window) {
    'use strict';

    function formatIndianCurrency(amount) {
        const num = parseFloat(amount);
        if (isNaN(num)) return "₹0.00";
        try {
            return "₹" + num.toLocaleString("en-IN", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            });
        } catch (e) {
            return `₹${num.toFixed(2)}`;
        }
    }

    function formatCompactCurrency(amount) {
        const num = parseFloat(amount);
        if (isNaN(num)) return "₹0";
        if (num >= 10000000) {
            return `₹${(num / 10000000).toFixed(2)} Cr`;
        }
        if (num >= 100000) {
            return `₹${(num / 100000).toFixed(2)} L`;
        }
        if (num >= 1000) {
            return `₹${(num / 1000).toFixed(1)}k`;
        }
        return `₹${num.toFixed(0)}`;
    }

    function getBaseChartOptions() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 400
            },
            plugins: {
                legend: {
                    labels: {
                        color: "#94a3b8",
                        font: { size: 11, family: "inherit" },
                        boxWidth: 12,
                        padding: 12
                    }
                },
                tooltip: {
                    backgroundColor: "#1e293b",
                    titleColor: "#f8fafc",
                    bodyColor: "#cbd5e1",
                    borderColor: "#475569",
                    borderWidth: 1,
                    padding: 10,
                    cornerRadius: 6,
                    displayColors: true,
                    boxPadding: 4
                }
            }
        };
    }

    function destroyChart(canvasOrId) {
        const canvas = typeof canvasOrId === "string" ? document.getElementById(canvasOrId) : canvasOrId;
        if (canvas && canvas._chartInstance) {
            try {
                canvas._chartInstance.destroy();
            } catch (err) {
                console.warn("Error destroying previous chart instance:", err);
            }
            canvas._chartInstance = null;
        }
    }

    function createChart(canvasId, config) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) {
            console.warn(`Canvas element #${canvasId} not found.`);
            return null;
        }

        if (typeof Chart === "undefined") {
            console.error("Chart.js library is not loaded.");
            showEmptyState(canvas.parentElement, "Visualization Engine Unavailable", "Chart library failed to load");
            return null;
        }

        // Clean up previous instance on this canvas
        destroyChart(canvas);
        removeEmptyState(canvas.parentElement);

        try {
            const ctx = canvas.getContext("2d");
            const chart = new Chart(ctx, config);
            canvas._chartInstance = chart;
            return chart;
        } catch (e) {
            console.error(`Failed to create chart on #${canvasId}:`, e);
            showEmptyState(canvas.parentElement, "Failed to render visualization", e.message);
            return null;
        }
    }

    function showEmptyState(container, title = "No data available", message = "No records found for this period.") {
        if (!container) return;
        let emptyEl = container.querySelector(".chart-empty-state");
        if (!emptyEl) {
            emptyEl = document.createElement("div");
            emptyEl.className = "chart-empty-state";
            container.appendChild(emptyEl);
        }
        emptyEl.innerHTML = `
            <div class="empty-state-inner">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="empty-icon-svg" style="opacity: 0.6; margin-bottom: 6px;"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>
                <strong class="empty-title">${title}</strong>
                <p class="empty-msg">${message}</p>
            </div>
        `;
        emptyEl.style.display = "flex";

        const canvas = container.querySelector("canvas");
        if (canvas) canvas.style.display = "none";
    }

    function removeEmptyState(container) {
        if (!container) return;
        const emptyEl = container.querySelector(".chart-empty-state");
        if (emptyEl) emptyEl.style.display = "none";

        const canvas = container.querySelector("canvas");
        if (canvas) canvas.style.display = "block";
    }

    function resizeSection(containerOrId) {
        const container = typeof containerOrId === "string" ? document.getElementById(containerOrId) : containerOrId;
        if (!container) return;
        const canvases = container.querySelectorAll("canvas");
        canvases.forEach(cv => {
            if (cv._chartInstance) {
                try {
                    cv._chartInstance.resize();
                } catch (e) {
                    console.warn("Chart resize warning:", e);
                }
            }
        });
    }

    function resizeAll() {
        document.querySelectorAll("canvas").forEach(cv => {
            if (cv._chartInstance) {
                try {
                    cv._chartInstance.resize();
                } catch (e) {}
            }
        });
    }

    function toggleChartSection(collapseId, buttonId, singleChart = false) {
        const collapseEl = document.getElementById(collapseId);
        const btn = document.getElementById(buttonId);
        if (!collapseEl) return;

        const isCurrentlyHidden = collapseEl.style.display === "none" || window.getComputedStyle(collapseEl).display === "none";
        
        if (isCurrentlyHidden) {
            collapseEl.style.display = "block";
            if (btn) {
                btn.textContent = singleChart ? "Hide Graph" : "Hide Graphs";
                btn.setAttribute("aria-expanded", "true");
                btn.classList.add("active");
            }
            // Ensure Chart.js reflows and measures correct container dimensions
            requestAnimationFrame(() => {
                resizeSection(collapseEl);
                setTimeout(() => resizeSection(collapseEl), 100);
            });
        } else {
            collapseEl.style.display = "none";
            if (btn) {
                btn.textContent = singleChart ? "Show Graph" : "Show Graphs";
                btn.setAttribute("aria-expanded", "false");
                btn.classList.remove("active");
            }
        }
    }

    window.toggleChartSection = toggleChartSection;

    window.ApnaCharts = {
        formatRupees: formatIndianCurrency,
        formatCompactRupees: formatCompactCurrency,
        getBaseOptions: getBaseChartOptions,
        destroyChart: destroyChart,
        createChart: createChart,
        showEmptyState: showEmptyState,
        removeEmptyState: removeEmptyState,
        resizeSection: resizeSection,
        resizeAll: resizeAll
    };
})(window);
