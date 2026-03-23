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
  ? window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: false,
      },
    })
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
  overlay.innerHTML = ` // trusted markup — static login form template
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

  // Styles are in design-system.css (ht-auth-* classes)
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
  overlay.innerHTML = ` // trusted markup — static connection error template
    <div class="ht-auth-modal">
      <div class="ht-auth-icon">&#x26A0;</div>
      <h2>Connection Error</h2>
      <p class="ht-auth-subtitle">Unable to reach the server. Check your connection and try again.</p>
      <button id="ht-auth-retry">Retry</button>
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
