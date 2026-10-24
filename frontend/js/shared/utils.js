/**
 * Shared Utilities Module
 * Contains common helpers for audio synthesis, notifications, formatting,
 * password visibility toggling, and image validation.
 */

(function(window) {
    'use strict';

    let audioCtx = null;
    let audioEnabled = true;

    // Single dedicated HTMLAudioElement for ElevenLabs playback (avoids overlapping audio)
    let _audioPlayer = null;
    let _activeAbortController = null;
    let _isSpeaking = false;

    function getAudioPlayer() {
        if (!_audioPlayer) {
            _audioPlayer = new Audio();
            _audioPlayer.preload = "auto";
            _audioPlayer.addEventListener("ended", () => {
                _isSpeaking = false;
                window.dispatchEvent(new CustomEvent("elevenlabs-speech-stopped"));
            });
            _audioPlayer.addEventListener("pause", () => {
                if (_audioPlayer.currentTime === 0 || _audioPlayer.ended) {
                    _isSpeaking = false;
                    window.dispatchEvent(new CustomEvent("elevenlabs-speech-stopped"));
                }
            });
            _audioPlayer.addEventListener("error", (e) => {
                _isSpeaking = false;
                window.dispatchEvent(new CustomEvent("elevenlabs-speech-stopped"));
                console.warn("ElevenLabs audio player error:", e);
            });
        }
        return _audioPlayer;
    }

    function isAudioEnabled() {
        const saved = localStorage.getItem("shopkeeper_audio_enabled");
        if (saved !== null) {
            return saved === "true";
        }
        return audioEnabled;
    }

    function stopVoicePlayback() {
        if (_activeAbortController) {
            try {
                _activeAbortController.abort();
            } catch (e) {}
            _activeAbortController = null;
        }
        if (_audioPlayer) {
            try {
                _audioPlayer.pause();
                _audioPlayer.currentTime = 0;
                _audioPlayer.removeAttribute("src");
            } catch (e) {}
        }
        if ("speechSynthesis" in window) {
            try {
                window.speechSynthesis.cancel();
            } catch (e) {}
        }
        _isSpeaking = false;
        window.dispatchEvent(new CustomEvent("elevenlabs-speech-stopped"));
    }

    function speakBrowserTTS(text) {
        if (!("speechSynthesis" in window)) {
            console.warn("Browser does not support window.speechSynthesis.");
            _isSpeaking = false;
            window.dispatchEvent(new CustomEvent("elevenlabs-speech-stopped"));
            return false;
        }

        try {
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(text);

            // Detect Hindi or English/Hinglish
            const hasDevanagari = /[\u0900-\u097F]/.test(text);
            const lower = text.toLowerCase();
            const isHindi = hasDevanagari || (/\b(namaste|dhanyawad|shukriya|udhaar|khata|maal|khatam|paisa|rupaye|kaise|karein|batao|kitna|hai|hain|aapse|aapka|bhai|dukaan|kirana)\b/.test(lower));

            utterance.lang = isHindi ? "hi-IN" : "en-IN";
            utterance.rate = 1.0;
            utterance.pitch = 1.0;

            const voices = window.speechSynthesis.getVoices() || [];
            if (voices.length > 0) {
                const targetLangPrefix = isHindi ? "hi" : "en";
                const match = voices.find(v => v.lang && v.lang.toLowerCase().startsWith(targetLangPrefix)) ||
                              voices.find(v => v.lang && v.lang.toLowerCase().includes("in"));
                if (match) {
                    utterance.voice = match;
                }
            }

            _isSpeaking = true;
            window.dispatchEvent(new CustomEvent("elevenlabs-speech-started", { detail: { text, provider: "browser" } }));

            utterance.onend = () => {
                _isSpeaking = false;
                window.dispatchEvent(new CustomEvent("elevenlabs-speech-stopped"));
            };

            utterance.onerror = (e) => {
                console.warn("Browser SpeechSynthesis error:", e);
                _isSpeaking = false;
                window.dispatchEvent(new CustomEvent("elevenlabs-speech-stopped"));
            };

            window.speechSynthesis.speak(utterance);
            return true;
        } catch (e) {
            console.error("Browser TTS fallback failed:", e);
            _isSpeaking = false;
            window.dispatchEvent(new CustomEvent("elevenlabs-speech-stopped"));
            return false;
        }
    }

    async function speakWithElevenLabs(text, options = {}) {
        const force = Boolean(options && options.force);
        if (!force && !isAudioEnabled()) {
            return false;
        }

        if (!text || typeof text !== "string" || !text.trim()) {
            return false;
        }

        const cleanText = text.trim();

        // Non-blocking: cleanly stop previous audio before playing new prompt
        stopVoicePlayback();

        const abortCtrl = new AbortController();
        _activeAbortController = abortCtrl;
        _isSpeaking = true;
        window.dispatchEvent(new CustomEvent("elevenlabs-speech-started", { detail: { text: cleanText } }));

        try {
            const player = getAudioPlayer();
            const res = await fetch("/api/voice/speak", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    text: cleanText,
                    voice_id: options.voice_id || undefined
                }),
                signal: abortCtrl.signal
            });

            // If server indicated browser fallback (204 No Content or header)
            if (res.status === 204 || res.headers.get("x-audio-provider") === "browser") {
                return speakBrowserTTS(cleanText);
            }

            if (!res.ok) {
                throw new Error(`Voice server error: ${res.status}`);
            }

            const audioBlob = await res.blob();
            if (abortCtrl.signal.aborted) {
                return false;
            }

            if (!audioBlob || audioBlob.size === 0) {
                console.warn("Received empty audio blob, falling back to Layer 3 Browser TTS");
                return speakBrowserTTS(cleanText);
            }

            const audioUrl = URL.createObjectURL(audioBlob);
            player.src = audioUrl;

            const cleanupHandler = () => {
                try { URL.revokeObjectURL(audioUrl); } catch (e) {}
                player.removeEventListener("ended", cleanupHandler);
            };
            player.addEventListener("ended", cleanupHandler);

            await player.play();
            return true;
        } catch (err) {
            if (err.name !== "AbortError") {
                console.warn("Backend TTS notice, triggering Layer 3 Browser TTS fallback:", err.message);
                return speakBrowserTTS(cleanText);
            }
            _isSpeaking = false;
            window.dispatchEvent(new CustomEvent("elevenlabs-speech-stopped"));
            return false;
        }
    }

    const ElevenLabsVoice = {
        speak: speakWithElevenLabs,
        speakBrowser: speakBrowserTTS,
        stop: stopVoicePlayback,
        isAudioEnabled,
        isPlaying: () => _isSpeaking,
        getPlayer: getAudioPlayer
    };
    window.speakBrowserTTS = speakBrowserTTS;

    function initAudioFeedback() {
        const toggleBtn = document.getElementById("audio-toggle-btn");
        const toggleLabel = document.getElementById("audio-toggle-label");
        const toggleIcon = document.getElementById("audio-toggle-icon");

        const saved = localStorage.getItem("shopkeeper_audio_enabled");
        if (saved !== null) {
            audioEnabled = saved === "true";
        }

        function updateAudioUI() {
            const enabled = isAudioEnabled();
            if (toggleLabel) {
                toggleLabel.textContent = enabled ? "AI Voice: ON" : "Voice: OFF";
            }
            if (toggleIcon) {
                toggleIcon.innerHTML = enabled
                    ? `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:2px; vertical-align:middle;"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path></svg>`
                    : `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:2px; vertical-align:middle;"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><line x1="23" y1="9" x2="17" y2="15"></line><line x1="17" y1="9" x2="23" y2="15"></line></svg>`;
            }
            if (toggleBtn) {
                toggleBtn.className = enabled 
                    ? "btn btn-sm audio-switch-pill audio-active-glow" 
                    : "btn btn-sm audio-switch-pill audio-muted";
            }
        }

        if (toggleBtn) {
            updateAudioUI();
            toggleBtn.addEventListener("click", () => {
                const nextState = !isAudioEnabled();
                audioEnabled = nextState;
                localStorage.setItem("shopkeeper_audio_enabled", nextState ? "true" : "false");
                updateAudioUI();
                if (nextState) {
                    // Short welcome confirmation via ElevenLabs
                    speakWithElevenLabs("ElevenLabs AI voice assistant activated.");
                } else {
                    stopVoicePlayback();
                }
            });
        }
    }

    function getAudioContext() {
        if (!audioCtx) {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (AudioContext) {
                audioCtx = new AudioContext();
            }
        }
        if (audioCtx && audioCtx.state === "suspended") {
            audioCtx.resume().catch(() => {});
        }
        return audioCtx;
    }

    function playAudioTone(type) {
        if (!isAudioEnabled()) return;
        try {
            const ctx = getAudioContext();
            if (!ctx) return;

            const now = ctx.currentTime;
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);

            if (type === "mic-start") {
                osc.type = "sine";
                osc.frequency.setValueAtTime(587.33, now);
                osc.frequency.setValueAtTime(880, now + 0.08);
                gain.gain.setValueAtTime(0.08, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.22);
                osc.start(now);
                osc.stop(now + 0.22);
            } else if (type === "mic-stop") {
                osc.type = "sine";
                osc.frequency.setValueAtTime(880, now);
                osc.frequency.setValueAtTime(587.33, now + 0.08);
                gain.gain.setValueAtTime(0.08, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.2);
                osc.start(now);
                osc.stop(now + 0.2);
            } else if (type === "order-parsed") {
                osc.type = "triangle";
                osc.frequency.setValueAtTime(659.25, now);
                osc.frequency.setValueAtTime(1046.50, now + 0.09);
                gain.gain.setValueAtTime(0.1, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.28);
                osc.start(now);
                osc.stop(now + 0.28);
            } else if (type === "bill-success") {
                const notes = [523.25, 659.25, 783.99, 1046.50];
                notes.forEach((freq, idx) => {
                    const noteOsc = ctx.createOscillator();
                    const noteGain = ctx.createGain();
                    noteOsc.type = "triangle";
                    noteOsc.frequency.setValueAtTime(freq, now + (idx * 0.07));
                    noteGain.gain.setValueAtTime(0.09, now + (idx * 0.07));
                    noteGain.gain.exponentialRampToValueAtTime(0.001, now + (idx * 0.07) + 0.25);
                    noteOsc.connect(noteGain);
                    noteGain.connect(ctx.destination);
                    noteOsc.start(now + (idx * 0.07));
                    noteOsc.stop(now + (idx * 0.07) + 0.25);
                });
            } else if (type === "error") {
                osc.type = "sawtooth";
                osc.frequency.setValueAtTime(220, now);
                osc.frequency.setValueAtTime(180, now + 0.08);
                gain.gain.setValueAtTime(0.07, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
                osc.start(now);
                osc.stop(now + 0.25);
            } else if (type === "success") {
                osc.type = "sine";
                osc.frequency.setValueAtTime(880, now);
                gain.gain.setValueAtTime(0.08, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.18);
                osc.start(now);
                osc.stop(now + 0.18);
            }
        } catch (e) {
            console.warn("AudioFeedback non-fatal warning:", e);
        }
    }

    function showAlert(boxId, msg, isError = true) {
        const box = document.getElementById(boxId);
        if (!box) return;
        box.className = `alert-box ${isError ? 'alert-danger' : 'alert-success'}`;
        box.textContent = msg;
        box.style.display = "flex";
    }

    function clearAlert(boxId) {
        const box = document.getElementById(boxId);
        if (box) {
            box.style.display = "none";
            box.textContent = "";
        }
    }

    function showToast(message, type = "success") {
        let container = document.getElementById("app-toast-container");
        if (!container) {
            container = document.createElement("div");
            container.id = "app-toast-container";
            container.className = "app-toast-container";
            document.body.appendChild(container);
        }

        const toast = document.createElement("div");
        toast.className = `app-toast toast-${type}`;

        let icon = "✓";
        if (type === "error" || type === "danger") icon = "✕";
        else if (type === "warning") icon = "!";
        else if (type === "info") icon = "i";

        toast.innerHTML = `
            <span class="toast-icon">${icon}</span>
            <span class="toast-message">${escapeHtml(message)}</span>
        `;

        toast.addEventListener("click", () => {
            toast.classList.add("toast-hiding");
            setTimeout(() => toast.remove(), 250);
        });

        container.appendChild(toast);

        // Animate slide-in
        requestAnimationFrame(() => {
            toast.classList.add("toast-show");
        });

        const dismissToast = () => {
            toast.classList.remove("toast-show");
            setTimeout(() => {
                if (toast.parentNode) toast.remove();
            }, 250);
        };

        toast.addEventListener("click", dismissToast);

        setTimeout(() => {
            if (toast.parentNode) dismissToast();
        }, 3200);
    }

    function togglePasswordVisibility(inputId, btnEl) {
        const input = document.getElementById(inputId);
        if (!input) return;
        if (input.type === "password") {
            input.type = "text";
            if (btnEl) btnEl.textContent = "Hide";
        } else {
            input.type = "password";
            if (btnEl) btnEl.textContent = "Show";
        }
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str).replace(/[&<>'"]/g, tag => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            "'": "&#39;",
            '"': "&quot;"
        }[tag] || tag));
    }

    function formatCurrency(val) {
        const num = parseFloat(val);
        if (isNaN(num)) return "₹0.00";
        return `₹${num.toFixed(2)}`;
    }

    function validateImageFile(file, maxBytes = 5 * 1024 * 1024) {
        if (!file) {
            return { valid: false, error: "No file selected." };
        }
        const allowedTypes = ["image/jpeg", "image/png", "image/webp"];
        if (!allowedTypes.includes(file.type)) {
            return {
                valid: false,
                error: "Invalid file format. Please upload a JPEG, PNG, or WebP image."
            };
        }
        if (file.size > maxBytes) {
            return {
                valid: false,
                error: `Image size exceeds the ${Math.round(maxBytes / (1024 * 1024))}MB limit.`
            };
        }
        return { valid: true };
    }

    const AppUtils = {
        initAudioFeedback,
        playAudioTone,
        speakWithElevenLabs,
        stopVoicePlayback,
        ElevenLabsVoice,
        isAudioEnabled,
        showAlert,
        clearAlert,
        showToast,
        togglePasswordVisibility,
        escapeHtml,
        formatCurrency,
        validateImageFile
    };

    // Exports
    window.AppUtils = AppUtils;
    window.initAudioFeedback = initAudioFeedback;
    window.playAudioTone = playAudioTone;
    window.ElevenLabsVoice = ElevenLabsVoice;
    window.speakWithElevenLabs = speakWithElevenLabs;
    window.stopVoicePlayback = stopVoicePlayback;
    window.isAudioEnabled = isAudioEnabled;
    window.showAlert = showAlert;
    window.clearAlert = clearAlert;
    window.showToast = showToast;
    window.togglePasswordVisibility = togglePasswordVisibility;
    window.escapeHtml = escapeHtml;
    window.formatCurrency = formatCurrency;
    window.validateImageFile = validateImageFile;

    // Route legacy browser speech synthesis calls to ElevenLabsVoice
    try {
        if (typeof window !== "undefined") {
            window.speechSynthesis = {
                speak: function(utterance) {
                    const text = (utterance && utterance.text) ? utterance.text : String(utterance || "");
                    speakWithElevenLabs(text);
                },
                cancel: function() { stopVoicePlayback(); },
                pause: function() { stopVoicePlayback(); },
                resume: function() {},
                getVoices: function() {
                    return [{ name: "ElevenLabs Flash v2.5", lang: "en-IN", default: true }];
                }
            };
            if (!window.SpeechSynthesisUtterance) {
                window.SpeechSynthesisUtterance = function(text) {
                    this.text = text || "";
                };
            }
        }
    } catch (legacyPolyfillErr) {
        console.warn("Legacy speechSynthesis redirect notice:", legacyPolyfillErr);
    }

})(window);
