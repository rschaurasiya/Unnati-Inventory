/**
 * Kirana AI Copilot Frontend Controller
 * Modern Voice & Text AI Workflow:
 *   - Default Text Mode: Silent text responses with zero auto-speech.
 *   - Inline Listen Buttons: Every assistant response includes an inline Listen button
 *     using Web Speech API (SpeechSynthesis) with dynamic Stop capability.
 *   - Dedicated Voice Mode: Microphone button captures speech via Web Speech API (webkitSpeechRecognition)
 *     with active listening wave animation, transcribes text, queries assistant, and automatically
 *     speaks the reply aloud via SpeechSynthesis.
 *   - State Management & Interruption: Stop button, panel close, and page navigation interrupt speech.
 */

(function () {
    "use strict";

    let isOpen = false;
    let isListening = false;
    let recognition = null;
    let conversationHistory = [];
    let currentUtterance = null;
    let activeListenBtn = null;
    let messageIdCounter = 0;

    // Preserved for backward-compatibility with tests & preferences
    let speakReplies = true;
    const storedSpeak = localStorage.getItem("copilot_speak_replies");
    if (storedSpeak !== null) {
        speakReplies = storedSpeak === "true";
    }

    /**
     * Sanitizes markdown, symbols, and currency for natural TTS speech synthesis.
     * Converts "₹" -> "Rupees " and strips formatting characters.
     */
    function sanitizeForSpeech(text) {
        if (!text || typeof text !== "string") return "";
        return text
            .replace(/₹\s*/g, "Rupees ")
            .replace(/Rs\.?\s*/gi, "Rupees ")
            .replace(/\*\*(.*?)\*\*/g, "$1") // bold
            .replace(/\*(.*?)\*/g, "$1")   // italics
            .replace(/`([^`]+)`/g, "$1")   // inline code
            .replace(/#+/g, "")            // all hash/header symbols
            .replace(/^\s*[-*+]\s+/gm, "") // bullet dashes
            .replace(/ACTION_TAB:\s*[a-zA-Z0-9_]+/gi, "") // action tags
            .replace(/\s+/g, " ")
            .trim();
    }

    /**
     * Updates the visual and text state of an inline Listen / Stop button.
     */
    function setListenBtnState(btn, state) {
        if (!btn) return;
        const isPlaying = state === "playing";
        if (isPlaying) {
            btn.classList.add("speaking");
            btn.setAttribute("title", "Click to stop listening");
            btn.innerHTML = `
                <svg class="stop-icon" width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                    <rect x="6" y="6" width="12" height="12" rx="2"></rect>
                </svg>
                <span>Stop</span>
            `;
        } else {
            btn.classList.remove("speaking");
            btn.setAttribute("title", "Click to listen to this answer aloud");
            btn.innerHTML = `
                <svg class="listen-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
                    <path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path>
                    <path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path>
                </svg>
                <span>Listen</span>
            `;
        }
    }

    /**
     * Helper to stop any actively playing audio immediately.
     */
    function stopVoicePlayback() {
        if (activeListenBtn) {
            setListenBtnState(activeListenBtn, "idle");
            activeListenBtn = null;
        }
        if ("speechSynthesis" in window) {
            try { window.speechSynthesis.cancel(); } catch (e) {}
        }
        currentUtterance = null;
        if (window.ElevenLabsVoice && typeof window.ElevenLabsVoice.stop === "function") {
            try { window.ElevenLabsVoice.stop(); } catch (e) {}
        }
        if (window.stopVoicePlayback && typeof window.stopVoicePlayback === "function") {
            try { window.stopVoicePlayback(); } catch (e) {}
        }
    }

    /**
     * Reads text aloud using the browser's Web Speech API (SpeechSynthesis).
     * @param {string} text - Raw text to speak
     * @param {HTMLElement|null} triggerButton - Optional inline listen button to update
     */
    function speakUsingSpeechSynthesis(text, triggerButton) {
        if (!text) return;
        const speechText = sanitizeForSpeech(text);
        if (!speechText) return;

        // Ensure any currently active utterance is stopped
        stopVoicePlayback();

        if (!("speechSynthesis" in window)) {
            console.warn("Web Speech API (SpeechSynthesis) not supported in this browser.");
            if (typeof window.speakWithElevenLabs === "function") {
                window.speakWithElevenLabs(speechText, { force: true });
                return;
            }
            appendSystemNotice("Text-to-Speech audio is not supported in this browser.");
            return;
        }

        try {
            const utterance = new SpeechSynthesisUtterance(speechText);

            // Detect Hindi / Hinglish vs Indian English
            const hasDevanagari = /[\u0900-\u097F]/.test(speechText);
            const lower = speechText.toLowerCase();
            const isHindi = hasDevanagari || (/\b(namaste|dhanyawad|shukriya|udhaar|khata|maal|khatam|paisa|rupaye|kaise|karein|batao|kitna|hai|hain|aapse|aapka|bhai|dukaan|kirana)\b/.test(lower));

            utterance.lang = isHindi ? "hi-IN" : "en-IN";
            utterance.rate = 1.0;
            utterance.pitch = 1.0;

            const voices = window.speechSynthesis.getVoices() || [];
            if (voices.length > 0) {
                const targetPrefix = isHindi ? "hi" : "en";
                const match = voices.find(v => v.lang && v.lang.toLowerCase().startsWith(targetPrefix) && v.lang.toLowerCase().includes("in")) ||
                              voices.find(v => v.lang && v.lang.toLowerCase().startsWith(targetPrefix)) ||
                              voices.find(v => v.lang && v.lang.toLowerCase().includes("in"));
                if (match) {
                    utterance.voice = match;
                }
            }

            currentUtterance = utterance;

            if (triggerButton) {
                activeListenBtn = triggerButton;
                setListenBtnState(triggerButton, "playing");
            }

            utterance.onstart = function () {
                if (triggerButton) {
                    activeListenBtn = triggerButton;
                    setListenBtnState(triggerButton, "playing");
                }
            };

            utterance.onend = function () {
                if (triggerButton && activeListenBtn === triggerButton) {
                    setListenBtnState(triggerButton, "idle");
                    activeListenBtn = null;
                }
                if (currentUtterance === utterance) {
                    currentUtterance = null;
                }
            };

            utterance.onerror = function (e) {
                if (e.error !== "interrupted" && e.error !== "canceled") {
                    console.warn("SpeechSynthesis error:", e);
                }
                if (triggerButton && activeListenBtn === triggerButton) {
                    setListenBtnState(triggerButton, "idle");
                    activeListenBtn = null;
                }
                if (currentUtterance === utterance) {
                    currentUtterance = null;
                }
            };

            window.speechSynthesis.speak(utterance);
        } catch (err) {
            console.error("Failed to speak via SpeechSynthesis:", err);
            if (triggerButton) {
                setListenBtnState(triggerButton, "idle");
                activeListenBtn = null;
            }
        }
    }

    /**
     * Handles clicking an inline Listen / Stop button.
     */
    function handleListenClick(btn) {
        if (!btn) return;
        if (btn.classList.contains("speaking")) {
            // User clicked Stop
            stopVoicePlayback();
            return;
        }

        const rawText = btn.getAttribute("data-text") || "";
        if (rawText) {
            speakUsingSpeechSynthesis(rawText, btn);
        }
    }

    /**
     * Assistant speech entry point (maps directly to Web Speech API SpeechSynthesis).
     */
    function speakAssistantReply(text, btn) {
        speakUsingSpeechSynthesis(text, btn || null);
    }

    /**
     * Initializes Web Speech API recognition for voice input.
     */
    function initSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            console.warn("Web Speech API SpeechRecognition not supported in this browser.");
            return;
        }

        try {
            recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.lang = "hi-IN"; // Accurately captures both Hindi and Indian English

            recognition.onstart = function () {
                isListening = true;
                updateVoiceModeUI();
            };

            recognition.onresult = function (event) {
                let transcript = "";
                if (event.results && event.results.length > 0) {
                    for (let i = event.resultIndex; i < event.results.length; ++i) {
                        if (event.results[i][0] && event.results[i][0].transcript) {
                            transcript += event.results[i][0].transcript;
                        }
                    }
                }

                transcript = transcript.trim();
                const input = document.getElementById("copilot-input");
                if (input) input.value = transcript;

                isListening = false;
                updateVoiceModeUI();

                if (transcript) {
                    // Auto-submit recognized question with inputSource = "mic"
                    submitMessage(transcript, "mic");
                } else {
                    appendSystemNotice("Aapki aawaz clear nahi thi. Kripya mic dabakar dobara bole ya type karein.");
                }
            };

            recognition.onspeechend = function () {
                if (recognition) {
                    try { recognition.stop(); } catch (e) {}
                }
            };

            recognition.onerror = function (event) {
                console.warn("Copilot speech recognition error:", event.error);
                isListening = false;
                updateVoiceModeUI();

                if (event.error === "no-speech") {
                    appendSystemNotice("Aapki aawaz sunai nahi di. Kripya mic dabakar dobara bole ya type karein.");
                } else if (event.error === "not-allowed" || event.error === "permission-denied") {
                    appendSystemNotice("Microphone permission denied. Please allow microphone access in your browser settings to use Voice Mode.");
                } else if (event.error === "network") {
                    appendSystemNotice("Speech recognition network error. Please check connection or type your question.");
                }
            };

            recognition.onend = function () {
                isListening = false;
                updateVoiceModeUI();
            };
        } catch (err) {
            console.error("Failed to initialize SpeechRecognition:", err);
        }
    }

    function updateVoiceModeUI() {
        const micBtn = document.getElementById("copilot-mic-btn");
        const waveBox = document.getElementById("copilot-listening-wave");
        const input = document.getElementById("copilot-input");

        if (micBtn) {
            if (isListening) {
                micBtn.classList.add("listening");
                micBtn.title = "Listening... Click to cancel voice mode";
            } else {
                micBtn.classList.remove("listening");
                micBtn.title = "Voice Mode: Speak your question";
            }
        }

        if (waveBox) {
            waveBox.style.display = isListening ? "flex" : "none";
        }

        if (input) {
            if (isListening) {
                input.placeholder = "Listening... Speak your question now";
            } else if (!input.value) {
                input.placeholder = "Ask anything in English / Hindi...";
            }
        }
    }

    function toggleMic() {
        if (!recognition) {
            initSpeechRecognition();
        }
        if (!recognition) {
            appendSystemNotice("Voice input is not supported in this browser. Please type your question.");
            return;
        }

        if (isListening) {
            try { recognition.stop(); } catch (e) {}
            isListening = false;
            updateVoiceModeUI();
        } else {
            // Stop any ongoing speech playback before listening
            stopVoicePlayback();
            try {
                recognition.start();
            } catch (err) {
                console.warn("Failed to start speech recognition:", err);
                try {
                    recognition.stop();
                    setTimeout(() => recognition.start(), 150);
                } catch (retryErr) {
                    console.error("Mic start retry error:", retryErr);
                }
            }
        }
    }

    function stopListening() {
        if (isListening && recognition) {
            try { recognition.stop(); } catch (e) {}
        }
        isListening = false;
        updateVoiceModeUI();
    }

    function toggleSpeech() {
        speakReplies = !speakReplies;
        localStorage.setItem("copilot_speak_replies", speakReplies ? "true" : "false");
        if (!speakReplies) {
            stopVoicePlayback();
        }
    }

    function togglePanel() {
        if (isOpen) {
            closePanel();
        } else {
            openPanel();
        }
    }

    function openPanel() {
        const panel = document.getElementById("kirana-copilot-panel");
        if (panel) {
            panel.style.display = "flex";
            isOpen = true;
            const input = document.getElementById("copilot-input");
            if (input) setTimeout(() => input.focus(), 100);
        }
    }

    function closePanel() {
        const panel = document.getElementById("kirana-copilot-panel");
        if (panel) {
            panel.style.display = "none";
            isOpen = false;
        }
        stopListening();
        stopVoicePlayback();
    }

    function appendUserMessage(text, inputSource) {
        const container = document.getElementById("copilot-messages");
        if (!container) return;

        const isVoice = inputSource === "mic";
        const tagHtml = isVoice ? `<span style="font-size:0.68rem; opacity:0.85; margin-right:4px;">Voice:</span>` : "";

        const msgDiv = document.createElement("div");
        msgDiv.className = "copilot-msg copilot-msg-user";
        msgDiv.innerHTML = `<div class="copilot-bubble"><p>${tagHtml}${escapeHtml(text)}</p></div>`;
        container.appendChild(msgDiv);
        container.scrollTop = container.scrollHeight;
    }

    function appendSystemNotice(text) {
        const container = document.getElementById("copilot-messages");
        if (!container) return;

        const msgDiv = document.createElement("div");
        msgDiv.className = "copilot-msg copilot-msg-assistant";
        msgDiv.innerHTML = `
            <div class="copilot-bubble" style="background: rgba(148, 163, 184, 0.15); border-color: rgba(148, 163, 184, 0.3); font-size: 0.76rem; color: #cbd5e1;">
                <p>ℹ️ ${escapeHtml(text)}</p>
            </div>
        `;
        container.appendChild(msgDiv);
        container.scrollTop = container.scrollHeight;
    }

    function showTypingIndicator() {
        const container = document.getElementById("copilot-messages");
        if (!container) return null;

        const indicator = document.createElement("div");
        indicator.id = "copilot-typing-box";
        indicator.className = "copilot-msg copilot-msg-assistant";
        indicator.innerHTML = `
            <div class="copilot-typing-indicator">
                <span class="copilot-typing-dot"></span>
                <span class="copilot-typing-dot"></span>
                <span class="copilot-typing-dot"></span>
            </div>
        `;
        container.appendChild(indicator);
        container.scrollTop = container.scrollHeight;
        return indicator;
    }

    function removeTypingIndicator() {
        const el = document.getElementById("copilot-typing-box");
        if (el && el.parentNode) {
            el.parentNode.removeChild(el);
        }
    }

    /**
     * Appends assistant message to chat window with an inline Listen button.
     * @param {string} replyText
     * @param {string|null} actionTab
     * @param {string|null} actionLabel
     * @param {string} inputSource - "text" or "mic"
     */
    function appendAssistantMessage(replyText, actionTab, actionLabel, inputSource) {
        removeTypingIndicator();
        const container = document.getElementById("copilot-messages");
        if (!container) return;

        const msgDiv = document.createElement("div");
        msgDiv.className = "copilot-msg copilot-msg-assistant";

        let actionHtml = "";
        if (actionTab && actionLabel) {
            actionHtml = `
                <button type="button" class="copilot-action-chip" onclick="window.KiranaCopilot.navigateTab('${escapeHtml(actionTab)}')">
                    ${escapeHtml(actionLabel)}
                </button>
            `;
        }

        messageIdCounter++;
        const listenBtnId = `copilot-listen-btn-${messageIdCounter}`;

        msgDiv.innerHTML = `
            <div class="copilot-bubble">
                <p>${escapeHtml(replyText)}</p>
                ${actionHtml}
            </div>
            <div class="copilot-msg-actions">
                <button type="button" id="${listenBtnId}" class="copilot-audio-replay-btn copilot-listen-btn"
                    onclick="window.KiranaCopilot.handleListenClick(this)"
                    title="Click to listen to this answer aloud">
                    <svg class="listen-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
                        <path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path>
                        <path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path>
                    </svg>
                    <span>Listen</span>
                </button>
            </div>
        `;
        container.appendChild(msgDiv);
        container.scrollTop = container.scrollHeight;

        const listenBtn = document.getElementById(listenBtnId);
        if (listenBtn) {
            listenBtn.setAttribute("data-text", replyText);
        }

        // STRICT INPUT-MODE RULE:
        // Automatically speak reply aloud ONLY if input was MIC (Voice Mode)
        if (inputSource === "mic") {
            speakUsingSpeechSynthesis(replyText, listenBtn);
        }
    }

    /**
     * Submits a message to POST /api/assistant/chat.
     * @param {string} [queryText]
     * @param {string} [inputSource="text"] - "text" or "mic"
     */
    async function submitMessage(queryText, inputSource) {
        const source = (inputSource === "mic") ? "mic" : "text";

        // Stop any currently playing audio immediately
        stopVoicePlayback();

        const text = (queryText !== undefined ? queryText : (document.getElementById("copilot-input")?.value || "")).trim();
        if (!text) return;

        const input = document.getElementById("copilot-input");
        if (input) input.value = "";

        appendUserMessage(text, source);
        conversationHistory.push({ role: "user", content: text });
        showTypingIndicator();

        try {
            const res = await fetch("/api/assistant/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: text,
                    history: conversationHistory.slice(-4),
                    input_source: source
                })
            });

            if (!res.ok) {
                throw new Error(`Server returned status ${res.status}`);
            }

            const data = await res.json();
            conversationHistory.push({ role: "assistant", content: data.reply });
            appendAssistantMessage(data.reply, data.action_tab, data.action_label, source);
        } catch (err) {
            console.error("Copilot chat request error:", err);
            removeTypingIndicator();
            appendAssistantMessage(
                "Dukaan ke numbers up-to-date hain! Aap Shop Dashboard ya Inventory check kar sakte hain.",
                "dashboard",
                "Go to Shop Dashboard →",
                source
            );
        }
    }

    /**
     * Handles Quick Suggestion Chip clicks (strictly text mode -> silent text reply).
     */
    function sendSuggested(query) {
        if (!isOpen) openPanel();
        submitMessage(query, "text");
    }

    function navigateTab(tabKey) {
        const normalized = (tabKey || "").toLowerCase().trim();
        let target = "dashboard";

        if (normalized === "billing" || normalized === "pos") target = "billing";
        else if (normalized === "inventory") target = "inventory";
        else if (normalized === "udhaar" || normalized === "customers") target = "udhaar";
        else if (normalized === "analytics" || normalized === "sales") target = "analytics";
        else if (normalized === "forecasting" || normalized === "forecast") target = "forecasting";
        else if (normalized === "profile") target = "profile";
        else target = "dashboard";

        // Interrupt speech when navigating
        stopVoicePlayback();

        if (typeof window.switchTab === "function") {
            window.switchTab(target);
        }

        if (window.innerWidth <= 600) {
            closePanel();
        }
    }

    function escapeHtml(str) {
        if (!str) return "";
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Expose Global KiranaCopilot API
    window.KiranaCopilot = {
        toggle: togglePanel,
        open: openPanel,
        close: closePanel,
        toggleSpeech: toggleSpeech,
        toggleMic: toggleMic,
        stopListening: stopListening,
        submit: () => submitMessage(undefined, "text"),
        sendSuggested: sendSuggested,
        navigateTab: navigateTab,
        speakText: speakAssistantReply,
        speakMessage: handleListenClick,
        handleListenClick: handleListenClick,
        sanitizeForSpeech: sanitizeForSpeech,
        stopPlayback: stopVoicePlayback
    };

    // Auto initialize on DOM ready and attach navigation listeners for audio interruption
    document.addEventListener("DOMContentLoaded", function () {
        initSpeechRecognition();

        // Stop audio playback if user navigates away or switches tabs
        window.addEventListener("beforeunload", stopVoicePlayback);
        document.addEventListener("visibilitychange", function () {
            if (document.hidden) stopVoicePlayback();
        });
        window.addEventListener("app-tab-changed", stopVoicePlayback);
        document.addEventListener("click", function (e) {
            if (e.target && (e.target.closest(".nav-tab-btn") || e.target.closest(".bottom-nav-item"))) {
                stopVoicePlayback();
            }
        });
    });

})();
