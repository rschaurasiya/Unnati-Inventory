/**
 * Shared Application State & Real-Time Synchronization Module
 * Serves as the single source of truth for user profile, business data,
 * products, and global application state.
 */

(function(window) {
    'use strict';

    // In-memory state store
    let currentAuthUser = null;
    let currentShopProfile = null;
    let currentProducts = [];

    // Initialize from localStorage cache if present
    try {
        const cachedUser = localStorage.getItem("pos_auth_user");
        if (cachedUser) currentAuthUser = JSON.parse(cachedUser);
    } catch (e) {}

    try {
        const cachedShop = localStorage.getItem("pos_shop_profile");
        if (cachedShop) currentShopProfile = JSON.parse(cachedShop);
    } catch (e) {}

    // Expose onto window for global interoperability
    window.currentAuthUser = currentAuthUser;
    window.currentShopProfile = currentShopProfile;
    window.currentProducts = currentProducts;

    /**
     * Cache-busting URL helper so browser does not display stale cached images
     */
    function withCacheBuster(url) {
        if (!url) return url;
        if (url.startsWith("data:")) return url;
        const separator = url.includes("?") ? "&" : "?";
        return `${url}${separator}t=${Date.now()}`;
    }

    /**
     * Synchronize receipt modal store details
     */
    function syncReceiptModalStoreDetails(shop) {
        if (!shop) return;
        const nameEl = document.getElementById("receipt-modal-shop-name");
        const addrEl = document.getElementById("receipt-modal-shop-address");
        const phoneEl = document.getElementById("receipt-modal-shop-phone");
        const gstinEl = document.getElementById("receipt-modal-shop-gstin");
        const footerEl = document.getElementById("receipt-modal-custom-footer");
        const logoWrap = document.getElementById("receipt-modal-logo-wrap");
        const logoImg = document.getElementById("receipt-modal-logo-img");

        if (nameEl) nameEl.textContent = shop.shop_name || "Apna Kirana Store";
        if (addrEl) addrEl.textContent = shop.shop_address || "";
        if (phoneEl) {
            phoneEl.textContent = shop.shop_phone ? shop.shop_phone : "";
            phoneEl.style.display = shop.shop_phone ? "inline" : "none";
        }
        if (gstinEl) {
            if (shop.gstin) {
                gstinEl.textContent = `GSTIN: ${shop.gstin}`;
                gstinEl.style.display = "inline";
            } else {
                gstinEl.style.display = "none";
            }
        }
        if (footerEl) {
            footerEl.textContent = shop.invoice_footer || "Thank you for shopping with us! Visit again.";
        }
        if (logoWrap && logoImg) {
            const fallbackBadge = document.getElementById("receipt-modal-logo-fallback");
            const hasValidLogo = shop.shop_logo_url && typeof shop.shop_logo_url === "string" && shop.shop_logo_url.trim().length > 0;
            if (hasValidLogo) {
                logoImg.src = withCacheBuster(shop.shop_logo_url.trim());
                logoImg.style.display = "block";
                logoWrap.style.display = "inline-flex";
                if (fallbackBadge) fallbackBadge.style.display = "none";
            } else {
                logoImg.src = "";
                logoImg.style.display = "none";
                logoWrap.style.display = "inline-flex";
                if (fallbackBadge) fallbackBadge.style.display = "inline-flex";
            }
        }
    }

    /**
     * Synchronize business & shop details across the entire application UI
     */
    function syncBusinessDataAcrossUI(shopData) {
        if (!shopData) return;
        currentShopProfile = Object.assign({}, currentShopProfile || {}, shopData);
        window.currentShopProfile = currentShopProfile;

        try {
            localStorage.setItem("pos_shop_profile", JSON.stringify(currentShopProfile));
        } catch (e) {}

        // 1. Browser Title
        if (currentShopProfile.shop_name) {
            document.title = `${currentShopProfile.shop_name} — Shopkeeper Voice POS & AI Inventory`;
        }

        // 2. Header Shop Name & Logo
        const headerShop = document.getElementById("header-shop-name");
        if (headerShop) {
            headerShop.textContent = currentShopProfile.shop_name || "Apna Store";
        }

        // 3. Mobile Navigation Drawer
        const drawerTitle = document.getElementById("drawer-shop-title");
        if (drawerTitle) {
            drawerTitle.textContent = currentShopProfile.shop_name || "Shopkeeper POS";
        }
        const drawerSub = document.getElementById("drawer-shop-subtitle");
        if (drawerSub && currentShopProfile.shop_address) {
            drawerSub.textContent = currentShopProfile.shop_address;
        }

        // 4. Dashboard Command Center Header
        const dashTitle = document.getElementById("dash-store-title");
        if (dashTitle) {
            dashTitle.textContent = currentShopProfile.shop_name ? `${currentShopProfile.shop_name} Command Center` : "Store Command Center";
        }
        const dashSub = document.getElementById("dash-store-subtitle");
        if (dashSub && currentShopProfile.shop_address) {
            dashSub.textContent = currentShopProfile.shop_address;
        }

        // 5. Billing POS Draft Card
        const draftShop = document.getElementById("draft-store-title");
        if (draftShop) {
            draftShop.textContent = currentShopProfile.shop_name || "Apna Kirana Store";
        }

        // 6. Completed Bill Modal Branding
        syncReceiptModalStoreDetails(currentShopProfile);

        // 7. Profile & Settings Form Fields
        const shopNameInp = document.getElementById("shop-name-input");
        if (shopNameInp && currentShopProfile.shop_name) shopNameInp.value = currentShopProfile.shop_name;

        const shopGstinInp = document.getElementById("shop-gstin-input");
        if (shopGstinInp) shopGstinInp.value = currentShopProfile.gstin || "";

        const shopAddrInp = document.getElementById("shop-address-input");
        if (shopAddrInp) shopAddrInp.value = currentShopProfile.shop_address || "";

        const shopPhoneInp = document.getElementById("shop-phone-input");
        if (shopPhoneInp) shopPhoneInp.value = currentShopProfile.shop_phone || "";

        const shopEmailInp = document.getElementById("shop-email-input");
        if (shopEmailInp) shopEmailInp.value = currentShopProfile.shop_email || "";

        const shopLogoPrev = document.getElementById("shop-logo-preview");
        if (shopLogoPrev && currentShopProfile.shop_logo_url) {
            shopLogoPrev.src = withCacheBuster(currentShopProfile.shop_logo_url);
        }

        const settingUnit = document.getElementById("setting-unit");
        if (settingUnit && currentShopProfile.default_measurement_unit) {
            settingUnit.value = currentShopProfile.default_measurement_unit;
        }
        const settingMinStock = document.getElementById("setting-min-stock");
        if (settingMinStock && currentShopProfile.default_min_stock_threshold !== undefined) {
            settingMinStock.value = currentShopProfile.default_min_stock_threshold;
        }
        const settingTax = document.getElementById("setting-tax-rate");
        if (settingTax && currentShopProfile.tax_percentage !== undefined) {
            settingTax.value = currentShopProfile.tax_percentage;
        }
        const settingFooter = document.getElementById("setting-receipt-footer");
        if (settingFooter && currentShopProfile.invoice_footer !== undefined) {
            settingFooter.value = currentShopProfile.invoice_footer;
        }

        // 8. Update Add/Edit Product defaults if modal is opened
        if (currentShopProfile.default_measurement_unit) {
            const unitEl = document.getElementById("product-crud-unit");
            if (unitEl && !unitEl.value) unitEl.value = currentShopProfile.default_measurement_unit;
        }
        if (currentShopProfile.default_min_stock_threshold !== undefined) {
            const stockEl = document.getElementById("product-crud-min-threshold");
            if (stockEl && (!stockEl.value || stockEl.value === "10")) {
                stockEl.value = currentShopProfile.default_min_stock_threshold;
            }
        }

        // 9. If an active completed bill is currently shown, re-fetch formatted delivery receipt
        if (typeof window.currentCompletedBillId !== "undefined" && window.currentCompletedBillId && typeof window.prepareDigitalReceiptDelivery === "function") {
            window.prepareDigitalReceiptDelivery(window.currentCompletedBillId);
        }

        // 10. Dispatch custom event for reactive subscribers
        window.dispatchEvent(new CustomEvent("shop-profile-updated", { detail: currentShopProfile }));
        if (window.AppEvents) window.AppEvents.emit("profile-updated", { user: currentAuthUser, shop: currentShopProfile });
    }

    /**
     * Synchronize personal shopkeeper user information across the entire application UI
     */
    function syncUserDataAcrossUI(userData) {
        if (!userData) return;
        currentAuthUser = Object.assign({}, currentAuthUser || {}, userData);
        window.currentAuthUser = currentAuthUser;

        try {
            localStorage.setItem("pos_auth_user", JSON.stringify(currentAuthUser));
        } catch (e) {}

        const nameEl = document.getElementById("header-user-name");
        const avatarEl = document.getElementById("header-user-avatar");

        if (nameEl) {
            nameEl.textContent = currentAuthUser.full_name || "Shopkeeper";
        }

        if (avatarEl) {
            const avatarUrl = currentAuthUser.avatar_url;
            if (avatarUrl) {
                avatarEl.innerHTML = `<img src="${withCacheBuster(avatarUrl)}" alt="Avatar" style="width:100%;height:100%;border-radius:50%;object-fit:cover;">`;
            } else {
                const initial = (currentAuthUser.full_name || "S").trim().charAt(0).toUpperCase();
                avatarEl.textContent = initial || "S";
            }
        }

        // Form fields on Profile tab
        const profName = document.getElementById("prof-fullname");
        if (profName && currentAuthUser.full_name) profName.value = currentAuthUser.full_name;

        const profPhone = document.getElementById("prof-phone");
        if (profPhone && currentAuthUser.phone) profPhone.value = currentAuthUser.phone;

        const profEmail = document.getElementById("prof-email");
        if (profEmail) profEmail.value = currentAuthUser.email || "";

        const profRole = document.getElementById("prof-role");
        if (profRole) profRole.value = currentAuthUser.role || "Store Owner";

        const profAvatarPrev = document.getElementById("profile-avatar-preview");
        if (profAvatarPrev && currentAuthUser.avatar_url) {
            profAvatarPrev.src = withCacheBuster(currentAuthUser.avatar_url);
        }

        window.dispatchEvent(new CustomEvent("user-profile-updated", { detail: currentAuthUser }));
        if (window.AppEvents) window.AppEvents.emit("profile-updated", { user: currentAuthUser, shop: currentShopProfile });
    }

    /**
     * Updates products catalog in shared state and dispatches products-updated and inventory-updated
     */
    function setProducts(products) {
        currentProducts = products || [];
        window.currentProducts = currentProducts;
        window.dispatchEvent(new CustomEvent("products-updated", { detail: currentProducts }));
        window.dispatchEvent(new CustomEvent("inventory-updated", { detail: currentProducts }));
        if (window.AppEvents) {
            window.AppEvents.emit("products-updated", currentProducts);
            window.AppEvents.emit("inventory-updated", currentProducts);
        }
    }

    /**
     * Unified Real-Time Event Bus
     * Broadcasts products-updated, inventory-updated, sales-updated, customers-updated, profile-updated
     */
    const AppEvents = {
        emit: function(event, detail) {
            try {
                window.dispatchEvent(new CustomEvent(event, { detail }));
            } catch (e) {
                console.warn("[AppEvents] emit error:", e);
            }
        },
        on: function(event, handler) {
            window.addEventListener(event, handler);
        },
        off: function(event, handler) {
            window.removeEventListener(event, handler);
        }
    };
    window.AppEvents = AppEvents;

    // Cross-tab synchronization via native storage events
    window.addEventListener("storage", function(event) {
        if (event.key === "pos_shop_profile" && event.newValue) {
            try {
                const parsed = JSON.parse(event.newValue);
                syncBusinessDataAcrossUI(parsed);
            } catch (e) {}
        } else if (event.key === "pos_auth_user" && event.newValue) {
            try {
                const parsed = JSON.parse(event.newValue);
                syncUserDataAcrossUI(parsed);
            } catch (e) {}
        } else if (event.key === "pos_auth_token") {
            if (!event.newValue) {
                if (typeof window.clearAuthToken === "function") window.clearAuthToken();
                if (typeof window.updateAuthHeaderUI === "function") window.updateAuthHeaderUI(false);
            }
        }
    });

    const AppState = {
        getUser: () => currentAuthUser,
        getShop: () => currentShopProfile,
        getProducts: () => currentProducts,
        setProducts,
        withCacheBuster,
        syncUserDataAcrossUI,
        syncBusinessDataAcrossUI,
        syncReceiptModalStoreDetails
    };

    // Exports
    window.AppState = AppState;
    window.syncUserDataAcrossUI = syncUserDataAcrossUI;
    window.syncBusinessDataAcrossUI = syncBusinessDataAcrossUI;
    window.syncReceiptModalStoreDetails = syncReceiptModalStoreDetails;
    window.withCacheBuster = withCacheBuster;

})(window);
