/**
 * Shared API helper module
 * Handles authentication tokens, tenant isolation headers, global fetch interceptor,
 * and cache cleanup across multi-tenant sessions.
 */

(function(window) {
    'use strict';

    function getAuthToken() {
        return localStorage.getItem("pos_auth_token") || localStorage.getItem("access_token");
    }

    function setAuthToken(token) {
        if (token) {
            localStorage.setItem("pos_auth_token", token);
            localStorage.setItem("access_token", token);
        } else {
            localStorage.removeItem("pos_auth_token");
            localStorage.removeItem("access_token");
        }
    }

    function clearStoreDataCaches() {
        // 1. Reset in-memory cached arrays across window modules
        if (window.currentProducts) window.currentProducts = [];
        if (window.cachedProducts) window.cachedProducts = [];
        if (window.inventoryProducts) window.inventoryProducts = [];
        if (window.cachedCustomers) window.cachedCustomers = [];
        if (window.salesRecords) window.salesRecords = [];
        if (window.rawSalesRows) window.rawSalesRows = [];

        // 2. Clear cart and active transaction state
        if (typeof window.clearCartDraft === "function") {
            try { window.clearCartDraft(); } catch (_) {}
        }

        // 3. Purge tenant-specific caches from localStorage
        const storeKeysToRemove = [
            "pos_draft_cart",
            "pos_active_cart",
            "billing_draft_items",
            "recent_bills_cache",
            "kpi_cache",
            "inventory_cache",
            "customers_cache",
            "sales_cache",
            "forecasting_cache"
        ];
        storeKeysToRemove.forEach(k => {
            try { localStorage.removeItem(k); } catch (_) {}
        });

        console.log("[ShopApi] In-memory arrays and localStorage tenant caches cleared.");
    }

    function clearAuthToken() {
        clearStoreDataCaches();
        localStorage.removeItem("pos_auth_token");
        localStorage.removeItem("access_token");
        localStorage.removeItem("shopkeeper_user");
        localStorage.removeItem("pos_auth_user");
        localStorage.removeItem("pos_shop_profile");
        localStorage.removeItem("pos_onboarding_completed");
    }

    // Install global fetch interceptor to guarantee Authorization & X-User-Id are ALWAYS attached
    const nativeFetch = window.fetch;
    window.fetch = async function(input, init = {}) {
        let url = typeof input === "string" ? input : (input && input.url ? input.url : "");

        if (url.startsWith("/api/") || url.startsWith("api/")) {
            init = init || {};
            const headers = new Headers(init.headers || {});

            const token = getAuthToken();
            if (token && !headers.has("Authorization")) {
                headers.set("Authorization", `Bearer ${token}`);
            }

            let userId = null;
            try {
                const u = JSON.parse(localStorage.getItem("shopkeeper_user") || localStorage.getItem("pos_auth_user") || "{}");
                if (u && (u.id || u.user_id || u.firebase_uid)) {
                    userId = String(u.id || u.user_id || u.firebase_uid);
                }
            } catch (_) {}

            if (userId) {
                if (!headers.has("X-User-Id")) headers.set("X-User-Id", userId);
                if (!headers.has("X-Tenant-Id")) headers.set("X-Tenant-Id", userId);
            }

            init.headers = headers;
        }

        return nativeFetch.call(this, input, init);
    };

    async function authFetch(url, options = {}) {
        const token = getAuthToken();
        const headers = options.headers ? { ...options.headers } : {};

        if (token && !headers["Authorization"]) {
            headers["Authorization"] = `Bearer ${token}`;
        }

        const isFormData = options.body instanceof FormData;
        if (!isFormData && !headers["Content-Type"] && options.method && options.method.toUpperCase() !== "GET") {
            headers["Content-Type"] = "application/json";
        }

        const fetchOptions = {
            ...options,
            headers
        };

        try {
            const res = await window.fetch(url, fetchOptions);

            if (res.status === 401 && !url.includes("/api/auth/login") && !url.includes("/api/v1/auth/login")) {
                console.warn(`[ShopApi] Unauthorized (401) at ${url}. Directing to login.`);
                window.dispatchEvent(new CustomEvent("pos-unauthorized", { detail: { url } }));
                if (typeof window.showAuthView === "function") {
                    window.showAuthView("login");
                }
            }

            return res;
        } catch (err) {
            console.error(`[ShopApi] Network error requesting ${url}:`, err);
            throw err;
        }
    }

    const ShopApi = {
        getAuthToken,
        setAuthToken,
        clearAuthToken,
        clearStoreDataCaches,
        authFetch
    };

    // Export module
    window.ShopApi = ShopApi;
    window.getAuthToken = getAuthToken;
    window.setAuthToken = setAuthToken;
    window.clearAuthToken = clearAuthToken;
    window.clearStoreDataCaches = clearStoreDataCaches;
    window.authFetch = authFetch;

})(window);
