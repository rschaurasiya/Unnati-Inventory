/**
 * Profile, Settings & Identity Module
 * Manages shopkeeper personal profile, shop business details, security & passwords,
 * store localization preferences, and interactive image upload with crop/resize workflow.
 */

(function(window) {
    'use strict';

    // Cropper State
    let cropperState = {
        activeType: null, // "avatar" or "logo"
        image: null,
        imgWidth: 0,
        imgHeight: 0,
        scale: 1.0,
        minScale: 0.5,
        maxScale: 3.0,
        offsetX: 0,
        offsetY: 0,
        isDragging: false,
        dragStartX: 0,
        dragStartY: 0,
        cropSize: 180 // Diameter/width of crop zone for compact 100% zoom layout
    };

    function initProfileModule() {
        initImageCropper();
        initProfileAccordions();

        // Wire up unified master onboarding submit button (Phase 2 & Phase 3)
        const masterSubmitBtn = document.getElementById("master-onboarding-submit");
        if (masterSubmitBtn) {
            masterSubmitBtn.removeEventListener("click", handleMasterOnboardingSubmit);
            masterSubmitBtn.addEventListener("click", handleMasterOnboardingSubmit);
        }

        // Attach listeners to clear error highlight when user edits inputs
        const monitoredFieldIds = [
            "prof-fullname", "prof-phone", "shop-name-input",
            "shop-address-input", "shop-phone-input", "setting-currency", "setting-unit"
        ];
        monitoredFieldIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener("input", () => el.classList.remove("input-error-highlight"));
                el.addEventListener("change", () => el.classList.remove("input-error-highlight"));
            }
        });

        // Listen for profile changes across tabs or windows
        window.addEventListener("shop-profile-updated", (e) => {
            const shop = e.detail;
            if (shop) populateShopForm(shop);
        });

        window.addEventListener("user-profile-updated", (e) => {
            const user = e.detail;
            if (user) populatePersonalForm(user);
        });
    }

    function toggleExclusiveProfileAccordion(targetCard) {
        if (!targetCard) return;
        const willOpen = targetCard.classList.contains("collapsed");
        const allCards = document.querySelectorAll(".profile-card");

        // Collapse all other containers so only one is open
        allCards.forEach(c => {
            c.classList.add("collapsed");
            const h = c.querySelector(".profile-card-header");
            const pt = c.querySelector(".accordion-pill-text");
            const ct = c.querySelector(".accordion-caret");
            if (h) h.setAttribute("aria-expanded", "false");
            if (pt) pt.textContent = "Expand";
            if (ct) ct.textContent = "⌄";
        });

        // If target card was collapsed, expand it exclusively
        if (willOpen) {
            targetCard.classList.remove("collapsed");
            const header = targetCard.querySelector(".profile-card-header");
            const pillText = targetCard.querySelector(".accordion-pill-text");
            const caret = targetCard.querySelector(".accordion-caret");
            if (header) header.setAttribute("aria-expanded", "true");
            if (pillText) pillText.textContent = "Collapse";
            if (caret) caret.textContent = "‸";
        }
    }

    function expandExclusiveProfileCard(cardId) {
        const allCards = document.querySelectorAll(".profile-card");
        allCards.forEach(c => {
            c.classList.add("collapsed");
            const h = c.querySelector(".profile-card-header");
            const pt = c.querySelector(".accordion-pill-text");
            const ct = c.querySelector(".accordion-caret");
            if (h) h.setAttribute("aria-expanded", "false");
            if (pt) pt.textContent = "Expand";
            if (ct) ct.textContent = "⌄";
        });

        const target = typeof cardId === "string" ? document.getElementById(cardId) : cardId;
        if (target) {
            target.classList.remove("collapsed");
            const header = target.querySelector(".profile-card-header");
            const pillText = target.querySelector(".accordion-pill-text");
            const caret = target.querySelector(".accordion-caret");
            if (header) header.setAttribute("aria-expanded", "true");
            if (pillText) pillText.textContent = "Collapse";
            if (caret) caret.textContent = "‸";
        }
    }


    function initProfileAccordions() {
        const cards = document.querySelectorAll(".profile-card");
        cards.forEach(card => {
            const header = card.querySelector(".profile-card-header");
            const pillText = card.querySelector(".accordion-pill-text");
            const caret = card.querySelector(".accordion-caret");
            if (!header || header.dataset.accordionInit === "true") return;
            header.dataset.accordionInit = "true";

            // Default state: collapsed
            if (card.classList.contains("collapsed")) {
                if (pillText) pillText.textContent = "Expand";
                if (caret) caret.textContent = "⌄";
                header.setAttribute("aria-expanded", "false");
            } else {
                if (pillText) pillText.textContent = "Collapse";
                if (caret) caret.textContent = "‸";
                header.setAttribute("aria-expanded", "true");
            }

            header.addEventListener("click", (e) => {
                if (e.target.closest("button:not(.profile-card-header)") || e.target.closest("input") || e.target.closest("label") || e.target.closest("textarea")) return;
                toggleExclusiveProfileAccordion(card);
            });

            header.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    toggleExclusiveProfileAccordion(card);
                }
            });
        });

        if (!window._profileAccordionDelegated) {
            window._profileAccordionDelegated = true;
            document.addEventListener("click", (e) => {
                const header = e.target.closest(".profile-card-header");
                if (!header) return;
                if (e.target.closest("button:not(.profile-card-header)") || e.target.closest("input") || e.target.closest("label") || e.target.closest("textarea")) return;
                const card = header.closest(".profile-card");
                if (!card) return;
                if (header.dataset.accordionInit !== "true") {
                    header.dataset.accordionInit = "true";
                    toggleExclusiveProfileAccordion(card);
                }
            });
        }
    }

    function initImageCropper() {
        const stage = document.getElementById("cropper-stage");
        const canvas = document.getElementById("cropper-canvas");
        const zoomRange = document.getElementById("cropper-zoom-range");
        const btnZoomIn = document.getElementById("cropper-btn-zoom-in");
        const btnZoomOut = document.getElementById("cropper-btn-zoom-out");
        const btnReset = document.getElementById("cropper-btn-reset");
        const btnConfirm = document.getElementById("btn-cropper-confirm");

        if (!stage || !canvas) return;

        // Pointer / Touch Drag handlers for panning
        stage.addEventListener("mousedown", onDragStart);
        window.addEventListener("mousemove", onDragMove);
        window.addEventListener("mouseup", onDragEnd);

        stage.addEventListener("touchstart", onTouchStart, { passive: false });
        window.addEventListener("touchmove", onTouchMove, { passive: false });
        window.addEventListener("touchend", onDragEnd);

        // Zoom slider
        if (zoomRange) {
            zoomRange.addEventListener("input", (e) => {
                cropperState.scale = parseFloat(e.target.value);
                drawCropper();
            });
        }

        if (btnZoomIn) {
            btnZoomIn.addEventListener("click", () => {
                cropperState.scale = Math.min(cropperState.maxScale, cropperState.scale + 0.15);
                if (zoomRange) zoomRange.value = cropperState.scale.toFixed(2);
                drawCropper();
            });
        }

        if (btnZoomOut) {
            btnZoomOut.addEventListener("click", () => {
                cropperState.scale = Math.max(cropperState.minScale, cropperState.scale - 0.15);
                if (zoomRange) zoomRange.value = cropperState.scale.toFixed(2);
                drawCropper();
            });
        }

        if (btnReset) {
            btnReset.addEventListener("click", () => {
                resetCropperTransform();
                drawCropper();
            });
        }

        if (btnConfirm) {
            btnConfirm.addEventListener("click", handleConfirmCropUpload);
        }
    }

    function onDragStart(e) {
        if (!cropperState.image) return;
        cropperState.isDragging = true;
        cropperState.dragStartX = e.clientX - cropperState.offsetX;
        cropperState.dragStartY = e.clientY - cropperState.offsetY;
    }

    function onDragMove(e) {
        if (!cropperState.isDragging) return;
        cropperState.offsetX = e.clientX - cropperState.dragStartX;
        cropperState.offsetY = e.clientY - cropperState.dragStartY;
        drawCropper();
    }

    function onTouchStart(e) {
        if (!cropperState.image || e.touches.length !== 1) return;
        e.preventDefault();
        cropperState.isDragging = true;
        const touch = e.touches[0];
        cropperState.dragStartX = touch.clientX - cropperState.offsetX;
        cropperState.dragStartY = touch.clientY - cropperState.offsetY;
    }

    function onTouchMove(e) {
        if (!cropperState.isDragging || e.touches.length !== 1) return;
        e.preventDefault();
        const touch = e.touches[0];
        cropperState.offsetX = touch.clientX - cropperState.dragStartX;
        cropperState.offsetY = touch.clientY - cropperState.dragStartY;
        drawCropper();
    }

    function onDragEnd() {
        cropperState.isDragging = false;
    }

    function resetCropperTransform() {
        const canvas = document.getElementById("cropper-canvas");
        const canvasW = canvas ? canvas.width : 240;
        const canvasH = canvas ? canvas.height : 240;

        if (cropperState.imgWidth > 0 && cropperState.imgHeight > 0) {
            // Fit initial scale so crop area is covered
            const scaleX = cropperState.cropSize / cropperState.imgWidth;
            const scaleY = cropperState.cropSize / cropperState.imgHeight;
            const fitScale = Math.max(scaleX, scaleY, 0.8);
            cropperState.scale = Math.min(Math.max(fitScale, 0.5), 2.0);
        } else {
            cropperState.scale = 1.0;
        }

        cropperState.offsetX = canvasW / 2;
        cropperState.offsetY = canvasH / 2;

        const zoomRange = document.getElementById("cropper-zoom-range");
        if (zoomRange) zoomRange.value = cropperState.scale.toFixed(2);
    }

    function drawCropper() {
        const canvas = document.getElementById("cropper-canvas");
        if (!canvas || !cropperState.image) return;
        const ctx = canvas.getContext("2d");
        const w = canvas.width;
        const h = canvas.height;

        ctx.clearRect(0, 0, w, h);
        ctx.save();

        // Translate to image center position
        ctx.translate(cropperState.offsetX, cropperState.offsetY);
        ctx.scale(cropperState.scale, cropperState.scale);

        // Draw image centered at origin
        ctx.drawImage(
            cropperState.image,
            -cropperState.imgWidth / 2,
            -cropperState.imgHeight / 2,
            cropperState.imgWidth,
            cropperState.imgHeight
        );

        ctx.restore();

        // Update previews
        updatePreviews();
    }

    function updatePreviews() {
        const previewCircle = document.getElementById("cropper-preview-canvas");
        const previewSquare = document.getElementById("cropper-preview-square-canvas");
        const mainCanvas = document.getElementById("cropper-canvas");
        if (!mainCanvas || !previewCircle || !previewSquare) return;

        const cropSize = cropperState.cropSize;
        const cropX = (mainCanvas.width - cropSize) / 2;
        const cropY = (mainCanvas.height - cropSize) / 2;

        // 1. Circle preview
        const cCtx = previewCircle.getContext("2d");
        cCtx.clearRect(0, 0, previewCircle.width, previewCircle.height);
        cCtx.save();
        cCtx.beginPath();
        cCtx.arc(previewCircle.width / 2, previewCircle.height / 2, previewCircle.width / 2, 0, Math.PI * 2);
        cCtx.clip();
        cCtx.drawImage(
            mainCanvas,
            cropX, cropY, cropSize, cropSize,
            0, 0, previewCircle.width, previewCircle.height
        );
        cCtx.restore();

        // 2. Square preview
        const sCtx = previewSquare.getContext("2d");
        sCtx.clearRect(0, 0, previewSquare.width, previewSquare.height);
        sCtx.drawImage(
            mainCanvas,
            cropX, cropY, cropSize, cropSize,
            0, 0, previewSquare.width, previewSquare.height
        );
    }

    /**
     * Switch preview option and stage guide between circle and square
     */
    function setCropperPreviewMode(mode) {
        cropperState.previewMode = mode;
        const btnCircle = document.getElementById("btn-preview-circle");
        const btnSquare = document.getElementById("btn-preview-square");
        const colCircle = document.getElementById("col-preview-circle");
        const colSquare = document.getElementById("col-preview-square");
        const ringEl = document.getElementById("cropper-guide-ring");

        if (mode === "circle") {
            if (btnCircle) btnCircle.classList.add("active");
            if (btnSquare) btnSquare.classList.remove("active");
            if (colCircle) colCircle.classList.add("active-preview");
            if (colSquare) colSquare.classList.remove("active-preview");
            if (ringEl) ringEl.classList.remove("guide-square");
        } else {
            if (btnSquare) btnSquare.classList.add("active");
            if (btnCircle) btnCircle.classList.remove("active");
            if (colSquare) colSquare.classList.add("active-preview");
            if (colCircle) colCircle.classList.remove("active-preview");
            if (ringEl) ringEl.classList.add("guide-square");
        }
    }

    /**
     * Open Cropper Modal for file
     */
    function openImageCropper(file, type = "avatar") {
        const modal = document.getElementById("image-cropper-modal");
        const titleEl = document.getElementById("cropper-modal-title");
        const subtitleEl = document.getElementById("cropper-modal-subtitle");
        const ringEl = document.getElementById("cropper-guide-ring");
        const errEl = document.getElementById("cropper-modal-error");

        if (errEl) errEl.style.display = "none";
        cropperState.activeType = type;

        if (titleEl) {
            titleEl.textContent = type === "avatar" ? "Crop & Resize Profile Photo" : "Crop & Resize Shop Logo";
        }
        if (subtitleEl) {
            subtitleEl.textContent = type === "avatar"
                ? "Position photo inside circle mask. Drag to move, slider to zoom."
                : "Position logo inside square mask. Drag to move, slider to zoom.";
        }

        if (type === "avatar") {
            setCropperPreviewMode("circle");
        } else {
            setCropperPreviewMode("square");
        }


        // Validate image format & size
        if (window.AppUtils && typeof window.AppUtils.validateImageFile === "function") {
            const check = window.AppUtils.validateImageFile(file);
            if (!check.valid) {
                const boxId = type === "avatar" ? "personal-alert-box" : "shop-alert-box";
                if (window.AppUtils.showAlert) window.AppUtils.showAlert(boxId, check.error);
                return;
            }
        } else {
            if (!file.type.startsWith("image/")) {
                alert("Please select a valid image file (PNG, JPG, WebP).");
                return;
            }
            if (file.size > 5 * 1024 * 1024) {
                alert("Image size must be less than 5MB.");
                return;
            }
        }

        // Load image into memory
        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                cropperState.image = img;
                cropperState.imgWidth = img.naturalWidth || img.width;
                cropperState.imgHeight = img.naturalHeight || img.height;

                resetCropperTransform();
                drawCropper();

                if (modal) modal.style.display = "flex";
            };
            img.onerror = () => {
                const boxId = type === "avatar" ? "personal-alert-box" : "shop-alert-box";
                if (window.AppUtils && window.AppUtils.showAlert) {
                    window.AppUtils.showAlert(boxId, "Unable to read image file. It may be corrupted.");
                } else {
                    alert("Unable to read image file.");
                }
            };
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);
    }

    function closeImageCropperModal() {
        const modal = document.getElementById("image-cropper-modal");
        if (modal) modal.style.display = "none";
        cropperState.image = null;

        // Reset file input so selecting same file again triggers change event
        const avInp = document.getElementById("profile-avatar-input");
        const logoInp = document.getElementById("shop-logo-input");
        if (avInp) avInp.value = "";
        if (logoInp) logoInp.value = "";
    }

    /**
     * Render high-resolution cropped canvas, export Blob, and upload to server
     */
    async function handleConfirmCropUpload() {
        if (!cropperState.image) return;
        const btnConfirm = document.getElementById("btn-cropper-confirm");
        const errEl = document.getElementById("cropper-modal-error");
        if (errEl) errEl.style.display = "none";

        if (btnConfirm) {
            btnConfirm.disabled = true;
            btnConfirm.textContent = "Saving...";
        }

        try {
            // Render high-res 400x400 output canvas
            const outputCanvas = document.createElement("canvas");
            const outputDim = 400;
            outputCanvas.width = outputDim;
            outputCanvas.height = outputDim;
            const outCtx = outputCanvas.getContext("2d");

            const mainCanvas = document.getElementById("cropper-canvas");
            const cropSize = cropperState.cropSize;
            const cropX = (mainCanvas.width - cropSize) / 2;
            const cropY = (mainCanvas.height - cropSize) / 2;

            // Draw cropped area scaled up with smooth interpolation
            outCtx.imageSmoothingEnabled = true;
            outCtx.imageSmoothingQuality = "high";
            outCtx.drawImage(
                mainCanvas,
                cropX, cropY, cropSize, cropSize,
                0, 0, outputDim, outputDim
            );

            // Convert to JPEG/PNG blob
            const blob = await new Promise((resolve, reject) => {
                outputCanvas.toBlob(b => b ? resolve(b) : reject(new Error("Failed to process cropped image.")), "image/jpeg", 0.92);
            });

            const token = window.getAuthToken ? window.getAuthToken() : localStorage.getItem("pos_auth_token");
            const formData = new FormData();

            if (cropperState.activeType === "avatar") {
                formData.append("file", blob, "avatar.jpg");
                const res = await fetch("/api/v1/auth/upload-avatar", {
                    method: "POST",
                    headers: token ? { "Authorization": `Bearer ${token}` } : {},
                    body: formData
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || "Failed to upload avatar.");

                closeImageCropperModal();

                // Synchronize user photo across entire application
                const freshUrl = data.avatar_url;
                if (window.currentAuthUser) {
                    window.currentAuthUser.avatar_url = freshUrl;
                    if (window.syncUserDataAcrossUI) window.syncUserDataAcrossUI(window.currentAuthUser);
                } else if (window.syncUserDataAcrossUI) {
                    window.syncUserDataAcrossUI({ avatar_url: freshUrl });
                }

                if (window.AppUtils && window.AppUtils.showAlert) {
                    window.AppUtils.showAlert("personal-alert-box", "Profile photo updated successfully!", false);
                }
                if (window.showToast) window.showToast("Profile Photo Updated", "success");
                if (window.playAudioTone) window.playAudioTone("success");

            } else {
                // Shop Logo
                formData.append("file", blob, "shop_logo.jpg");
                const res = await fetch("/api/v1/auth/upload-logo", {
                    method: "POST",
                    headers: token ? { "Authorization": `Bearer ${token}` } : {},
                    body: formData
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || "Failed to upload shop logo.");

                closeImageCropperModal();

                // Synchronize shop logo across entire application & receipts
                const freshLogoUrl = data.shop_logo_url || data.logo_url;
                if (window.currentShopProfile) {
                    window.currentShopProfile.shop_logo_url = freshLogoUrl;
                    if (window.syncBusinessDataAcrossUI) window.syncBusinessDataAcrossUI(window.currentShopProfile);
                } else if (window.syncBusinessDataAcrossUI) {
                    window.syncBusinessDataAcrossUI({ shop_logo_url: freshLogoUrl });
                }

                if (window.AppUtils && window.AppUtils.showAlert) {
                    window.AppUtils.showAlert("shop-alert-box", "Shop logo updated successfully!", false);
                }
                if (window.showToast) window.showToast("Shop Logo Updated", "success");
                if (window.playAudioTone) window.playAudioTone("success");
            }

        } catch (err) {
            console.error("Image crop and upload error:", err);
            if (errEl) {
                errEl.textContent = err.message;
                errEl.style.display = "block";
            }
        } finally {
            if (btnConfirm) {
                btnConfirm.disabled = false;
                btnConfirm.textContent = "Crop & Save";
            }
        }
    }

    // Input file selected handlers
    function handleAvatarFileSelected(event) {
        const file = event.target.files && event.target.files[0];
        if (!file) return;
        openImageCropper(file, "avatar");
    }

    function handleLogoFileSelected(event) {
        const file = event.target.files && event.target.files[0];
        if (!file) return;
        openImageCropper(file, "logo");
    }

    // Helper alerts
    function showAlert(boxId, msg, isError = true) {
        if (window.AppUtils && typeof window.AppUtils.showAlert === "function") {
            window.AppUtils.showAlert(boxId, msg, isError);
            return;
        }
        const box = document.getElementById(boxId);
        if (!box) return;
        box.className = `alert-box ${isError ? 'alert-danger' : 'alert-success'}`;
        box.textContent = msg;
        box.style.display = "flex";
    }

    function clearAlert(boxId) {
        if (window.AppUtils && typeof window.AppUtils.clearAlert === "function") {
            window.AppUtils.clearAlert(boxId);
            return;
        }
        const box = document.getElementById(boxId);
        if (box) {
            box.style.display = "none";
            box.textContent = "";
        }
    }

    function populatePersonalForm(user) {
        if (!user) return;
        const nameEl = document.getElementById("prof-fullname");
        const phoneEl = document.getElementById("prof-phone");
        const emailEl = document.getElementById("prof-email");
        const roleEl = document.getElementById("prof-role");
        const lastLoginEl = document.getElementById("prof-last-login");
        const avatarPrev = document.getElementById("profile-avatar-preview");

        if (nameEl && user.full_name) nameEl.value = user.full_name;
        if (phoneEl && user.phone) phoneEl.value = user.phone;
        if (emailEl) emailEl.value = user.email || "";
        if (roleEl) roleEl.value = user.role || "Store Owner";
        if (lastLoginEl) {
            lastLoginEl.value = user.last_login_at
                ? new Date(user.last_login_at).toLocaleString()
                : "Active Now";
        }
        if (avatarPrev && user.avatar_url) {
            const buster = window.AppState ? window.AppState.withCacheBuster(user.avatar_url) : user.avatar_url;
            avatarPrev.src = buster;
        }
    }

    function populateShopForm(shop) {
        const nameInp = document.getElementById("shop-name-input");
        const gstinInp = document.getElementById("shop-gstin-input");
        const addrInp = document.getElementById("shop-address-input");
        const phoneInp = document.getElementById("shop-phone-input");
        const emailInp = document.getElementById("shop-email-input");
        const logoPrev = document.getElementById("shop-logo-preview");

        if (!shop) {
            if (nameInp) nameInp.value = "";
            if (gstinInp) gstinInp.value = "";
            if (addrInp) addrInp.value = "";
            if (phoneInp) phoneInp.value = "";
            if (emailInp) emailInp.value = "";
            return;
        }

        // When backend returns empty strings, ensure the store input fields remain completely empty
        if (nameInp) nameInp.value = (shop.shop_name && typeof shop.shop_name === "string") ? shop.shop_name : "";
        if (gstinInp) gstinInp.value = shop.gstin || "";
        if (addrInp) addrInp.value = shop.shop_address || "";
        if (phoneInp) phoneInp.value = shop.shop_phone || "";
        if (emailInp) emailInp.value = shop.shop_email || "";
        if (logoPrev && shop.shop_logo_url) {
            const buster = window.AppState ? window.AppState.withCacheBuster(shop.shop_logo_url) : shop.shop_logo_url;
            logoPrev.src = buster;
        }

        // Settings inputs
        const currInp = document.getElementById("setting-currency");
        const tzInp = document.getElementById("setting-timezone");
        const unitInp = document.getElementById("setting-unit");
        const minInp = document.getElementById("setting-min-stock");
        const footerInp = document.getElementById("setting-footer");

        if (currInp && shop.currency) currInp.value = shop.currency;
        if (tzInp && shop.timezone) tzInp.value = shop.timezone;
        if (unitInp && shop.default_measurement_unit) unitInp.value = shop.default_measurement_unit;
        if (minInp && shop.default_min_stock_threshold !== undefined) minInp.value = shop.default_min_stock_threshold;
        if (footerInp && shop.invoice_footer !== undefined) footerInp.value = shop.invoice_footer;
    }

    // Profile & Settings Loader
    async function loadUserProfileData() {
        clearAlert("personal-alert-box");
        clearAlert("shop-alert-box");
        clearAlert("security-alert-box");
        clearAlert("settings-alert-box");

        try {
            const authFetcher = window.authFetch || fetch;
            const res = await authFetcher("/api/v1/auth/me");
            if (!res.ok) return;
            const data = await res.json();
            const user = data.user || data;
            const shop = data.shop || (data.user && data.user.shop_profile) || data.shop_profile || null;

            if (user && window.syncUserDataAcrossUI) window.syncUserDataAcrossUI(user);
            if (shop && window.syncBusinessDataAcrossUI) window.syncBusinessDataAcrossUI(shop);

            populatePersonalForm(user);
            populateShopForm(shop);

            if (typeof window.updateAuthHeaderUI === "function") {
                window.updateAuthHeaderUI(true);
            }

            // Phase 1 check: Determine if user profile & shop setup is complete
            const isComplete = (typeof window.isProfileAndShopSetupComplete === "function")
                ? window.isProfileAndShopSetupComplete()
                : (localStorage.getItem("pos_onboarding_completed") === "true");

            if (typeof window.setOnboardingLock === "function") {
                window.setOnboardingLock(!isComplete);
            }

            if (!isComplete) {
                // Ensure the first container is open for clear, seamless onboarding completion
                expandExclusiveProfileCard("profile-card-personal");
            }
        } catch (err) {
            showAlert("personal-alert-box", "Failed to load profile data: " + err.message);
        }
    }

    // Form submission handlers
    async function handlePersonalProfileSubmit(event) {
        if (event) event.preventDefault();
        clearAlert("personal-alert-box");

        const fullName = (document.getElementById("prof-fullname") ? document.getElementById("prof-fullname").value : "").trim();
        const phone = (document.getElementById("prof-phone") ? document.getElementById("prof-phone").value : "").trim();
        const email = (document.getElementById("prof-email") ? document.getElementById("prof-email").value : "").trim();
        const submitBtn = document.getElementById("btn-save-personal");

        if (!fullName) {
            showAlert("personal-alert-box", "Full name is required.");
            return;
        }

        const cleanPhone = phone.replace(/\D/g, "");
        if (cleanPhone.length !== 10) {
            showAlert("personal-alert-box", "Mobile number must be exactly 10 digits.");
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
            const authFetcher = window.authFetch || fetch;
            const res = await authFetcher("/api/v1/auth/profile", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    full_name: fullName,
                    phone: cleanPhone,
                    email: email || null
                })
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Failed to update profile.");

            if (window.syncUserDataAcrossUI) window.syncUserDataAcrossUI(data);
            if (typeof window.updateAuthHeaderUI === "function") window.updateAuthHeaderUI(true);

            // Complete onboarding, emit event and auto-redirect to dashboard
            localStorage.setItem('pos_onboarding_completed', 'true');
            if (window.AppEvents && typeof window.AppEvents.emit === "function") {
                window.AppEvents.emit("profile-updated", data);
            }
            const obBanner = document.getElementById("profile-onboarding-banner");
            if (obBanner) obBanner.style.display = "none";

            showAlert("personal-alert-box", "Personal details saved successfully! Redirecting to Dashboard...", false);
            if (window.showToast) window.showToast("Personal Info Saved! Redirecting...", "success");
            if (window.playAudioTone) window.playAudioTone("success");

            setTimeout(() => {
                if (typeof window.navigateTo === "function") {
                    window.navigateTo("/");
                } else if (typeof window.switchTab === "function") {
                    window.switchTab("dashboard", true);
                }
            }, 800);

        } catch (err) {
            showAlert("personal-alert-box", err.message || "Failed to update profile.");
        } finally {
            if (btnText && btnSpinner) {
                btnText.style.display = "inline";
                btnSpinner.style.display = "none";
                submitBtn.disabled = false;
            }
        }
    }

    async function handleShopProfileSubmit(event) {
        if (event) event.preventDefault();
        clearAlert("shop-alert-box");

        const shopName = (document.getElementById("shop-name-input") ? document.getElementById("shop-name-input").value : "").trim();
        const gstin = (document.getElementById("shop-gstin-input") ? document.getElementById("shop-gstin-input").value : "").trim();
        const shopAddress = (document.getElementById("shop-address-input") ? document.getElementById("shop-address-input").value : "").trim();
        const shopPhone = (document.getElementById("shop-phone-input") ? document.getElementById("shop-phone-input").value : "").trim();
        const shopEmail = (document.getElementById("shop-email-input") ? document.getElementById("shop-email-input").value : "").trim();
        const submitBtn = document.getElementById("btn-save-shop");

        if (!shopName) {
            showAlert("shop-alert-box", "Shop name is required.");
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
            const authFetcher = window.authFetch || fetch;
            const res = await authFetcher("/api/v1/auth/shop", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    shop_name: shopName,
                    shop_address: shopAddress,
                    gstin: gstin || null,
                    shop_phone: shopPhone || null,
                    shop_email: shopEmail || null
                })
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Failed to update shop details.");

            if (window.syncBusinessDataAcrossUI) window.syncBusinessDataAcrossUI(data);
            if (typeof window.updateAuthHeaderUI === "function") window.updateAuthHeaderUI(true);

            // Complete onboarding, emit event and auto-redirect to dashboard
            localStorage.setItem('pos_onboarding_completed', 'true');
            if (window.AppEvents && typeof window.AppEvents.emit === "function") {
                window.AppEvents.emit("profile-updated", data);
            }
            const obBannerShop = document.getElementById("profile-onboarding-banner");
            if (obBannerShop) obBannerShop.style.display = "none";

            showAlert("shop-alert-box", "Shop details updated successfully! Redirecting to Dashboard...", false);
            if (window.showToast) window.showToast("Shop Details Saved! Redirecting...", "success");
            if (window.playAudioTone) window.playAudioTone("success");

            setTimeout(() => {
                if (typeof window.navigateTo === "function") {
                    window.navigateTo("/");
                } else if (typeof window.switchTab === "function") {
                    window.switchTab("dashboard", true);
                }
            }, 800);

        } catch (err) {
            showAlert("shop-alert-box", err.message || "Failed to update shop details.");
        } finally {
            if (btnText && btnSpinner) {
                btnText.style.display = "inline";
                btnSpinner.style.display = "none";
                submitBtn.disabled = false;
            }
        }
    }

    async function handleChangePasswordSubmit(event) {
        if (event) event.preventDefault();
        clearAlert("security-alert-box");

        const currentPassword = document.getElementById("pwd-current") ? document.getElementById("pwd-current").value : "";
        const newPassword = document.getElementById("pwd-new") ? document.getElementById("pwd-new").value : "";
        const confirmNewPassword = document.getElementById("pwd-confirm") ? document.getElementById("pwd-confirm").value : "";
        const submitBtn = document.getElementById("btn-change-password");

        if (!currentPassword) {
            showAlert("security-alert-box", "Please enter your current password.");
            return;
        }
        if (newPassword.length < 6) {
            showAlert("security-alert-box", "New password must be at least 6 characters.");
            return;
        }
        if (newPassword !== confirmNewPassword) {
            showAlert("security-alert-box", "New password and confirmation do not match.");
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
            const authFetcher = window.authFetch || fetch;
            const res = await authFetcher("/api/v1/auth/change-password", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    current_password: currentPassword,
                    new_password: newPassword,
                    confirm_new_password: confirmNewPassword
                })
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Failed to change password.");

            showAlert("security-alert-box", "Password updated successfully!", false);
            if (window.showToast) window.showToast("Password Updated Successfully", "success");
            if (window.playAudioTone) window.playAudioTone("success");
            const pwdF = document.getElementById("change-password-form"); if (pwdF) pwdF.reset();

        } catch (err) {
            showAlert("security-alert-box", err.message || "Failed to update password.");
        } finally {
            if (btnText && btnSpinner) {
                btnText.style.display = "inline";
                btnSpinner.style.display = "none";
                submitBtn.disabled = false;
            }
        }
    }

    async function handleShopSettingsSubmit(event) {
        if (event) event.preventDefault();
        clearAlert("settings-alert-box");

        const elCurr = document.getElementById("setting-currency"); const currency = (elCurr ? elCurr.value : "") || "₹";
        const elTz = document.getElementById("setting-timezone"); const timezone = (elTz ? elTz.value : "") || "Asia/Kolkata";
        const elUnit = document.getElementById("setting-unit"); const unit = (elUnit ? elUnit.value : "") || "kg";
        const elMin = document.getElementById("setting-min-stock"); const minStock = parseFloat((elMin ? elMin.value : "") || "10");
        const elFooter = document.getElementById("setting-footer"); const footer = (elFooter ? elFooter.value : "").trim();
        const submitBtn = document.getElementById("btn-save-settings");

        const btnText = submitBtn ? submitBtn.querySelector(".btn-text") : null;
        const btnSpinner = submitBtn ? submitBtn.querySelector(".btn-spinner") : null;
        if (btnText && btnSpinner) {
            btnText.style.display = "none";
            btnSpinner.style.display = "inline";
            submitBtn.disabled = true;
        }

        try {
            const authFetcher = window.authFetch || fetch;
            const res = await authFetcher("/api/v1/auth/settings", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    currency,
                    timezone,
                    default_measurement_unit: unit,
                    default_min_stock_threshold: minStock,
                    invoice_footer: footer
                })
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Failed to save settings.");

            if (window.syncBusinessDataAcrossUI) window.syncBusinessDataAcrossUI(data);
            showAlert("settings-alert-box", "Store preferences saved successfully!", false);
            if (window.showToast) window.showToast("Store Preferences Saved", "success");
            if (window.playAudioTone) window.playAudioTone("success");

        } catch (err) {
            showAlert("settings-alert-box", err.message || "Failed to save settings.");
        } finally {
            if (btnText && btnSpinner) {
                btnText.style.display = "inline";
                btnSpinner.style.display = "none";
                submitBtn.disabled = false;
            }
        }
    }

    /**
     * Cross-Container Validation & Unified Master Onboarding Submission (Phase 3 & Phase 4)
     * Performs strict validation across Personal Info, Shop & Business Details, and Settings.
     * Executes PUT /api/v1/auth/profile, PUT /api/v1/auth/shop, and PUT /api/v1/auth/settings.
     * Updates AppState, unlocks navigation tabs, shows toast, and redirects to /dashboard.
     */
    async function handleMasterOnboardingSubmit(event) {
        if (event) event.preventDefault();

        // 1. Clear previous error highlights and alert banner
        document.querySelectorAll(".input-error-highlight").forEach(el => el.classList.remove("input-error-highlight"));
        const alertBox = document.getElementById("master-onboarding-alert");
        if (alertBox) {
            alertBox.style.display = "none";
            alertBox.textContent = "";
            alertBox.className = "alert-box alert-danger";
        }

        const showMasterError = (fieldId, cardId, message) => {
            expandExclusiveProfileCard(cardId);
            const field = document.getElementById(fieldId);
            if (field) {
                field.classList.add("input-error-highlight");
                field.focus();
                try {
                    field.scrollIntoView({ behavior: "smooth", block: "center" });
                } catch (e) {}
            }
            if (alertBox) {
                alertBox.className = "alert-box alert-danger";
                alertBox.textContent = message || "Please fill in all required fields (e.g., Shop Name, Shop Address) before continuing.";
                alertBox.style.display = "block";
            }
            if (window.showToast) window.showToast(message, "error");
            if (window.playAudioTone) window.playAudioTone("error");
        };

        // 2. Cross-Container Validation
        // A. Personal Info: full_name (required), phone (required, 10 digits)
        const fullName = (document.getElementById("prof-fullname") ? document.getElementById("prof-fullname").value : "").trim();
        const phone = (document.getElementById("prof-phone") ? document.getElementById("prof-phone").value : "").trim();
        const email = (document.getElementById("prof-email") ? document.getElementById("prof-email").value : "").trim();

        if (!fullName) {
            showMasterError("prof-fullname", "profile-card-personal", "Please fill in all required fields (e.g., Full Name) before continuing.");
            return;
        }

        const cleanPhone = phone.replace(/\D/g, "");
        if (!phone || cleanPhone.length !== 10) {
            showMasterError("prof-phone", "profile-card-personal", "Please enter a valid 10-digit mobile number.");
            return;
        }

        // B. Shop & Business Details: shop_name (required), shop_address (required), shop_phone (required)
        const shopName = (document.getElementById("shop-name-input") ? document.getElementById("shop-name-input").value : "").trim();
        const shopAddress = (document.getElementById("shop-address-input") ? document.getElementById("shop-address-input").value : "").trim();
        const shopPhone = (document.getElementById("shop-phone-input") ? document.getElementById("shop-phone-input").value : "").trim();
        const gstin = (document.getElementById("shop-gstin-input") ? document.getElementById("shop-gstin-input").value : "").trim();
        const shopEmail = (document.getElementById("shop-email-input") ? document.getElementById("shop-email-input").value : "").trim();

        if (!shopName) {
            showMasterError("shop-name-input", "profile-card-shop", "Please fill in all required fields (e.g., Shop Name, Shop Address) before continuing.");
            return;
        }

        if (!shopAddress) {
            showMasterError("shop-address-input", "profile-card-shop", "Please fill in all required fields (e.g., Shop Name, Shop Address) before continuing.");
            return;
        }

        const cleanShopPhone = shopPhone.replace(/\D/g, "");
        if (!shopPhone || cleanShopPhone.length < 10) {
            showMasterError("shop-phone-input", "profile-card-shop", "Please enter a valid shop phone number (at least 10 digits).");
            return;
        }

        // C. Settings & Preferences: Ensure default units and currency are selected
        const elCurr = document.getElementById("setting-currency");
        const currency = (elCurr ? elCurr.value : "").trim() || "₹";
        const elUnit = document.getElementById("setting-unit");
        const unit = (elUnit ? elUnit.value : "").trim() || "kg";
        const elTz = document.getElementById("setting-timezone");
        const timezone = (elTz ? elTz.value : "").trim() || "Asia/Kolkata";
        const elMin = document.getElementById("setting-min-stock");
        const minStock = parseFloat((elMin ? elMin.value : "").trim() || "10");
        const elFooter = document.getElementById("setting-footer");
        const footer = (elFooter ? elFooter.value : "").trim();

        if (!currency) {
            showMasterError("setting-currency", "profile-card-settings", "Please select a currency.");
            return;
        }

        if (!unit) {
            showMasterError("setting-unit", "profile-card-settings", "Please select a default measurement unit.");
            return;
        }

        // 3. Update Button State
        const submitBtn = document.getElementById("master-onboarding-submit");
        const btnText = submitBtn ? submitBtn.querySelector(".btn-text") : null;
        const btnSpinner = submitBtn ? submitBtn.querySelector(".btn-spinner") : null;
        if (btnText && btnSpinner) {
            btnText.style.display = "none";
            btnSpinner.style.display = "inline";
        } else if (submitBtn) {
            submitBtn.textContent = "Saving Profile...";
        }
        if (submitBtn) submitBtn.disabled = true;

        try {
            const authFetcher = window.authFetch || fetch;

            // Sequential / Promise.all PUT execution
            const [resProfile, resShop, resSettings] = await Promise.all([
                authFetcher("/api/v1/auth/profile", {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        full_name: fullName,
                        phone: cleanPhone,
                        email: email || null
                    })
                }),
                authFetcher("/api/v1/auth/shop", {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        shop_name: shopName,
                        shop_address: shopAddress,
                        gstin: gstin || null,
                        shop_phone: cleanShopPhone,
                        shop_email: shopEmail || null
                    })
                }),
                authFetcher("/api/v1/auth/settings", {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        currency: currency,
                        timezone: timezone,
                        default_measurement_unit: unit,
                        default_min_stock_threshold: minStock,
                        invoice_footer: footer
                    })
                })
            ]);

            if (!resProfile.ok) {
                const errData = await resProfile.json();
                throw new Error(errData.detail || "Failed to update personal profile.");
            }
            if (!resShop.ok) {
                const errData = await resShop.json();
                throw new Error(errData.detail || "Failed to update shop details.");
            }
            if (!resSettings.ok) {
                const errData = await resSettings.json();
                throw new Error(errData.detail || "Failed to update settings.");
            }

            const dataProfile = await resProfile.json();
            const dataShop = await resShop.json();
            const dataSettings = await resSettings.json();

            // Synchronize application state & caches
            if (window.syncUserDataAcrossUI) window.syncUserDataAcrossUI(dataProfile);
            if (window.syncBusinessDataAcrossUI) window.syncBusinessDataAcrossUI(dataShop);
            if (window.AppState) {
                if (typeof window.AppState.setUser === "function") window.AppState.setUser(dataProfile);
                if (typeof window.AppState.setShop === "function") window.AppState.setShop(dataShop);
            }
            if (typeof window.updateAuthHeaderUI === "function") {
                window.updateAuthHeaderUI(true);
            }

            // Mark user as fully onboarded in AppState & localStorage
            localStorage.setItem("pos_onboarding_completed", "true");

            if (window.AppEvents && typeof window.AppEvents.emit === "function") {
                window.AppEvents.emit("profile-updated", {
                    user: dataProfile,
                    shop: dataShop,
                    settings: dataSettings
                });
            }

            // Phase 4: Dynamically unlock tabs and drawer
            if (typeof window.setOnboardingLock === "function") {
                window.setOnboardingLock(false);
            } else {
                document.body.classList.remove("onboarding-locked");
                const navTabs = document.getElementById("main-nav-tabs");
                if (navTabs) {
                    navTabs.style.removeProperty("display");
                    navTabs.style.removeProperty("pointer-events");
                    navTabs.style.display = "flex";
                }
            }

            // Hide onboarding banner & master container
            const obBanner = document.getElementById("profile-onboarding-banner");
            if (obBanner) obBanner.style.display = "none";
            const masterCont = document.getElementById("onboarding-master-container");
            if (masterCont) masterCont.style.display = "none";

            // Success feedback
            if (alertBox) {
                alertBox.className = "alert-box alert-success";
                alertBox.textContent = "Profile setup complete! Redirecting to Dashboard...";
                alertBox.style.display = "block";
            }
            if (window.showToast) window.showToast("Profile setup complete!", "success");
            if (window.playAudioTone) window.playAudioTone("success");

            // Redirect automatically to Dashboard
            setTimeout(() => {
                if (typeof window.navigateTo === "function") {
                    window.navigateTo("/dashboard");
                } else if (typeof window.switchTab === "function") {
                    window.switchTab("dashboard", true);
                }
            }, 600);

        } catch (err) {
            if (alertBox) {
                alertBox.className = "alert-box alert-danger";
                alertBox.textContent = err.message || "Failed to complete setup. Please check your inputs and try again.";
                alertBox.style.display = "block";
            }
            if (window.showToast) window.showToast(err.message || "Failed to complete setup.", "error");
            if (window.playAudioTone) window.playAudioTone("error");
        } finally {
            if (btnText && btnSpinner) {
                btnText.style.display = "inline";
                btnSpinner.style.display = "none";
            } else if (submitBtn) {
                submitBtn.textContent = "Complete Profile & Launch Dashboard";
            }
            if (submitBtn) submitBtn.disabled = false;
        }
    }

    const ProfileModule = {
        init: initProfileModule,
        initAccordions: initProfileAccordions,
        expandExclusiveCard: expandExclusiveProfileCard,
        loadUserProfileData,
        handlePersonalProfileSubmit,
        handleShopProfileSubmit,
        handleChangePasswordSubmit,
        handleShopSettingsSubmit,
        handleMasterOnboardingSubmit,
        handleAvatarFileSelected,
        handleLogoFileSelected,
        openImageCropper,
        closeImageCropperModal
    };

    window.ProfileModule = ProfileModule;
    window.initProfile = initProfileModule;
    window.initProfileModule = initProfileModule;
    window.initProfileAccordions = initProfileAccordions;
    window.expandExclusiveProfileCard = expandExclusiveProfileCard;
    window.loadUserProfileData = loadUserProfileData;
    window.handlePersonalProfileSubmit = handlePersonalProfileSubmit;
    window.handleShopProfileSubmit = handleShopProfileSubmit;
    window.handleChangePasswordSubmit = handleChangePasswordSubmit;
    window.handleShopSettingsSubmit = handleShopSettingsSubmit;
    window.handleMasterOnboardingSubmit = handleMasterOnboardingSubmit;
    window.handleAvatarFileSelected = handleAvatarFileSelected;
    window.handleLogoFileSelected = handleLogoFileSelected;
    window.openImageCropper = openImageCropper;
    window.closeImageCropperModal = closeImageCropperModal;
    window.setCropperPreviewMode = setCropperPreviewMode;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initProfileAccordions);
    } else {
        initProfileAccordions();
    }

})(window);
