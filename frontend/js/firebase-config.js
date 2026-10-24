/**
 * Apna Kirana OS - Real Firebase Authentication Module
 * Project: unnati-03
 * Uses browser-native Google CDN ES Modules directly (no bundler required).
 * Supports Email/Password, 10-Digit Mobile/Password (mapped to virtual email),
 * and Google Popup Sign-In, fully synchronized with FastAPI + SQLite multi-tenant isolation.
 */

import { initializeApp, getApps, getApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
  getAuth,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signInWithPopup,
  GoogleAuthProvider,
  signOut,
  onAuthStateChanged,
  sendPasswordResetEmail
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";

// Real Web App's Firebase configuration
const firebaseConfig = {
  apiKey: "AIzaSyDy8nIk6HW-gR6F3eM8B6mxPlxEiSGFoxM",
  authDomain: "unnati-03.firebaseapp.com",
  projectId: "unnati-03",
  storageBucket: "unnati-03.firebasestorage.app",
  messagingSenderId: "17363807307",
  appId: "1:17363807307:web:ea4c22b547038d808071ce"
};

// Initialize Firebase App & Auth instance
const app = getApps().length > 0 ? getApp() : initializeApp(firebaseConfig);
const auth = getAuth(app);
const googleProvider = new GoogleAuthProvider();
googleProvider.setCustomParameters({ prompt: "select_account" });

/**
 * KiranaAuthService - Authentication & Backend Sync Controller
 */
class KiranaAuthService {
  constructor(firebaseApp, firebaseAuth) {
    this.app = firebaseApp;
    this.auth = firebaseAuth;
    this.config = firebaseConfig;
    this._isSyncing = false;
    this._syncPromise = null;
    this.isAuthenticating = false;
  }

  /**
   * Helper: Formats 10-digit mobile number into an internal email for Firebase Auth.
   * e.g. 9876543210 -> 9876543210@user.apnakirana.in
   */
  formatPhoneToEmail(phone) {
    const clean = String(phone).replace(/\D/g, "");
    const tenDigits = clean.length >= 10 ? clean.slice(-10) : clean;
    return `${tenDigits}@user.apnakirana.in`;
  }

  /**
   * Extracts clean 10-digit phone if identifier is a phone number.
   */
  extractPhone(identifier) {
    if (!identifier) return null;
    const clean = String(identifier).trim();
    if (clean.includes("@")) return null;
    const digits = clean.replace(/\D/g, "");
    return digits.length >= 10 ? digits.slice(-10) : digits;
  }

  /**
   * Checks whether an identifier (phone/email) or firebase_uid is registered in our master user registry.
   * @param {string|null} identifier
   * @param {string|null} firebaseUid
   * @returns {Promise<boolean>}
   */
  async checkUserRegistered(identifier, firebaseUid = null) {
    if (!identifier && !firebaseUid) return false;
    const cleanIdent = identifier ? String(identifier).trim() : "";
    const cleanDigits = cleanIdent.replace(/\D/g, "");

    // Demo account is always considered registered
    if (cleanDigits === "9876543210" || cleanIdent.toLowerCase() === "owner@apnakirana.com") {
      return true;
    }

    try {
      const params = new URLSearchParams();
      if (cleanIdent) params.set("identifier", cleanIdent);
      if (firebaseUid) params.set("firebase_uid", firebaseUid);

      const res = await fetch(`/api/auth/check-user?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        return Boolean(data && data.registered);
      }
    } catch (e) {
      console.warn("[AuthService] checkUserRegistered network warning:", e);
    }
    return false;
  }

  /**
   * Strict Store Registration Workflow:
   * Creates the Firebase auth credential and provisions user metadata in FastAPI master registry.
   * Immediately signs out of the temporary Firebase session so the user is NOT auto-logged in.
   *
   * @param {Object} details Registration parameters
   * @returns {Promise<{success: boolean, user: Object, identifier: string}>}
   */
  async registerNewStore({ fullName, phone, email, password, shopName }) {
    const cleanName = String(fullName || "").trim();
    const cleanPhone = String(phone || "").replace(/\D/g, "").slice(-10);
    const cleanEmail = email && String(email).trim().includes("@") ? String(email).trim().toLowerCase() : null;
    const cleanPass = String(password || "");
    const cleanShop = shopName && String(shopName).trim() ? String(shopName).trim() : `${cleanName}'s Kirana Store`;

    if (!cleanName) throw new Error("Full name is required.");
    if (cleanPhone.length !== 10) throw new Error("Valid 10-digit mobile number is required.");
    if (cleanPass.length < 6) throw new Error("Password must be at least 6 characters.");

    // Map phone to internal auth email if email is not provided
    const authEmail = cleanEmail || this.formatPhoneToEmail(cleanPhone);

    // 1. Attempt Firebase account creation (best-effort; if domain not authorized or offline, fallback to backend)
    let fbUser = null;
    try {
      const cred = await createUserWithEmailAndPassword(this.auth, authEmail, cleanPass);
      fbUser = cred.user;
    } catch (fbErr) {
      if (fbErr.code === "auth/email-already-in-use") {
        // User already has a Firebase auth record; verify password by signing in
        try {
          const loginCred = await signInWithEmailAndPassword(this.auth, authEmail, cleanPass);
          fbUser = loginCred.user;
        } catch (_) {
          throw new Error("An account with this email already exists in Firebase. Please enter your account password to link this store, or sign in.");
        }
      } else if (fbErr.code === "auth/weak-password") {
        throw new Error("Password must be at least 6 characters long.");
      } else if (fbErr.code === "auth/unauthorized-domain") {
        console.warn("[AuthService] Firebase domain not authorized; proceeding with backend registration.");
      } else {
        console.warn("[AuthService] Firebase registration note:", fbErr.message);
      }
    }

    // 2. Register user metadata in FastAPI master user registry & provision isolated empty bucket
    const regPayload = {
      full_name: cleanName,
      phone: cleanPhone,
      email: cleanEmail,
      password: cleanPass,
      confirm_password: cleanPass,
      shop_name: cleanShop,
      firebase_uid: fbUser ? fbUser.uid : null
    };

    let regResp;
    try {
      regResp = await fetch("/api/v1/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(regPayload)
      });
    } catch (_) {
      regResp = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(regPayload)
      });
    }

    if (!regResp.ok) {
      const errData = await regResp.json().catch(() => ({}));
      throw new Error(errData.detail || "Store registration failed on server.");
    }

    const data = await regResp.json();

    // 3. IMMEDIATELY SIGN OUT of the temporary Firebase auto-session
    try {
      if (fbUser) await signOut(this.auth);
    } catch (_) {}

    // Clear any transient tokens from registration
    if (typeof window.clearAuthToken === "function") {
      window.clearAuthToken();
    }

    return {
      success: true,
      user: data.user,
      identifier: cleanPhone || cleanEmail
    };
  }

  /**
   * Authenticates user via FastAPI Backend & Firebase Auth with zero-failure fallback.
   * Supports pre-seeded demo account (9876543210 / Password@123) and multi-tenant stores on Render.
   *
   * @param {string} identifier Mobile phone (10 digits) or Email
   * @param {string} password Account password
   * @returns {Promise<{status: string, success: boolean, user: Object, token: string, access_token: string, data: Object}>}
   */
  async login(identifier, password) {
    this.isAuthenticating = true;
    window.isAuthenticating = true;

    try {
      const cleanIdent = String(identifier || "").trim();
      const cleanPass = String(password || "");

      if (!cleanIdent) {
        throw new Error("Please enter your 10-digit mobile number or email address.");
      }
      if (!cleanPass) {
        throw new Error("Please enter your account password.");
      }

      let authEmail = cleanIdent.toLowerCase();
      let phone = null;
      const digitsOnly = cleanIdent.replace(/\D/g, "");

      if (cleanIdent.includes("@")) {
        authEmail = cleanIdent.toLowerCase();
      } else if (digitsOnly.length >= 10) {
        phone = digitsOnly.slice(-10);
        authEmail = this.formatPhoneToEmail(phone);
      } else {
        throw new Error("Please enter a valid 10-digit mobile number or email address.");
      }

      // Step 1: Direct Backend Login (FastAPI + SQLite Multi-Tenant Authentication)
      // Handles demo accounts (9876543210 / Password@123) and registered stores natively on Render
      try {
        const loginPayload = {
          identifier: cleanIdent,
          password: cleanPass
        };

        let bResp = await fetch("/api/v1/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(loginPayload)
        });

        if (!bResp.ok && bResp.status === 404) {
          bResp = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(loginPayload)
          });
        }

        if (bResp.ok) {
          const bData = await bResp.json();
          const token = bData?.token || bData?.access_token || bData?.data?.token;
          const user = bData?.user || bData?.data?.user;

          localStorage.setItem("access_token", token);
          localStorage.setItem("pos_auth_token", token);
          if (user) {
            localStorage.setItem("shopkeeper_user", JSON.stringify(user));
            localStorage.setItem("pos_auth_user", JSON.stringify(user));
          }

          if (typeof window.setAuthToken === "function") window.setAuthToken(token);
          if (typeof window.syncUserDataAcrossUI === "function") window.syncUserDataAcrossUI(user);
          if (user && user.shop_profile && typeof window.syncBusinessDataAcrossUI === "function") {
            window.syncBusinessDataAcrossUI(user.shop_profile);
          }
          if (typeof window.updateAuthHeaderUI === "function") window.updateAuthHeaderUI(true);

          // Best-effort background Firebase session sync
          try {
            await signInWithEmailAndPassword(this.auth, authEmail, cleanPass);
          } catch (_) {}

          return {
            status: "success",
            success: true,
            token: token,
            access_token: token,
            data: { token, user },
            user: user
          };
        } else if (bResp.status === 401) {
          const isReg = await this.checkUserRegistered(cleanIdent);
          if (isReg) {
            throw new Error("Incorrect password. Please verify your password and try again.");
          }
        }
      } catch (backendErr) {
        if (backendErr.message && backendErr.message.includes("Incorrect password")) {
          throw backendErr;
        }
        console.warn("[AuthService] Direct backend login note:", backendErr.message);
      }

      // Step 2: Attempt Firebase Sign In for cloud-registered or Google-linked users
      let fbUser = null;
      try {
        const userCredential = await signInWithEmailAndPassword(this.auth, authEmail, cleanPass);
        fbUser = userCredential.user;
      } catch (signInErr) {
        const errCode = signInErr.code || "";
        if (errCode === "auth/wrong-password" || errCode === "auth/invalid-credential") {
          throw new Error("Incorrect password. Please verify your password and try again. (If you originally registered via Google, please click 'Continue with Google')");
        } else if (errCode === "auth/user-not-found") {
          const notRegErr = new Error("Account Not Registered");
          notRegErr.code = "ACCOUNT_NOT_REGISTERED";
          notRegErr.identifier = cleanIdent;
          throw notRegErr;
        } else if (errCode === "auth/too-many-requests") {
          throw new Error("Access temporarily disabled due to many failed login attempts. Please try again later.");
        } else if (errCode === "auth/invalid-email") {
          throw new Error("Invalid mobile number or email address format.");
        } else if (errCode === "auth/unauthorized-domain") {
          throw new Error("Domain not authorized in Firebase Console. Please add your Render domain in Firebase Console, or sign in using Mobile Number & Password.");
        } else {
          throw new Error(signInErr.message || "Authentication failed. Please verify credentials and try again.");
        }
      }

      if (!fbUser) {
        throw new Error("Failed to authenticate.");
      }

      // Step 3: Synchronize authenticated Firebase user with FastAPI backend & SQLite DB
      return await this.syncWithBackend(fbUser, phone);
    } finally {
      this.isAuthenticating = false;
      window.isAuthenticating = false;
    }
  }

  /**
   * Authenticates user via Google Popup Sign-In.
   * Provisions store in FastAPI master registry automatically upon Google verification.
   *
   * @returns {Promise<{status: string, success: boolean, user: Object, token: string, access_token: string, data: Object}>}
   */
  async loginWithGoogle() {
    this.isAuthenticating = true;
    window.isAuthenticating = true;

    try {
      const result = await signInWithPopup(this.auth, googleProvider);
      const fbUser = result.user;

      // Automatically sync and provision the store in FastAPI backend SQLite DB
      return await this.syncWithBackend(fbUser, null);
    } catch (err) {
      if (err.code === "auth/popup-closed-by-user" || err.code === "auth/cancelled-popup-request") {
        const cancelErr = new Error("Google sign-in was cancelled.");
        cancelErr.code = "auth/popup-closed-by-user";
        throw cancelErr;
      } else if (err.code === "auth/popup-blocked") {
        throw new Error("Sign-in popup was blocked by browser. Please allow popups for this site.");
      }
      throw err;
    } finally {
      this.isAuthenticating = false;
      window.isAuthenticating = false;
    }
  }

  /**
   * Synchronizes an authenticated Firebase user with the FastAPI backend (/api/auth/firebase-sync).
   * Shares a single promise to eliminate race conditions between onAuthStateChanged and form submit.
   *
   * @param {Object} fbUser Firebase User instance
   * @param {string|null} phoneOverride Explicit 10-digit phone if provided during login
   * @returns {Promise<{status: string, success: boolean, user: Object, token: string, access_token: string, data: Object}>}
   */
  async syncWithBackend(fbUser, phoneOverride = null) {
    if (this._syncPromise) {
      return await this._syncPromise;
    }

    this._isSyncing = true;
    this._syncPromise = (async () => {
      try {
        const idToken = await fbUser.getIdToken();

        let phone = phoneOverride;
        if (!phone && fbUser.phoneNumber) {
          phone = fbUser.phoneNumber.replace(/\D/g, "").slice(-10);
        }
        if (!phone && fbUser.email && fbUser.email.endsWith("@user.apnakirana.in")) {
          phone = fbUser.email.split("@")[0];
        }

        const syncPayload = {
          firebase_uid: fbUser.uid,
          email: fbUser.email || null,
          phone: phone || null,
          display_name: fbUser.displayName || (phone ? `Shopkeeper ${phone.slice(-4)}` : "Shopkeeper"),
          photo_url: fbUser.photoURL || null,
          id_token: idToken
        };

        let resp;
        try {
          resp = await fetch("/api/auth/firebase-sync", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(syncPayload)
          });
        } catch (netErr) {
          resp = await fetch("/api/v1/auth/firebase-sync", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(syncPayload)
          });
        }

        if (!resp.ok) {
          let errMsg = "Failed to synchronize profile with local database.";
          try {
            const errData = await resp.json();
            if (errData && errData.detail) {
              errMsg = typeof errData.detail === "string" ? errData.detail : JSON.stringify(errData.detail);
            }
          } catch (_) {}
          throw new Error(errMsg);
        }

        const resData = await resp.json();
        // Safe token extraction using optional chaining
        const token = resData?.token || resData?.access_token || resData?.data?.token || idToken || "local-session-token";
        const user = resData?.user || resData?.data?.user;

        // Persist authenticated tokens in localStorage
        localStorage.setItem("access_token", token);
        localStorage.setItem("pos_auth_token", token);
        if (user) {
          localStorage.setItem("shopkeeper_user", JSON.stringify(user));
          localStorage.setItem("pos_auth_user", JSON.stringify(user));
        }

        // Global state broadcasts
        if (typeof window.setAuthToken === "function") window.setAuthToken(token);
        if (typeof window.syncUserDataAcrossUI === "function") window.syncUserDataAcrossUI(user);
        if (user && user.shop_profile && typeof window.syncBusinessDataAcrossUI === "function") {
          window.syncBusinessDataAcrossUI(user.shop_profile);
        }
        if (typeof window.updateAuthHeaderUI === "function") window.updateAuthHeaderUI(true);

        return {
          status: "success",
          success: true,
          token: token,
          access_token: token,
          data: { token: token, user: user },
          user: user
        };
      } finally {
        this._isSyncing = false;
        this._syncPromise = null;
      }
    })();

    return await this._syncPromise;
  }

  /**
   * Signs out the current user from Firebase and backend session.
   */
  async logout() {
    const token = localStorage.getItem("pos_auth_token") || localStorage.getItem("access_token");
    try {
      if (token) {
        await fetch("/api/auth/logout", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`
          }
        }).catch(() => {});
      }
    } catch (_) {}

    try {
      await signOut(this.auth);
    } catch (err) {
      console.warn("[AuthService] Firebase signOut error:", err);
    }

    if (typeof window.clearAuthToken === "function") {
      window.clearAuthToken();
    } else {
      localStorage.removeItem("access_token");
      localStorage.removeItem("pos_auth_token");
      localStorage.removeItem("shopkeeper_user");
      localStorage.removeItem("pos_auth_user");
      localStorage.removeItem("pos_onboarding_completed");
    }
    return true;
  }

  /**
   * Sends a native Firebase password reset email.
   * If identifier is a 10-digit phone, converts to virtual email format.
   *
   * @param {string} emailOrPhone
   * @returns {Promise<void>}
   */
  async sendPasswordResetEmail(emailOrPhone) {
    const raw = String(emailOrPhone || "").trim();
    if (!raw) {
      throw new Error("Please enter your registered email address.");
    }

    let targetEmail = raw.toLowerCase();
    if (!targetEmail.includes("@")) {
      const digitsOnly = targetEmail.replace(/\D/g, "");
      if (digitsOnly.length >= 10) {
        targetEmail = this.formatPhoneToEmail(digitsOnly.slice(-10));
      } else {
        throw new Error("Please enter a valid email address.");
      }
    }

    return await sendPasswordResetEmail(this.auth, targetEmail);
  }

  /**
   * Checks whether an authenticated session exists.
   */
  isAuthenticated() {
    const token = localStorage.getItem("pos_auth_token") || localStorage.getItem("access_token");
    return Boolean(token && token.trim().length > 0);
  }

  /**
   * Returns current user stored in local session.
   */
  getCurrentUser() {
    try {
      const stored = localStorage.getItem("shopkeeper_user") || localStorage.getItem("pos_auth_user");
      return stored ? JSON.parse(stored) : null;
    } catch (_) {
      return null;
    }
  }
}

// Instantiate singleton AuthService
const authService = new KiranaAuthService(app, auth);

// Set up Firebase Auth state change observer for session persistence
onAuthStateChanged(auth, async (fbUser) => {
  // Prevent race conditions while manual form submission is in progress
  if (authService.isAuthenticating || window.isAuthenticating) {
    return;
  }

  if (fbUser) {
    const localToken = localStorage.getItem("pos_auth_token") || localStorage.getItem("access_token");
    if (!localToken) {
      try {
        await authService.syncWithBackend(fbUser);
      } catch (err) {
        console.warn("[AuthService] Auto-sync on auth state change failed:", err.message);
      }
    }
  }
});

// Helper for Google Sign-In button click
async function handleGoogleSignIn() {
  const alertBoxId = "login-alert-box";
  if (window.AppUtils && window.AppUtils.clearAlert) window.AppUtils.clearAlert(alertBoxId);

  const googleLoginBtn = document.getElementById("google-login-btn");
  const googleRegBtn = document.getElementById("google-register-btn");
  if (googleLoginBtn) googleLoginBtn.disabled = true;
  if (googleRegBtn) googleRegBtn.disabled = true;

  try {
    const result = await authService.loginWithGoogle();
    const token = result?.token || result?.access_token || result?.data?.token;
    const user = result?.user || result?.data?.user;

    // Clear caches from any prior account
    if (typeof window.clearStoreDataCaches === "function") {
      window.clearStoreDataCaches();
    }

    if (token && window.setAuthToken) window.setAuthToken(token);
    if (user && window.syncUserDataAcrossUI) window.syncUserDataAcrossUI(user);
    if (user && user.shop_profile && window.syncBusinessDataAcrossUI) {
      window.syncBusinessDataAcrossUI(user.shop_profile);
    }
    if (typeof window.updateAuthHeaderUI === "function") window.updateAuthHeaderUI(true);

    if (window.playAudioTone) window.playAudioTone("success");

    // Trigger Welcome Greeting Popup Modal
    if (typeof window.showWelcomeGreetingModal === "function") {
      window.showWelcomeGreetingModal(user || { full_name: user?.full_name || "Shopkeeper" });
    }
  } catch (err) {
    if (err.code === "auth/popup-closed-by-user") {
      return; // Silently handle user cancellation
    }
    if (err.code === "ACCOUNT_NOT_REGISTERED") {
      if (typeof window.showAccountNotRegisteredModal === "function") {
        window.showAccountNotRegisteredModal(err.googleUser || null);
      }
      return;
    }
    if (err.code === "auth/unauthorized-domain") {
      if (window.AppUtils) {
        window.AppUtils.showAlert(
          alertBoxId,
          "Domain Authorization Needed: To use Google Sign-In on Render, add this domain to Firebase Console > Authentication > Settings > Authorized Domains. Alternatively, use Mobile Number & Password."
        );
      }
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

// Expose globals for non-modular vanilla scripts
window.FIREBASE_CONFIG = firebaseConfig;
window.firebaseConfig = firebaseConfig;
window.firebaseApp = app;
window.firebaseAuth = auth;
window.AuthService = authService;
window.sendPasswordResetEmail = (authOrEmail, maybeEmail) => {
  if (maybeEmail) {
    return sendPasswordResetEmail(authOrEmail, maybeEmail);
  }
  return sendPasswordResetEmail(auth, authOrEmail);
};
window.handleGoogleSignIn = handleGoogleSignIn;
window.firebaseReady = Promise.resolve(authService);
