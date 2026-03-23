// ============================================
// Health Tracker — Supabase Auth Module
//
// Handles login/logout, session persistence, and auth gating.
// Must be loaded AFTER config.js and supabase-js CDN.
//
// Usage in HTML:
//   <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
//   <script src="config.js"></script>
//   <script src="auth.js"></script>
//   <script src="data-loader.js"></script>
// ============================================

// --- Supabase Client (singleton) ---
// Named _supabaseClient to avoid colliding with window.supabase (the CDN library object)
const _supabaseClient = window.supabase
  ? window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
  : null;

if (!_supabaseClient) {
  console.error('[auth] @supabase/supabase-js not loaded');
}
// Expose for data-loader.js and other scripts (avoids CDN name collision)
window.htSupabase = _supabaseClient;

// --- Auth State ---
let _currentUser = null;

function getCurrentUser() {
  return _currentUser;
}

function isAuthenticated() {
  return _currentUser !== null;
}

// --- Login Modal ---

function _createLoginModal() {
  if (document.getElementById('ht-auth-overlay')) return;

  const overlay = document.createElement('div');
  overlay.id = 'ht-auth-overlay';
  overlay.innerHTML = `
    <div class="ht-auth-modal">
      <div class="ht-auth-icon">&#x1f512;</div>
      <h2>Health Tracker</h2>
      <p class="ht-auth-subtitle">Sign in to continue</p>
      <form id="ht-auth-form" autocomplete="on">
        <input type="email" id="ht-auth-email" placeholder="Email" required autocomplete="email" />
        <input type="password" id="ht-auth-password" placeholder="Password" required autocomplete="current-password" />
        <button type="submit" id="ht-auth-submit">Sign In</button>
        <div id="ht-auth-error" class="ht-auth-error" role="alert"></div>
      </form>
    </div>
  `;

  // Inline styles scoped to the modal (no external CSS dependency)
  const style = document.createElement('style');
  style.textContent = `
    #ht-auth-overlay {
      position: fixed;
      inset: 0;
      z-index: 99999;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(15, 10, 40, 0.85);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      padding: 20px;
    }
    .ht-auth-modal {
      background: rgba(255, 255, 255, 0.12);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid rgba(255, 255, 255, 0.25);
      border-radius: 20px;
      padding: 40px 32px 32px;
      width: 100%;
      max-width: 340px;
      text-align: center;
      color: #fff;
      box-shadow: 0 8px 32px rgba(0,0,0,0.3);
    }
    .ht-auth-icon {
      font-size: 36px;
      margin-bottom: 8px;
    }
    .ht-auth-modal h2 {
      margin: 0 0 4px;
      font-size: 22px;
      font-weight: 700;
      letter-spacing: -0.3px;
    }
    .ht-auth-subtitle {
      margin: 0 0 24px;
      font-size: 14px;
      opacity: 0.7;
    }
    .ht-auth-modal input {
      display: block;
      width: 100%;
      padding: 12px 14px;
      margin-bottom: 12px;
      border: 1px solid rgba(255,255,255,0.2);
      border-radius: 12px;
      background: rgba(255,255,255,0.08);
      color: #fff;
      font-size: 15px;
      outline: none;
      transition: border-color 0.2s;
      box-sizing: border-box;
    }
    .ht-auth-modal input::placeholder {
      color: rgba(255,255,255,0.45);
    }
    .ht-auth-modal input:focus {
      border-color: rgba(139, 92, 246, 0.7);
    }
    .ht-auth-modal button {
      display: block;
      width: 100%;
      padding: 12px;
      margin-top: 8px;
      border: none;
      border-radius: 12px;
      background: linear-gradient(135deg, #8B5CF6, #6D28D9);
      color: #fff;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
      transition: opacity 0.2s;
    }
    .ht-auth-modal button:hover { opacity: 0.9; }
    .ht-auth-modal button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .ht-auth-error {
      margin-top: 12px;
      font-size: 13px;
      color: #f87171;
      min-height: 18px;
    }
  `;

  document.head.appendChild(style);
  document.body.appendChild(overlay);

  // Wire up form
  document.getElementById('ht-auth-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('ht-auth-email').value.trim();
    const password = document.getElementById('ht-auth-password').value;
    const errEl = document.getElementById('ht-auth-error');
    const btn = document.getElementById('ht-auth-submit');

    errEl.textContent = '';
    btn.disabled = true;
    btn.textContent = 'Signing in\u2026';

    try {
      const { data, error } = await _supabaseClient.auth.signInWithPassword({ email, password });
      if (error) {
        errEl.textContent = error.message;
        btn.disabled = false;
        btn.textContent = 'Sign In';
        return;
      }
      _currentUser = data.user;
      _removeLoginModal();
      // Dispatch event so pages can proceed with data loading
      window.dispatchEvent(new CustomEvent('ht-auth-ready', { detail: { user: data.user } }));
    } catch (err) {
      errEl.textContent = 'Connection error. Please try again.';
      btn.disabled = false;
      btn.textContent = 'Sign In';
    }
  });
}

function _removeLoginModal() {
  const overlay = document.getElementById('ht-auth-overlay');
  if (overlay) overlay.remove();
}

function _showConnectionError(onRetry) {
  // Remove any existing overlay (login modal or previous error)
  const existing = document.getElementById('ht-auth-overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'ht-auth-overlay';
  overlay.innerHTML = `
    <div class="ht-auth-modal">
      <div class="ht-auth-icon">&#x26A0;</div>
      <h2>Connection Error</h2>
      <p class="ht-auth-subtitle">Unable to reach the server. Check your connection and try again.</p>
      <button id="ht-auth-retry" style="
        display:block; width:100%; padding:12px; margin-top:16px;
        border:none; border-radius:12px;
        background:linear-gradient(135deg,#8B5CF6,#6D28D9);
        color:#fff; font-size:15px; font-weight:600; cursor:pointer;
      ">Retry</button>
    </div>
  `;
  document.body.appendChild(overlay);
  document.getElementById('ht-auth-retry').addEventListener('click', () => {
    overlay.remove();
    if (onRetry) onRetry();
  });
}

// --- Session Restore (non-blocking, no modal) ---

async function _restoreSession() {
  if (!_supabaseClient) return;
  const { data: { session } } = await _supabaseClient.auth.getSession();
  if (session && session.user) _currentUser = session.user;
}

// --- Session Check (blocking — shows login modal if needed) ---

async function checkAuth() {
  if (!_supabaseClient) {
    console.error('[auth] Supabase client not initialized');
    return null;
  }

  // Check for existing session (persisted in localStorage by supabase-js)
  // Distinguish network errors from "no session" — don't show login modal on network failure
  let session = null;
  try {
    const { data, error } = await _supabaseClient.auth.getSession();
    if (error) throw error;
    session = data.session;
  } catch (err) {
    console.error('[auth] Network error checking session:', err.message);
    // Network error — show retry UI, not login modal
    return new Promise((resolve) => {
      _showConnectionError(() => {
        // Retry on user tap
        checkAuth().then(resolve);
      });
    });
  }

  if (session && session.user) {
    _currentUser = session.user;
    return session.user;
  }

  // No session — show login modal and wait for auth
  return new Promise((resolve) => {
    _createLoginModal();
    window.addEventListener('ht-auth-ready', (e) => {
      resolve(e.detail.user);
    }, { once: true });
  });
}

// --- Require Auth (lazy gate — prompts login only if not already signed in) ---

async function requireAuth() {
  if (isAuthenticated()) return _currentUser;
  return checkAuth();
}

// --- Logout ---

async function logout() {
  if (!_supabaseClient) return;
  await _supabaseClient.auth.signOut();
  _currentUser = null;
  // Dispatch event so UI can update (e.g. flip Sign Out → Sign In)
  window.dispatchEvent(new CustomEvent('ht-auth-logout'));
}

// --- Auth state listener (handles token refresh, tab sync) ---
if (_supabaseClient) {
  _supabaseClient.auth.onAuthStateChange((event, session) => {
    if (event === 'SIGNED_OUT') {
      _currentUser = null;
    } else if (session && session.user) {
      _currentUser = session.user;
    }
  });
}
