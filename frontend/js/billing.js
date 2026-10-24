/**
 * POS Voice Billing & Checkout Module
 * Handles Web Speech voice order parsing, draft bills, line item calculations,
 * customer 2FA challenge verification, digital receipt preparation,
 * and POS Udhaar OTP verification flows.
 */

(function(window) {
    'use strict';

let currentDraft = null;
let currentIdempotencyKey = null;
let isFinalizing = false;
let speechRecognizer = null;
let isListening = false;
let currentVoiceLanguage = localStorage.getItem("pos_voice_lang") || "hinglish";
let allCatalogProductsCache = [];

function generateFreshIdempotencyKey(prefix = "pos") {
    const timestamp = Date.now();
    const randomHex = Math.random().toString(36).substring(2, 9);
    return `${prefix}-${timestamp}-${randomHex}`;
}

const LANGUAGE_CONFIG = {
    english: {
        code: "en-IN",
        label: "Lang: English",
        hint: 'Supports English: <em>"2 kg sugar and 1 packet milk"</em>',
        placeholder: "Speak into mic or type order here (e.g. 2 kg sugar and 1 packet milk)...",
        chips: [
            { text: "2 kg sugar and 1 packet milk", label: '"2 kg sugar, 1 packet milk"' },
            { text: "Half kg mustard oil", label: '"Half kg mustard oil"' },
            { text: "2.5 kg rice and 3 packets maggi", label: '"2.5 kg rice, 3 maggi"' },
            { text: "1 kg sugar", label: '"1 kg sugar"' },
            { text: "1 kg dragonfruit", label: '"1 kg dragonfruit" (Unmatched test)', warn: true }
        ]
    },
    hinglish: {
        code: "en-IN",
        label: "Lang: Hinglish",
        hint: 'Supports Hindi & Hinglish: <em>"Do kilo cheeni aur ek packet doodh"</em>',
        placeholder: "Speak into mic or type order here (e.g. Do kilo cheeni aur ek packet doodh)...",
        chips: [
            { text: "Do kilo cheeni aur ek packet doodh", label: '"Do kilo cheeni, ek packet doodh"' },
            { text: "Aadha kilo sarson tel", label: '"Aadha kilo sarson tel"' },
            { text: "Dhai kilo chawal aur teen packet maggi", label: '"Dhai kilo chawal, teen maggi"' },
            { text: "ek kilo chini", label: '"ek kilo chini"' },
            { text: "ek kilo dragonfruit", label: '"ek kilo dragonfruit" (Unmatched test)', warn: true }
        ]
    },
    hindi: {
        code: "hi-IN",
        label: "Lang: हिन्दी",
        hint: 'हिन्दी समर्थित: <em>"दो किलो चीनी और एक पैकेट दूध"</em>',
        placeholder: "माइक में बोलें या यहाँ आर्डर लिखें (जैसे: दो किलो चीनी और एक पैकेट दूध)...",
        chips: [
            { text: "दो किलो चीनी और एक पैकेट दूध", label: '"दो किलो चीनी, एक पैकेट दूध"' },
            { text: "आधा किलो सरसों तेल", label: '"आधा किलो सरसों तेल"' },
            { text: "ढाई किलो चावल और तीन पैकेट मैगी", label: '"ढाई किलो चावल, तीन मैगी"' },
            { text: "एक किलो चीनी", label: '"एक किलो चीनी"' },
            { text: "एक किलो ड्रैगनफ्रूट", label: '"एक किलो ड्रैगनफ्रूट" (Unmatched test)', warn: true }
        ]
    }
};

function setMicVisualState(state) {
    const micBtn = document.getElementById("mic-toggle-btn");
    const micWrapper = document.getElementById("mic-pulsing-wrapper");
    const micLabel = document.getElementById("mic-btn-label");
    const sttBadge = document.getElementById("stt-status-badge");
    const audioWave = document.getElementById("audio-status-wave");

    if (state === "listening") {
        if (micBtn) micBtn.classList.add("recording");
        if (micWrapper) micWrapper.classList.add("active");
        if (audioWave) audioWave.style.display = "flex";
        if (micLabel) micLabel.textContent = "Listening... Speak order now";
        if (sttBadge) {
            sttBadge.className = "badge badge-listening";
            sttBadge.textContent = "Listening...";
        }
    } else if (state === "parsing") {
        if (micBtn) micBtn.classList.remove("recording");
        if (micWrapper) micWrapper.classList.remove("active");
        if (audioWave) audioWave.style.display = "none";
        if (micLabel) micLabel.textContent = "Tap to Speak Order";
        if (sttBadge) {
            sttBadge.className = "badge badge-parsing";
            sttBadge.textContent = "Parsing Order...";
        }
    } else if (state === "matched") {
        if (micBtn) micBtn.classList.remove("recording");
        if (micWrapper) micWrapper.classList.remove("active");
        if (audioWave) audioWave.style.display = "none";
        if (micLabel) micLabel.textContent = "Tap to Speak Order";
        if (sttBadge) {
            sttBadge.className = "badge badge-matched";
            sttBadge.textContent = "Matched";
        }
    } else { // "ready"
        if (micBtn) micBtn.classList.remove("recording");
        if (micWrapper) micWrapper.classList.remove("active");
        if (audioWave) audioWave.style.display = "none";
        if (micLabel) micLabel.textContent = "Tap to Speak Order";
        if (sttBadge) {
            sttBadge.className = "badge badge-ready";
            sttBadge.textContent = "Voice: Ready";
        }
    }
}


function stopListening() {
    if (isListening && speechRecognizer) {
        try { speechRecognizer.stop(); } catch(e){}
    }
    if (isListening) {
        playAudioTone("mic-stop");
    }
    isListening = false;
    setMicVisualState("ready");
}

function toggleVoiceRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition && !speechRecognizer) {
        alert("Web Speech API is not supported in this browser. Please type the order or click a test chip below.");
        return;
    }
    if (!speechRecognizer && SpeechRecognition) {
        try {
            speechRecognizer = new SpeechRecognition();
            speechRecognizer.continuous = false;
            speechRecognizer.interimResults = false;
            speechRecognizer.lang = (LANGUAGE_CONFIG[currentVoiceLanguage] && LANGUAGE_CONFIG[currentVoiceLanguage].code) || "en-IN";
            speechRecognizer.onstart = () => {
                isListening = true;
                playAudioTone("mic-start");
                setMicVisualState("listening");
            };
            speechRecognizer.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                const textInput = document.getElementById("order-text-input");
                if (textInput) textInput.value = transcript;
                stopListening();
                setMicVisualState("parsing");
                generateDraftBill(transcript);
            };
            speechRecognizer.onerror = (event) => {
                console.warn("Speech recognition notice:", event.error);
                stopListening();
                setMicVisualState("ready");
            };
            speechRecognizer.onend = () => {
                stopListening();
            };
        } catch(e) {
            console.warn("Speech recognition init error:", e);
        }
    }
    if (isListening) {
        stopListening();
    } else if (speechRecognizer) {
        try {
            speechRecognizer.lang = (LANGUAGE_CONFIG[currentVoiceLanguage] && LANGUAGE_CONFIG[currentVoiceLanguage].code) || "en-IN";
            speechRecognizer.start();
        } catch (err) {
            console.error("Failed to start speech recognition:", err);
            stopListening();
        }
    }
}
window.stopListening = stopListening;
window.toggleVoiceRecognition = toggleVoiceRecognition;

function selectVoiceLanguage(lang) {
    if (!LANGUAGE_CONFIG[lang]) lang = "hinglish";
    currentVoiceLanguage = lang;
    try {
        localStorage.setItem("pos_voice_lang", lang);
    } catch(e){}

    const config = LANGUAGE_CONFIG[lang];

    // Speech Recognition Language Sync:
    // If recognition is active when switching tabs, restart with new lang setting
    if (speechRecognizer) {
        const wasListening = isListening;
        if (wasListening) {
            try {
                speechRecognizer.stop();
            } catch(e){}
            isListening = false;
        }
        try {
            speechRecognizer.lang = config.code;
        } catch(e){}
        if (wasListening) {
            setTimeout(() => {
                try {
                    speechRecognizer.start();
                    isListening = true;
                    setMicVisualState("listening");
                } catch(e){
                    setMicVisualState("ready");
                }
            }, 180);
        }
    }

    // Move blue .active highlight class to clicked language tab
    const tabBtns = document.querySelectorAll(".pos-lang-tab-btn, [data-lang]");
    tabBtns.forEach(btn => {
        const isMatch = btn.dataset && btn.dataset.lang === lang;
        btn.classList.toggle("active", isMatch);
        btn.setAttribute("aria-selected", isMatch ? "true" : "false");
    });

    // Update top badge text immediately (Lang: English, Lang: Hinglish, or Lang: हिन्दी)
    const langBadge = document.getElementById("pos-active-lang-badge");
    if (langBadge) {
        langBadge.textContent = config.label;
    }

    // Update helper text below "Tap to Speak Order"
    const hintText = document.getElementById("voice-hint-text");
    if (hintText) hintText.innerHTML = config.hint;

    // Update textarea placeholder
    const textInput = document.getElementById("order-text-input");
    if (textInput) textInput.placeholder = config.placeholder;

    // Update Quick Test Voice Inputs buttons (guarded)
    const chipsContainer = document.getElementById("sample-chips-container");
    if (chipsContainer && config.chips) {
        chipsContainer.innerHTML = config.chips.map(c => `
            <button type="button" class="chip-btn ${c.warn ? "chip-warn" : ""}" data-text="${escapeHtml(c.text)}">${escapeHtml(c.label)}</button>
        `).join("");

        chipsContainer.querySelectorAll(".chip-btn").forEach(chip => {
            chip.addEventListener("click", () => {
                const sampleText = chip.dataset.text;
                if (textInput) textInput.value = sampleText;
                generateDraftBill(sampleText);
            });
        });
    }
}

// Global window exports for immediate accessibility
const switchVoiceLanguage = selectVoiceLanguage;
window.selectVoiceLanguage = selectVoiceLanguage;
window.switchVoiceLanguage = selectVoiceLanguage;

// Initial execution to sync active language immediately
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
        selectVoiceLanguage(currentVoiceLanguage);
    });
} else {
    selectVoiceLanguage(currentVoiceLanguage);
}

async function loadCatalogForQuickSearch() {
    try {
        const res = await fetch("/api/v1/products");
        if (res.ok) {
            allCatalogProductsCache = await res.json();
            renderPosProductCatalog(window.activePosCategory || "All");
        }
    } catch(e) {
        console.warn("Could not load catalog products for search:", e);
    }
}

function selectPosCategory(category) {
    window.activePosCategory = category;
    const searchInput = document.getElementById("draft-quick-product-search");
    const q = searchInput ? searchInput.value.trim() : "";
    renderPosProductCatalog(category, q);
}

function renderPosProductCatalog(category = "All", searchQuery = "") {
    const pillsContainer = document.getElementById("pos-category-pills");
    const gridContainer = document.getElementById("pos-quick-product-grid");
    if (!gridContainer) return;

    if (!allCatalogProductsCache || allCatalogProductsCache.length === 0) {
        gridContainer.innerHTML = `<div style="grid-column: 1 / -1; padding: 1.25rem; color: var(--text-secondary); font-size: 0.85rem; text-align: center;">Loading catalog products...</div>`;
        return;
    }

    // Extract categories
    const categories = ["All", ...new Set(allCatalogProductsCache.map(p => p.category || "General").filter(Boolean))];
    if (pillsContainer) {
        pillsContainer.innerHTML = categories.map(cat => `
            <button type="button" class="pos-cat-pill ${cat === category ? 'active' : ''}" onclick="selectPosCategory('${escapeHtml(cat)}')">
                ${escapeHtml(cat)}
            </button>
        `).join("");
    }

    // Filter products
    let prods = allCatalogProductsCache;
    if (category && category !== "All") {
        prods = prods.filter(p => (p.category || "General") === category);
    }
    if (searchQuery) {
        const q = searchQuery.toLowerCase();
        prods = prods.filter(p => 
            (p.name || "").toLowerCase().includes(q) ||
            (p.hindi_name || "").toLowerCase().includes(q) ||
            (p.aliases || "").toLowerCase().includes(q)
        );
    }

    if (prods.length === 0) {
        gridContainer.innerHTML = `<div style="grid-column: 1 / -1; padding: 1.25rem; color: var(--text-secondary); font-size: 0.85rem; text-align: center;">No catalog items match "${escapeHtml(searchQuery)}"</div>`;
        return;
    }

    gridContainer.innerHTML = prods.map(p => {
        const isOutOfStock = (p.stock_quantity <= 0);
        const isLow = (p.is_low_stock || p.stock_quantity <= p.min_stock_threshold);
        let badgeHtml = '';
        if (isOutOfStock) {
            badgeHtml = `<span class="badge badge-out-stock" style="font-size: 0.68rem; padding: 1px 5px;">0 ${escapeHtml(p.unit || '')} (Out)</span>`;
        } else if (isLow) {
            badgeHtml = `<span class="badge badge-low-stock" style="font-size: 0.68rem; padding: 1px 5px;">${p.stock_quantity} ${escapeHtml(p.unit || '')}</span>`;
        } else {
            badgeHtml = `<span class="badge badge-in-stock" style="font-size: 0.68rem; padding: 1px 5px;">${p.stock_quantity} ${escapeHtml(p.unit || '')}</span>`;
        }

        return `
            <div class="pos-prod-card ${isOutOfStock ? 'pos-prod-card-disabled' : ''}" 
                 ${isOutOfStock ? 'style="opacity: 0.5; cursor: not-allowed;" title="Out of stock — cannot add"' : `onclick="quickAddProductToDraft(${p.id})" title="Click to add 1 unit to draft bill"`}>
                <div class="pos-prod-top">
                    <span class="pos-prod-name">${escapeHtml(p.name)}</span>
                    ${p.hindi_name ? `<span class="pos-prod-hindi">${escapeHtml(p.hindi_name)}</span>` : ''}
                </div>
                <div class="pos-prod-bottom">
                    <span class="pos-prod-price">₹${p.unit_price.toFixed(2)}</span>
                    ${badgeHtml}
                </div>
            </div>
        `;
    }).join("");
}

function initQuickProductSearch() {
    const searchInput = document.getElementById("draft-quick-product-search");
    const dropdown = document.getElementById("draft-search-dropdown");
    if (!searchInput || !dropdown) return;

    loadCatalogForQuickSearch();

    searchInput.addEventListener("input", (e) => {
        const q = e.target.value.trim().toLowerCase();
        renderPosProductCatalog(window.activePosCategory || "All", q);

        if (!q) {
            dropdown.style.display = "none";
            dropdown.innerHTML = "";
            return;
        }

        const filtered = allCatalogProductsCache.filter(p => {
            const name = (p.name || "").toLowerCase();
            const hindi = (p.hindi_name || "").toLowerCase();
            const aliases = (p.aliases || "").toLowerCase();
            return name.includes(q) || hindi.includes(q) || aliases.includes(q);
        }).slice(0, 8);

        if (filtered.length === 0) {
            dropdown.innerHTML = `<div style="padding: 0.65rem 0.85rem; font-size: 0.82rem; color: var(--text-secondary);">No catalog items match "${escapeHtml(q)}"</div>`;
            dropdown.style.display = "block";
            return;
        }

        dropdown.innerHTML = filtered.map(p => {
            const isOutOfStock = (p.stock_quantity <= 0);
            return `
                <div class="draft-search-item ${isOutOfStock ? 'out-of-stock-item' : ''}" 
                     ${isOutOfStock ? 'style="opacity: 0.55; cursor: not-allowed;" title="Out of stock"' : `onclick="quickAddProductToDraft(${p.id})"`}>
                    <div>
                        <div class="draft-item-title">${escapeHtml(p.name)} ${p.hindi_name ? `<span style="font-size: 0.8rem; color: var(--accent); font-weight: normal;">(${escapeHtml(p.hindi_name)})</span>` : ""}</div>
                        <div class="draft-item-sub">Stock: ${isOutOfStock ? '<strong style="color: #ef4444;">OUT OF STOCK</strong>' : `${p.stock_quantity} ${escapeHtml(p.unit)}`}</div>
                    </div>
                    <div class="draft-item-price">
                        ${isOutOfStock ? '<span class="badge badge-out-stock" style="font-size: 0.7rem;">Out of Stock</span>' : `₹${p.unit_price.toFixed(2)}`}
                    </div>
                </div>
            `;
        }).join("");
        dropdown.style.display = "block";
    });

    document.addEventListener("click", (e) => {
        if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.style.display = "none";
        }
    });
}

function initPOSBilling() {
    const micBtn = document.getElementById("mic-toggle-btn");
    const micLabel = document.getElementById("mic-btn-label");
    const sttBadge = document.getElementById("stt-status-badge");
    const parseBtn = document.getElementById("parse-order-btn");
    const clearInputBtn = document.getElementById("clear-input-btn");
    const clearDraftBtn = document.getElementById("clear-draft-btn");
    const textInput = document.getElementById("order-text-input");

    // Initialize Language Selection Tab Bar
    const langTabBtns = document.querySelectorAll(".pos-lang-tab-btn");
    langTabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const selectedLang = btn.dataset.lang;
            if (selectedLang) switchVoiceLanguage(selectedLang);
        });
    });

    // Initialize Web Speech API for Selected Language
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        try {
            speechRecognizer = new SpeechRecognition();
            speechRecognizer.continuous = false;
            speechRecognizer.interimResults = false;
            speechRecognizer.lang = (LANGUAGE_CONFIG[currentVoiceLanguage] && LANGUAGE_CONFIG[currentVoiceLanguage].code) || "en-IN";

            speechRecognizer.onstart = () => {
                isListening = true;
                playAudioTone("mic-start");
                setMicVisualState("listening");
            };

            speechRecognizer.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                if (textInput) textInput.value = transcript;
                stopListening();
                setMicVisualState("parsing");
                generateDraftBill(transcript);
            };

            speechRecognizer.onerror = (event) => {
                console.warn("Speech recognition notice:", event.error);
                stopListening();
                setMicVisualState("ready");
            };

            speechRecognizer.onend = () => {
                stopListening();
            };
        } catch (e) {
            console.warn("Could not instantiate SpeechRecognition:", e);
        }
    } else {
        if (sttBadge) {
            sttBadge.className = "badge badge-ready";
            sttBadge.textContent = "Voice: Text Fallback";
        }
        if (micLabel) micLabel.textContent = "Mic unsupported (Use text/chips)";
    }

    // Apply persisted language configuration
    switchVoiceLanguage(currentVoiceLanguage);

    // Initialize Quick Product Search & Add Bar
    initQuickProductSearch();

    if (micBtn) {
        micBtn.addEventListener("click", toggleVoiceRecognition);
    }

    // Parse text order button
    if (parseBtn) {
        parseBtn.addEventListener("click", () => {
            const text = textInput ? textInput.value.trim() : "";
            if (!text) {
                alert("Please speak into the mic or enter order text first.");
                return;
            }
            generateDraftBill(text);
        });
    }

    // Clear Text button
    if (clearInputBtn && textInput) {
        clearInputBtn.addEventListener("click", () => {
            textInput.value = "";
        });
    }

    // Payment Mode Radio Option Styling & Udhaar selection handler
    const modeOptions = document.querySelectorAll(".mode-option");
    modeOptions.forEach(opt => {
        opt.addEventListener("click", () => {
            const radio = opt.querySelector("input[type='radio']");
            if (radio) {
                setPaymentMode(radio.value);
            }
        });
    });

    // POS Primary Customer Dropdown change
    const custSelect = document.getElementById("udhaar-primary-customer-select");
    if (custSelect) {
        custSelect.addEventListener("change", handlePOSCustomerChange);
    }

    // POS Family Member Dropdown change
    const memberSelect = document.getElementById("udhaar-family-member-select");
    if (memberSelect) {
        memberSelect.addEventListener("change", handlePOSFamilyMemberChange);
    }

    // Finalize Bill button
    const finalizeBtn = document.getElementById("finalize-bill-btn");
    if (finalizeBtn) {
        finalizeBtn.addEventListener("click", finalizeCurrentDraft);
    }

    // New Order button in modal
    const newOrderBtn = document.getElementById("new-order-btn");
    if (newOrderBtn) {
        newOrderBtn.addEventListener("click", () => {
            closeFinalizedBillModal();
        });
    }

    // Close button in receipt modal
    const closeReceiptBtn = document.getElementById("receipt-modal-close-btn");
    if (closeReceiptBtn) {
        closeReceiptBtn.addEventListener("click", closeFinalizedBillModal);
    }

    // Regenerate 2FA Challenge button in modal
    const regenBtn = document.getElementById("regenerate-challenge-btn");
    if (regenBtn) {
        regenBtn.addEventListener("click", () => {
            if (currentVerificationBillId) {
                initVerificationSessionForBill(currentVerificationBillId);
            }
        });
    }

    // WhatsApp Share button
    const waBtn = document.getElementById("whatsapp-share-btn");
    if (waBtn) {
        waBtn.addEventListener("click", handleOpenWhatsApp);
    }

    // Toggle SMS Mock preview
    const toggleSmsBtn = document.getElementById("toggle-sms-btn");
    if (toggleSmsBtn) {
        toggleSmsBtn.addEventListener("click", () => {
            const smsBox = document.getElementById("sms-mock-container");
            if (smsBox) {
                const isHidden = smsBox.style.display === "none";
                smsBox.style.display = isHidden ? "block" : "none";
                toggleSmsBtn.textContent = isHidden ? "Hide SMS Preview" : "View SMS Preview";
            }
        });
    }

    // Toggle Thermal Receipt preview
    const toggleThermalBtn = document.getElementById("toggle-thermal-btn");
    if (toggleThermalBtn) {
        toggleThermalBtn.addEventListener("click", () => {
            const thermalBox = document.getElementById("thermal-receipt-container");
            if (thermalBox) {
                const isHidden = thermalBox.style.display === "none";
                thermalBox.style.display = isHidden ? "block" : "none";
                toggleThermalBtn.textContent = isHidden ? "Hide Thermal Receipt" : "View Thermal Receipt";
            }
        });
    }

    // Thermal Print buttons
    const directThermalBtn = document.getElementById("btn-thermal-print-direct");
    if (directThermalBtn) {
        directThermalBtn.addEventListener("click", () => {
            window.printThermalReceipt();
        });
    }

    const thermalBtn = document.getElementById("btn-thermal-print");
    if (thermalBtn) {
        thermalBtn.addEventListener("click", () => {
            window.printThermalReceipt();
        });
    }

    // Print Receipt button inside thermal preview
    const printNowBtn = document.getElementById("btn-print-now");
    if (printNowBtn) {
        printNowBtn.addEventListener("click", () => {
            window.printThermalReceipt();
        });
    }

    // Channel selection & send challenge buttons
    const btnSms = document.getElementById("btn-channel-sms");
    if (btnSms) {
        btnSms.addEventListener("click", () => {
            selectVerificationChannel("SMS", true);
        });
    }
    const btnWa = document.getElementById("btn-channel-whatsapp");
    if (btnWa) {
        btnWa.addEventListener("click", () => {
            selectVerificationChannel("WHATSAPP", true);
        });
    }
    const btnSend = document.getElementById("btn-send-verification");
    if (btnSend) {
        btnSend.addEventListener("click", () => {
            sendVerificationChallenge();
        });
    }

    // Clear Draft button
    if (clearDraftBtn) {
        clearDraftBtn.addEventListener("click", clearDraftBill);
    }
}

async function generateDraftBill(orderText) {
    const tableBody = document.getElementById("draft-bill-items-body");
    const billIdEl = document.getElementById("draft-bill-id");

    if (!orderText.trim()) return;

    setMicVisualState("parsing");

    try {
        if (tableBody) {
            tableBody.innerHTML = `<tr><td colspan="7" class="loading-cell">Parsing order and calculating draft bill...</td></tr>`;
        }

        const res = await fetch("/api/v1/billing/draft", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ 
                text: orderText,
                language: currentVoiceLanguage || "hinglish"
            })
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        currentDraft = await res.json();
        playAudioTone("order-parsed");
        setMicVisualState("matched");

        if (billIdEl) billIdEl.textContent = `Draft #${currentDraft.draft_id}`;
        renderDraftBill();

        // ElevenLabs Voice Assistant Spoken Feedback (Adding items / Clarification)
        try {
            if (currentDraft && currentDraft.items && currentDraft.items.length > 0) {
                const unmatched = currentDraft.items.filter(it => it.status === "UNMATCHED" || it.match_status === "UNMATCHED");
                const matched = currentDraft.items.filter(it => it.status === "MATCHED");
                if (unmatched.length > 0) {
                    const unmatchedNames = unmatched.map(it => it.raw_product_name || it.item_name || "item").slice(0, 3).join(", ");
                    if (typeof window.speakWithElevenLabs === "function") {
                        window.speakWithElevenLabs(`Could not find ${unmatchedNames}. Please clarify or select a product.`);
                    }
                } else if (matched.length > 0) {
                    const itemsSummary = matched.map(it => `${it.quantity} ${it.unit || ''} ${it.product_name || ''}`.trim()).slice(0, 3).join(", ");
                    if (typeof window.speakWithElevenLabs === "function") {
                        window.speakWithElevenLabs(`Added ${itemsSummary} to bill.`);
                    }
                }
            }
        } catch (voiceNotice) {
            console.warn("Draft voice announcement notice:", voiceNotice);
        }
    } catch (e) {
        setMicVisualState("ready");
        playAudioTone("error");
        console.error("Failed to generate draft bill:", e);
        if (tableBody) {
            tableBody.innerHTML = `<tr><td colspan="7" class="loading-cell error-msg">Error creating draft: ${e.message}</td></tr>`;
        }
    }
}

function renderDraftBill() {
    const tableBody = document.getElementById("draft-bill-items-body");
    const subtotalEl = document.getElementById("draft-subtotal");
    const taxEl = document.getElementById("draft-tax");
    const totalEl = document.getElementById("draft-total");
    const unmatchedBanner = document.getElementById("draft-unmatched-banner");
    const unmatchedText = document.getElementById("draft-unmatched-text");
    const finalizeBtn = document.getElementById("finalize-bill-btn");

    if (!currentDraft || !tableBody) return;

    if (!currentDraft.items || currentDraft.items.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="7" class="loading-cell">No items extracted from speech. Try speaking item name and quantity clearly or add manually.</td></tr>`;
        if (unmatchedBanner) unmatchedBanner.style.display = "none";
        if (finalizeBtn) {
            finalizeBtn.disabled = true;
            finalizeBtn.textContent = "Finalize Bill";
        }
        if (subtotalEl) subtotalEl.textContent = "₹0.00";
        if (taxEl) taxEl.textContent = "₹0.00";
        if (totalEl) totalEl.textContent = "₹0.00";
        const headerClearBtn = document.getElementById("header-clear-draft-btn");
        if (headerClearBtn) headerClearBtn.style.display = "none";
        return;
    }

    const headerClearBtn = document.getElementById("header-clear-draft-btn");
    if (headerClearBtn) headerClearBtn.style.display = "inline-flex";

    // Update totals
    if (subtotalEl) subtotalEl.textContent = `₹${(currentDraft.subtotal || 0).toFixed(2)}`;
    if (taxEl) taxEl.textContent = `₹${(currentDraft.tax || 0).toFixed(2)}`;
    if (totalEl) totalEl.textContent = `₹${(currentDraft.total_amount || 0).toFixed(2)}`;

    // Check unmatched / Product Not Available status
    const hasUnmatched = currentDraft.items.some(it => it.status === "UNMATCHED" || it.match_status === "UNMATCHED");
    const hasMatched = currentDraft.items.some(it => it.status === "MATCHED");

    // Block bill finalization if any "Product Not Available" row remains unresolved in the draft bill
    if (finalizeBtn) {
        if (hasUnmatched) {
            finalizeBtn.disabled = true;
            finalizeBtn.textContent = "Finalize Blocked (Unresolved Items)";
        } else if (!hasMatched) {
            finalizeBtn.disabled = true;
            finalizeBtn.textContent = "Finalize Bill";
        } else {
            finalizeBtn.disabled = false;
            finalizeBtn.textContent = "Finalize Bill";
        }
    }

    // Show/hide unmatched banner
    if (unmatchedBanner) {
        const unmatchedCount = currentDraft.items.filter(it => it.status === "UNMATCHED" || it.match_status === "UNMATCHED").length;
        if (unmatchedCount > 0) {
            unmatchedBanner.style.display = "flex";
            if (unmatchedText) {
                unmatchedText.textContent = `${unmatchedCount} item(s) are "Product Not Available". Please select a product or remove them before finalizing.`;
            }
        } else {
            unmatchedBanner.style.display = "none";
        }
    }

    const standardUnits = ["kg", "gram", "liter", "ml", "packet", "piece", "bottle", "box", "dozen"];

    // Render line items
    tableBody.innerHTML = currentDraft.items.map((item, idx) => {
        const isMatched = item.status === "MATCHED";
        const isUnmatched = item.status === "UNMATCHED" || item.match_status === "UNMATCHED";
        const rowClass = isMatched ? "" : "unmatched-row";

        let statusBadge = `<span class="badge badge-in-stock">Matched</span>`;
        if (isUnmatched) {
            statusBadge = `<span class="badge pos-unmatched-badge">Product Not Available</span>`;
        } else if (item.status === "AMBIGUOUS") {
            statusBadge = `<span class="badge badge-low-stock">Review</span>`;
        }

        const reasonNote = isUnmatched
            ? `<div class="product-subtext error-msg" style="margin-top: 0.2rem;">${escapeHtml(item.unmatched_reason || "Not found in catalog")}</div>`
            : (item.unmatched_reason ? `<div class="product-subtext error-msg">${escapeHtml(item.unmatched_reason)}</div>` : "");

        const assignBtn = isUnmatched
            ? `<button type="button" class="btn-assign-product" onclick="promptAssignProduct(${idx})" style="margin-top: 0.25rem; font-size: 0.74rem; padding: 0.15rem 0.45rem; background: rgba(56,189,248,0.15); color: #38bdf8; border: 1px solid rgba(56,189,248,0.3); border-radius: 4px; cursor: pointer;">Select Product</button>`
            : "";

        const currentUnit = escapeHtml(item.unit || "piece");

        return `
            <tr class="${rowClass}">
                <td>
                    <strong>${escapeHtml(item.product_name)}</strong>
                    ${reasonNote}
                    ${assignBtn}
                </td>
                <td>${isMatched ? `₹${(item.unit_price || 0).toFixed(2)}` : "—"}</td>
                <td>
                    <div class="qty-stepper">
                        <button type="button" class="qty-step-btn" onclick="handleDraftStepQty(${idx}, -0.5)" title="Decrease quantity">−</button>
                        <input type="number" class="qty-input" min="0.1" step="0.5" value="${item.quantity}"
                               onchange="handleDraftQtyChange(${idx}, this.value)">
                        <button type="button" class="qty-step-btn" onclick="handleDraftStepQty(${idx}, 0.5)" title="Increase quantity">+</button>
                    </div>
                </td>
                <td>
                    <span class="badge-draft-unit">${currentUnit}</span>
                </td>
                <td><strong>${isMatched ? `₹${(item.line_total || 0).toFixed(2)}` : "₹0.00"}</strong></td>
                <td>${statusBadge}</td>
                <td>
                    <button class="btn-delete-row" title="Remove line item" onclick="handleDeleteDraftItem(${idx})">&times;</button>
                </td>
            </tr>
        `;
    }).join("");
}

async function handleDraftStepQty(index, delta) {
    if (!currentDraft || !currentDraft.items || !currentDraft.items[index]) return;
    let newQty = parseFloat(currentDraft.items[index].quantity || 1) + delta;
    if (newQty < 0.1) newQty = 0.1;
    newQty = Math.round(newQty * 10) / 10;
    currentDraft.items[index].quantity = newQty;
    await recalculateCurrentDraft();
}

async function handleDraftUnitChange(index, newUnit) {
    if (!currentDraft || !currentDraft.items || !currentDraft.items[index]) return;
    currentDraft.items[index].unit = newUnit;
    await recalculateCurrentDraft();
}

async function promptAssignProduct(index) {
    if (!currentDraft || !currentDraft.items || !currentDraft.items[index]) return;
    if (!allCatalogProductsCache || allCatalogProductsCache.length === 0) {
        await loadCatalogForQuickSearch();
    }
    const item = currentDraft.items[index];
    const topProducts = (allCatalogProductsCache || []).slice(0, 10);
    const optionsText = topProducts.map((p, i) => `${i + 1}. ${p.name} (₹${p.unit_price}/${p.unit})`).join("\n");
    const choice = prompt(`Select replacement product for "${item.product_name}":\n\n${optionsText}\n\nEnter number (1-${topProducts.length}) or type product name:`);
    if (!choice) return;

    const num = parseInt(choice.trim());
    let chosen = null;
    if (!isNaN(num) && num >= 1 && num <= topProducts.length) {
        chosen = topProducts[num - 1];
    } else {
        const query = choice.trim().toLowerCase();
        chosen = allCatalogProductsCache.find(p => 
            p.name.toLowerCase().includes(query) ||
            (p.hindi_name && p.hindi_name.toLowerCase().includes(query)) ||
            (p.aliases && p.aliases.toLowerCase().includes(query))
        );
    }

    if (chosen) {
        item.product_id = chosen.id;
        item.product_name = chosen.name;
        item.unit_price = chosen.unit_price;
        item.unit = chosen.unit;
        item.status = "MATCHED";
        item.match_status = "MATCHED";
        item.confidence_score = 1.0;
        item.unmatched_reason = null;
        item.matched = true;
        await recalculateCurrentDraft();
    } else {
        alert(`No catalog product found matching "${choice}".`);
    }
}

async function quickAddProductToDraft(productId) {
    const dropdown = document.getElementById("draft-search-dropdown");
    const searchInput = document.getElementById("draft-quick-product-search");
    if (dropdown) dropdown.style.display = "none";
    if (searchInput) searchInput.value = "";

    const prod = (allCatalogProductsCache || []).find(p => p.id === productId);
    if (!prod) return;

    if (prod.stock_quantity <= 0) {
        if (typeof window.showToast === 'function') {
            window.showToast(`Cannot add "${prod.name}": Product is out of stock!`, "warning");
        } else {
            alert(`Cannot add "${prod.name}": Product is out of stock!`);
        }
        return;
    }

    if (!currentDraft) {
        currentDraft = {
            draft_id: `manual-${Date.now()}`,
            items: [],
            subtotal: 0,
            tax: 0,
            total_amount: 0,
            matched_items_count: 0,
            unmatched_items_count: 0
        };
        const billIdEl = document.getElementById("draft-bill-id");
        if (billIdEl) billIdEl.textContent = `Draft #${currentDraft.draft_id}`;
    }

    const existingIndex = currentDraft.items.findIndex(it => it.product_id === prod.id && it.status === "MATCHED");
    if (existingIndex >= 0) {
        currentDraft.items[existingIndex].quantity += 1;
    } else {
        currentDraft.items.push({
            product_id: prod.id,
            product_name: prod.name,
            quantity: 1,
            unit: prod.unit,
            unit_price: prod.unit_price,
            line_total: prod.unit_price,
            status: "MATCHED",
            match_status: "MATCHED",
            confidence_score: 1.0,
            matched: true
        });
    }

    await recalculateCurrentDraft();
    try {
        if (typeof window.speakWithElevenLabs === "function") {
            window.speakWithElevenLabs(`Added 1 ${prod.unit || 'unit'} of ${prod.name} to bill.`);
        }
    } catch (voiceErr) {
        console.warn("Item add voice notice:", voiceErr);
    }
}

async function handleDraftQtyChange(index, newQtyStr) {
    if (!currentDraft || !currentDraft.items[index]) return;
    const newQty = parseFloat(newQtyStr);
    if (isNaN(newQty) || newQty <= 0) {
        alert("Please enter a valid quantity greater than 0.");
        renderDraftBill();
        return;
    }

    currentDraft.items[index].quantity = newQty;
    await recalculateCurrentDraft();
};

async function handleDeleteDraftItem(index) {
    if (!currentDraft || !currentDraft.items[index]) return;
    currentDraft.items.splice(index, 1);
    await recalculateCurrentDraft();
};

async function recalculateCurrentDraft() {
    if (!currentDraft) return;

    try {
        const res = await fetch("/api/v1/billing/draft/recalculate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ items: currentDraft.items })
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const updated = await res.json();
        currentDraft.items = updated.items;
        currentDraft.subtotal = updated.subtotal;
        currentDraft.tax = updated.tax;
        currentDraft.total_amount = updated.total_amount;
        currentDraft.matched_items_count = updated.matched_items_count;
        currentDraft.unmatched_items_count = updated.unmatched_items_count;

        // If items changed while an Udhaar OTP was pending or verified, reset verification
        if (currentPendingUdhaarBill || isUdhaarCustomerVerified) {
            resetUdhaarVerificationState();
        }

        renderDraftBill();
        if (selectedPOSCustomer) {
            validatePOSCreditLimit();
        }
    } catch (e) {
        console.error("Failed to recalculate draft:", e);
    }
}

function clearDraftBill() {
    currentDraft = null;
    currentIdempotencyKey = null;
    isFinalizing = false;
    const tableBody = document.getElementById("draft-bill-items-body");
    const billIdEl = document.getElementById("draft-bill-id");
    const subtotalEl = document.getElementById("draft-subtotal");
    const taxEl = document.getElementById("draft-tax");
    const totalEl = document.getElementById("draft-total");
    const unmatchedBanner = document.getElementById("draft-unmatched-banner");
    const textInput = document.getElementById("order-text-input");
    const finalizeBtn = document.getElementById("finalize-bill-btn");

    if (tableBody) tableBody.innerHTML = `<tr><td colspan="7" class="loading-cell">No items in draft bill. Speak or type an order above.</td></tr>`;
    if (billIdEl) billIdEl.textContent = "Draft #---";
    if (subtotalEl) subtotalEl.textContent = "₹0.00";
    if (taxEl) taxEl.textContent = "₹0.00";
    if (totalEl) totalEl.textContent = "₹0.00";
    if (unmatchedBanner) unmatchedBanner.style.display = "none";
    if (textInput) textInput.value = "";
    if (finalizeBtn) {
        finalizeBtn.disabled = true;
        finalizeBtn.textContent = "Finalize Bill";
    }
    const headerClearBtn = document.getElementById("header-clear-draft-btn");
    if (headerClearBtn) headerClearBtn.style.display = "none";

    // Reset Udhaar OTP and verification states
    if (typeof resetUdhaarVerificationState === "function") {
        resetUdhaarVerificationState();
    }
    if (selectedPOSCustomer && typeof validatePOSCreditLimit === "function") {
        validatePOSCreditLimit();
    }
}

let allPOSCustomers = [];
let selectedPOSCustomer = null;
let currentPendingUdhaarBill = null;
let currentUdhaarOtpSession = null;
let currentUdhaarDeliveryChannel = "SMS";
let isUdhaarCustomerVerified = false;
let udhaarOtpCountdownInterval = null;

function getValidDraftItems() {
    if (!currentDraft || !Array.isArray(currentDraft.items)) return [];
    return currentDraft.items.filter(it => 
        it && 
        it.product_id && 
        it.quantity > 0 && 
        (it.status === "MATCHED" || it.matched === true)
    );
}

function resetUdhaarVerificationState() {
    isUdhaarCustomerVerified = false;
    currentUdhaarOtpSession = null;
    currentPendingUdhaarBill = null;
    stopUdhaarOtpCountdown();

    const channelStep = document.getElementById("udhaar-otp-channel-selection");
    const otpStep = document.getElementById("udhaar-otp-input-area");
    const verifiedBadge = document.getElementById("udhaar-verified-badge");
    const otpInput = document.getElementById("inline-udhaar-otp-input");
    const feedbackEl = document.getElementById("inline-otp-feedback");
    const demoHint = document.getElementById("inline-otp-demo-hint");

    if (channelStep) channelStep.style.display = "block";
    if (otpStep) otpStep.style.display = "none";
    if (verifiedBadge) verifiedBadge.style.display = "none";
    if (otpInput) {
        otpInput.value = "";
        otpInput.disabled = false;
    }
    if (feedbackEl) feedbackEl.style.display = "none";
    if (demoHint) demoHint.style.display = "none";

    const finalizeBtn = document.getElementById("finalize-bill-btn");
    const selectedMode = document.querySelector("input[name='payment-mode']:checked");
    if (finalizeBtn && selectedMode && selectedMode.value === "UDHAAR") {
        finalizeBtn.disabled = true;
        finalizeBtn.textContent = "Finalize Bill";
    }
}

function updatePOSCreditDisplay(cust) {
    renderPOSCustomerSelection(cust);
};

function renderPOSCustomerSelection(cust) {
    const cardEl = document.getElementById("udhaar-selected-customer-card");
    const nameEl = document.getElementById("udhaar-card-cust-name");
    const codeEl = document.getElementById("udhaar-card-cust-code");
    const phoneEl = document.getElementById("udhaar-card-cust-phone");
    const limitEl = document.getElementById("udhaar-card-cust-limit");
    const balanceEl = document.getElementById("udhaar-card-cust-balance");
    const availEl = document.getElementById("udhaar-card-cust-available");
    const verifBox = document.getElementById("udhaar-verification-box");

    if (!cust) {
        if (cardEl) cardEl.style.display = "none";
        if (verifBox) verifBox.style.display = "none";
        resetUdhaarVerificationState();
        return;
    }

    if (nameEl) nameEl.textContent = cust.full_name;
    if (codeEl) codeEl.textContent = cust.customer_code || `C-${String(cust.id).padStart(6, "0")}`;
    if (phoneEl) phoneEl.textContent = cust.phone || "--";
    if (limitEl) limitEl.textContent = `₹${(cust.credit_limit || 0).toFixed(2)}`;
    if (balanceEl) balanceEl.textContent = `₹${(cust.current_udhaar_balance || 0).toFixed(2)}`;

    const avail = cust.available_credit !== undefined
        ? cust.available_credit
        : Math.max(0, (cust.credit_limit || 0) - (cust.current_udhaar_balance || 0));
    if (availEl) availEl.textContent = `₹${avail.toFixed(2)}`;

    if (cardEl) cardEl.style.display = "block";
    if (verifBox) verifBox.style.display = "block";

    validatePOSCreditLimit();
}


function setPaymentMode(mode) {
    const val = (mode || "CASH").toUpperCase();
    const modeOptions = document.querySelectorAll(".mode-option");
    modeOptions.forEach(opt => {
        const radio = opt.querySelector("input[name='payment-mode']");
        if (radio && radio.value.toUpperCase() === val) {
            opt.classList.add("active");
            radio.checked = true;
        } else {
            opt.classList.remove("active");
        }
    });
    handlePaymentModeChange(val);
}
window.setPaymentMode = setPaymentMode;

async function handlePaymentModeChange(mode) {
    const udhaarSection = document.getElementById("udhaar-customer-select-section");
    const noticeEl = document.getElementById("draft-checkout-notice");
    if (!udhaarSection) return;

    if (mode === "UDHAAR") {
        udhaarSection.style.display = "block";
        if (noticeEl) {
            noticeEl.textContent = "For Udhaar, transaction requires customer 4-digit OTP verification via SMS or WhatsApp before stock deduction.";
        }
        await loadPOSCustomerDropdown();
        if (selectedPOSCustomer) {
            renderPOSCustomerSelection(selectedPOSCustomer);
        }
    } else {
        udhaarSection.style.display = "none";
        selectedPOSCustomer = null;
        const custSelect = document.getElementById("udhaar-primary-customer-select");
        if (custSelect) custSelect.value = "";
        renderPOSCustomerSelection(null);
        resetUdhaarVerificationState();
        if (noticeEl) {
            noticeEl.textContent = "Finalizing will commit the transaction to database and deduct stock atomically.";
        }
    }
}

async function loadPOSCustomerDropdown() {
    const custSelect = document.getElementById("udhaar-primary-customer-select");
    if (!custSelect) return;

    try {
        const res = await fetch("/api/v1/customers");
        if (!res.ok) throw new Error("Failed to load customer accounts");
        allPOSCustomers = await res.json();

        custSelect.innerHTML = `<option value="">-- Select Customer Account --</option>` +
            allPOSCustomers.map(c => `
                <option value="${c.id}">${escapeHtml(c.full_name)} (${escapeHtml(c.phone)}) — Avail: ₹${c.available_credit.toFixed(2)}</option>
            `).join("");

        // If previously selected, retain selection
        if (selectedPOSCustomer) {
            custSelect.value = selectedPOSCustomer.id;
            renderPOSCustomerSelection(selectedPOSCustomer);
        }
    } catch (e) {
        console.error("Error loading POS customers:", e);
    }
}

function handlePOSCustomerChange() {
    const custSelect = document.getElementById("udhaar-primary-customer-select");
    const memberGroup = document.getElementById("udhaar-family-member-group");
    const memberSelect = document.getElementById("udhaar-family-member-select");

    const custId = custSelect && custSelect.value ? parseInt(custSelect.value) : null;
    const prevCustId = selectedPOSCustomer ? selectedPOSCustomer.id : null;

    selectedPOSCustomer = allPOSCustomers.find(c => c.id === custId) || null;

    if (prevCustId !== custId) {
        resetUdhaarVerificationState();
    }

    renderPOSCustomerSelection(selectedPOSCustomer);

    if (!selectedPOSCustomer) {
        if (memberGroup) memberGroup.style.display = "none";
        return;
    }

    // Populate family member dropdown
    if (memberSelect) {
        let memberOptions = `<option value="">Primary Account Holder (Self) — ${escapeHtml(selectedPOSCustomer.full_name)}</option>`;
        const activeMembers = (selectedPOSCustomer.family_members || []).filter(m => m.is_active !== false);
        if (activeMembers.length > 0) {
            memberOptions += activeMembers.map(m => `
                <option value="${m.id}">
                    ${escapeHtml(m.full_name)} (${escapeHtml(m.relation_type)})${m.allowed_spending_limit ? ` — Cap: ₹${m.allowed_spending_limit}` : ""}
                </option>
            `).join("");
        }
        memberSelect.innerHTML = memberOptions;
    }
    if (memberGroup) memberGroup.style.display = "block";
}

function handlePOSFamilyMemberChange() {
    validatePOSCreditLimit();
}

function validatePOSCreditLimit() {
    const alertBox = document.getElementById("udhaar-credit-limit-alert");
    const alertMsg = document.getElementById("udhaar-credit-limit-msg");
    const finalizeBtn = document.getElementById("finalize-bill-btn");
    const btnSms = document.getElementById("btn-inline-send-sms");
    const btnWa = document.getElementById("btn-inline-send-whatsapp");
    if (!alertBox || !alertMsg) return true;

    if (!selectedPOSCustomer || !currentDraft) {
        alertBox.style.display = "none";
        return true;
    }

    const billTotal = currentDraft.total_amount || 0;
    const avail = selectedPOSCustomer.available_credit !== undefined
        ? selectedPOSCustomer.available_credit
        : Math.max(0, (selectedPOSCustomer.credit_limit || 0) - (selectedPOSCustomer.current_udhaar_balance || 0));
    const projectedBalance = (selectedPOSCustomer.current_udhaar_balance || 0) + billTotal;

    if (projectedBalance > selectedPOSCustomer.credit_limit) {
        const excess = (projectedBalance - selectedPOSCustomer.credit_limit).toFixed(2);
        alertMsg.textContent = `Bill total (₹${billTotal.toFixed(2)}) exceeds available credit (₹${avail.toFixed(2)}) by ₹${excess}. Udhaar cannot be approved.`;
        alertBox.style.display = "block";
        if (finalizeBtn) finalizeBtn.disabled = true;
        if (btnSms) btnSms.disabled = true;
        if (btnWa) btnWa.disabled = true;
        return false;
    }

    // Check individual family member limit if selected
    const memberSelect = document.getElementById("udhaar-family-member-select");
    const memberId = memberSelect && memberSelect.value ? parseInt(memberSelect.value) : null;
    if (memberId && selectedPOSCustomer.family_members) {
        const member = selectedPOSCustomer.family_members.find(m => m.id === memberId);
        if (member && member.allowed_spending_limit && billTotal > member.allowed_spending_limit) {
            alertMsg.textContent = `Bill total (₹${billTotal.toFixed(2)}) exceeds ${member.full_name}'s individual spending cap of ₹${member.allowed_spending_limit.toFixed(2)}.`;
            alertBox.style.display = "block";
            if (finalizeBtn) finalizeBtn.disabled = true;
            if (btnSms) btnSms.disabled = true;
            if (btnWa) btnWa.disabled = true;
            return false;
        }
    }

    alertBox.style.display = "none";
    if (btnSms) btnSms.disabled = false;
    if (btnWa) btnWa.disabled = false;
    return true;
}

let isSendingUdhaarOtp = false;

window.sendInlineUdhaarOtp = async function(channel) {
    if (isSendingUdhaarOtp) return;

    currentUdhaarDeliveryChannel = channel || "SMS";

    const validItems = getValidDraftItems();
    if (validItems.length === 0) {
        alert("Please add at least one item to the bill.");
        return;
    }

    if (!selectedPOSCustomer) {
        alert("Please select a customer for Udhaar.");
        return;
    }

    const billTotal = currentDraft ? currentDraft.total_amount : 0;
    const avail = selectedPOSCustomer.available_credit !== undefined
        ? selectedPOSCustomer.available_credit
        : Math.max(0, (selectedPOSCustomer.credit_limit || 0) - (selectedPOSCustomer.current_udhaar_balance || 0));

    if (billTotal > avail) {
        alert(`Bill total (₹${billTotal.toFixed(2)}) exceeds available credit limit (₹${avail.toFixed(2)}). Udhaar cannot be approved.`);
        return;
    }

    const btnSms = document.getElementById("btn-inline-send-sms");
    const btnWa = document.getElementById("btn-inline-send-whatsapp");
    const activeBtn = channel === "WHATSAPP" ? btnWa : btnSms;
    const originalText = activeBtn ? activeBtn.textContent : "";

    isSendingUdhaarOtp = true;
    if (activeBtn) {
        activeBtn.disabled = true;
        activeBtn.textContent = "Sending OTP...";
    }

    try {
        // Step 1: Create or reuse pending bill
        if (!currentPendingUdhaarBill) {
            const memberSelect = document.getElementById("udhaar-family-member-select");
            const familyMemberId = memberSelect && memberSelect.value ? parseInt(memberSelect.value) : null;

            const billPayload = {
                items: validItems.map(it => ({
                    product_id: it.product_id,
                    quantity: it.quantity
                })),
                payment_mode: "UDHAAR",
                customer_id: selectedPOSCustomer.id,
                family_member_id: familyMemberId,
                idempotency_key: `draft-${currentDraft.draft_id}-${Date.now()}`,
                notes: "Udhaar POS Sale (Pending OTP Verification)"
            };

            const billRes = await fetch("/api/v1/billing/finalize", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(billPayload)
            });

            if (!billRes.ok) {
                const errData = await billRes.json();
                throw new Error(errData.detail || "Failed to create Udhaar transaction.");
            }
            currentPendingUdhaarBill = await billRes.json();
        }

        // Step 2: Create 4-digit OTP session
        const sessionPayload = {
            bill_id: currentPendingUdhaarBill.id,
            delivery_channel: currentUdhaarDeliveryChannel,
            verification_type: "OTP",
            expiry_seconds: 180
        };

        const sessRes = await fetch("/api/v1/verification/sessions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(sessionPayload)
        });

        if (!sessRes.ok) {
            const errData = await sessRes.json();
            throw new Error(errData.detail || "Failed to generate OTP session.");
        }

        currentUdhaarOtpSession = await sessRes.json();

        // Switch inline UI to Step 2: OTP Input
        const channelStep = document.getElementById("udhaar-otp-channel-selection");
        const otpStep = document.getElementById("udhaar-otp-input-area");
        if (channelStep) channelStep.style.display = "none";
        if (otpStep) otpStep.style.display = "block";

        // Display masked phone
        const sentPhoneEl = document.getElementById("udhaar-otp-sent-phone");
        const rawPhone = selectedPOSCustomer.phone || "";
        const cleanPhone = rawPhone.replace(/\D/g, "");
        const masked = cleanPhone.length >= 4 ? `******${cleanPhone.slice(-4)}` : (cleanPhone || "registered mobile");
        if (sentPhoneEl) sentPhoneEl.textContent = masked;

        // Populate Demo / Test Environment OTP badge (no fake preview or candidate options)
        const demoHint = document.getElementById("inline-otp-demo-hint");
        const demoBadge = document.getElementById("inline-otp-demo-code-badge");
        if (demoHint && demoBadge) {
            if (currentUdhaarOtpSession.demo_otp) {
                demoBadge.textContent = `Demo OTP: ${currentUdhaarOtpSession.demo_otp}`;
                demoHint.style.display = "block";
            } else {
                demoHint.style.display = "none";
            }
        }

        // Focus input
        const otpInput = document.getElementById("inline-udhaar-otp-input");
        const feedbackEl = document.getElementById("inline-otp-feedback");
        const attemptsEl = document.getElementById("inline-udhaar-otp-attempts");

        if (otpInput) {
            otpInput.value = "";
            otpInput.disabled = false;
            setTimeout(() => otpInput.focus(), 100);
        }
        if (feedbackEl) feedbackEl.style.display = "none";
        if (attemptsEl) attemptsEl.textContent = "Attempt 0 of 3";

        startInlineUdhaarOtpCountdown(currentUdhaarOtpSession.expires_in_seconds || 180);

    } catch (err) {
        console.error("Error creating Udhaar OTP:", err);
        alert(`Verification Error: ${err.message}`);
    } finally {
        isSendingUdhaarOtp = false;
        if (activeBtn) {
            activeBtn.disabled = false;
            activeBtn.textContent = originalText;
        }
    }
};

function startInlineUdhaarOtpCountdown(seconds) {
    stopUdhaarOtpCountdown();
    let remaining = seconds;
    const timerEl = document.getElementById("inline-udhaar-otp-timer");

    function update() {
        const mins = Math.floor(remaining / 60);
        const secs = remaining % 60;
        if (timerEl) {
            timerEl.textContent = `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
        }
    }
    update();

    udhaarOtpCountdownInterval = setInterval(() => {
        remaining -= 1;
        if (remaining <= 0) {
            stopUdhaarOtpCountdown();
            handleInlineUdhaarOtpExpired();
        } else {
            update();
        }
    }, 1000);
}

function handleInlineUdhaarOtpExpired() {
    const timerEl = document.getElementById("inline-udhaar-otp-timer");
    const otpInput = document.getElementById("inline-udhaar-otp-input");
    const feedbackEl = document.getElementById("inline-otp-feedback");

    if (timerEl) timerEl.textContent = "Expired";
    if (otpInput) otpInput.disabled = true;

    if (feedbackEl) {
        feedbackEl.className = "alert-banner alert-danger";
        feedbackEl.textContent = "OTP has expired. Please request a new OTP.";
        feedbackEl.style.display = "block";
    }
}

window.resendInlineUdhaarOtp = function() {
    sendInlineUdhaarOtp(currentUdhaarDeliveryChannel || "SMS");
};

window.verifyInlineUdhaarOtp = async function() {
    if (!currentUdhaarOtpSession || !currentPendingUdhaarBill || !selectedPOSCustomer) return;

    const otpInput = document.getElementById("inline-udhaar-otp-input");
    const feedbackEl = document.getElementById("inline-otp-feedback");
    const attemptsEl = document.getElementById("inline-udhaar-otp-attempts");
    const verifyBtn = document.getElementById("btn-inline-verify-otp");

    const otp = otpInput ? otpInput.value.trim() : "";
    if (otp.length !== 4 || !/^\d{4}$/.test(otp)) {
        if (feedbackEl) {
            feedbackEl.className = "alert-banner alert-warning";
            feedbackEl.textContent = "Please enter a 4-digit numeric OTP.";
            feedbackEl.style.display = "block";
        }
        if (otpInput) otpInput.focus();
        return;
    }

    if (verifyBtn) {
        verifyBtn.disabled = true;
        verifyBtn.textContent = "Verifying...";
    }

    try {
        const verifyRes = await fetch("/api/v1/verification/verify", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: currentUdhaarOtpSession.session_id,
                otp: otp,
                bill_id: currentPendingUdhaarBill.id,
                customer_id: selectedPOSCustomer.id
            })
        });

        const verifyData = await verifyRes.json();

        if (!verifyRes.ok || !verifyData.success) {
            playAudioTone("error");
            let errMsg = "Invalid OTP. Please try again.";
            const rawDetail = verifyData.detail || verifyData.message || "";
            if (rawDetail.toLowerCase().includes("expired") || rawDetail.toLowerCase().includes("elapsed")) {
                errMsg = "OTP has expired. Please request a new OTP.";
            } else if (rawDetail && !rawDetail.toLowerCase().includes("invalid otp")) {
                errMsg = rawDetail;
            }
            if (attemptsEl && verifyData.attempts !== undefined) {
                attemptsEl.textContent = `Attempt ${verifyData.attempts} of 3`;
            }
            if (feedbackEl) {
                feedbackEl.className = "alert-banner alert-danger";
                feedbackEl.textContent = errMsg;
                feedbackEl.style.display = "block";
            }
            if (otpInput) {
                otpInput.value = "";
                otpInput.focus();
            }
            return;
        }

        // Verification Succeeded!
        stopUdhaarOtpCountdown();
        playAudioTone("bill-success");
        isUdhaarCustomerVerified = true;

        // Hide OTP input area, show verified badge
        const otpStep = document.getElementById("udhaar-otp-input-area");
        const verifiedBadge = document.getElementById("udhaar-verified-badge");
        const verifName = document.getElementById("verified-card-cust-name");
        const verifPhone = document.getElementById("verified-card-cust-phone");

        if (otpStep) otpStep.style.display = "none";
        if (verifiedBadge) verifiedBadge.style.display = "block";
        if (verifName) verifName.textContent = selectedPOSCustomer.full_name;

        const rawP = selectedPOSCustomer.phone || "";
        const cleanP = rawP.replace(/\D/g, "");
        const masked = cleanP.length >= 4 ? `******${cleanP.slice(-4)}` : cleanP;
        if (verifPhone) verifPhone.textContent = masked;

        // Enable Finalize Bill button
        const finalizeBtn = document.getElementById("finalize-bill-btn");
        if (finalizeBtn) {
            finalizeBtn.disabled = false;
            finalizeBtn.textContent = "Finalize Bill";
        }

    } catch (err) {
        console.error("Error verifying OTP:", err);
        if (feedbackEl) {
            feedbackEl.className = "alert-banner alert-danger";
            feedbackEl.textContent = err.message;
            feedbackEl.style.display = "block";
        }
    } finally {
        if (verifyBtn) {
            verifyBtn.disabled = false;
            verifyBtn.textContent = "Verify OTP";
        }
    }
};

async function finalizeCurrentDraft() {
    const validItems = getValidDraftItems();
    if (validItems.length === 0) {
        alert("Please add at least one item to the bill.");
        return;
    }

    // Block bill finalization if any "Product Not Available" row remains unresolved in the draft bill!
    const hasUnmatched = currentDraft && currentDraft.items.some(it => it.status === "UNMATCHED" || it.match_status === "UNMATCHED");
    if (hasUnmatched) {
        alert("Cannot finalize bill: One or more items are 'Product Not Available'. Please select a valid product or remove the unavailable item(s) before finalizing.");
        return;
    }

    // Check for ambiguous items that need review
    const hasAmbiguous = currentDraft && currentDraft.items.some(it => it.status === "AMBIGUOUS");
    if (hasAmbiguous) {
        const proceed = confirm(
            "There are unreviewed items in this draft.\nOnly fully matched items will be finalized and deducted from inventory.\n\nDo you want to proceed?"
        );
        if (!proceed) return;
    }

    // Get selected payment mode
    const selectedModeEl = document.querySelector("input[name='payment-mode']:checked");
    const paymentMode = selectedModeEl ? selectedModeEl.value : "CASH";

    let customerId = null;
    let familyMemberId = null;

    if (paymentMode === "UDHAAR") {
        const custSelect = document.getElementById("udhaar-primary-customer-select");
        const memberSelect = document.getElementById("udhaar-family-member-select");
        customerId = custSelect && custSelect.value ? parseInt(custSelect.value) : (selectedPOSCustomer ? selectedPOSCustomer.id : null);
        familyMemberId = memberSelect && memberSelect.value ? parseInt(memberSelect.value) : null;

        if (!selectedPOSCustomer) {
            alert("Please select a customer for Udhaar.");
            return;
        }

        if (!isUdhaarCustomerVerified || !currentPendingUdhaarBill) {
            alert("Please verify the customer OTP before finalizing the Udhaar bill.");
            return;
        }

        // Bill has already been completed atomically by /api/v1/verification/verify!
        const completedBill = {
            ...currentPendingUdhaarBill,
            status: "COMPLETED",
            payment_mode: "UDHAAR",
            customer_name: selectedPOSCustomer.full_name,
            customer_code: selectedPOSCustomer.customer_code || `C-${String(selectedPOSCustomer.id).padStart(6, "0")}`,
            customer_phone_masked: selectedPOSCustomer.phone && selectedPOSCustomer.phone.length >= 4
                ? `******${selectedPOSCustomer.phone.slice(-4)}`
                : selectedPOSCustomer.phone,
            is_phone_verified: selectedPOSCustomer.is_phone_verified
        };
        resetUdhaarVerificationState();
        clearDraftBill();

        // Collapse background Udhaar customer & verification panels so they don't clutter the screen behind the modal
        const udhaarCard = document.getElementById("udhaar-selected-customer-card");
        const udhaarVerifBox = document.getElementById("udhaar-verification-box");
        const udhaarLimitAlert = document.getElementById("udhaar-credit-limit-alert");
        const custSelectEl = document.getElementById("udhaar-primary-customer-select");
        if (udhaarCard) udhaarCard.style.display = "none";
        if (udhaarVerifBox) udhaarVerifBox.style.display = "none";
        if (udhaarLimitAlert) udhaarLimitAlert.style.display = "none";
        if (custSelectEl) custSelectEl.value = "";
        selectedPOSCustomer = null;

        displayBillCompletedModal(completedBill);
        if (typeof loadInventorySummary === "function") loadInventorySummary();
        if (typeof loadProducts === "function") loadProducts();
        if (typeof loadMainDashboard === "function") loadMainDashboard();
        return;
    }

    if (isFinalizing) {
        console.warn("Bill finalization is already in progress...");
        return;
    }
    isFinalizing = true;

    const finalizeBtn = document.getElementById("finalize-bill-btn");
    if (finalizeBtn) {
        finalizeBtn.disabled = true;
        finalizeBtn.textContent = (paymentMode === "UDHAAR")
            ? "Verifying Credit..."
            : "Finalizing Bill & Deducting Stock...";
    }

    try {
        const draftPrefix = (currentDraft && currentDraft.draft_id) ? currentDraft.draft_id : "draft";
        currentIdempotencyKey = generateFreshIdempotencyKey(draftPrefix);

        const payload = {
            items: validItems.map(it => ({
                product_id: it.product_id,
                quantity: it.quantity
            })),
            payment_mode: paymentMode,
            customer_id: customerId,
            family_member_id: familyMemberId,
            idempotency_key: currentIdempotencyKey,
            notes: "Finalized via POS Web Interface"
        };

        const res = await fetch("/api/v1/billing/finalize", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        let data;
        const respText = await res.text();
        try {
            data = JSON.parse(respText);
        } catch (e) {
            data = { detail: respText };
        }
        if (!res.ok) {
            playAudioTone("error");
            throw new Error(data.detail || `Server returned error ${res.status}`);
        }

        // Display Completed Modal
        displayBillCompletedModal(data);
        playAudioTone("bill-success");

        // Clear the draft from POS table
        clearDraftBill();
        currentIdempotencyKey = null;

        // Refresh inventory and dashboard metrics so shopkeeper sees stock updates in real time
        if (typeof loadInventorySummary === "function") loadInventorySummary();
        if (typeof loadProducts === "function") loadProducts();
        if (typeof loadMainDashboard === "function") loadMainDashboard();

    } catch (err) {
        playAudioTone("error");
        console.error("Failed to finalize bill:", err);
        alert(`Finalization Error:\n${err.message}`);
    } finally {
        isFinalizing = false;
        if (finalizeBtn) {
            finalizeBtn.disabled = false;
            finalizeBtn.textContent = "Finalize Bill";
        }
    }
}

function displayBillCompletedModal(bill) {
    if (window.AppEvents) {
        window.AppEvents.emit("bills-updated", bill);
        window.AppEvents.emit("sales-updated", bill);
        window.AppEvents.emit("inventory-updated", bill);
        window.AppEvents.emit("products-updated", bill);
        if (bill.payment_mode === "UDHAAR") {
            window.AppEvents.emit("customers-updated", bill);
        }
    }
    try { window.dispatchEvent(new CustomEvent("bills-updated", { detail: bill })); } catch(e){}
    try { window.dispatchEvent(new CustomEvent("sales-updated", { detail: bill })); } catch(e){}
    try { window.dispatchEvent(new CustomEvent("inventory-updated", { detail: bill })); } catch(e){}
    try { window.dispatchEvent(new CustomEvent("products-updated", { detail: bill })); } catch(e){}
    if (bill.payment_mode === "UDHAAR") {
        try { window.dispatchEvent(new CustomEvent("customers-updated", { detail: bill })); } catch(e){}
    }

    const setText = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = (val !== undefined && val !== null) ? val : "";
    };
    const setHtml = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = (val !== undefined && val !== null) ? val : "";
    };
    const setDisplay = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.style.display = val;
    };

    try {
        currentCompletedBillId = bill ? bill.id : null;

        setText("completed-bill-num", bill.bill_number || "BILL-XXXX");
        setText("completed-bill-total", `₹${(bill.total_amount || 0).toFixed(2)}`);

        // Populate 2x2 Transaction Summary Grid
        const custRowEl = document.getElementById("completed-customer-row");
        if (custRowEl) custRowEl.style.display = "flex";
        setText("completed-customer-name", bill.customer_name || (selectedPOSCustomer ? selectedPOSCustomer.full_name : "Walk-in Customer"));

        setText("completed-payment-mode", bill.payment_mode === "UDHAAR" ? "Udhaar (Credit)" : (bill.payment_mode || "CASH"));

        const statusBadgeEl = document.getElementById("completed-status-badge");
        if (statusBadgeEl) {
            if (bill.payment_mode === "UDHAAR") {
                statusBadgeEl.textContent = "Verified & Completed";
                statusBadgeEl.className = "badge badge-in-stock";
            } else {
                statusBadgeEl.textContent = "COMPLETED";
                statusBadgeEl.className = "badge badge-in-stock";
            }
        }

        if (bill.payment_mode === "UDHAAR") {
            setText("completed-modal-title", "Udhaar Bill Finalized Successfully");
        } else {
            setText("completed-modal-title", "Bill Finalized & Recorded");
        }

        // Dynamically sync and display store identity on the finalized receipt
        if (window.currentShopProfile && typeof window.syncReceiptModalStoreDetails === "function") {
            try { window.syncReceiptModalStoreDetails(window.currentShopProfile); } catch (e) { console.warn(e); }
        }

        // Smart Kirana Soundbox Announcement via ElevenLabs
        try {
            const rawAmount = (bill.total_amount !== undefined && bill.total_amount !== null)
                ? Number(bill.total_amount).toFixed(2)
                : "0.00";
            const rawMode = (bill.payment_mode || "CASH").toUpperCase();
            const modeLabel = rawMode === "UDHAAR" ? "Udhaar Credit" : (rawMode === "UPI" ? "UPI" : "Cash");
            const soundboxAnnouncement = `Bill completed for ₹${rawAmount} via ${modeLabel}. Thank you for shopping!`;
            if (typeof window.speakWithElevenLabs === "function") {
                window.speakWithElevenLabs(soundboxAnnouncement);
            }
        } catch (soundboxErr) {
            console.warn("Smart Soundbox announcement notice:", soundboxErr);
        }

        // Notification banner is only for legacy simulation; keep hidden on clean finalized bills
        setDisplay("udhaar-mock-notification-banner", "none");
        setDisplay("verification-card", "none");

        // Populate Purchased Items List
        const itemsListEl = document.getElementById("completed-items-list");
        if (itemsListEl) {
            if (bill.items && Array.isArray(bill.items) && bill.items.length > 0) {
                itemsListEl.innerHTML = bill.items.map(it => `
                    <li class="receipt-item-row">
                        <span><strong>${escapeHtml(it.product_name || it.name || "Item")}</strong> (${it.quantity} ${escapeHtml(it.unit || "unit")} &times; ₹${(it.unit_price || 0).toFixed(2)})</span>
                        <strong>₹${(it.line_total || 0).toFixed(2)}</strong>
                    </li>
                `).join("");
            } else {
                itemsListEl.innerHTML = `<li class="receipt-item-row text-muted">No items recorded.</li>`;
            }
        }

        // Low stock alerts
        const lowStockAlertEl = document.getElementById("completed-low-stock-alert");
        const lowStockItemsEl = document.getElementById("completed-low-stock-items");
        if (lowStockAlertEl && lowStockItemsEl) {
            if (bill.low_stock_alerts && bill.low_stock_alerts.length > 0) {
                lowStockAlertEl.style.display = "block";
                lowStockItemsEl.innerHTML = bill.low_stock_alerts.map(alert => `
                    <div class="low-stock-item-row">
                        <strong>${escapeHtml(alert.product_name)}</strong>: Remaining stock is <strong>${alert.current_stock} ${escapeHtml(alert.unit)}</strong> (Min threshold: ${alert.min_stock_threshold})
                    </div>
                `).join("");
            } else {
                lowStockAlertEl.style.display = "none";
                lowStockItemsEl.innerHTML = "";
            }
        }

        // Reset / collapse background Udhaar panels so they do not clutter the screen behind the modal backdrop
        if (typeof resetUdhaarVerificationState === "function") {
            try { resetUdhaarVerificationState(); } catch(e){}
        }
        setDisplay("udhaar-selected-customer-card", "none");
        setDisplay("udhaar-verification-box", "none");
        setDisplay("udhaar-credit-limit-alert", "none");

        // Reveal receipt delivery section inside modal
        setDisplay("receipt-delivery-section", "block");

        // Immediate clean thermal preview formatting (ensures zero delay, no cut-offs)
        const thermalTextEl = document.getElementById("thermal-receipt-text");
        if (thermalTextEl && bill) {
            thermalTextEl.textContent = formatClientThermalReceipt(bill, window.currentShopProfile);
        }

        if (bill && bill.id) {
            prepareDigitalReceiptDelivery(bill.id);
        }

        // Authoritatively reveal both outer backdrop and inner card
        openFinalizedBillModal();

    } catch (err) {
        console.error("Error populating completed bill modal:", err);
        closeFinalizedBillModal();
        alert(`Error displaying bill receipt: ${err.message}`);
    }
}

function centerReceiptText(text, width = 38) {
    if (!text) return "";
    const str = String(text).trim();
    if (str.length >= width) return str.slice(0, width);
    const pad = Math.floor((width - str.length) / 2);
    const rightPad = width - str.length - pad;
    return " ".repeat(pad) + str + " ".repeat(rightPad);
}

function wrapReceiptText(text, width = 38) {
    if (!text) return [];
    const str = String(text).trim();
    if (str.length <= width) return [str];
    const words = str.split(/\s+/);
    const lines = [];
    let cur = "";
    words.forEach(w => {
        if (!cur) {
            cur = w;
        } else if ((cur + " " + w).length <= width) {
            cur += " " + w;
        } else {
            lines.push(cur);
            cur = w;
        }
    });
    if (cur) lines.push(cur);
    return lines;
}

function formatClientThermalReceipt(bill, shop) {
    const LINE_WIDTH = 38;
    const shopName = ((shop && shop.shop_name) || "Apna Kirana Store").toUpperCase();
    const shopAddr = (shop && shop.shop_address) || "Main Market, Sector 4, New Delhi";
    const shopPhone = (shop && shop.shop_phone) || "+91 98765 43210";
    const gstin = (shop && shop.gstin) ? `GSTIN: ${shop.gstin}` : null;
    const dateStr = bill.created_at ? new Date(bill.created_at).toLocaleString() : new Date().toLocaleString();

    let lines = [];
    lines.push("=".repeat(LINE_WIDTH));
    lines.push(centerReceiptText(shopName, LINE_WIDTH));
    const addrLines = wrapReceiptText(shopAddr, LINE_WIDTH);
    addrLines.forEach(al => lines.push(centerReceiptText(al, LINE_WIDTH)));
    lines.push(centerReceiptText(`Phone: ${shopPhone}`, LINE_WIDTH));
    if (gstin) lines.push(centerReceiptText(gstin, LINE_WIDTH));
    lines.push("=".repeat(LINE_WIDTH));
    lines.push(`Bill No:    ${bill.bill_number || "BILL-XXXX"}`);
    lines.push(`Date:       ${dateStr}`);

    if (bill.payment_mode === "CASH") {
        lines.push("Payment:    CASH");
        lines.push("Customer:   Walk-in Customer");
        lines.push("Status:     COMPLETED (CASH SALE)");
    } else if (bill.payment_mode === "UPI") {
        lines.push("Payment:    UPI / QR");
        if (bill.customer_name) {
            wrapReceiptText(`Customer:   ${bill.customer_name}`, LINE_WIDTH).forEach(cl => lines.push(cl));
        } else {
            lines.push("Customer:   Walk-in Customer");
        }
        lines.push("Status:     COMPLETED (UPI SALE)");
    } else if (bill.payment_mode === "UDHAAR") {
        lines.push("Payment:    UDHAAR (CREDIT)");
        if (bill.customer_code) lines.push(`Customer ID:${bill.customer_code}`);
        if (bill.customer_name) {
            wrapReceiptText(`Customer:   ${bill.customer_name}`, LINE_WIDTH).forEach(cl => lines.push(cl));
        }
        if (bill.customer_phone_masked) lines.push(`Phone:      ${bill.customer_phone_masked}`);
        lines.push("Status:     VERIFIED: YES");
    } else {
        lines.push(`Payment:    ${bill.payment_mode || "CASH"}`);
        lines.push("Status:     COMPLETED");
    }

    lines.push("-".repeat(LINE_WIDTH));
    lines.push("Product".padEnd(18) + "Qty".padEnd(6) + "Rate".padEnd(7) + "Total".padStart(7));
    lines.push("-".repeat(LINE_WIDTH));

    (bill.items || []).forEach(it => {
        const pName = (it.product_name || it.name || "Item").trim();
        const qtyVal = Number.isInteger(Number(it.quantity)) ? String(Number(it.quantity)) : Number(it.quantity || 0).toFixed(1);
        const unitVal = (it.unit || "").trim();
        const qtyStr = `${qtyVal}${unitVal}`.slice(0, 6);
        const rateStr = Number(it.unit_price || 0).toFixed(2).slice(0, 7);
        const lineTotal = it.line_total !== undefined ? it.line_total : ((it.quantity || 0) * (it.unit_price || 0));
        const totalStr = Number(lineTotal).toFixed(2).slice(0, 7);

        // Never truncate product names with '..'! Wrap cleanly at LINE_WIDTH
        if (pName.length <= 17) {
            lines.push(pName.padEnd(18) + qtyStr.padEnd(6) + rateStr.padEnd(7) + totalStr.padStart(7));
        } else {
            const nameLines = wrapReceiptText(pName, LINE_WIDTH);
            nameLines.forEach(nl => lines.push(nl));
            lines.push(" ".repeat(18) + qtyStr.padEnd(6) + rateStr.padEnd(7) + totalStr.padStart(7));
        }
    });

    const subtotal = (bill.subtotal !== undefined ? bill.subtotal : bill.total_amount) || 0;
    const tax = bill.tax || 0;
    const discount = bill.discount || 0;
    const grandTotal = bill.total_amount || 0;

    lines.push("-".repeat(LINE_WIDTH));
    lines.push("Subtotal:".padEnd(22) + `Rs. ${Number(subtotal).toFixed(2)}`.padStart(16));
    lines.push("Tax / VAT:".padEnd(22) + `Rs. ${Number(tax).toFixed(2)}`.padStart(16));
    lines.push("Discount:".padEnd(22) + `-Rs. ${Number(discount).toFixed(2)}`.padStart(16));
    lines.push("=".repeat(LINE_WIDTH));
    lines.push("GRAND TOTAL:".padEnd(22) + `Rs. ${Number(grandTotal).toFixed(2)}`.padStart(16));
    lines.push("=".repeat(LINE_WIDTH));

    if (bill.payment_mode === "UDHAAR") {
        if (bill.udhaar_transaction_id) {
            lines.push("Udhaar TX:".padEnd(22) + `TX-${String(bill.udhaar_transaction_id).padStart(5, '0')}`.padStart(16));
        }
        const bal = (bill.customer && bill.customer.current_udhaar_balance !== undefined) 
            ? bill.customer.current_udhaar_balance 
            : (bill.udhaar_balance_after !== undefined ? bill.udhaar_balance_after : 0);
        lines.push("Outstanding Balance:".padEnd(22) + `Rs. ${Number(bal).toFixed(2)}`.padStart(16));
        lines.push("=".repeat(LINE_WIDTH));
    }

    const footer = ((shop && shop.invoice_footer) || "Thank you for shopping with us! Visit again.").trim();
    lines.push("=".repeat(LINE_WIDTH));
    const footerLines = wrapReceiptText(footer, LINE_WIDTH);
    footerLines.forEach(fl => lines.push(centerReceiptText(fl, LINE_WIDTH)));
    lines.push(centerReceiptText("Please Visit Again Soon", LINE_WIDTH));
    lines.push("=".repeat(LINE_WIDTH));

    return lines.join("\n");
}

function openFinalizedBillModal() {
    const overlayEl = document.getElementById("bill-completed-modal");
    const cardEl = document.getElementById("bill-completed-card") || 
                   (overlayEl ? overlayEl.querySelector(".modal-card") : null) || 
                   document.querySelector(".modal-receipt");
    const modalBody = document.getElementById("receipt-scrollable-body") || 
                      (cardEl ? cardEl.querySelector(".receipt-scrollable-body") : null);

    if (overlayEl) {
        overlayEl.classList.remove("hidden");
        overlayEl.classList.add("active", "open", "show");
        overlayEl.style.removeProperty("display");
        overlayEl.style.setProperty("display", "flex", "important");
        overlayEl.style.setProperty("visibility", "visible", "important");
        overlayEl.style.setProperty("opacity", "1", "important");
    }

    if (cardEl) {
        cardEl.classList.remove("hidden");
        cardEl.classList.add("active", "open", "show");
        cardEl.style.removeProperty("display");
        cardEl.style.setProperty("display", "flex", "important");
        cardEl.style.setProperty("visibility", "visible", "important");
        cardEl.style.setProperty("opacity", "1", "important");
    }

    if (modalBody) {
        modalBody.scrollTop = 0;
    }

    document.body.style.overflow = "hidden";
}

function closeFinalizedBillModal() {
    if (typeof stopVerificationCountdown === "function") stopVerificationCountdown();
    if (typeof stopUdhaarOtpCountdown === "function") stopUdhaarOtpCountdown();

    const overlayEl = document.getElementById("bill-completed-modal");
    const cardEl = document.getElementById("bill-completed-card") || 
                   (overlayEl ? overlayEl.querySelector(".modal-card") : null) || 
                   document.querySelector(".modal-receipt");

    if (overlayEl) {
        overlayEl.classList.remove("active", "open", "show");
        overlayEl.classList.add("hidden");
        overlayEl.style.removeProperty("display");
        overlayEl.style.setProperty("display", "none", "important");
    }

    if (cardEl) {
        cardEl.classList.remove("active", "open", "show");
        cardEl.classList.add("hidden");
        cardEl.style.removeProperty("display");
        cardEl.style.setProperty("display", "none", "important");
    }

    // Hide any secondary receipt / SMS preview sub-modals / containers
    const smsBox = document.getElementById("sms-mock-container");
    if (smsBox) smsBox.style.display = "none";
    const thermalBox = document.getElementById("thermal-receipt-container");
    if (thermalBox) thermalBox.style.display = "none";
    const toggleSmsBtn = document.getElementById("toggle-sms-btn");
    if (toggleSmsBtn) toggleSmsBtn.textContent = "View SMS Preview";
    const toggleThermalBtn = document.getElementById("toggle-thermal-btn");
    if (toggleThermalBtn) toggleThermalBtn.textContent = "View Thermal Receipt";
    const phoneInput = document.getElementById("customer-phone-input");
    if (phoneInput) phoneInput.value = "";
    currentDeliveryPrep = null;

    // Remove any stray modal backdrops or body scroll locks
    document.body.style.overflow = "";

    // Clear completed draft state
    if (typeof clearDraftBill === "function") {
        clearDraftBill();
    }

    // Reset open Udhaar verification panels and state in the background
    if (typeof resetUdhaarVerificationState === "function") {
        resetUdhaarVerificationState();
    }
    const udhaarCard = document.getElementById("udhaar-selected-customer-card");
    const udhaarVerifBox = document.getElementById("udhaar-verification-box");
    const udhaarLimitAlert = document.getElementById("udhaar-credit-limit-alert");
    const udhaarVerifiedBadge = document.getElementById("udhaar-verified-badge");
    const udhaarOtpInputArea = document.getElementById("udhaar-otp-input-area");
    if (udhaarCard) udhaarCard.style.display = "none";
    if (udhaarVerifBox) udhaarVerifBox.style.display = "none";
    if (udhaarLimitAlert) udhaarLimitAlert.style.display = "none";
    if (udhaarVerifiedBadge) udhaarVerifiedBadge.style.display = "none";
    if (udhaarOtpInputArea) udhaarOtpInputArea.style.display = "none";

    currentCompletedBillId = null;
    currentVerificationSession = null;
    currentVerificationBillId = null;
    currentIdempotencyKey = null;
    isFinalizing = false;
}

const closeReceiptModal = closeFinalizedBillModal;
const closeCompletedBillModal = closeFinalizedBillModal;
const startNewSale = closeFinalizedBillModal;

// Immediate global exports
window.openFinalizedBillModal = openFinalizedBillModal;
window.closeFinalizedBillModal = closeFinalizedBillModal;
window.closeReceiptModal = closeReceiptModal;
window.closeCompletedBillModal = closeCompletedBillModal;
window.startNewSale = startNewSale;

// Capture-phase document-level click listener (guaranteed to intercept before any child stopPropagation)
document.addEventListener("click", (e) => {
    // 1. Close button in finalized receipt modal
    const closeBtn = e.target.closest("#receipt-modal-close-btn, .receipt-close-btn");
    if (closeBtn) {
        e.preventDefault();
        e.stopPropagation();
        window.closeFinalizedBillModal();
        return;
    }

    // 2. Start New Sale / Order button in finalized receipt modal
    const newSaleBtn = e.target.closest("#new-order-btn");
    if (newSaleBtn) {
        e.preventDefault();
        e.stopPropagation();
        window.closeFinalizedBillModal();
        return;
    }

    // 3. Dark modal backdrop overlay click
    const modalBackdrop = document.getElementById("bill-completed-modal");
    if (modalBackdrop && e.target === modalBackdrop) {
        window.closeFinalizedBillModal();
        return;
    }

    // 4. Language selection tab buttons delegation
    const langBtn = e.target.closest(".pos-lang-tab-btn, [data-lang]");
    if (langBtn && langBtn.closest("#pos-lang-tabs")) {
        const lang = langBtn.dataset.lang;
        if (lang) {
            selectVoiceLanguage(lang);
            return;
        }
    }

    // 5. Microphone button toggle delegation
    const micBtn = e.target.closest("#mic-toggle-btn, .btn-mic");
    if (micBtn && micBtn.closest("#tab-billing")) {
        e.preventDefault();
        toggleVoiceRecognition();
        return;
    }

    // 6. Quick Test Voice Input Chips delegation
    const chipBtn = e.target.closest("#sample-chips-container .chip-btn, .sample-chips .chip-btn, .quick-samples .chip-btn");
    if (chipBtn) {
        e.preventDefault();
        const sampleText = chipBtn.dataset.text || chipBtn.getAttribute("data-text");
        if (sampleText) {
            const tInput = document.getElementById("order-text-input");
            if (tInput) tInput.value = sampleText;
            generateDraftBill(sampleText);
        }
        return;
    }

    // 7. Clear Text button delegation
    const clearInBtn = e.target.closest("#clear-input-btn");
    if (clearInBtn) {
        e.preventDefault();
        const tInput = document.getElementById("order-text-input");
        if (tInput) tInput.value = "";
        return;
    }

    // 8. Generate Draft Bill button delegation
    const parseBtn = e.target.closest("#parse-order-btn");
    if (parseBtn) {
        e.preventDefault();
        const tInput = document.getElementById("order-text-input");
        const text = tInput ? tInput.value.trim() : "";
        if (!text) {
            alert("Please speak into the mic or enter order text first.");
            return;
        }
        generateDraftBill(text);
        return;
    }

    // 9. Payment Mode buttons delegation
    const modeOpt = e.target.closest(".mode-option");
    if (modeOpt && modeOpt.closest(".payment-mode-selector")) {
        const radio = modeOpt.querySelector("input[name='payment-mode'], input[type='radio']");
        if (radio) {
            setPaymentMode(radio.value);
        }
    }

    // 10. Clear Draft button delegation
    const clrDraftBtn = e.target.closest("#clear-draft-btn");
    if (clrDraftBtn) {
        e.preventDefault();
        clearDraftBill();
        return;
    }

    // 11. Finalize Bill button delegation
    const finBtn = e.target.closest("#finalize-bill-btn");
    if (finBtn) {
        if (!finBtn.disabled) {
            e.preventDefault();
            finalizeCurrentDraft();
        }
        return;
    }

    // 12. Browse Udhaar Customers modal trigger delegation
    const browseCustBtn = e.target.closest("#btn-browse-udhaar-customers");
    if (browseCustBtn) {
        e.preventDefault();
        openUdhaarCustomerModal();
        return;
    }

    // 13. Inline Udhaar OTP triggers delegation
    if (e.target.closest("#btn-inline-send-sms")) {
        e.preventDefault();
        sendInlineUdhaarOtp("SMS");
        return;
    }
    if (e.target.closest("#btn-inline-send-whatsapp")) {
        e.preventDefault();
        sendInlineUdhaarOtp("WHATSAPP");
        return;
    }
    if (e.target.closest("#btn-inline-verify-otp")) {
        e.preventDefault();
        verifyInlineUdhaarOtp();
        return;
    }
    if (e.target.closest("#btn-inline-resend-otp")) {
        e.preventDefault();
        resendInlineUdhaarOtp();
        return;
    }

    // 14. Thermal Print Direct & Secondary buttons delegation
    if (e.target.closest("#btn-thermal-print-direct, #btn-print-now, #btn-thermal-print")) {
        e.preventDefault();
        printThermalReceipt();
        return;
    }
}, true);

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" || e.keyCode === 27) {
        const modal = document.getElementById("bill-completed-modal");
        if (modal && modal.style.display !== "none" && !modal.classList.contains("hidden")) {
            window.closeFinalizedBillModal();
        }
    }
});

// ==============================================================================
// Customer 2FA Verification Logic (Step 7 & Issue 5)
// ==============================================================================

let currentCompletedBillId = null;
let currentVerificationSession = null;
let currentVerificationBillId = null;
let verificationTimerInterval = null;
let currentDeliveryChannel = "SMS";

function updateVerificationCustomerDisplay({ name, code, phoneMasked, isPhoneVerified }) {
    const nameEls = [document.getElementById("udhaar-verif-customer-name"), document.getElementById("verif-customer-name")].filter(Boolean);
    const codeEls = [document.getElementById("udhaar-verif-customer-code"), document.getElementById("verif-customer-code")].filter(Boolean);
    const phoneEls = [document.getElementById("udhaar-verif-customer-phone"), document.getElementById("verif-customer-phone")].filter(Boolean);
    const phoneLabelEls = [document.getElementById("udhaar-verif-phone-label"), document.getElementById("verif-phone-label")].filter(Boolean);
    const sendBtn = document.getElementById("btn-send-verification");

    nameEls.forEach(el => { el.textContent = name || "--"; });
    codeEls.forEach(el => { el.textContent = code || "--"; });

    phoneEls.forEach(el => {
        if (isPhoneVerified === false) {
            el.textContent = "Not Verified";
            el.className = "text-danger";
        } else {
            el.textContent = phoneMasked || "--";
            el.className = "";
        }
    });

    phoneLabelEls.forEach(el => {
        el.textContent = (isPhoneVerified === false) ? "Phone:" : "Verified Phone:";
    });

    if (sendBtn) {
        if (isPhoneVerified === false) {
            sendBtn.disabled = true;
            sendBtn.title = "Customer phone number is not verified. Verify phone before sending 2FA.";
        } else {
            sendBtn.disabled = false;
            sendBtn.title = "";
        }
    }
}

async function printThermalReceipt() {
    const targetBillId = currentCompletedBillId || (currentVerificationSession && currentVerificationSession.bill_id);
    let receiptText = "";

    const thermalTextEl = document.getElementById("thermal-receipt-text");
    if (thermalTextEl && thermalTextEl.textContent.trim() && !thermalTextEl.textContent.includes("Preparing")) {
        receiptText = thermalTextEl.textContent;
    }

    if (!receiptText && targetBillId) {
        try {
            const res = await fetch("/api/v1/receipts/delivery-prep", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ bill_id: targetBillId })
            });
            if (res.ok) {
                const data = await res.json();
                if (data.receipt && data.receipt.formatted_text_receipt) {
                    receiptText = data.receipt.formatted_text_receipt;
                    if (thermalTextEl) {
                        thermalTextEl.textContent = receiptText;
                    }
                }
            }
        } catch (e) {
            console.error("Failed to fetch receipt text for print:", e);
        }
    }

    if (!receiptText && thermalTextEl) {
        receiptText = thermalTextEl.textContent || "";
    }

    // Populate dedicated #pos-thermal-print-container with ONLY the clean formatted receipt
    let printContainer = document.getElementById("pos-thermal-print-container");
    if (!printContainer) {
        printContainer = document.createElement("div");
        printContainer.id = "pos-thermal-print-container";
        printContainer.className = "thermal-print-only";
        printContainer.style.display = "none";
        document.body.appendChild(printContainer);
    }

    let preEl = document.getElementById("pos-thermal-print-pre");
    if (!preEl) {
        preEl = document.createElement("pre");
        preEl.id = "pos-thermal-print-pre";
        preEl.className = "thermal-receipt-pre";
        printContainer.appendChild(preEl);
    }
    preEl.textContent = receiptText;

    window.print();
};

function selectVerificationChannel(channel, triggerSend = true) {
    currentDeliveryChannel = channel;
    const btnSms = document.getElementById("btn-channel-sms");
    const btnWa = document.getElementById("btn-channel-whatsapp");
    if (btnSms) {
        if (channel === "SMS") btnSms.classList.add("active");
        else btnSms.classList.remove("active");
    }
    if (btnWa) {
        if (channel === "WHATSAPP") btnWa.classList.add("active");
        else btnWa.classList.remove("active");
    }
    if (triggerSend && currentVerificationBillId) {
        initVerificationSessionForBill(currentVerificationBillId, channel);
    }
};

function sendVerificationChallenge() {
    if (currentVerificationBillId) {
        initVerificationSessionForBill(currentVerificationBillId, currentDeliveryChannel);
    }
};

async function initVerificationSessionForBill(billId, channel = "SMS") {
    currentVerificationBillId = billId;
    stopVerificationCountdown();

    const badge = document.getElementById("verification-status-badge");
    const container = document.getElementById("challenge-numbers-container");
    const resultBox = document.getElementById("verification-result-box");
    const retryActions = document.getElementById("verification-retry-actions");
    const timerEl = document.getElementById("verification-timer");
    const noteEl = document.getElementById("verif-channel-note");
    const previewBox = document.getElementById("verif-delivery-preview");
    const previewText = document.getElementById("verif-msg-preview");

    if (badge) {
        badge.className = "badge badge-low-stock";
        badge.textContent = "GENERATING 2FA...";
    }
    if (resultBox) resultBox.style.display = "none";
    if (retryActions) retryActions.style.display = "none";
    if (timerEl) timerEl.textContent = "03:00";
    if (noteEl) noteEl.style.display = "none";
    if (previewBox) previewBox.style.display = "none";
    if (container) {
        container.innerHTML = `<div style="text-align: center; color: var(--text-secondary); width: 100%; padding: 0.5rem;">Generating secure challenge...</div>`;
    }

    try {
        const res = await fetch("/api/v1/verification/sessions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                bill_id: billId,
                delivery_channel: channel,
                expiry_seconds: 180
            })
        });

        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.detail || `Failed to create verification session (${res.status})`);
        }

        const session = await res.json();
        currentVerificationSession = session;

        // Populate authoritative customer info from verification session
        updateVerificationCustomerDisplay({
            name: session.customer_name,
            code: session.customer_code,
            phoneMasked: session.customer_phone_masked,
            isPhoneVerified: session.is_phone_verified
        });

        // Channel status note (e.g. Demo / Not Configured)
        if (noteEl) {
            if (session.channel_status_note) {
                noteEl.textContent = session.channel_status_note;
                noteEl.style.display = "block";
            } else {
                noteEl.style.display = "none";
            }
        }

        // Delivery message preview
        if (previewBox && previewText) {
            if (session.delivery_message_preview) {
                previewText.textContent = session.delivery_message_preview;
                previewBox.style.display = "block";
            } else {
                previewBox.style.display = "none";
            }
        }

        if (badge) {
            badge.className = "badge badge-low-stock";
            badge.textContent = "WAITING CUSTOMER...";
        }

        renderChallengeNumbers(session.challenge_numbers);
        startVerificationCountdown(session.expires_in_seconds || 180);

    } catch (err) {
        console.error("Verification session setup error:", err);
        if (badge) {
            badge.className = "badge badge-out-stock";
            badge.textContent = "SETUP ERROR";
        }
        if (resultBox) {
            resultBox.className = "verification-result-box result-failure";
            resultBox.innerHTML = `<strong>Verification Notice:</strong><br>${escapeHtml(err.message)}`;
            resultBox.style.display = "block";
        }
        if (retryActions) retryActions.style.display = "block";
    }
}

function renderChallengeNumbers(numbers) {
    const container = document.getElementById("challenge-numbers-container");
    if (!container || !numbers) return;

    container.innerHTML = numbers.map(num => `
        <button type="button" class="challenge-num-btn" data-number="${num}" onclick="handleSelectChallengeNumber(${num})">
            ${num}
        </button>
    `).join("");
}

function startVerificationCountdown(seconds) {
    stopVerificationCountdown();
    let remaining = seconds;
    const timerEl = document.getElementById("verification-timer");

    function updateDisplay() {
        const mins = Math.floor(remaining / 60);
        const secs = remaining % 60;
        if (timerEl) {
            timerEl.textContent = `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
        }
    }

    updateDisplay();

    verificationTimerInterval = setInterval(() => {
        remaining -= 1;
        if (remaining <= 0) {
            stopVerificationCountdown();
            handleVerificationExpired();
        } else {
            updateDisplay();
        }
    }, 1000);
}

function stopVerificationCountdown() {
    if (verificationTimerInterval) {
        clearInterval(verificationTimerInterval);
        verificationTimerInterval = null;
    }
}

function handleVerificationExpired() {
    const badge = document.getElementById("verification-status-badge");
    const timerEl = document.getElementById("verification-timer");
    const resultBox = document.getElementById("verification-result-box");
    const retryActions = document.getElementById("verification-retry-actions");
    const buttons = document.querySelectorAll(".challenge-num-btn");

    if (badge) {
        badge.className = "badge badge-out-stock";
        badge.textContent = "EXPIRED";
    }
    if (timerEl) timerEl.textContent = "Expired";
    buttons.forEach(btn => btn.disabled = true);

    if (resultBox) {
        resultBox.className = "verification-result-box result-expired";
        resultBox.innerHTML = `Verification challenge timed out. Tap below to generate a new challenge.`;
        resultBox.style.display = "block";
    }
    if (retryActions) retryActions.style.display = "block";
}

async function handleSelectChallengeNumber(selectedNum) {
    if (!currentVerificationSession) return;

    stopVerificationCountdown();
    const buttons = document.querySelectorAll(".challenge-num-btn");
    buttons.forEach(btn => btn.disabled = true);

    const badge = document.getElementById("verification-status-badge");
    const resultBox = document.getElementById("verification-result-box");
    const retryActions = document.getElementById("verification-retry-actions");

    if (badge) {
        badge.className = "badge badge-listening";
        badge.textContent = "VERIFYING...";
    }

    try {
        const res = await fetch("/api/v1/verification/verify", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: currentVerificationSession.session_id,
                selected_number: selectedNum,
                bill_id: currentVerificationSession.bill_id || currentVerificationBillId
            })
        });

        const data = await res.json();

        if (res.ok && data.success) {
            // VERIFIED
            playAudioTone("bill-success");
            if (badge) {
                badge.className = "badge badge-in-stock";
                badge.textContent = "VERIFIED";
            }
            if (resultBox) {
                resultBox.className = "verification-result-box result-success";
                if (data.payment_mode === "UDHAAR") {
                    resultBox.innerHTML = `<strong>Primary Account Holder Verified!</strong><br>Udhaar purchase approved & inventory deducted atomically.<br>Family account balance updated to <strong>₹${data.udhaar_balance_after !== null ? data.udhaar_balance_after.toFixed(2) : "0.00"}</strong>.`;
                } else {
                    resultBox.innerHTML = `<strong>Customer Verified Successfully!</strong><br>Transaction confirmed with 2FA matching number <strong>${selectedNum}</strong>.`;
                }
                resultBox.style.display = "block";
            }
            if (retryActions) retryActions.style.display = "none";

            // If low stock alerts triggered upon Udhaar stock deduction
            if (data.low_stock_alerts && data.low_stock_alerts.length > 0) {
                const lowStockAlertEl = document.getElementById("completed-low-stock-alert");
                const lowStockItemsEl = document.getElementById("completed-low-stock-items");
                if (lowStockAlertEl && lowStockItemsEl) {
                    lowStockAlertEl.style.display = "block";
                    lowStockItemsEl.innerHTML = data.low_stock_alerts.map(alert => `
                        <div class="low-stock-item-row">
                            <strong>${escapeHtml(alert.product_name)}</strong>: Remaining stock is <strong>${alert.current_stock} ${escapeHtml(alert.unit)}</strong> (Min threshold: ${alert.min_stock_threshold})
                        </div>
                    `).join("");
                }
            }

            // Refresh live inventory, Udhaar, and dashboard metrics
            loadInventorySummary();
            loadUdhaarDashboard();
            loadMainDashboard();

            // Highlight selected button
            buttons.forEach(btn => {
                if (parseInt(btn.dataset.number) === selectedNum) {
                    btn.style.background = "var(--success)";
                    btn.style.borderColor = "#86efac";
                    btn.style.color = "#0f172a";
                }
            });

            // Step 8: Reveal Receipt & Delivery Section and Prepare WhatsApp / SMS
            const receiptSection = document.getElementById("receipt-delivery-section");
            if (receiptSection) {
                receiptSection.style.display = "block";
            }
            prepareDigitalReceiptDelivery(currentVerificationSession.bill_id);

        } else {
            // FAILED
            playAudioTone("error");
            if (badge) {
                badge.className = "badge badge-out-stock";
                badge.textContent = "FAILED";
            }
            if (resultBox) {
                resultBox.className = "verification-result-box result-failure";
                resultBox.innerHTML = `<strong>Verification Failed</strong><br>Selected number ${selectedNum} did not match. Please regenerate challenge.`;
                resultBox.style.display = "block";
            }
            if (retryActions) retryActions.style.display = "block";

            // Hide Receipt Section on failure
            const receiptSection = document.getElementById("receipt-delivery-section");
            if (receiptSection) {
                receiptSection.style.display = "none";
            }

            // Highlight wrong button
            buttons.forEach(btn => {
                if (parseInt(btn.dataset.number) === selectedNum) {
                    btn.style.background = "var(--danger)";
                    btn.style.borderColor = "#fca5a5";
                    btn.style.color = "#ffffff";
                }
            });
        }
    } catch (err) {
        playAudioTone("error");
        console.error("Verification submission error:", err);
        if (badge) {
            badge.className = "badge badge-out-stock";
            badge.textContent = "ERROR";
        }
        if (resultBox) {
            resultBox.className = "verification-result-box result-failure";
            resultBox.innerHTML = `Error: ${escapeHtml(err.message)}`;
            resultBox.style.display = "block";
        }
        if (retryActions) retryActions.style.display = "block";

        const receiptSection = document.getElementById("receipt-delivery-section");
        if (receiptSection) {
            receiptSection.style.display = "none";
        }
    }
};

// ==============================================================================
// Digital Receipt & Delivery Preparation Logic (Step 8)
// ==============================================================================

let currentDeliveryPrep = null;

async function prepareDigitalReceiptDelivery(billId) {
    const phoneInput = document.getElementById("customer-phone-input");
    const rawPhone = phoneInput ? phoneInput.value.trim() : "";

    try {
        const res = await fetch("/api/v1/receipts/delivery-prep", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                bill_id: billId,
                customer_phone: rawPhone || null
            })
        });

        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.detail || `Failed to prepare receipt (${res.status})`);
        }

        const data = await res.json();
        currentDeliveryPrep = data;

        // Populate Thermal Receipt
        const thermalTextEl = document.getElementById("thermal-receipt-text");
        if (thermalTextEl && data.receipt) {
            thermalTextEl.textContent = data.receipt.formatted_text_receipt;
        }

        // Dynamically update receipt modal with latest authoritative shop info
        if (data.receipt) {
            window.syncReceiptModalStoreDetails(data.receipt);
        }

        // Populate SMS Mock
        const smsTextEl = document.getElementById("sms-preview-text");
        const smsCounterEl = document.getElementById("sms-char-counter");
        const smsTimeEl = document.getElementById("sms-timestamp");
        if (smsTextEl && data.sms) {
            smsTextEl.textContent = data.sms.sms_text;
        }
        if (smsCounterEl && data.sms) {
            smsCounterEl.textContent = `${data.sms.char_count} / 160`;
        }
        if (smsTimeEl) {
            smsTimeEl.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }

    } catch (err) {
        console.error("Failed to prepare digital receipt delivery:", err);
    }
}

function handleOpenWhatsApp() {
    const targetBillId = (currentVerificationSession && currentVerificationSession.bill_id) || currentCompletedBillId;
    if (!targetBillId) {
        alert("No active bill found to share receipt.");
        return;
    }

    const phoneInput = document.getElementById("customer-phone-input");
    const phone = phoneInput ? phoneInput.value.trim() : "";

    // Fetch fresh delivery-prep with the current phone entered
    fetch("/api/v1/receipts/delivery-prep", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            bill_id: targetBillId,
            customer_phone: phone || null
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.whatsapp && data.whatsapp.click_to_chat_url) {
            window.open(data.whatsapp.click_to_chat_url, "_blank");
        } else {
            alert(data.detail || "Unable to prepare WhatsApp Click-to-Chat URL.");
        }
    })
    .catch(err => {
        console.error("WhatsApp Click-to-Chat error:", err);
        alert(`WhatsApp error: ${err.message}`);
    });
}



// ==============================================================================
// Udhaar Customer Directory & 4-Digit OTP Verification Flow
// ==============================================================================

let modalUdhaarCustomers = [];
// Udhaar session variables (currentUdhaarDeliveryChannel, currentUdhaarOtpSession, currentPendingUdhaarBill, udhaarOtpCountdownInterval) are declared globally at lines 990-994

async function openUdhaarCustomerModal() {
    const modal = document.getElementById("udhaar-customer-modal");
    const searchInput = document.getElementById("udhaar-modal-search-input");
    const listContainer = document.getElementById("udhaar-customer-cards-list");
    const countLabel = document.getElementById("udhaar-customer-count-label");

    if (modal) modal.style.display = "flex";
    if (searchInput) {
        searchInput.value = "";
        setTimeout(() => searchInput.focus(), 100);
    }
    if (listContainer) {
        listContainer.innerHTML = `<div style="text-align: center; color: var(--text-secondary); padding: 1.5rem;">Loading customer accounts...</div>`;
    }

    try {
        const res = await fetch("/api/v1/customers");
        if (!res.ok) throw new Error("Failed to load customer list");
        modalUdhaarCustomers = await res.json();
        // Deterministic alphabetical sort by customer name
        modalUdhaarCustomers.sort((a, b) => a.full_name.localeCompare(b.full_name, undefined, { sensitivity: "base" }));
        renderUdhaarModalCustomerCards(modalUdhaarCustomers);
    } catch (err) {
        console.error("Error loading Udhaar customers:", err);
        if (listContainer) {
            listContainer.innerHTML = `<div style="text-align: center; color: var(--danger); padding: 1.5rem;">Error: ${escapeHtml(err.message)}</div>`;
        }
    }
};

function closeUdhaarCustomerModal() {
    const modal = document.getElementById("udhaar-customer-modal");
    if (modal) modal.style.display = "none";
};

function renderUdhaarModalCustomerCards(customers) {
    const listContainer = document.getElementById("udhaar-customer-cards-list");
    const countLabel = document.getElementById("udhaar-customer-count-label");
    if (!listContainer) return;

    if (countLabel) {
        countLabel.textContent = `${customers.length} customer account(s)`;
    }

    if (customers.length === 0) {
        listContainer.innerHTML = `
            <div style="text-align: center; color: var(--text-secondary); padding: 2rem; background: var(--bg-card); border-radius: 8px;">
                <p style="margin: 0; font-size: 0.95rem; font-weight: 600;">No matching customers found.</p>
                <span style="font-size: 0.8rem; opacity: 0.7;">Check search spelling or register a new customer in Udhaar tab.</span>
            </div>
        `;
        return;
    }

    listContainer.innerHTML = customers.map(c => {
        const isSelected = selectedPOSCustomer && selectedPOSCustomer.id === c.id;
        const custCode = c.customer_code || `C-${String(c.id).padStart(6, "0")}`;
        const phone = c.phone || "No phone";
        const avail = c.available_credit !== undefined ? c.available_credit : Math.max(0, c.credit_limit - c.current_udhaar_balance);
        const bal = c.current_udhaar_balance || 0;

        return `
            <div class="customer-select-card ${isSelected ? 'selected' : ''}" onclick="selectUdhaarModalCustomer(${c.id})">
                <div class="customer-select-info">
                    <div class="customer-select-name">
                        ${escapeHtml(c.full_name)}
                        <span class="badge" style="font-size: 0.72rem; background: rgba(56, 189, 248, 0.2); color: #38bdf8;">${custCode}</span>
                    </div>
                    <div class="customer-select-meta">
                        ${escapeHtml(phone)} ${c.address ? `• ${escapeHtml(c.address)}` : ''}
                    </div>
                </div>
                <div class="customer-select-credits">
                    <span class="credit-badge-avail">Avail: ₹${avail.toFixed(2)}</span>
                    <div class="credit-badge-balance">Bal: ₹${bal.toFixed(2)} / Limit: ₹${c.credit_limit.toFixed(2)}</div>
                </div>
            </div>
        `;
    }).join("");
}

// Live search listener on customer modal search input
document.addEventListener("DOMContentLoaded", () => {
    const searchInput = document.getElementById("udhaar-modal-search-input");
    if (searchInput) {
        searchInput.addEventListener("input", (e) => {
            const query = e.target.value.trim().toLowerCase();
            if (!query) {
                renderUdhaarModalCustomerCards(modalUdhaarCustomers);
                return;
            }
            const filtered = modalUdhaarCustomers.filter(c => 
                (c.full_name && c.full_name.toLowerCase().includes(query)) ||
                (c.phone && c.phone.includes(query)) ||
                (c.customer_code && c.customer_code.toLowerCase().includes(query)) ||
                (c.address && c.address.toLowerCase().includes(query))
            );
            renderUdhaarModalCustomerCards(filtered);
        });
    }
});

window.selectUdhaarModalCustomer = function(customerId) {
    const cust = (modalUdhaarCustomers || []).find(c => c.id === customerId) || (allPOSCustomers || []).find(c => c.id === customerId);
    if (!cust) return;

    selectedPOSCustomer = cust;

    // Sync POS select dropdown
    const custSelect = document.getElementById("udhaar-primary-customer-select");
    if (custSelect) {
        let opt = Array.from(custSelect.options).find(o => parseInt(o.value) === customerId);
        if (!opt) {
            opt = new Option(`${cust.full_name} (${cust.customer_code || `C-${cust.id}`})`, cust.id);
            custSelect.add(opt);
        }
        custSelect.value = customerId;
    }

    closeUdhaarCustomerModal();
    resetUdhaarVerificationState();
    renderPOSCustomerSelection(cust);
};

function openUdhaarConfirmModal() {
    if (!selectedPOSCustomer) {
        openUdhaarCustomerModal();
        return;
    }

    const validItems = getValidDraftItems();
    if (validItems.length === 0) {
        alert("Please add at least one item to the bill.");
        return;
    }

    const modal = document.getElementById("udhaar-confirm-modal");
    const nameEl = document.getElementById("confirm-cust-name");
    const codeEl = document.getElementById("confirm-cust-code");
    const phoneEl = document.getElementById("confirm-cust-phone");
    const addrEl = document.getElementById("confirm-cust-address");
    const limitEl = document.getElementById("confirm-cust-limit");
    const balEl = document.getElementById("confirm-cust-balance");
    const availEl = document.getElementById("confirm-cust-available");

    const itemsBody = document.getElementById("confirm-tx-items-body");
    const totalAmountEl = document.getElementById("confirm-tx-total-amount");
    const creditExceededAlert = document.getElementById("confirm-credit-exceeded-alert");
    const btnSendOtp = document.getElementById("btn-send-udhaar-otp");

    // Populate customer info
    const cust = selectedPOSCustomer;
    if (nameEl) nameEl.textContent = cust.full_name;
    if (codeEl) codeEl.textContent = cust.customer_code || `C-${String(cust.id).padStart(6, "0")}`;
    if (phoneEl) phoneEl.textContent = cust.phone || "--";
    if (addrEl) addrEl.textContent = cust.address || cust.address_line || "Dehradun";
    if (limitEl) limitEl.textContent = `₹${cust.credit_limit.toFixed(2)}`;
    if (balEl) balEl.textContent = `₹${cust.current_udhaar_balance.toFixed(2)}`;

    const avail = cust.available_credit !== undefined ? cust.available_credit : Math.max(0, cust.credit_limit - cust.current_udhaar_balance);
    if (availEl) availEl.textContent = `₹${avail.toFixed(2)}`;

    // Populate draft items table
    let grandTotal = 0;
    if (itemsBody) {
        itemsBody.innerHTML = validItems.map(it => {
            const lineTotal = it.quantity * it.unit_price;
            grandTotal += lineTotal;
            return `
                <tr style="border-bottom: 1px solid rgba(71, 85, 105, 0.2);">
                    <td style="padding: 0.45rem 0.6rem;"><strong>${escapeHtml(it.product_name)}</strong></td>
                    <td style="padding: 0.45rem 0.6rem; text-align: center;">${it.quantity} ${escapeHtml(it.unit || '')}</td>
                    <td style="padding: 0.45rem 0.6rem; text-align: right;">₹${it.unit_price.toFixed(2)}</td>
                    <td style="padding: 0.45rem 0.6rem; text-align: right; font-weight: 600;">₹${lineTotal.toFixed(2)}</td>
                </tr>
            `;
        }).join("");
    }
    if (totalAmountEl) totalAmountEl.textContent = `₹${grandTotal.toFixed(2)}`;

    // Credit limit check
    if (grandTotal > avail) {
        if (creditExceededAlert) {
            creditExceededAlert.style.display = "block";
            const msgSpan = document.getElementById("confirm-credit-exceeded-msg");
            if (msgSpan) msgSpan.textContent = `Bill total (₹${grandTotal.toFixed(2)}) exceeds available credit limit (₹${avail.toFixed(2)}) by ₹${(grandTotal - avail).toFixed(2)}.`;
        }
        if (btnSendOtp) {
            btnSendOtp.disabled = true;
            btnSendOtp.style.opacity = "0.5";
            btnSendOtp.style.cursor = "not-allowed";
        }
    } else {
        if (creditExceededAlert) creditExceededAlert.style.display = "none";
        if (btnSendOtp) {
            btnSendOtp.disabled = false;
            btnSendOtp.style.opacity = "1";
            btnSendOtp.style.cursor = "pointer";
        }
    }

    // Reset to Step A
    const stepA = document.getElementById("confirm-delivery-step");
    const stepB = document.getElementById("confirm-otp-entry-step");
    if (stepA) stepA.style.display = "block";
    if (stepB) stepB.style.display = "none";

    setUdhaarOtpMethod("SMS");

    if (modal) modal.style.display = "flex";
};

function closeUdhaarConfirmModal() {
    const modal = document.getElementById("udhaar-confirm-modal");
    if (modal) modal.style.display = "none";
    stopUdhaarOtpCountdown();
};

function setUdhaarOtpMethod(method) {
    currentUdhaarDeliveryChannel = method;
    const btnSms = document.getElementById("btn-otp-method-sms");
    const btnWa = document.getElementById("btn-otp-method-whatsapp");
    if (btnSms) {
        if (method === "SMS") btnSms.classList.add("active");
        else btnSms.classList.remove("active");
    }
    if (btnWa) {
        if (method === "WHATSAPP") btnWa.classList.add("active");
        else btnWa.classList.remove("active");
    }
};

async function requestUdhaarOtp() {
    if (!selectedPOSCustomer) return;
    const validItems = getValidDraftItems();
    if (validItems.length === 0) return;

    const btnSend = document.getElementById("btn-send-udhaar-otp");
    const btnResend = document.getElementById("btn-resend-udhaar-otp");
    if (btnSend) {
        btnSend.disabled = true;
        btnSend.textContent = "Generating OTP...";
    }
    if (btnResend) {
        btnResend.disabled = true;
        btnResend.textContent = "Sending...";
    }

    try {
        // Step 1: Create draft bill in PENDING_VERIFICATION
        if (!currentPendingUdhaarBill) {
            const billPayload = {
                items: validItems.map(it => ({
                    product_id: it.product_id,
                    quantity: it.quantity
                })),
                payment_mode: "UDHAAR",
                customer_id: selectedPOSCustomer.id,
                idempotency_key: `draft-${currentDraft.draft_id}-${Date.now()}`,
                notes: "Udhaar POS Sale (Pending OTP Verification)"
            };

            const billRes = await fetch("/api/v1/billing/finalize", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(billPayload)
            });
            if (!billRes.ok) {
                const err = await billRes.json();
                throw new Error(err.detail || "Failed to create Udhaar transaction.");
            }
            currentPendingUdhaarBill = await billRes.json();
        }

        // Step 2: Create 4-digit OTP verification session
        const sessionPayload = {
            bill_id: currentPendingUdhaarBill.id,
            delivery_channel: currentUdhaarDeliveryChannel,
            verification_type: "OTP",
            expiry_seconds: 180
        };

        const sessRes = await fetch("/api/v1/verification/sessions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(sessionPayload)
        });
        if (!sessRes.ok) {
            const err = await sessRes.json();
            throw new Error(err.detail || "Failed to generate OTP session.");
        }
        currentUdhaarOtpSession = await sessRes.json();

        // Switch to Step B: OTP Entry
        const stepA = document.getElementById("confirm-delivery-step");
        const stepB = document.getElementById("confirm-otp-entry-step");
        if (stepA) stepA.style.display = "none";
        if (stepB) stepB.style.display = "block";

        // Display Message Preview if simulated demo
        const previewBanner = document.getElementById("udhaar-otp-preview-banner");
        const previewText = document.getElementById("udhaar-otp-preview-text");
        if (previewBanner && previewText) {
            if (currentUdhaarOtpSession.delivery_message_preview) {
                previewText.textContent = currentUdhaarOtpSession.delivery_message_preview;
                previewBanner.style.display = "block";
            } else {
                previewBanner.style.display = "none";
            }
        }

        // Reset and focus OTP input
        const otpInput = document.getElementById("udhaar-otp-input");
        const feedbackEl = document.getElementById("udhaar-otp-feedback");
        const attemptsEl = document.getElementById("udhaar-otp-attempts-info");

        if (otpInput) {
            otpInput.value = "";
            otpInput.disabled = false;
            setTimeout(() => otpInput.focus(), 100);
        }
        if (feedbackEl) feedbackEl.style.display = "none";
        if (attemptsEl) attemptsEl.textContent = "Attempt 0 of 3";

        startUdhaarOtpCountdown(currentUdhaarOtpSession.expires_in_seconds || 180);

    } catch (err) {
        console.error("Error creating Udhaar OTP session:", err);
        alert(`Verification Error: ${err.message}`);
    } finally {
        if (btnSend) {
            btnSend.disabled = false;
            btnSend.textContent = "Send 4-Digit OTP to Customer";
        }
        if (btnResend) {
            btnResend.disabled = false;
            btnResend.textContent = "Resend OTP";
        }
    }
};

function startUdhaarOtpCountdown(seconds) {
    stopUdhaarOtpCountdown();
    let remaining = seconds;
    const timerEl = document.getElementById("udhaar-otp-timer");

    function updateDisplay() {
        const mins = Math.floor(remaining / 60);
        const secs = remaining % 60;
        if (timerEl) {
            timerEl.textContent = `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
        }
    }
    updateDisplay();

    udhaarOtpCountdownInterval = setInterval(() => {
        remaining -= 1;
        if (remaining <= 0) {
            stopUdhaarOtpCountdown();
            handleUdhaarOtpExpired();
        } else {
            updateDisplay();
        }
    }, 1000);
}

function stopUdhaarOtpCountdown() {
    if (udhaarOtpCountdownInterval) {
        clearInterval(udhaarOtpCountdownInterval);
        udhaarOtpCountdownInterval = null;
    }
}

function handleUdhaarOtpExpired() {
    const timerEl = document.getElementById("udhaar-otp-timer");
    const otpInput = document.getElementById("udhaar-otp-input");
    const feedbackEl = document.getElementById("udhaar-otp-feedback");

    if (timerEl) timerEl.textContent = "Expired";
    if (otpInput) otpInput.disabled = true;

    if (feedbackEl) {
        feedbackEl.className = "alert-banner alert-danger";
        feedbackEl.innerHTML = "OTP has expired. Please click <strong>Resend OTP</strong> to generate a fresh verification code.";
        feedbackEl.style.display = "block";
    }
}

async function submitUdhaarOtp() {
    if (!currentUdhaarOtpSession || !currentPendingUdhaarBill) return;

    const otpInput = document.getElementById("udhaar-otp-input");
    const feedbackEl = document.getElementById("udhaar-otp-feedback");
    const attemptsEl = document.getElementById("udhaar-otp-attempts-info");
    const submitBtn = document.getElementById("btn-submit-udhaar-otp");

    const otp = otpInput ? otpInput.value.trim() : "";
    if (otp.length !== 4 || !/^\d{4}$/.test(otp)) {
        if (feedbackEl) {
            feedbackEl.className = "alert-banner alert-warning";
            feedbackEl.textContent = "Please enter the complete 4-digit numeric OTP.";
            feedbackEl.style.display = "block";
        }
        if (otpInput) otpInput.focus();
        return;
    }

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Verifying & Finalizing...";
    }

    try {
        const verifyRes = await fetch("/api/v1/verification/verify", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: currentUdhaarOtpSession.session_id,
                otp: otp,
                bill_id: currentPendingUdhaarBill.id,
                customer_id: selectedPOSCustomer.id
            })
        });

        const verifyData = await verifyRes.json();

        if (!verifyRes.ok || !verifyData.success) {
            // Failure handling
            playAudioTone("error");
            const detailMsg = verifyData.detail || verifyData.message || "Invalid OTP entered. Please try again.";
            if (attemptsEl && verifyData.attempts !== undefined) {
                attemptsEl.textContent = `Attempt ${verifyData.attempts} of ${verifyData.max_attempts || 3}`;
            }
            if (feedbackEl) {
                feedbackEl.className = "alert-banner alert-danger";
                feedbackEl.textContent = detailMsg;
                feedbackEl.style.display = "block";
            }
            if (otpInput) {
                otpInput.value = "";
                otpInput.focus();
            }
            return;
        }

        // Success! Finalized atomically
        stopUdhaarOtpCountdown();
        playAudioTone("bill-success");

        if (feedbackEl) {
            feedbackEl.className = "alert-banner alert-success";
            feedbackEl.innerHTML = "<strong>Customer Verified!</strong> Udhaar transaction recorded and stock deducted.";
            feedbackEl.style.display = "block";
        }

        const completedBill = currentPendingUdhaarBill;
        currentPendingUdhaarBill = null;
        currentUdhaarOtpSession = null;

        // Clear draft from POS
        clearDraftBill();

        setTimeout(() => {
            closeUdhaarConfirmModal();
            displayBillCompletedModal(completedBill);
            loadInventorySummary();
            loadProducts();
            loadDashboardData();
        }, 800);

    } catch (err) {
        console.error("Error submitting Udhaar OTP:", err);
        if (feedbackEl) {
            feedbackEl.className = "alert-banner alert-danger";
            feedbackEl.textContent = err.message;
            feedbackEl.style.display = "block";
        }
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = "Verify & Finalize Udhaar";
        }
    }
};



    // Real-time synchronization listeners
    window.addEventListener('products-updated', () => {
        if (typeof currentDraft !== 'undefined' && currentDraft && currentDraft.items && currentDraft.items.length > 0) {
            recalculateCurrentDraft();
        }
        if (typeof allPOSCustomers !== 'undefined') {
            loadPOSCustomerDropdown();
        }
    });

    window.addEventListener('shop-profile-updated', (e) => {
        const shop = e.detail || window.currentShopProfile;
        if (shop) {
            const draftStore = document.getElementById('draft-store-title');
            if (draftStore) draftStore.textContent = shop.shop_name || 'Apna Kirana Store';
            if (typeof syncReceiptModalStoreDetails === 'function') {
                syncReceiptModalStoreDetails(shop);
            }
        }
    });

    const BillingModule = {
        init: initPOSBilling,
        generateDraftBill,
        renderDraftBill,
        handleDraftQtyChange,
        handleDeleteDraftItem,
        recalculateCurrentDraft,
        clearDraftBill,
        finalizeCurrentDraft,
        loadPOSCustomerDropdown,
        updatePOSCreditDisplay,
        printThermalReceipt,
        selectVerificationChannel,
        sendVerificationChallenge,
        handleSelectChallengeNumber,
        displayBillCompletedModal,
        prepareDigitalReceiptDelivery,
        openUdhaarCustomerModal,
        closeUdhaarCustomerModal,
        openUdhaarConfirmModal,
        closeUdhaarConfirmModal,
        setUdhaarOtpMethod,
        requestUdhaarOtp,
        submitUdhaarOtp,
        handleDraftStepQty,
        handleDraftUnitChange,
        promptAssignProduct,
        quickAddProductToDraft,
        closeCompletedBillModal,
        closeFinalizedBillModal,
        closeReceiptModal,
        openFinalizedBillModal,
        startNewSale,
        selectVoiceLanguage,
        switchVoiceLanguage,
        setMicVisualState
    };

    window.BillingModule = BillingModule;
    window.initPOSBilling = initPOSBilling;
    window.initBilling = initPOSBilling;
    window.generateDraftBill = generateDraftBill;
    window.renderDraftBill = renderDraftBill;
    window.handleDraftQtyChange = handleDraftQtyChange;
    window.handleDraftStepQty = handleDraftStepQty;
    window.handleDraftUnitChange = handleDraftUnitChange;
    window.promptAssignProduct = promptAssignProduct;
    window.quickAddProductToDraft = quickAddProductToDraft;
    window.closeCompletedBillModal = closeCompletedBillModal;
    window.closeFinalizedBillModal = closeFinalizedBillModal;
    window.closeReceiptModal = closeReceiptModal;
    window.openFinalizedBillModal = openFinalizedBillModal;
    window.startNewSale = startNewSale;
    window.selectVoiceLanguage = selectVoiceLanguage;
    window.switchVoiceLanguage = switchVoiceLanguage;
    window.setMicVisualState = setMicVisualState;
    window.handleDeleteDraftItem = handleDeleteDraftItem;
    window.recalculateCurrentDraft = recalculateCurrentDraft;
    window.clearDraftBill = clearDraftBill;
    window.finalizeCurrentDraft = finalizeCurrentDraft;
    window.loadPOSCustomerDropdown = loadPOSCustomerDropdown;
    window.updatePOSCreditDisplay = updatePOSCreditDisplay;
    window.printThermalReceipt = printThermalReceipt;
    window.selectVerificationChannel = selectVerificationChannel;
    window.sendVerificationChallenge = sendVerificationChallenge;
    window.handleSelectChallengeNumber = handleSelectChallengeNumber;
    window.displayBillCompletedModal = displayBillCompletedModal;
    window.prepareDigitalReceiptDelivery = prepareDigitalReceiptDelivery;
    window.openUdhaarCustomerModal = openUdhaarCustomerModal;
    window.closeUdhaarCustomerModal = closeUdhaarCustomerModal;
    window.openUdhaarConfirmModal = openUdhaarConfirmModal;
    window.closeUdhaarConfirmModal = closeUdhaarConfirmModal;
    window.setUdhaarOtpMethod = setUdhaarOtpMethod;
    window.requestUdhaarOtp = requestUdhaarOtp;
    window.submitUdhaarOtp = submitUdhaarOtp;
    window.toggleVoiceRecognition = toggleVoiceRecognition;
    window.finalizeBill = finalizeCurrentDraft;
    window.setPaymentMode = setPaymentMode;
    window.handlePaymentModeChange = handlePaymentModeChange;
    window.sendInlineUdhaarOtp = sendInlineUdhaarOtp;
    window.verifyInlineUdhaarOtp = verifyInlineUdhaarOtp;
    window.resendInlineUdhaarOtp = resendInlineUdhaarOtp;
    window.selectUdhaarModalCustomer = selectUdhaarModalCustomer;
    window.selectPosCategory = selectPosCategory;
    window.renderPosProductCatalog = renderPosProductCatalog;

    // Automatic self-initialization on load & DOMContentLoaded
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
            initPOSBilling();
            selectVoiceLanguage(currentVoiceLanguage);
        });
    } else {
        initPOSBilling();
        selectVoiceLanguage(currentVoiceLanguage);
    }

})(window);
