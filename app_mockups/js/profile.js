function navigateTo(page) { window.location.href = page; }
function toggleNotifications(el) {
  var toggle = el.querySelector('.toggle-switch');
  toggle.classList.toggle('active');
}

/** Populate diagnostics panel with live data. */
async function populateDiagnostics() {
  var panel = document.getElementById('diagnostics-panel');
  if (!panel) return;

  // App version — from config.js constant
  document.getElementById('diag-app-version').textContent =
    typeof APP_VERSION !== 'undefined' ? APP_VERSION : 'unknown';

  // Schema version — from config.js constant (not _meta table — RLS blocks browser reads)
  document.getElementById('diag-schema-version').textContent =
    typeof SCHEMA_VERSION !== 'undefined' ? SCHEMA_VERSION : 'unknown';

  // Auth status — from auth.js globals
  try {
    if (typeof isAuthenticated === 'function') {
      var authed = isAuthenticated();
      var user = typeof getCurrentUser === 'function' ? getCurrentUser() : null;
      document.getElementById('diag-auth-status').textContent =
        authed && user ? 'Signed in (' + user.email + ')' : 'Not signed in';
    } else {
      document.getElementById('diag-auth-status').textContent = 'auth.js not loaded';
    }
  } catch (_) {
    document.getElementById('diag-auth-status').textContent = 'error';
  }

  // Offline queue count — CryptoStore.getItem returns already-parsed data
  try {
    if (typeof CryptoStore !== 'undefined') {
      var items = await CryptoStore.getItem('ht_offline_queue', []);
      var count = Array.isArray(items) ? items.length : 0;
      document.getElementById('diag-offline-queue').textContent =
        count + ' item' + (count !== 1 ? 's' : '');
    } else {
      document.getElementById('diag-offline-queue').textContent = '0 items';
    }
  } catch (_) {
    document.getElementById('diag-offline-queue').textContent = 'error';
  }

  // Last data load — stored in localStorage by initData() on success
  try {
    var lastLoad = localStorage.getItem('ht_last_data_load');
    if (lastLoad) {
      var d = new Date(lastLoad);
      document.getElementById('diag-last-sync').textContent =
        d.toLocaleDateString() + ' ' + d.toLocaleTimeString();
    } else {
      document.getElementById('diag-last-sync').textContent = 'never';
    }
  } catch (_) {
    document.getElementById('diag-last-sync').textContent = 'error';
  }

  // SW status
  if ('serviceWorker' in navigator) {
    var sw = navigator.serviceWorker.controller;
    document.getElementById('diag-sw-status').textContent = sw ? sw.state || 'active' : 'no controller';
  } else {
    document.getElementById('diag-sw-status').textContent = 'unsupported';
  }

  // SW cache name via message
  try {
    if (typeof getSWVersion === 'function') {
      var info = await getSWVersion();
      document.getElementById('diag-sw-cache').textContent =
        info ? info.cacheName : 'unavailable';
    } else {
      document.getElementById('diag-sw-cache').textContent = 'unavailable';
    }
  } catch (_) {
    document.getElementById('diag-sw-cache').textContent = 'error';
  }
}

document.addEventListener('DOMContentLoaded', function () {

  // Restore auth session silently (profile page doesn't need initData)
  if (typeof _restoreSession === 'function') _restoreSession();

  // Menu items with data-page navigate to that page
  document.querySelectorAll('.menu-item[data-page]').forEach(function (item) {
    item.addEventListener('click', function () {
      navigateTo(item.dataset.page);
    });
  });

  // Menu items with data-action dispatch to the appropriate handler
  document.querySelectorAll('.menu-item[data-action]').forEach(function (item) {
    item.addEventListener('click', function () {
      var action = item.dataset.action;
      if (action === 'export') {
        alert('Export coming soon');
      } else if (action === 'goals') {
        alert('Goals coming soon');
      } else if (action === 'sync') {
        alert('Sync running...\nLast sync: Today, 8:00 PM');
      } else if (action === 'about') {
        var panel = document.getElementById('diagnostics-panel');
        if (panel) {
          var isHidden = panel.hidden;
          panel.hidden = !isHidden;
          if (isHidden) populateDiagnostics();
        }
      } else if (action === 'notifications') {
        toggleNotifications(item);
      }
    });
  });

  // Tab bar items with data-page navigate to that page
  document.querySelectorAll('.tab-bar [data-page]').forEach(function (tab) {
    tab.addEventListener('click', function () {
      navigateTo(tab.dataset.page);
    });
  });

});
