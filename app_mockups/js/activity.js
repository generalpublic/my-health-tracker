    // --- Global functions for onclick handlers ---
    function navigateTo(page) { window.location.href = page; }
    function closeSessionDetail(e) {
      if (e.target === document.getElementById('sessionDetailOverlay')) dismissSessionDetail();
    }
    function dismissSessionDetail() {
      const sheet = document.querySelector('.session-detail-sheet');
      sheet.style.transform = 'translateY(100%)';
      setTimeout(() => {
        document.getElementById('sessionDetailOverlay').classList.remove('visible');
        sheet.style.transform = '';
      }, 250);
    }
    function getActivityIcon(type, size) {
      size = size || 24;
      const t = (type || '').toLowerCase().replace(/[_ ]/g, '');
      if (t.includes('run') || t.includes('trail')) {
        return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor"><circle cx="13.5" cy="3.5" r="2"/><path d="M14 21v-4.15l-2.35-1.65-1.65 4.3L4 18l.75-1.85 4.25 1.15 2.45-6.3-2.15 1V15H7.3v-4.3l4.45-2.1c.6-.3 1.3-.2 1.8.2L15.8 10.5c.7.8 1.7 1.5 2.9 1.5v2c-1.6 0-3-.7-4-1.7l-.7 3.2L16 17v4h-2z"/></svg>`;
      }
      if (t.includes('cycl') || t.includes('bik')) {
        return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 5.5c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zM5 12c-2.8 0-5 2.2-5 5s2.2 5 5 5 5-2.2 5-5-2.2-5-5-5zm0 8.5c-1.9 0-3.5-1.6-3.5-3.5s1.6-3.5 3.5-3.5 3.5 1.6 3.5 3.5-1.6 3.5-3.5 3.5zm5.8-10l2.4-2.4.8.8c1.3 1.3 3 2.1 5 2.1v-2c-1.4 0-2.5-.5-3.4-1.4L13.4 5.5c-.4-.4-.9-.5-1.4-.5s-1 .2-1.4.5L7.8 8.4c-.4.4-.6.9-.6 1.4 0 .6.2 1.1.6 1.4L11 14v5h2v-6.2l-2.2-2.3zM19 12c-2.8 0-5 2.2-5 5s2.2 5 5 5 5-2.2 5-5-2.2-5-5-5zm0 8.5c-1.9 0-3.5-1.6-3.5-3.5s1.6-3.5 3.5-3.5 3.5 1.6 3.5 3.5-1.6 3.5-3.5 3.5z"/></svg>`;
      }
      if (t.includes('swim') || t.includes('pool') || t.includes('lap')) {
        return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor"><path d="M22 21c-1.11 0-1.73-.37-2.18-.64-.37-.22-.6-.36-1.15-.36-.56 0-.78.13-1.15.36-.46.27-1.07.64-2.18.64s-1.73-.37-2.18-.64c-.37-.22-.6-.36-1.15-.36-.56 0-.78.13-1.15.36-.46.27-1.08.64-2.19.64-1.11 0-1.73-.37-2.18-.64-.37-.23-.6-.36-1.15-.36v-2c1.11 0 1.73.37 2.18.64.37.22.6.36 1.15.36.56 0 .78-.13 1.15-.36.46-.27 1.08-.64 2.19-.64s1.73.37 2.18.64c.37.23.59.36 1.15.36.56 0 .78-.13 1.15-.36.45-.27 1.07-.64 2.18-.64s1.73.37 2.18.64c.37.23.59.36 1.15.36v2zM22 16.3c-1.11 0-1.73-.37-2.18-.64-.37-.22-.6-.36-1.15-.36-.56 0-.78.13-1.15.36-.46.27-1.07.64-2.18.64s-1.73-.37-2.18-.64c-.37-.22-.6-.36-1.15-.36-.56 0-.78.13-1.15.36-.46.27-1.08.64-2.19.64-1.11 0-1.73-.37-2.18-.64-.37-.23-.6-.36-1.15-.36v-2c1.11 0 1.73.37 2.18.64.37.22.6.36 1.15.36.56 0 .78-.13 1.15-.36.46-.27 1.08-.64 2.19-.64s1.73.37 2.18.64c.37.23.59.36 1.15.36.56 0 .78-.13 1.15-.36.45-.27 1.07-.64 2.18-.64s1.73.37 2.18.64c.37.23.59.36 1.15.36v2zm-8.47-4.88l1.62-1.62c-.63-.54-1.44-.88-2.32-.88-1.09 0-2.06.49-2.71 1.27L8.5 8.57l-2.43 2.43 3.07 2.56c.49.41 1.19.41 1.68 0zm2.97-6.92a2 2 0 1 0 0-4 2 2 0 0 0 0 4z"/></svg>`;
      }
      // Fallback: generic activity/fitness icon
      return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor"><path d="M20.57 14.86L22 13.43 20.57 12 17 15.57 8.43 7 12 3.43 10.57 2 9.14 3.43 7.71 2 5.57 4.14 4.14 2.71 2.71 4.14l1.43 1.43L2 7.71l1.43 1.43L2 10.57 3.43 12 7 8.43 15.57 17 12 20.57 13.43 22l1.43-1.43L16.29 22l2.14-2.14 1.43 1.43 1.43-1.43-1.43-1.43L22 16.29z"/></svg>`;
    }

    var weekSessionsData = [];
    function showSessionDetail(idx) {
      const s = weekSessionsData[idx];
      if (!s) return;
      const date = new Date(s.date + 'T12:00:00');
      const dateLabel = date.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric', year: 'numeric' });
      const durColor = s.duration ? getStatusColor(s.duration, 'workout_duration') : '';
      const distColor = s.distance ? getStatusColor(s.distance, 'session_distance') : '';
      const calColor = s.calories ? getStatusColor(s.calories, 'workout_calories') : '';
      const hrColor = s.avg_hr ? getStatusColor(s.avg_hr, 'session_avg_hr') : '';
      document.getElementById('sessionDetailContent').innerHTML = `
        <div style="display:flex;align-items:center;gap:var(--space-sm);margin-bottom:var(--space-sm)">
          <span style="color:var(--text-primary)">${getActivityIcon(s.type, 28)}</span>
          <div style="font-size:var(--text-lg);font-weight:700">${escapeHtml(s.activity_name)}</div>
        </div>
        <div style="font-size:var(--text-sm);color:var(--text-secondary);margin-bottom:var(--space-lg)">${dateLabel}</div>
        <div class="session-stats">
          <div class="session-stat">
            <div class="session-stat-value" style="color:${durColor}">${s.duration}m</div>
            <div class="session-stat-label">Duration</div>
          </div>
          <div class="session-stat">
            <div class="session-stat-value" style="color:${distColor}">${s.distance ? s.distance.toFixed(1) + ' mi' : '--'}</div>
            <div class="session-stat-label">Distance</div>
          </div>
          <div class="session-stat">
            <div class="session-stat-value" style="color:${calColor}">${s.calories}</div>
            <div class="session-stat-label">Calories</div>
          </div>
        </div>
        <div class="session-stats" style="margin-top:var(--space-sm)">
          <div class="session-stat">
            <div class="session-stat-value" style="color:${hrColor}">${s.avg_hr || '--'}</div>
            <div class="session-stat-label">Avg HR</div>
          </div>
          <div class="session-stat">
            <div class="session-stat-value">--</div>
            <div class="session-stat-label">&nbsp;</div>
          </div>
          <div class="session-stat">
            <div class="session-stat-value">--</div>
            <div class="session-stat-label">&nbsp;</div>
          </div>
        </div>`;
      document.getElementById('sessionDetailOverlay').classList.add('visible');
    }
    function showView(view) {
      document.getElementById('sessionsView').style.display = view === 'sessions' ? 'block' : 'none';
      document.getElementById('strengthView').style.display = view === 'strength' ? 'block' : 'none';
      document.getElementById('segSessions').className = 'segment-item' + (view === 'sessions' ? ' segment-item-active' : '');
      document.getElementById('segStrength').className = 'segment-item' + (view === 'strength' ? ' segment-item-active' : '');
    }
    // --- Strength form helpers ---
    function selectPill(el) {
      el.parentElement.querySelectorAll('.pill').forEach(p => p.classList.remove('pill-active'));
      el.classList.add('pill-active');
    }
    function stepValue(id, delta) {
      const el = document.getElementById(id);
      const val = Math.max(0, parseInt(el.textContent) + delta);
      el.textContent = val;
    }
    async function addStrengthSet() {
      const muscleGroup = document.querySelector('#muscleGroupPills .pill-active')?.textContent || 'Other';
      const exercise = document.getElementById('exerciseInput').value.trim();
      if (!exercise) { alert('Enter an exercise name'); return; }
      const weight = parseInt(document.getElementById('weightVal').textContent);
      const reps = parseInt(document.getElementById('repsVal').textContent);
      const rpe = parseInt(document.getElementById('rpeSlider').value);

      try {
        const result = await saveStrengthSet(muscleGroup, exercise, weight, reps, rpe);
        // Show success toast
        const toast = document.createElement('div');
        toast.style.cssText = 'position:fixed;bottom:120px;left:50%;transform:translateX(-50%);background:var(--text);color:var(--text-inverse);padding:8px 24px;border-radius:100px;font-size:13px;font-weight:600;z-index:100;opacity:0;transition:opacity 0.3s';
        toast.textContent = result === null ? 'Saved offline' : 'Set added';
        document.body.appendChild(toast);
        requestAnimationFrame(() => toast.style.opacity = '1');
        setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 1500);

        // Append to visible list
        const list = document.getElementById('strengthList');
        const setHtml = `<div class="strength-exercise"><div class="strength-header"><div class="strength-name">${escapeHtml(exercise)}</div><span class="muscle-tag">${escapeHtml(muscleGroup)}</span></div><div class="strength-sets">Set: ${escapeHtml(String(weight))} lbs x ${escapeHtml(String(reps))} @ RPE ${escapeHtml(String(rpe))}</div></div>`;
        list.insertAdjacentHTML('beforeend', setHtml);
      } catch (err) {
        console.error('[strength] Save failed:', err);
        alert('Failed to save set: ' + err.message);
      }
    }
    function toggleAddForm() {
      const form = document.getElementById('addForm');
      const btn = document.getElementById('addBtn');
      form.classList.toggle('visible');
      btn.style.display = form.classList.contains('visible') ? 'none' : 'block';
    }

    // --- Render after data loads ---
    initData().then(() => {

    console.log('[activity] initData resolved — sessions:', SAMPLE_DATA.sessions_history.length, ', today sessions:', SAMPLE_DATA.today?.sessions?.length, ', error:', SAMPLE_DATA._error);

    const D = SAMPLE_DATA.today;

    // ============================================
    // Today's session
    // ============================================

    (function renderTodaySession() {
      const s = D.sessions[0];
      if (!s) {
        document.getElementById('todaySession').innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:var(--space-xl);">No sessions today yet</div>';
        return;
      }

      const icons = { running: '&#127939;', cycling: '&#128690;', swimming: '&#127946;', strength: '&#127947;', walking: '&#128694;' };
      const totalZone = s.zone_1_min + s.zone_2_min + s.zone_3_min + s.zone_4_min + s.zone_5_min;

      // TE gauge helper
      function teGauge(val, label) {
        const r = 26, sw = 6, w = 70;
        const circ = 2 * Math.PI * r;
        const pct = val / 5;
        const offset = circ * (1 - pct);
        const color = getStatusColor(val, 'aerobic_te');
        const gId = 'teGrad' + label.replace(/\s/g, '');
        return `
          <div class="te-item">
            <div class="gauge te-gauge">
              <svg width="${w}" height="${w}" viewBox="0 0 ${w} ${w}">
                <defs>
                  <linearGradient id="${gId}" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#8B5CF6" />
                    <stop offset="100%" stop-color="#06B6D4" />
                  </linearGradient>
                </defs>
                <circle cx="${w/2}" cy="${w/2}" r="${r}" class="gauge-track" stroke-width="${sw}" />
                <circle cx="${w/2}" cy="${w/2}" r="${r}" class="gauge-fill"
                  style="--gauge-circumference:${circ}"
                  stroke="url(#${gId})" stroke-width="${sw}"
                  stroke-dasharray="${circ}" stroke-dashoffset="${offset}"
                  stroke-linecap="round" />
              </svg>
              <div class="gauge-value">
                <div class="gauge-number" style="font-size:var(--text-lg);color:${color}">${val}</div>
              </div>
            </div>
            <div class="te-label">${label}</div>
          </div>`;
      }

      document.getElementById('todaySession').innerHTML = `
        <div class="session-top">
          <div class="session-info">
            <div class="session-icon">${icons[s.activity_type] || '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="2,12 6,12 9,3 12,21 15,7 18,12 22,12"/></svg>'}</div>
            <div>
              <div class="session-name">${escapeHtml(s.activity_name)}</div>
              <div class="session-meta">${s.duration_min} min &bull; ${s.distance_mi} mi</div>
            </div>
          </div>
          <div class="session-cals">
            <div class="session-cal-num">${s.calories}</div>
            <div class="session-cal-label">calories</div>
          </div>
        </div>

        <div class="session-stats">
          <div class="session-stat">
            <div class="session-stat-value">${s.avg_hr}</div>
            <div class="session-stat-label">Avg HR</div>
          </div>
          <div class="session-stat">
            <div class="session-stat-value">${s.max_hr}</div>
            <div class="session-stat-label">Max HR</div>
          </div>
          <div class="session-stat">
            <div class="session-stat-value">${s.distance_mi} mi</div>
            <div class="session-stat-label">Distance</div>
          </div>
        </div>

        <div class="te-row">
          ${teGauge(s.aerobic_te, 'Aerobic TE')}
          ${teGauge(s.anaerobic_te, 'Anaerobic TE')}
        </div>

        <div class="zone-section">
          <div style="font-size:var(--text-sm);font-weight:600;margin-bottom:var(--space-sm)">HR Zones</div>
          <div class="zone-bar-lg">
            <div style="width:${(s.zone_1_min/totalZone*100)}%;background:var(--zone-1)"></div>
            <div style="width:${(s.zone_2_min/totalZone*100)}%;background:var(--zone-2)"></div>
            <div style="width:${(s.zone_3_min/totalZone*100)}%;background:var(--zone-3)"></div>
            <div style="width:${(s.zone_4_min/totalZone*100)}%;background:var(--zone-4)"></div>
            <div style="width:${(s.zone_5_min/totalZone*100)}%;background:var(--zone-5)"></div>
          </div>
          <div class="zone-legend">
            <div class="zone-legend-item"><div class="zone-legend-dot" style="background:var(--zone-1)"></div>Z1 ${s.zone_1_min}m</div>
            <div class="zone-legend-item"><div class="zone-legend-dot" style="background:var(--zone-2)"></div>Z2 ${s.zone_2_min}m</div>
            <div class="zone-legend-item"><div class="zone-legend-dot" style="background:var(--zone-3)"></div>Z3 ${s.zone_3_min}m</div>
            <div class="zone-legend-item"><div class="zone-legend-dot" style="background:var(--zone-4)"></div>Z4 ${s.zone_4_min}m</div>
            <div class="zone-legend-item"><div class="zone-legend-dot" style="background:var(--zone-5)"></div>Z5 ${s.zone_5_min}m</div>
          </div>
        </div>

        <div class="manual-section">
          <div class="manual-row">
            <span class="manual-label">Perceived Effort</span>
            <span class="manual-pill">${s.perceived_effort}/10</span>
          </div>
          <div class="manual-row">
            <span class="manual-label">Post-Workout Energy</span>
            <span class="manual-pill">${s.post_workout_energy}/10</span>
          </div>
          ${s.notes ? `<div style="font-size:var(--text-sm);color:var(--text-secondary);margin-top:var(--space-sm);">"${escapeHtml(s.notes)}"</div>` : ''}
        </div>`;
    })();

    // ============================================
    // This week's sessions
    // ============================================

    (function renderWeekSessions() {
      const sessions = SAMPLE_DATA.sessions_history;
      weekSessionsData = sessions;
      document.getElementById('weekSessions').innerHTML = sessions.map((s, i) => {
        const date = new Date(s.date + 'T12:00:00');
        const dayStr = date.toLocaleDateString('en-US', { weekday: 'short' });
        const numDate = `${date.getMonth()+1}/${date.getDate()}/${date.getFullYear()}`;
        return `
          <div class="week-session" data-session-idx="${i}" style="cursor:pointer">
            <div class="week-date"><div style="font-size:var(--text-xs);color:var(--text-secondary)">${numDate}</div><div>${dayStr}</div></div>
            <div style="color:var(--text-secondary);display:flex;align-items:center">${getActivityIcon(s.type, 22)}</div>
            <div class="week-dur">${s.duration} min</div>
            <div class="week-cal">${s.calories} cal</div>
          </div>`;
      }).join('');
    })();

    // ============================================
    // Strength view
    // ============================================

    (function renderStrength() {
      const exercises = D.strength;
      document.getElementById('setCount').textContent = exercises.length + ' sets';

      // Group by exercise
      const grouped = {};
      exercises.forEach(e => {
        const key = e.exercise;
        if (!grouped[key]) grouped[key] = { ...e, sets: [] };
        grouped[key].sets.push(e);
      });

      document.getElementById('strengthList').innerHTML = Object.values(grouped).map(g => `
        <div class="strength-exercise">
          <div class="strength-header">
            <div class="strength-name">${escapeHtml(g.exercise)}</div>
            <span class="muscle-tag">${escapeHtml(g.muscle_group)}</span>
          </div>
          <div class="strength-sets">
            ${g.sets.map((s, i) => `Set ${i+1}: ${escapeHtml(String(s.weight))} lbs x ${escapeHtml(String(s.reps))} @ RPE ${escapeHtml(String(s.rpe))}`).join('<br>')}
          </div>
        </div>
      `).join('');
    })();

    // Swipe-to-dismiss on session detail sheet
    (function() {
      let startY = 0, currentY = 0, isDragging = false;
      const overlay = document.getElementById('sessionDetailOverlay');
      overlay.addEventListener('touchstart', function(e) {
        const sheet = document.querySelector('.session-detail-sheet');
        if (sheet.scrollTop <= 0) { startY = e.touches[0].clientY; currentY = startY; isDragging = true; sheet.style.transition = 'none'; }
      }, { passive: true });
      overlay.addEventListener('touchmove', function(e) {
        if (!isDragging) return; currentY = e.touches[0].clientY; const dy = currentY - startY;
        if (dy > 0) { document.querySelector('.session-detail-sheet').style.transform = 'translateY(' + dy + 'px)'; e.preventDefault(); }
      }, { passive: false });
      overlay.addEventListener('touchend', function() {
        if (!isDragging) return; isDragging = false; const dy = currentY - startY;
        const sheet = document.querySelector('.session-detail-sheet'); sheet.style.transition = 'transform 0.25s ease';
        if (dy > 80) { dismissSessionDetail(); } else { sheet.style.transform = ''; }
      }, { passive: true });
    })();

    }).catch(err => {
      console.error('[activity] Rendering error:', err);
      var errTarget = document.getElementById('todaySession') || document.body;
      errTarget.textContent = '';
      var errDiv = document.createElement('div');
      errDiv.style.cssText = 'text-align:center;padding:48px 24px;color:#F87171;';
      var errTitle = document.createElement('div');
      errTitle.style.cssText = 'font-size:16px;font-weight:600;margin-bottom:8px;';
      errTitle.textContent = 'Something went wrong';
      var errMsg = document.createElement('div');
      errMsg.style.cssText = 'font-size:13px;';
      errMsg.textContent = err.message;
      errDiv.appendChild(errTitle);
      errDiv.appendChild(errMsg);
      errTarget.appendChild(errDiv);
    }); // end initData().then()

// ============================================
// Event listeners (replaces all inline handlers)
// ============================================
document.addEventListener('DOMContentLoaded', function () {

  // --- Segment control: delegate from .segment-control ---
  var segControl = document.querySelector('.segment-control');
  if (segControl) {
    segControl.addEventListener('click', function (e) {
      var item = e.target.closest('[data-view]');
      if (item) showView(item.getAttribute('data-view'));
    });
  }

  // --- Tab bar: delegate from .tab-bar ---
  var tabBar = document.querySelector('.tab-bar');
  if (tabBar) {
    tabBar.addEventListener('click', function (e) {
      var item = e.target.closest('[data-page]');
      if (item) navigateTo(item.getAttribute('data-page'));
    });
  }

  // --- Add Exercise toggle button ---
  var addBtn = document.getElementById('addBtn');
  if (addBtn) addBtn.addEventListener('click', function () { toggleAddForm(); });

  // --- Muscle group pills: delegate from #muscleGroupPills ---
  var muscleGroupPills = document.getElementById('muscleGroupPills');
  if (muscleGroupPills) {
    muscleGroupPills.addEventListener('click', function (e) {
      var pill = e.target.closest('.pill');
      if (pill) selectPill(pill);
    });
  }

  // --- Stepper buttons: delegate from .add-form ---
  var addForm = document.getElementById('addForm');
  if (addForm) {
    addForm.addEventListener('click', function (e) {
      var btn = e.target.closest('.stepper-btn[data-target]');
      if (btn) stepValue(btn.getAttribute('data-target'), parseInt(btn.getAttribute('data-step'), 10));
    });
  }

  // --- RPE slider ---
  var rpeSlider = document.getElementById('rpeSlider');
  if (rpeSlider) {
    rpeSlider.addEventListener('input', function () {
      document.getElementById('rpeDisplay').textContent = this.value;
    });
  }

  // --- Add Set button ---
  var addSetBtn = document.getElementById('addSetBtn');
  if (addSetBtn) addSetBtn.addEventListener('click', function () { addStrengthSet(); });

  // --- Done button ---
  var doneBtn = document.getElementById('doneBtn');
  if (doneBtn) doneBtn.addEventListener('click', function () { toggleAddForm(); });

  // --- Session detail overlay: click outside to close ---
  var overlay = document.getElementById('sessionDetailOverlay');
  if (overlay) {
    overlay.addEventListener('click', function (e) { closeSessionDetail(e); });
  }

  // --- Session detail sheet: stop propagation so clicks inside don't close ---
  var sheet = document.getElementById('sessionDetailSheet');
  if (sheet) {
    sheet.addEventListener('click', function (e) { e.stopPropagation(); });
  }

  // --- Drag handle: tap to dismiss ---
  var dragHandle = document.getElementById('sessionDetailDragHandle');
  if (dragHandle) {
    dragHandle.addEventListener('click', function () { dismissSessionDetail(); });
  }

  // --- Week session rows: delegate from #weekSessions ---
  var weekSessions = document.getElementById('weekSessions');
  if (weekSessions) {
    weekSessions.addEventListener('click', function (e) {
      var row = e.target.closest('[data-session-idx]');
      if (row) showSessionDetail(Number(row.getAttribute('data-session-idx')));
    });
  }

});