/**
 * Shopkeeper Voice POS & AI Inventory System
 * Application Orchestrator & SPA Router
 * Coordinates shared state, authentication, routing, and connects page modules:
 * - dashboard.js
 * - billing.js
 * - inventory.js
 * - customers.js
 * - sales.js
 * - forecasting.js
 * - profile.js
 */

(function(window) {
    'use strict';

    // ==============================================================================
    // URL Routing & Navigation Configuration (SPA Routing)
    // ==============================================================================
    const ROUTE_CONFIG = {
        "/": { tab: "dashboard", salesView: null },
        "/dashboard": { tab: "dashboard", salesView: null },
        "/billing": { tab: "billing", salesView: null },
        "/pos": { tab: "billing", salesView: null },
        "/inventory": { tab: "inventory", salesView: null },
        "/customers": { tab: "udhaar", salesView: null },
        "/udhaar": { tab: "udhaar", salesView: null },
        "/sales": { tab: "analytics", salesView: "history" },
        "/sales/history": { tab: "analytics", salesView: "history" },
        "/sales/import": { tab: "analytics", salesView: "import" },
        "/forecast": { tab: "forecasting", salesView: null },
        "/forecasting": { tab: "forecasting", salesView: null },
        "/profile": { tab: "profile", salesView: null },
        "/settings": { tab: "profile", salesView: null },
        "/reports": { tab: "reports", salesView: null },
        "/export": { tab: "reports", salesView: null },
        "/login": { tab: "auth", authView: "login" },
        "/register": { tab: "auth", authView: "register" },
        "/forgot-password": { tab: "auth", authView: "forgot" }
    };

    const TAB_TO_ROUTE = {
        "dashboard": "/dashboard",
        "billing": "/billing",
        "inventory": "/inventory",
        "udhaar": "/customers",
        "analytics": "/sales",
        "forecasting": "/forecast",
        "reports": "/reports",
        "profile": "/profile"
    };

    function getRouteForTab(tabId) {
        if (tabId === "analytics") {
            const importSection = document.getElementById("section-sales-import");
            if (importSection && importSection.style.display !== "none") {
                return "/sales/import";
            }
            return "/sales/history";
        }
        return TAB_TO_ROUTE[tabId] || "/dashboard";
    }

    function setEntryGateMode(active) {
        const authContainer = document.getElementById("auth-container");
        if (active) {
            document.body.classList.add("entry-gate-active");
            if (authContainer) authContainer.style.display = "flex";
            updateAuthHeaderUI(false);
        } else {
            document.body.classList.remove("entry-gate-active");
            if (authContainer) authContainer.style.display = "none";
            updateAuthHeaderUI(true);
        }
    }

    function showWelcomeGreetingModal(user) {
        const modal = document.getElementById("welcome-greeting-modal");
        const nameEl = document.getElementById("welcome-user-name");
        const voiceInd = document.getElementById("welcome-voice-indicator");

        const displayName = (user && (user.full_name || user.phone || user.email)) || "Shopkeeper";
        if (nameEl) nameEl.textContent = displayName;

        if (modal) modal.style.display = "flex";

        // Speak welcome greeting if audio feedback is active
        const audioOn = typeof window.isAudioEnabled === "function" ? window.isAudioEnabled() : false;
        if (audioOn && typeof window.speakWithElevenLabs === "function") {
            if (voiceInd) voiceInd.style.display = "inline-flex";
            const greetingMsg = `Welcome to Apna Kirana OS, ${displayName}. Let's set up your store profile.`;
            window.speakWithElevenLabs(greetingMsg).catch(() => {});
        } else {
            if (voiceInd) voiceInd.style.display = "none";
        }
    }

    /**
     * Evaluates whether the user's profile and shop onboarding are fully finalized.
     * Demo user is always complete. Other users require non-empty profile & shop fields.
     */
    function isProfileAndShopSetupComplete() {
        if (localStorage.getItem("pos_onboarding_completed") === "true") {
            return true;
        }
        const currentUser = window.currentAuthUser || (window.AuthService && window.AuthService.getCurrentUser());
        if (!currentUser) return false;

        // Default demo account is always considered complete
        const cleanPhone = (currentUser.phone || "").replace(/\D/g, "");
        if (cleanPhone === "9876543210" || (currentUser.email && currentUser.email.toLowerCase() === "owner@apnakirana.com")) {
            localStorage.setItem("pos_onboarding_completed", "true");
            return true;
        }

        // For non-demo users, check required fields
        const hasFullName = Boolean(currentUser.full_name && currentUser.full_name.trim().length > 0 && !currentUser.full_name.startsWith("Shopkeeper User"));
        const hasPhone = Boolean(cleanPhone.length === 10);
        const shop = currentUser.shop_profile || window.currentShopProfile;
        const hasShopName = Boolean(shop && shop.shop_name && shop.shop_name.trim().length > 0);
        const hasShopAddress = Boolean(shop && shop.shop_address && shop.shop_address.trim().length > 0 && shop.shop_address !== "Main Market");
        const hasShopPhone = Boolean(shop && shop.shop_phone && shop.shop_phone.replace(/\D/g, "").length >= 10);

        if (hasFullName && hasPhone && hasShopName && hasShopAddress && hasShopPhone) {
            localStorage.setItem("pos_onboarding_completed", "true");
            return true;
        }
        return false;
    }

    /**
     * Forcefully locks or unlocks navigation during mandatory onboarding.
     * Applies display: none !important and pointer-events: none to #main-nav-tabs and mobile drawer.
     */
    function setOnboardingLock(locked) {
        if (locked) {
            document.body.classList.add("onboarding-locked");
            const navTabs = document.getElementById("main-nav-tabs");
            if (navTabs) {
                navTabs.style.setProperty("display", "none", "important");
                navTabs.style.setProperty("pointer-events", "none", "important");
            }
            const mobileToggle = document.getElementById("mobile-nav-toggle");
            if (mobileToggle) {
                mobileToggle.style.setProperty("display", "none", "important");
                mobileToggle.style.setProperty("pointer-events", "none", "important");
            }
            document.querySelectorAll(".mobile-drawer-nav .mobile-nav-item").forEach(item => {
                if (item.getAttribute("data-tab") !== "profile") {
                    item.style.setProperty("display", "none", "important");
                    item.style.setProperty("pointer-events", "none", "important");
                }
            });
            const masterContainer = document.getElementById("onboarding-master-container");
            if (masterContainer) masterContainer.style.display = "block";
            const obBanner = document.getElementById("profile-onboarding-banner");
            if (obBanner) obBanner.style.display = "flex";

            ["btn-save-personal", "btn-save-shop", "btn-save-settings"].forEach(btnId => {
                const btn = document.getElementById(btnId);
                if (btn && btn.closest(".card-action-bar")) {
                    btn.closest(".card-action-bar").style.display = "none";
                }
            });
        } else {
            document.body.classList.remove("onboarding-locked");
            const navTabs = document.getElementById("main-nav-tabs");
            if (navTabs) {
                navTabs.style.removeProperty("display");
                navTabs.style.removeProperty("pointer-events");
                navTabs.style.display = "flex";
            }
            const mobileToggle = document.getElementById("mobile-nav-toggle");
            if (mobileToggle) {
                mobileToggle.style.removeProperty("display");
                mobileToggle.style.removeProperty("pointer-events");
                mobileToggle.style.display = "";
            }
            document.querySelectorAll(".mobile-drawer-nav .mobile-nav-item").forEach(item => {
                item.style.removeProperty("display");
                item.style.removeProperty("pointer-events");
                item.style.display = "";
            });
            const masterContainer = document.getElementById("onboarding-master-container");
            if (masterContainer) masterContainer.style.display = "none";
            const obBanner = document.getElementById("profile-onboarding-banner");
            if (obBanner) obBanner.style.display = "none";

            ["btn-save-personal", "btn-save-shop", "btn-save-settings"].forEach(btnId => {
                const btn = document.getElementById(btnId);
                if (btn && btn.closest(".card-action-bar")) {
                    btn.closest(".card-action-bar").style.display = "";
                }
            });
        }
    }

    function continueToProfileOnboarding() {
        const modal = document.getElementById("welcome-greeting-modal");
        if (modal) modal.style.display = "none";

        // Deactivate full-screen Entry Gate mode to reveal app shell
        setEntryGateMode(false);

        const setupComplete = isProfileAndShopSetupComplete();
        if (setupComplete) {
            setOnboardingLock(false);
            if (window.history && window.history.replaceState) {
                window.history.replaceState({ path: "/dashboard" }, "", "/dashboard");
            }
            switchTab("dashboard", true);
            return;
        }

        // Strictly lock navigation during onboarding
        setOnboardingLock(true);

        // Switch to profile tab
        switchTab("profile", true);

        // Pre-fill user data into personal profile form if available
        const currentUser = window.currentAuthUser || (window.AuthService && window.AuthService.getCurrentUser());
        if (currentUser) {
            const phoneInput = document.getElementById("prof-phone");
            const emailInput = document.getElementById("prof-email");
            const nameInput = document.getElementById("prof-fullname");
            const shopNameInput = document.getElementById("shop-name-input");
            const shopPhoneInput = document.getElementById("shop-phone-input");

            if (phoneInput && (!phoneInput.value || phoneInput.value === "9876543210") && currentUser.phone) {
                phoneInput.value = currentUser.phone;
            }
            if (emailInput) {
                if (currentUser.email && !currentUser.email.includes("@user.apnakirana.in") && !currentUser.email.includes("@apnakirana.internal")) {
                    emailInput.value = currentUser.email;
                } else if (!emailInput.value || emailInput.value.includes("@user.apnakirana.in")) {
                    emailInput.value = "";
                }
            }
            if (nameInput && (!nameInput.value || nameInput.value.startsWith("Shopkeeper")) && currentUser.full_name) {
                nameInput.value = currentUser.full_name;
            }

            // Store information fields (Shop Name, Shop Address, Shop Phone) remain completely blank for new onboarding
            if (shopNameInput && (!currentUser.shop_profile || !currentUser.shop_profile.shop_name)) {
                shopNameInput.value = "";
            }
            const shopAddressInput = document.getElementById("shop-address-input");
            if (shopAddressInput && (!currentUser.shop_profile || !currentUser.shop_profile.shop_address)) {
                shopAddressInput.value = "";
            }
            if (shopPhoneInput && (!currentUser.shop_profile || !currentUser.shop_profile.shop_phone)) {
                shopPhoneInput.value = "";
            }
        }

        // Show onboarding guidance banner
        const obBanner = document.getElementById("profile-onboarding-banner");
        if (obBanner) obBanner.style.display = "flex";

        // Expand Personal Info card
        if (typeof window.expandExclusiveProfileCard === "function") {
            window.expandExclusiveProfileCard("profile-card-personal");
        } else {
            const personalCard = document.getElementById("profile-card-personal");
            if (personalCard) personalCard.classList.remove("collapsed");
        }
    }

    function showAuthView(viewName) {
        setEntryGateMode(true);
        const loginCard = document.getElementById("auth-login-card");
        const regCard = document.getElementById("auth-register-card");
        const forgotCard = document.getElementById("auth-forgot-card");
        const navTabs = document.getElementById("main-nav-tabs");

        // Hide all tab contents
        document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
        document.querySelectorAll(".nav-tab").forEach(el => el.classList.remove("active"));
        if (navTabs) navTabs.style.display = "none";

        if (loginCard) loginCard.style.display = (viewName === "login") ? "block" : "none";
        if (regCard) regCard.style.display = (viewName === "register") ? "block" : "none";
        if (forgotCard) forgotCard.style.display = (viewName === "forgot") ? "block" : "none";

        if (viewName === "forgot") {
            const loginIdent = document.getElementById("login-identifier");
            const forgotEmail = document.getElementById("forgot-email");
            if (loginIdent && forgotEmail && loginIdent.value.includes("@") && !forgotEmail.value) {
                forgotEmail.value = loginIdent.value.trim();
            }
            const msgBox = document.getElementById("forgot-password-message");
            if (msgBox) {
                msgBox.style.display = "none";
                msgBox.textContent = "";
            }
            if (window.AppUtils && window.AppUtils.clearAlert) {
                window.AppUtils.clearAlert("forgot-password-message");
                window.AppUtils.clearAlert("forgot-alert-box");
            }
        }

        const cardBox = document.querySelector(".auth-card-box");
        if (cardBox) {
            if (viewName === "register") {
                cardBox.classList.add("wide-mode");
            } else {
                cardBox.classList.remove("wide-mode");
            }
        }

        const path = viewName === "register" ? "/register" : (viewName === "forgot" ? "/forgot-password" : "/login");
        if (window.history && window.history.pushState && window.location.pathname !== path) {
            window.history.pushState({ path }, "", path);
        }
    }

    function navigateTo(path, updateHistory = true) {
        const cleanPath = (path || "/").toLowerCase().split("?")[0].replace(/\/+$/, "") || "/";
        const route = ROUTE_CONFIG[cleanPath] || ROUTE_CONFIG["/"];
        const token = window.getAuthToken ? window.getAuthToken() : localStorage.getItem("pos_auth_token");

        if (route.tab === "auth") {
            if (token) {
                switchTab("dashboard", updateHistory);
                return;
            }
            showAuthView(route.authView || "login");
            return;
        }

        if (!token) {
            showAuthView("login");
            return;
        }

        // Strict Onboarding Gate: If profile setup is not complete, lock to Profile tab
        if (!isProfileAndShopSetupComplete() && route.tab !== "profile" && route.tab !== "auth") {
            continueToProfileOnboarding();
            return;
        }

        setEntryGateMode(false);
        switchTab(route.tab, false);

        if (route.salesView && typeof window.switchSalesView === "function") {
            window.switchSalesView(route.salesView, false);
        }

        const targetUrl = cleanPath === "/" ? "/dashboard" : cleanPath;
        if (updateHistory && window.history && window.history.pushState) {
            if (window.location.pathname !== targetUrl) {
                window.history.pushState({ path: targetUrl }, "", targetUrl);
            }
        }
    }

    function switchTab(targetTab, updateHistory = true) {
        const token = window.getAuthToken ? window.getAuthToken() : localStorage.getItem("pos_auth_token");
        if (!token) {
            const p = window.location.pathname;
            if (p === "/register") {
                showAuthView("register");
            } else if (p === "/forgot-password") {
                showAuthView("forgot");
            } else {
                showAuthView("login");
            }
            return;
        }

        setEntryGateMode(false);
        const authContainer = document.getElementById("auth-container");
        if (authContainer) authContainer.style.display = "none";

        // Strict Onboarding Gate: If profile setup is not complete, lock to Profile tab
        const setupComplete = isProfileAndShopSetupComplete();
        if (!setupComplete) {
            targetTab = "profile";
            setOnboardingLock(true);
        } else {
            setOnboardingLock(false);
            const navTabs = document.getElementById("main-nav-tabs");
            if (navTabs) navTabs.style.display = "flex";
        }

        const tabButtons = document.querySelectorAll(".nav-tab");
        const tabContents = document.querySelectorAll(".tab-content");

        tabButtons.forEach(btn => btn.classList.remove("active"));
        tabContents.forEach(tab => tab.classList.remove("active"));

        const targetButton = document.querySelector(`.nav-tab[data-tab="${targetTab}"]`);
        if (targetButton) targetButton.classList.add("active");

        const activeContent = document.getElementById(`tab-${targetTab}`);
        if (activeContent) {
            activeContent.classList.add("active");
        }

        updateMobileNavActive(targetTab);
        toggleMobileNav(false);

        if (updateHistory && window.history && window.history.pushState) {
            const route = getRouteForTab(targetTab);
            if (window.location.pathname !== route) {
                window.history.pushState({ path: route }, "", route);
            }
        }

        // Trigger safe page-specific data load on tab switch
        try {
            if (targetTab === "dashboard" && typeof window.loadMainDashboard === "function") {
                window.loadMainDashboard();
            } else if (targetTab === "inventory") {
                if (typeof window.loadInventorySummary === "function") window.loadInventorySummary();
                if (typeof window.loadProducts === "function") window.loadProducts();
            } else if (targetTab === "udhaar" && typeof window.loadUdhaarDashboard === "function") {
                window.loadUdhaarDashboard();
            } else if (targetTab === "analytics" && typeof window.loadSalesHistoryDashboard === "function") {
                window.loadSalesHistoryDashboard();
            } else if (targetTab === "forecasting" && typeof window.loadForecastingDashboard === "function") {
                window.loadForecastingDashboard();
            } else if (targetTab === "profile" && typeof window.loadUserProfileData === "function") {
                window.loadUserProfileData();
            } else if (targetTab === "reports" && typeof window.initReports === "function") {
                window.initReports();
            }
        } catch (err) {
            console.error(`Error loading data for tab ${targetTab}:`, err);
        }
    }

    function toggleMobileNav(open) {
        const drawer = document.getElementById("mobile-nav-drawer");
        const backdrop = document.getElementById("mobile-nav-backdrop");
        const toggleBtn = document.getElementById("mobile-nav-toggle");

        const shouldOpen = (open !== undefined) ? open : (drawer && !drawer.classList.contains("open"));

        if (drawer) {
            if (shouldOpen) drawer.classList.add("open");
            else drawer.classList.remove("open");
        }
        if (backdrop) {
            if (shouldOpen) backdrop.classList.add("open");
            else backdrop.classList.remove("open");
        }
        if (toggleBtn) {
            toggleBtn.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
        }
    }

    function selectMobileTab(tabId) {
        switchTab(tabId, true);
        toggleMobileNav(false);
    }

    function updateMobileNavActive(activeTab) {
        const mobileItems = document.querySelectorAll(".mobile-nav-item");
        mobileItems.forEach(item => {
            if (item.dataset.tab === activeTab) {
                item.classList.add("active");
            } else {
                item.classList.remove("active");
            }
        });
    }

    function resolveInitialRoute(isAuthenticated) {
        const currentPath = window.location.pathname.toLowerCase();
        if (!isAuthenticated) {
            setEntryGateMode(true);
            if (currentPath === "/register") {
                showAuthView("register");
            } else if (currentPath === "/forgot-password") {
                showAuthView("forgot");
            } else {
                showAuthView("login");
            }
            return;
        }

        setEntryGateMode(false);
        const onboarded = isProfileAndShopSetupComplete();
        setOnboardingLock(!onboarded);

        if (currentPath === "/" || currentPath === "" || currentPath === "/login" || currentPath === "/register" || currentPath === "/forgot-password") {
            if (!onboarded) {
                // If onboarding not completed yet, direct to profile onboarding
                continueToProfileOnboarding();
            } else {
                if (window.history && window.history.replaceState) {
                    window.history.replaceState({ path: "/dashboard" }, "", "/dashboard");
                }
                switchTab("dashboard", false);
            }
        } else {
            if (!onboarded && currentPath !== "/profile") {
                continueToProfileOnboarding();
            } else {
                navigateTo(currentPath, false);
            }
        }
    }

    // ==============================================================================
    // Authentication Controllers & Header State
    // ==============================================================================
    function updateAuthHeaderUI(isAuthenticated) {
        const userHeaderEl = document.getElementById("auth-user-header");
        const guestHeaderEl = document.getElementById("auth-guest-header");
        const mobileLogoutBtn = document.getElementById("mobile-logout-btn");
        const navTabsEl = document.getElementById("main-nav-tabs");
        const dividerEl = document.getElementById("header-user-divider");
        const currentUser = window.currentAuthUser;
        const currentShop = window.currentShopProfile;

        if (isAuthenticated && currentUser) {
            if (userHeaderEl) userHeaderEl.style.display = "flex";
            if (dividerEl) dividerEl.style.display = "block";
            if (guestHeaderEl) guestHeaderEl.style.display = "none";
            if (mobileLogoutBtn) mobileLogoutBtn.style.display = "flex";
            if (navTabsEl) navTabsEl.style.display = "flex";

            const nameEl = document.getElementById("header-user-name");
            const shopEl = document.getElementById("header-shop-name");
            const avatarEl = document.getElementById("header-user-avatar");

            if (nameEl) nameEl.textContent = currentUser.full_name || "Shopkeeper";
            if (shopEl) {
                const sName = (currentShop && currentShop.shop_name) || (currentUser.shop_profile && currentUser.shop_profile.shop_name) || "Apna Store";
                shopEl.textContent = sName;
            }
            if (avatarEl) {
                const avatarUrl = currentUser.avatar_url;
                if (avatarUrl) {
                    const buster = window.AppState ? window.AppState.withCacheBuster(avatarUrl) : avatarUrl;
                    avatarEl.innerHTML = `<img src="${buster}" alt="Avatar" style="width:100%;height:100%;border-radius:50%;object-fit:cover;">`;
                } else {
                    const initial = (currentUser.full_name || "S").trim().charAt(0).toUpperCase();
                    avatarEl.textContent = initial || "S";
                }
            }
        } else {
            if (userHeaderEl) userHeaderEl.style.display = "none";
            if (dividerEl) dividerEl.style.display = "none";
            if (guestHeaderEl) guestHeaderEl.style.display = "flex";
            if (mobileLogoutBtn) mobileLogoutBtn.style.display = "none";
            if (navTabsEl) navTabsEl.style.display = "none";
            closeUserDropdown();
        }
    }

    // ==============================================================================
    // Header User Menu Dropdown Controller
    // ==============================================================================
    function toggleUserDropdown(event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        const dropdown = document.getElementById("header-user-dropdown");
        const userBtn = document.getElementById("header-user-btn");
        if (!dropdown) return;
        const isOpen = dropdown.style.display === "block";
        if (isOpen) {
            closeUserDropdown();
        } else {
            dropdown.style.display = "block";
            if (userBtn) {
                userBtn.setAttribute("aria-expanded", "true");
                userBtn.classList.add("dropdown-open");
            }
        }
    }

    function closeUserDropdown() {
        const dropdown = document.getElementById("header-user-dropdown");
        const userBtn = document.getElementById("header-user-btn");
        if (dropdown) dropdown.style.display = "none";
        if (userBtn) {
            userBtn.setAttribute("aria-expanded", "false");
            userBtn.classList.remove("dropdown-open");
        }
    }

    function navigateToProfileFromMenu() {
        closeUserDropdown();
        if (typeof window.navigateTo === "function") {
            window.navigateTo("/profile");
        } else if (typeof window.switchTab === "function") {
            window.switchTab("profile", true);
        }
    }

    async function checkAuthSession() {
        const token = window.getAuthToken ? window.getAuthToken() : localStorage.getItem("pos_auth_token");
        if (!token) {
            if (window.clearAuthToken) window.clearAuthToken();
            updateAuthHeaderUI(false);
            return false;
        }

        try {
            const res = await fetch("/api/v1/auth/me", {
                headers: { "Authorization": `Bearer ${token}` }
            });

            if (!res.ok) {
                if (window.clearAuthToken) window.clearAuthToken();
                updateAuthHeaderUI(false);
                return false;
            }

            const data = await res.json();
            const user = data.user || data;
            const shop = data.shop || (data.user && data.user.shop_profile) || data.shop_profile || null;
            if (user && window.syncUserDataAcrossUI) window.syncUserDataAcrossUI(user);
            if (shop && window.syncBusinessDataAcrossUI) window.syncBusinessDataAcrossUI(shop);
            updateAuthHeaderUI(true);
            return true;
        } catch (err) {
            console.warn("[App] Auth check network error:", err);
            return false;
        }
    }

    // Modal state for unregistered account redirection
    let _pendingUnregisteredData = null;

    function showAccountNotRegisteredModal(userData = null) {
        _pendingUnregisteredData = userData;
        const modal = document.getElementById("account-not-registered-modal");
        if (modal) {
            modal.style.display = "flex";
        }
    }

    function closeAccountNotRegisteredModal() {
        const modal = document.getElementById("account-not-registered-modal");
        if (modal) {
            modal.style.display = "none";
        }
    }

    function handleGoToRegister() {
        closeAccountNotRegisteredModal();
        showAuthView("register");

        // Prefill registration inputs if user already typed phone or email
        if (_pendingUnregisteredData) {
            if (_pendingUnregisteredData.identifier) {
                const ident = _pendingUnregisteredData.identifier.trim();
                const digits = ident.replace(/\D/g, "");
                if (digits.length === 10) {
                    const regPhone = document.getElementById("reg-phone");
                    if (regPhone) regPhone.value = digits;
                } else if (ident.includes("@")) {
                    const regEmail = document.getElementById("reg-email");
                    if (regEmail) regEmail.value = ident;
                }
            } else if (_pendingUnregisteredData.email) {
                const regEmail = document.getElementById("reg-email");
                if (regEmail) regEmail.value = _pendingUnregisteredData.email;
                if (_pendingUnregisteredData.displayName) {
                    const regName = document.getElementById("reg-fullname");
                    if (regName) regName.value = _pendingUnregisteredData.displayName;
                }
            }
        }
    }

    function showRegistrationSuccessBanner(message) {
        const loginAlertBox = document.getElementById("login-alert-box");
        if (loginAlertBox) {
            loginAlertBox.className = "alert-box alert-box-success";
            loginAlertBox.style.display = "block";
            loginAlertBox.style.background = "rgba(34, 197, 94, 0.12)";
            loginAlertBox.style.border = "1px solid rgba(34, 197, 94, 0.35)";
            loginAlertBox.style.borderRadius = "8px";
            loginAlertBox.style.padding = "0.75rem 1rem";
            loginAlertBox.style.color = "#15803d";
            loginAlertBox.style.marginBottom = "1rem";
            loginAlertBox.innerHTML = `
                <div style="display: flex; align-items: flex-start; gap: 0.65rem; text-align: left;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink: 0; color: #16a34a; margin-top: 2px;">
                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                        <polyline points="22 4 12 14.01 9 11.01"></polyline>
                    </svg>
                    <div>
                        <strong style="display: block; font-size: 0.92rem; margin-bottom: 2px;">Registration Successful!</strong>
                        <span style="font-size: 0.84rem; line-height: 1.4; color: inherit;">${message || "Please sign in now using the same Email/Mobile and Password you just registered with."}</span>
                    </div>
                </div>
            `;
        }
    }

    // Auth Form Handlers
    async function handleLoginSubmit(event) {
        if (event) event.preventDefault();
        const alertBoxId = "login-alert-box";
        if (window.AppUtils && window.AppUtils.clearAlert) window.AppUtils.clearAlert(alertBoxId);

        const identifier = (document.getElementById("login-identifier") ? document.getElementById("login-identifier").value : "").trim();
        const password = document.getElementById("login-password") ? document.getElementById("login-password").value : "";
        const submitBtn = document.getElementById("login-submit-btn");

        if (!identifier) {
            if (window.AppUtils) window.AppUtils.showAlert(alertBoxId, "Please enter your mobile phone or email.");
            return;
        }
        if (!password) {
            if (window.AppUtils) window.AppUtils.showAlert(alertBoxId, "Please enter your password.");
            return;
        }

        const btnText = submitBtn ? submitBtn.querySelector(".btn-text") : null;
        const btnSpinner = submitBtn ? submitBtn.querySelector(".btn-spinner") : null;
        if (btnText && btnSpinner) {
            btnText.style.display = "none";
            btnSpinner.style.display = "inline";
            submitBtn.disabled = true;
        }

        window.isAuthenticating = true;

        try {
            if (!window.AuthService && window.firebaseReady) {
                await window.firebaseReady;
            }
            if (!window.AuthService || typeof window.AuthService.login !== "function") {
                throw new Error("Authentication service is initializing. Please try again.");
            }

            const result = await window.AuthService.login(identifier, password);

            // Safe token extraction using optional chaining
            const token = result?.token || result?.access_token || result?.data?.token || (window.firebaseAuth?.currentUser ? await window.firebaseAuth.currentUser.getIdToken() : "local-session-token");
            const user = result?.user || result?.data?.user;

            // Clear in-memory caches and localStorage store items from any previous session
            if (typeof window.clearStoreDataCaches === "function") {
                window.clearStoreDataCaches();
            }

            if (token && window.setAuthToken) window.setAuthToken(token);
            if (user && window.syncUserDataAcrossUI) window.syncUserDataAcrossUI(user);
            if (user && user.shop_profile && window.syncBusinessDataAcrossUI) {
                window.syncBusinessDataAcrossUI(user.shop_profile);
            }
            updateAuthHeaderUI(true);

            if (window.playAudioTone) window.playAudioTone("success");

            const setupDone = isProfileAndShopSetupComplete();
            setOnboardingLock(!setupDone);

            // Step 1: Trigger Welcome Greeting Popup Modal
            showWelcomeGreetingModal(user || { phone: identifier });
        } catch (err) {
            if (err.code === "ACCOUNT_NOT_REGISTERED") {
                showAccountNotRegisteredModal({ identifier });
                return;
            }
            if (window.AppUtils) window.AppUtils.showAlert(alertBoxId, err.message || "Failed to sign in. Please try again.");
        } finally {
            window.isAuthenticating = false;
            if (btnText && btnSpinner) {
                btnText.style.display = "inline";
                btnSpinner.style.display = "none";
                submitBtn.disabled = false;
            }
        }
    }

    async function handleRegisterSubmit(event) {
        if (event) event.preventDefault();
        const alertBoxId = "register-alert-box";
        if (window.AppUtils && window.AppUtils.clearAlert) window.AppUtils.clearAlert(alertBoxId);

        const fullName = (document.getElementById("reg-fullname") ? document.getElementById("reg-fullname").value : "").trim();
        const shopName = (document.getElementById("reg-shopname") ? document.getElementById("reg-shopname").value : "").trim();
        const phone = (document.getElementById("reg-phone") ? document.getElementById("reg-phone").value : "").trim();
        const email = (document.getElementById("reg-email") ? document.getElementById("reg-email").value : "").trim();
        const password = document.getElementById("reg-password") ? document.getElementById("reg-password").value : "";
        const confirmPassword = document.getElementById("reg-confirmpassword") ? document.getElementById("reg-confirmpassword").value : "";
        const submitBtn = document.getElementById("reg-submit-btn");

        if (!fullName) {
            if (window.AppUtils) window.AppUtils.showAlert(alertBoxId, "Full name is required.");
            return;
        }
        const cleanPhone = phone.replace(/\D/g, "");
        if (cleanPhone.length !== 10) {
            if (window.AppUtils) window.AppUtils.showAlert(alertBoxId, "Please enter a valid 10-digit mobile number.");
            return;
        }
        if (password.length < 6) {
            if (window.AppUtils) window.AppUtils.showAlert(alertBoxId, "Password must be at least 6 characters.");
            return;
        }
        if (password !== confirmPassword) {
            if (window.AppUtils) window.AppUtils.showAlert(alertBoxId, "Passwords do not match.");
            return;
        }

        const btnText = submitBtn ? submitBtn.querySelector(".btn-text") : null;
        const btnSpinner = submitBtn ? submitBtn.querySelector(".btn-spinner") : null;
        if (btnText && btnSpinner) {
            btnText.style.display = "none";
            btnSpinner.style.display = "inline";
            submitBtn.disabled = true;
        }

        try {
            if (!window.AuthService && window.firebaseReady) {
                await window.firebaseReady;
            }
            if (!window.AuthService || typeof window.AuthService.registerNewStore !== "function") {
                throw new Error("Registration service is initializing. Please try again.");
            }

            // 1. Create account in Firebase & register metadata in backend master registry
            const regResult = await window.AuthService.registerNewStore({
                fullName,
                phone: cleanPhone,
                email: email || null,
                password,
                shopName
            });

            if (window.playAudioTone) window.playAudioTone("success");

            // 2. Switch the screen back to the "Shopkeeper Sign In" form
            showAuthView("login");

            // 3. Pre-fill their registered Email/Mobile
            const loginIdentInput = document.getElementById("login-identifier");
            if (loginIdentInput) {
                loginIdentInput.value = regResult.identifier || cleanPhone || email;
            }
            const loginPwdInput = document.getElementById("login-password");
            if (loginPwdInput) {
                loginPwdInput.value = "";
                setTimeout(() => loginPwdInput.focus(), 150);
            }

            // 4. Show prominent confirmation popup/banner
            showRegistrationSuccessBanner("Please sign in now using the same Email/Mobile and Password you just registered with.");

        } catch (err) {
            if (window.AppUtils) window.AppUtils.showAlert(alertBoxId, err.message || "Registration failed.");
        } finally {
            if (btnText && btnSpinner) {
                btnText.style.display = "inline";
                btnSpinner.style.display = "none";
                submitBtn.disabled = false;
            }
        }
    }

    /**
     * Firebase Native Password Reset Workflow
     * Sends password reset email via Firebase Auth sendPasswordResetEmail.
     */
    async function handleForgotPasswordSubmit(event) {
        if (event) event.preventDefault();

        const messageEl = document.getElementById("forgot-password-message") || document.getElementById("forgot-alert-box");
        const alertBoxId = messageEl ? messageEl.id : "forgot-password-message";

        if (window.AppUtils && window.AppUtils.clearAlert) {
            window.AppUtils.clearAlert("forgot-password-message");
            window.AppUtils.clearAlert("forgot-alert-box");
        } else if (messageEl) {
            messageEl.style.display = "none";
            messageEl.textContent = "";
        }

        const emailInput = document.getElementById("forgot-email") || document.getElementById("forgot-identifier");
        const rawEmail = (emailInput ? emailInput.value : "").trim();
        const submitBtn = document.getElementById("forgot-submit-btn") || document.getElementById("forgot-step1-btn");

        if (!rawEmail) {
            showForgotFeedback(alertBoxId, "Please enter your registered email address.", true);
            return;
        }

        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(rawEmail) && !/^\d{10}$/.test(rawEmail)) {
            showForgotFeedback(alertBoxId, "Invalid email format. Please enter a valid email address.", true);
            return;
        }

        const btnText = submitBtn ? submitBtn.querySelector(".btn-text") : null;
        const btnSpinner = submitBtn ? submitBtn.querySelector(".btn-spinner") : null;
        if (btnText && btnSpinner) {
            btnText.style.display = "none";
            btnSpinner.style.display = "inline";
            submitBtn.disabled = true;
        }

        try {
            if (!window.AuthService && window.firebaseReady) {
                await window.firebaseReady;
            }

            // Call native Firebase sendPasswordResetEmail
            if (window.AuthService && typeof window.AuthService.sendPasswordResetEmail === "function") {
                await window.AuthService.sendPasswordResetEmail(rawEmail);
            } else if (typeof window.sendPasswordResetEmail === "function" && window.firebaseAuth) {
                await window.sendPasswordResetEmail(window.firebaseAuth, rawEmail);
            } else {
                throw new Error("Authentication service is initializing. Please try again.");
            }

            // ON SUCCESS: Display a green success message in the status container
            showForgotFeedback(
                alertBoxId,
                "Success! A password reset link has been sent to your email. Please check your inbox, reset your password, and return here to log in.",
                false
            );

            if (window.playAudioTone) window.playAudioTone("success");
            if (emailInput) emailInput.value = "";
        } catch (err) {
            // ON ERROR: Catch the error and display a red error message
            let errMsg = err.message || "Failed to send password reset email.";
            const code = err.code || "";
            if (code === "auth/user-not-found") {
                errMsg = "Error: User not found with this email address.";
            } else if (code === "auth/invalid-email") {
                errMsg = "Error: Invalid email format. Please check your email address.";
            } else if (code === "auth/missing-email") {
                errMsg = "Error: Please enter your registered email address.";
            } else if (code === "auth/too-many-requests") {
                errMsg = "Error: Too many reset attempts. Please wait a few minutes before trying again.";
            } else if (code === "auth/network-request-failed") {
                errMsg = "Error: Network error. Please check your internet connection.";
            }
            showForgotFeedback(alertBoxId, errMsg, true);
        } finally {
            if (btnText && btnSpinner) {
                btnText.style.display = "inline";
                btnSpinner.style.display = "none";
                submitBtn.disabled = false;
            }
        }
    }

    function showForgotFeedback(boxId, msg, isError = true) {
        const box = document.getElementById(boxId) || document.getElementById("forgot-password-message") || document.getElementById("forgot-alert-box");
        if (!box) return;
        box.className = `alert-box ${isError ? 'alert-danger' : 'alert-success'}`;
        box.textContent = msg;
        box.style.display = "flex";
    }

    async function handleLogout() {
        closeUserDropdown();

        // 1. Stop any playing voice audio immediately
        if (typeof window.stopVoicePlayback === "function") {
            window.stopVoicePlayback();
        }

        // 2. Perform AuthService logout
        if (window.AuthService && typeof window.AuthService.logout === "function") {
            try {
                await window.AuthService.logout();
            } catch (e) {}
        } else {
            const token = window.getAuthToken ? window.getAuthToken() : localStorage.getItem("pos_auth_token");
            try {
                if (token) {
                    await fetch("/api/auth/logout", {
                        method: "POST",
                        headers: { "Authorization": `Bearer ${token}` }
                    });
                }
            } catch (err) {}
        }

        // 3. Clear all session tokens & onboarding flags
        if (window.clearAuthToken) window.clearAuthToken();
        localStorage.removeItem("pos_auth_token");
        localStorage.removeItem("access_token");
        localStorage.removeItem("shopkeeper_user");
        localStorage.removeItem("pos_onboarding_completed");
        window.currentAuthUser = null;
        window.currentShopProfile = null;

        // 4. Update Header UI & Return directly to Entry Gate
        updateAuthHeaderUI(false);
        if (window.playAudioTone) window.playAudioTone("success");
        setEntryGateMode(true);
        showAuthView("login");
    }

    // ==============================================================================
    // System Health Monitoring
    // ==============================================================================
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

    // ==============================================================================
    // Safe Module Initialization & App Bootstrap
    // ==============================================================================
    function initTabs() {
        const tabButtons = document.querySelectorAll(".nav-tab");
        tabButtons.forEach(button => {
            button.addEventListener("click", () => {
                const targetTab = button.dataset.tab;
                switchTab(targetTab, true);
            });
        });
    }

    function initAllModules() {
        const moduleInitializers = [
            { name: "AudioFeedback", fn: window.initAudioFeedback },
            { name: "Dashboard", fn: window.initDashboard || window.initMainDashboard },
            { name: "Billing", fn: window.initPOSBilling || window.initBilling },
            { name: "Inventory", fn: window.initInventory },
            { name: "Customers", fn: window.initCustomers || window.initUdhaarModule },
            { name: "Sales", fn: window.initSales || window.initSalesHistoryModule },
            { name: "Forecasting", fn: window.initForecasting || window.initForecastingModule },
            { name: "Reports", fn: window.initReports || window.initReportsModule },
            { name: "Profile", fn: window.initProfile || window.initProfileModule }
        ];

        moduleInitializers.forEach(mod => {
            try {
                if (typeof mod.fn === "function") {
                    mod.fn();
                } else {
                    console.info(`[App] ${mod.name} module initializer not registered or handled via auto-init.`);
                }
            } catch (err) {
                console.error(`[App] Error initializing ${mod.name} module:`, err);
            }
        });
    }

    // Popstate (Browser Back/Forward) Listener
    window.addEventListener("popstate", () => {
        const path = window.location.pathname.toLowerCase();
        const isAuth = !!(window.getAuthToken ? window.getAuthToken() : localStorage.getItem("pos_auth_token"));
        if (!isAuth) {
            if (path === "/register") {
                showAuthView("register");
            } else if (path === "/forgot-password") {
                showAuthView("forgot");
            } else {
                showAuthView("login");
            }
        } else {
            navigateTo(path, false);
        }
    });

    // Main Application Bootstrap on DOMContentLoaded
    document.addEventListener("DOMContentLoaded", async () => {
        initTabs();

        // Safe isolated module startup
        initAllModules();

        // System health checks
        checkHealth();
        setInterval(checkHealth, 20000);

        // Header user dropdown click-outside & Escape key handlers
        document.addEventListener("click", (event) => {
            const authUserHeader = document.getElementById("auth-user-header");
            if (authUserHeader && !authUserHeader.contains(event.target)) {
                closeUserDropdown();
            }
        });

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" || event.key === "Esc") {
                closeUserDropdown();
            }
        });

        // Resolve active user session & initial route
        const isAuth = await checkAuthSession();
        resolveInitialRoute(isAuth);
    });

    // ==============================================================================
    // Orchestrator Connection / Delegations for Billing & Udhaar 2FA
    // Connects orchestrator to billing.js module:
    // Elements: udhaar-verif-customer-name, udhaar-verif-customer-code, udhaar-verif-customer-phone, btn-thermal-print-direct
    // ==============================================================================
    function updateVerificationCustomerDisplay(customerInfo) {
        if (window.BillingModule && typeof window.BillingModule.updateVerificationCustomerDisplay === "function") {
            return window.BillingModule.updateVerificationCustomerDisplay(customerInfo);
        }
        const nameEl = document.getElementById("udhaar-verif-customer-name");
        const codeEl = document.getElementById("udhaar-verif-customer-code");
        const phoneEl = document.getElementById("udhaar-verif-customer-phone");
        if (customerInfo) {
            if (nameEl) nameEl.textContent = customerInfo.name || "--";
            if (codeEl) codeEl.textContent = customerInfo.code || "--";
            if (phoneEl) phoneEl.textContent = customerInfo.phoneMasked || "--";
        }
    }

    async function prepareDigitalReceiptDelivery(billId) {
        if (window.BillingModule && typeof window.BillingModule.prepareDigitalReceiptDelivery === "function") {
            return await window.BillingModule.prepareDigitalReceiptDelivery(billId);
        }
        const printBtn = document.getElementById("btn-thermal-print-direct");
        if (printBtn) printBtn.style.display = "inline-flex";
    }

    window.printThermalReceipt = async function() {
        if (window.BillingModule && typeof window.BillingModule.printThermalReceipt === "function") {
            return await window.BillingModule.printThermalReceipt();
        }
        const printBtn = document.getElementById("btn-thermal-print-direct");
        if (printBtn) printBtn.style.display = "inline-flex";
        window.print();
    };

    window.updateVerificationCustomerDisplay = updateVerificationCustomerDisplay;
    window.prepareDigitalReceiptDelivery = prepareDigitalReceiptDelivery;

    async function handleGoogleSignIn() {
        const alertBoxId = "login-alert-box";
        if (window.AppUtils && window.AppUtils.clearAlert) window.AppUtils.clearAlert(alertBoxId);

        const googleLoginBtn = document.getElementById("google-login-btn");
        const googleRegBtn = document.getElementById("google-register-btn");
        if (googleLoginBtn) googleLoginBtn.disabled = true;
        if (googleRegBtn) googleRegBtn.disabled = true;

        try {
            if (!window.AuthService && window.firebaseReady) {
                await window.firebaseReady;
            }
            if (!window.AuthService || typeof window.AuthService.loginWithGoogle !== "function") {
                throw new Error("Authentication service is initializing. Please try again.");
            }

            const result = await window.AuthService.loginWithGoogle();
            const token = result?.token || result?.access_token || result?.data?.token;
            const user = result?.user || result?.data?.user;

            // Clear in-memory caches and localStorage store items from any previous session
            if (typeof window.clearStoreDataCaches === "function") {
                window.clearStoreDataCaches();
            }

            if (token && window.setAuthToken) window.setAuthToken(token);
            if (user && window.syncUserDataAcrossUI) window.syncUserDataAcrossUI(user);
            if (user && user.shop_profile && window.syncBusinessDataAcrossUI) {
                window.syncBusinessDataAcrossUI(user.shop_profile);
            }
            updateAuthHeaderUI(true);

            if (window.playAudioTone) window.playAudioTone("success");
            showWelcomeGreetingModal(user || { full_name: user?.full_name || "Shopkeeper" });
        } catch (err) {
            if (err.code === "auth/popup-closed-by-user") return;
            if (err.code === "ACCOUNT_NOT_REGISTERED") {
                showAccountNotRegisteredModal(err.googleUser || null);
                return;
            }
            if (window.AppUtils) {
                window.AppUtils.showAlert(alertBoxId, err.message || "Google Sign-In failed. Please try again.");
            }
        } finally {
            if (googleLoginBtn) googleLoginBtn.disabled = false;
            if (googleRegBtn) googleRegBtn.disabled = false;
        }
    }

    function autoFillDemoCredentials() {
        const identInput = document.getElementById("login-identifier");
        const pwdInput = document.getElementById("login-password");
        if (identInput) identInput.value = "9876543210";
        if (pwdInput) pwdInput.value = "Password@123";
        if (typeof window.showToast === "function") {
            window.showToast("Demo credentials populated!", "info");
        }
    }

    // Global Orchestrator Exports
    window.navigateTo = navigateTo;
    window.switchTab = switchTab;
    window.showAuthView = showAuthView;
    window.toggleMobileNav = toggleMobileNav;
    window.selectMobileTab = selectMobileTab;
    window.updateAuthHeaderUI = updateAuthHeaderUI;
    window.toggleUserDropdown = toggleUserDropdown;
    window.closeUserDropdown = closeUserDropdown;
    window.navigateToProfileFromMenu = navigateToProfileFromMenu;
    window.checkHealth = checkHealth;
    window.checkBackendHealth = checkHealth;
    window.handleLoginSubmit = handleLoginSubmit;
    window.handleGoogleSignIn = handleGoogleSignIn;
    window.handleRegisterSubmit = handleRegisterSubmit;
    window.handleForgotPasswordSubmit = handleForgotPasswordSubmit;
    window.handleForgotStep1 = handleForgotPasswordSubmit; // Backward-compatible alias
    window.handleForgotStep2 = handleForgotPasswordSubmit; // Backward-compatible alias
    window.handleLogout = handleLogout;
    window.setEntryGateMode = setEntryGateMode;
    window.showWelcomeGreetingModal = showWelcomeGreetingModal;
    window.continueToProfileOnboarding = continueToProfileOnboarding;
    window.autoFillDemoCredentials = autoFillDemoCredentials;
    window.showAccountNotRegisteredModal = showAccountNotRegisteredModal;
    window.closeAccountNotRegisteredModal = closeAccountNotRegisteredModal;
    window.handleGoToRegister = handleGoToRegister;
    window.showRegistrationSuccessBanner = showRegistrationSuccessBanner;
    window.isProfileAndShopSetupComplete = isProfileAndShopSetupComplete;
    window.setOnboardingLock = setOnboardingLock;

})(window);

