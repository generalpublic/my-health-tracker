/**
 * crypto-store.js — Obfuscated localStorage for the offline queue.
 *
 * Uses WebCrypto AES-256-GCM to encrypt data before storing in localStorage.
 * Key is derived from the user's Supabase user ID (a public UUID) via PBKDF2,
 * NOT from a user secret. This means:
 *
 *   - It IS useful against: casual inspection of localStorage, automated
 *     scraping tools that expect cleartext JSON.
 *   - It is NOT protection against: XSS (attacker has the same JS context),
 *     local forensic access (user ID is in the auth session in the same
 *     localStorage), or a stolen device where the browser session persists.
 *
 * Server-side data is protected by RLS + Supabase auth, not this module.
 * This module only covers the small offline retry queue in localStorage.
 *
 * Graceful fallback: if WebCrypto is unavailable, stores cleartext.
 */

const CryptoStore = (() => {
  // Module-scoped encryption key (held in memory only, never persisted)
  let _cryptoKey = null;
  let _available = false;

  const _APP_SALT_PREFIX = 'HealthTracker-v1-';
  const _PBKDF2_ITERATIONS = 100000;

  /**
   * Initialize the crypto store with a user identifier.
   * Call after successful auth. Derives an AES-GCM key from the user ID.
   */
  async function init(userId) {
    if (!userId) {
      _available = false;
      return;
    }

    try {
      if (!window.crypto || !window.crypto.subtle) {
        console.warn('[crypto-store] WebCrypto not available — using cleartext fallback');
        _available = false;
        return;
      }

      // Derive key material from user ID
      const enc = new TextEncoder();
      const keyMaterial = await crypto.subtle.importKey(
        'raw',
        enc.encode(userId),
        'PBKDF2',
        false,
        ['deriveKey']
      );

      // Salt = app prefix + user ID (deterministic per user)
      const salt = enc.encode(_APP_SALT_PREFIX + userId);

      _cryptoKey = await crypto.subtle.deriveKey(
        { name: 'PBKDF2', salt, iterations: _PBKDF2_ITERATIONS, hash: 'SHA-256' },
        keyMaterial,
        { name: 'AES-GCM', length: 256 },
        false,
        ['encrypt', 'decrypt']
      );

      _available = true;

      // Migrate any existing cleartext data to encrypted
      await _migrateToEncrypted();
    } catch (err) {
      console.warn('[crypto-store] Init failed — using cleartext fallback:', err.message);
      _available = false;
    }
  }

  /**
   * Store data encrypted in localStorage.
   * @param {string} key - localStorage key
   * @param {*} data - JSON-serializable data
   */
  async function setItem(key, data) {
    const json = JSON.stringify(data);

    if (!_available || !_cryptoKey) {
      localStorage.setItem(key, json);
      return;
    }

    try {
      const enc = new TextEncoder();
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const ciphertext = await crypto.subtle.encrypt(
        { name: 'AES-GCM', iv },
        _cryptoKey,
        enc.encode(json)
      );

      // Store as: base64(iv) + '.' + base64(ciphertext)
      const payload = _toBase64(iv) + '.' + _toBase64(new Uint8Array(ciphertext));
      localStorage.setItem(key, '\x00ENC:' + payload);
    } catch (err) {
      console.warn('[crypto-store] Encrypt failed, storing cleartext:', err.message);
      localStorage.setItem(key, json);
    }
  }

  /**
   * Read and decrypt data from localStorage.
   * @param {string} key - localStorage key
   * @param {*} fallback - default value if key not found
   * @returns {*} parsed data or fallback
   */
  async function getItem(key, fallback = null) {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;

    // Check if encrypted
    if (raw.startsWith('\x00ENC:')) {
      if (!_available || !_cryptoKey) {
        console.warn('[crypto-store] Encrypted data found but no key — returning fallback');
        return fallback;
      }

      try {
        const payload = raw.substring(5); // skip '\x00ENC:'
        const [ivB64, ctB64] = payload.split('.');
        const iv = _fromBase64(ivB64);
        const ciphertext = _fromBase64(ctB64);

        const plaintext = await crypto.subtle.decrypt(
          { name: 'AES-GCM', iv },
          _cryptoKey,
          ciphertext
        );

        const dec = new TextDecoder();
        return JSON.parse(dec.decode(plaintext));
      } catch (err) {
        console.warn('[crypto-store] Decrypt failed:', err.message);
        return fallback;
      }
    }

    // Cleartext — parse as JSON
    try {
      return JSON.parse(raw);
    } catch {
      return raw;
    }
  }

  /**
   * Remove an item from localStorage.
   */
  function removeItem(key) {
    localStorage.removeItem(key);
  }

  /**
   * Check if encryption is active.
   */
  function isEncrypted() {
    return _available && !!_cryptoKey;
  }

  // --- Internal helpers ---

  function _toBase64(uint8Array) {
    let binary = '';
    for (let i = 0; i < uint8Array.length; i++) {
      binary += String.fromCharCode(uint8Array[i]);
    }
    return btoa(binary);
  }

  function _fromBase64(b64) {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  }

  /**
   * One-time migration: if cleartext ht_offline_queue exists, re-encrypt it.
   */
  async function _migrateToEncrypted() {
    const raw = localStorage.getItem('ht_offline_queue');
    if (raw && !raw.startsWith('\x00ENC:')) {
      try {
        const data = JSON.parse(raw);
        await setItem('ht_offline_queue', data);
        console.log('[crypto-store] Migrated ht_offline_queue to encrypted storage');
      } catch {}
    }
  }

  return { init, setItem, getItem, removeItem, isEncrypted };
})();
