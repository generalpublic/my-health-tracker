    // ============================================
    // SPA Navigation
    // ============================================
    const viewRendered = {};
    const mainTabs = ['today', 'trends', 'log', 'activity', 'profile'];

    function navigate(viewName) {
      document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
      const target = document.getElementById('view-' + viewName);
      if (target) {
        target.classList.add('active');
        if (target.classList.contains('stagger')) {
          target.querySelectorAll('.animate-in').forEach((el, i) => {
            el.style.animation = 'none';
            el.offsetHeight;
            el.style.animation = '';
          });
        }
      }
      history.pushState(null, '', '#' + viewName);
      updateTabBar(viewName);
      if (!viewRendered[viewName] && window._dataReady) {
        renderView(viewName);
      }
    }

    function updateTabBar(viewName) {
      const tabMap = { sleep: 'today', calendar: 'profile' };
      const activeTab = tabMap[viewName] || viewName;
      document.querySelectorAll('#tabBar .tab-item').forEach(item => {
        const isCenter = item.classList.contains('tab-center');
        if (isCenter) return;
        const view = item.dataset.view;
        item.className = 'tab-item ' + (view === activeTab ? 'tab-item-active' : 'tab-item-inactive');
      });
    }

    window.addEventListener('popstate', () => {
      const hash = location.hash.replace('#', '') || 'today';
      navigate(hash);
    });

    // ============================================
    // Day Navigation (Snapshot < >)
    // ============================================
    var _viewDate = null; // null = today
    var _navBusy = false;

    function _todayDateStr() {
      const d = new Date();
      return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
    }

    function _shiftDate(dateStr, delta) {
      const d = new Date(dateStr + 'T12:00:00');
      d.setDate(d.getDate() + delta);
      return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
    }

    function _formatDateLabel(dateStr) {
      const d = new Date(dateStr + 'T12:00:00');
      const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      return months[d.getMonth()] + ' ' + d.getDate();
    }

    function _updateDayNavUI() {
      const todayStr = _todayDateStr();
      const isToday = !_viewDate || _viewDate === todayStr;
      const prevBtn = document.getElementById('dayNavPrev');
      const nextBtn = document.getElementById('dayNavNext');
      const dayLabel = document.getElementById('dayNavLabel');

      // Hide > when on today
      if (nextBtn) nextBtn.classList.toggle('hidden', isToday);

      // Hide < when at earliest history date
      const earliest = SAMPLE_DATA.history && SAMPLE_DATA.history.length > 0 ? SAMPLE_DATA.history[0].date : todayStr;
      const currentDate = _viewDate || todayStr;
      if (prevBtn) prevBtn.classList.toggle('hidden', currentDate <= earliest);

      // Update day label (separate from Snapshot title)
      if (dayLabel) dayLabel.textContent = isToday ? 'Today' : _formatDateLabel(currentDate);

      // Update greeting
      const greeting = document.getElementById('greeting');
      const _name = (typeof USER_NAME !== 'undefined' && USER_NAME) ? USER_NAME : '';
      if (greeting) {
        if (isToday) {
          greeting.textContent = _name ? 'Howdy, ' + _name : 'Howdy';
        } else {
          greeting.textContent = _formatDateLabel(currentDate);
        }
      }
    }

    async function navDay(delta) {
      if (_navBusy) return;
      _navBusy = true;

      const todayStr = _todayDateStr();
      const currentDate = _viewDate || todayStr;
      const newDate = _shiftDate(currentDate, delta);

      // Clamp: can't go past today
      if (newDate > todayStr) { _navBusy = false; return; }

      // Clamp: can't go before earliest history date
      const earliest = SAMPLE_DATA.history && SAMPLE_DATA.history.length > 0 ? SAMPLE_DATA.history[0].date : todayStr;
      if (newDate < earliest) { _navBusy = false; return; }

      _viewDate = newDate === todayStr ? null : newDate;

      // Show loading state
      const dayLabel = document.getElementById('dayNavLabel');
      if (dayLabel) dayLabel.textContent = 'Loading...';

      try {
        const dayData = await fetchDateData(newDate);
        SAMPLE_DATA.today = dayData;
        renderViewToday();
        _updateDayNavUI();
      } catch (e) {
        if (dayLabel) dayLabel.textContent = 'Error';
      }

      _navBusy = false;
    }

    // ============================================
    // Global Helper Functions
    // ============================================
    function toggleExpand(card) {
      const expand = card.querySelector('.card-expand-content');
      const chevron = card.querySelector('.card-chevron');
      if (expand) {
        expand.classList.toggle('expanded');
        if (chevron) chevron.classList.toggle('expanded');
      }
    }

    function formatHours(hrs) {
      const h = Math.floor(hrs);
      const m = Math.round((hrs - h) * 60);
      return h + 'h ' + m + 'm';
    }

    function formatTime(time24) {
      if (!time24 || !time24.includes(':')) return '--:--';
      const [h, m] = time24.split(':').map(Number);
      if (isNaN(h) || isNaN(m)) return '--:--';
      const ampm = h >= 12 ? 'PM' : 'AM';
      const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
      return h12 + ':' + String(m).padStart(2, '0') + ' ' + ampm;
    }

    // --- Calendar helpers ---
    const calMetrics = [
      { key: 'readiness', label: 'Readiness', field: 'readiness', threshold: 'readiness_score' },
      { key: 'sleep_score', label: 'Sleep', field: 'sleep_score', threshold: 'sleep_analysis_score' },
      { key: 'total_sleep', label: 'Sleep Hrs', field: 'total_sleep', threshold: 'total_sleep_hrs' },
      { key: 'hrv', label: 'HRV', field: 'hrv', threshold: 'overnight_hrv_ms' },
      { key: 'body_battery', label: 'Battery', field: 'body_battery', threshold: 'body_battery' },
      { key: 'steps', label: 'Steps', field: 'steps', threshold: 'steps' },
      { key: 'stress', label: 'Stress', field: 'stress', threshold: 'avg_stress_level' },
    ];
    let currentCalMetric = calMetrics[0];
    var calDateMap = {};
    var renderCalendar, showDetail;

    function setCalMetric(key, el) {
      currentCalMetric = calMetrics.find(m => m.key === key);
      document.querySelectorAll('#calMetricPills .pill').forEach(p => p.classList.remove('pill-active'));
      el.classList.add('pill-active');
      renderCalendar();
    }
    function closeDetail(e) {
      if (e.target === document.getElementById('detailOverlay')) dismissSheet();
    }
    function dismissSheet() {
      const sheet = document.querySelector('.cal-detail-sheet');
      sheet.style.transform = 'translateY(100%)';
      setTimeout(() => {
        document.getElementById('detailOverlay').classList.remove('visible');
        sheet.style.transform = '';
      }, 250);
    }

    // --- Trends helpers ---
    const metrics = [
      { key: 'readiness', label: 'Readiness', field: 'readiness', threshold: 'readiness_score', category: 'readiness' },
      { key: 'sleep_score', label: 'Sleep Score', field: 'sleep_score', threshold: 'sleep_analysis_score', category: 'sleep' },
      { key: 'total_sleep', label: 'Sleep Hrs', field: 'total_sleep', threshold: 'total_sleep_hrs', category: 'sleep' },
      { key: 'hrv', label: 'HRV', field: 'hrv', threshold: 'overnight_hrv_ms', category: 'body' },
      { key: 'rhr', label: 'Resting HR', field: 'rhr', threshold: 'resting_hr', category: 'body' },
      { key: 'body_battery', label: 'Body Battery', field: 'body_battery', threshold: 'body_battery', category: 'body' },
      { key: 'steps', label: 'Steps', field: 'steps', threshold: 'steps', category: 'body' },
      { key: 'stress', label: 'Stress', field: 'stress', threshold: 'avg_stress_level', category: 'body' },
      { key: 'morning_energy', label: 'AM Energy', field: 'morning_energy', threshold: 'morning_energy', category: 'subjective' },
      { key: 'day_rating', label: 'Day Rating', field: 'day_rating', threshold: 'day_rating', category: 'subjective' },
      { key: 'cognition', label: 'Cognition', field: 'cognition', threshold: 'cognition', category: 'subjective' },
      { key: 'habits', label: 'Habits', field: 'habits', threshold: 'habits_total', category: 'subjective' },
    ];
    let currentMetric = metrics[0];
    let currentRange = 14;
    let renderChart, renderHeatmap;

    function setMetric(key, el) {
      currentMetric = metrics.find(m => m.key === key);
      document.querySelectorAll('#metricPills .pill').forEach(p => p.classList.remove('pill-active'));
      el.classList.add('pill-active');
      renderChart();
      renderHeatmap();
    }
    function setRange(days, el) {
      currentRange = days;
      document.querySelectorAll('#rangePills .pill').forEach(p => p.classList.remove('pill-active'));
      el.classList.add('pill-active');
      renderChart();
    }
    // Calendar month state
    let calViewYear = new Date().getFullYear();
    let calViewMonth = new Date().getMonth();

    function navigateCalMonth(delta) {
      calViewMonth += delta;
      if (calViewMonth > 11) { calViewMonth = 0; calViewYear++; }
      if (calViewMonth < 0) { calViewMonth = 11; calViewYear--; }
      const now = new Date();
      if (calViewYear > now.getFullYear() || (calViewYear === now.getFullYear() && calViewMonth > now.getMonth())) {
        calViewYear = now.getFullYear();
        calViewMonth = now.getMonth();
      }
      const nextBtn = document.getElementById('calMonthNext');
      if (calViewYear === now.getFullYear() && calViewMonth === now.getMonth()) {
        nextBtn.style.opacity = '0.25';
        nextBtn.style.pointerEvents = 'none';
      } else {
        nextBtn.style.opacity = '';
        nextBtn.style.pointerEvents = '';
      }
      renderHeatmap();
    }

    // --- Activity helpers ---
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
        const toast = document.createElement('div');
        toast.style.cssText = 'position:fixed;bottom:120px;left:50%;transform:translateX(-50%);background:var(--text);color:var(--text-inverse);padding:8px 24px;border-radius:100px;font-size:13px;font-weight:600;z-index:100;opacity:0;transition:opacity 0.3s';
        toast.textContent = result === null ? 'Saved offline' : 'Set added';
        document.body.appendChild(toast);
        requestAnimationFrame(() => toast.style.opacity = '1');
        setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 1500);

        const list = document.getElementById('strengthList');
        const setHtml = `<div class="strength-exercise"><div class="strength-header"><div class="strength-name">${exercise}</div><span class="muscle-tag">${muscleGroup}</span></div><div class="strength-sets">Set: ${weight} lbs x ${reps} @ RPE ${rpe}</div></div>`;
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

    // --- Log Entry helpers ---
    function showHub() {
      document.querySelectorAll('.form-view').forEach(v => v.classList.remove('active'));
      document.getElementById('hubView').classList.add('active');
      document.getElementById('view-log').scrollTop = 0;
    }

    function showForm(name) {
      document.querySelectorAll('.form-view').forEach(v => v.classList.remove('active'));
      document.getElementById(name + 'Form').classList.add('active');
      document.getElementById('view-log').scrollTop = 0;
    }

    function updateSlider(input, valueId, metric) {
      const val = parseInt(input.value);
      const el = document.getElementById(valueId);
      el.textContent = val;
      el.style.color = getStatusColor(val, metric);
    }

    function updateSliderInverted(input, valueId) {
      const val = parseInt(input.value);
      const el = document.getElementById(valueId);
      el.textContent = val;
      const color = getStatusColor(val, 'avg_stress_level');
      el.style.color = color;
    }

    let cognitionScore = 8;

    function stepCognition(delta) {
      cognitionScore = Math.max(1, Math.min(10, cognitionScore + delta));
      const el = document.getElementById('cognitionVal');
      el.textContent = cognitionScore;
      el.style.color = getStatusColor(cognitionScore, 'cognition');
    }

    async function saveForm(formType, message) {
      const toast = document.getElementById('toast');
      toast.textContent = '\u2713 ' + message;
      toast.style.background = '';
      toast.classList.add('show');

      try {
        let result;
        switch (formType) {
          case 'morning': result = await saveMorningCheckin(); break;
          case 'midday': result = await saveMiddayCheckin(); break;
          case 'evening': result = await saveEveningReview(); break;
          case 'nutrition': result = await saveNutrition(); break;
          case 'cognition': result = await saveCognition(); break;
          case 'sleep_notes': result = await saveSleepNotes(); break;
          default: console.warn('[save] Unknown form type:', formType);
        }
        if (result === null) {
          toast.textContent = '\uD83D\uDD16 Saved offline \u2014 will sync when connected';
        }
      } catch (err) {
        console.error(`[save] ${formType} failed:`, err);
        toast.textContent = '\u2717 Save failed \u2014 ' + err.message;
        toast.style.background = '#F87171';
      }

      setTimeout(() => { toast.classList.remove('show'); toast.style.background = ''; }, 2500);
      setTimeout(() => showHub(), 2000);
    }

    function renderHabits(containerId) {
      const D = SAMPLE_DATA.today;
      const habits = [
        { key: 'wake_930', label: 'Wake at 9:30 AM', icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>' },
        { key: 'no_morning_screens', label: 'No morning screens', icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2"/><path d="M1 1l22 22"/></svg>' },
        { key: 'creatine_hydrate', label: 'Creatine & Hydrate', icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v6l-3 8a5 5 0 0 0 6 0l-3-8V2"/><path d="M6 18.5a9 9 0 0 0 12 0"/></svg>' },
        { key: 'walk_breathing', label: '20 min walk + breathing', icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13 4a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z"/><path d="M7 21l3-4 2.5 1 3.5-7-2-1.5L12 6l-3 4 2 1-2 4-3 2"/></svg>' },
        { key: 'physical_activity', label: 'Physical Activity', icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4z"/><path d="M22 14l-4.5-2.5L14 14l-4-4-4 4"/><path d="M2 18h20"/></svg>' },
        { key: 'no_screens_bed', label: 'No screens before bed', icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z"/><path d="M1 1l22 22"/></svg>' },
        { key: 'bed_10pm', label: 'Bed at 10 PM', icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z"/></svg>' }
      ];
      const container = document.getElementById(containerId);
      container.innerHTML = habits.map(h => {
        const done = D.daily_log.habits[h.key];
        return `
          <div class="habit-toggle">
            <div class="habit-toggle-info">
              <div class="habit-toggle-icon">${h.icon}</div>
              <div class="habit-toggle-name">${h.label}</div>
            </div>
            <div class="toggle-switch ${done ? 'active' : ''}" data-action="toggle-self"></div>
          </div>`;
      }).join('');
    }

    // --- Profile helpers ---
    function toggleNotifications(el) {
      const toggle = el.querySelector('.toggle-switch');
      toggle.classList.toggle('active');
    }

    // ============================================
    // Per-View Render Functions
    // ============================================
    function renderView(name) {
      try {
        switch(name) {
          case 'today': renderViewToday(); break;
          case 'trends': renderViewTrends(); break;
          case 'log': renderViewLog(); break;
          case 'activity': renderViewActivity(); break;
          case 'profile': renderProfileStats(); break;
          case 'sleep': renderViewSleep(); break;
          case 'calendar': renderViewCalendar(); break;
        }
        viewRendered[name] = true;
      } catch(e) {
        console.error('[SPA] renderView(' + name + ') error:', e);
        // Show error in the view if possible
        const container = document.getElementById('view-' + name);
        if (container) {
          container.innerHTML = '<div style="padding:24px;color:red;font-size:14px;"><b>Render Error (' + escapeHtml(name) + ')</b><br>' + escapeHtml(e.message) + '<br><pre style="font-size:11px;white-space:pre-wrap;margin-top:8px;">' + escapeHtml(e.stack) + '</pre></div>';
        }
        // Don't set viewRendered — allow retry on next navigation
      }
    }

    function renderViewToday() {
    const D = SAMPLE_DATA.today;

    // --- Greeting ---
    const _name = (typeof USER_NAME !== 'undefined' && USER_NAME) ? USER_NAME : '';
    document.getElementById('greeting').textContent = _name ? 'Howdy, ' + _name : 'Howdy';
    const _pAvatar = document.getElementById('profile-avatar');
    const _pName = document.getElementById('profile-name');
    if (_pAvatar) _pAvatar.textContent = _name ? _name[0].toUpperCase() : 'S';
    if (_pName) _pName.textContent = _name || 'Sek';

    // --- Data Warnings Banner ---
    (function renderDataWarnings() {
      var banner = document.getElementById('dataWarningsBanner');
      if (!banner) return;
      var ds = D.data_status || {};
      var warnings = [];

      if (ds.sync_stale) warnings.push('Sync missed \u2014 data may be outdated');
      if (ds.analysis_pending) warnings.push('Analysis pending \u2014 readiness score not yet computed');
      if (ds.quality_flags && ds.quality_flags.length > 0) {
        ds.quality_flags.forEach(function(f) { warnings.push(f); });
      }
      if (!ds.has_garmin && !ds.sync_stale) warnings.push('No Garmin data for today');

      if (warnings.length === 0) { banner.style.display = 'none'; return; }
      banner.style.display = '';

      setText(document.getElementById('dataWarningsTitle'),
        ds.sync_stale ? 'Data may be stale' : 'Data quality notice');
      setText(document.getElementById('dataWarningsIcon'),
        ds.sync_stale ? '\u26A0' : '\u2139');

      var nodes = warnings.map(function(w) {
        return h('div', { className: 'data-warning-item' }, [
          h('div', { className: 'data-warning-bullet' }),
          h('span', {}, [w])
        ]);
      });
      replaceChildren(document.getElementById('dataWarningsList'), nodes);
    })();

    // --- Readiness Hero Card (isolated — never crashes other cards) ---
    try {
      const score = (D.readiness && D.readiness.score) || 0;
      const color = getStatusColor(score, 'readiness_score');

      // Gauge
      const r = 56, sw = 13, w = 140;
      const circ = 2 * Math.PI * r;
      const offset = circ * (1 - score / 10);
      const svg = document.getElementById('readinessGaugeSvg');
      svg.innerHTML = `
        <circle cx="${w/2}" cy="${w/2}" r="${r}" class="gauge-track" stroke-width="${sw}" />
        <circle cx="${w/2}" cy="${w/2}" r="${r}" class="gauge-fill"
          style="--gauge-circumference:${circ}"
          stroke="${color}" stroke-width="${sw}"
          stroke-dasharray="${circ}" stroke-dashoffset="${offset}"
          stroke-linecap="round" />`;
      document.getElementById('readinessScore').textContent = score > 0 ? score.toFixed(1) : '--';
      document.getElementById('readinessScore').style.color = score > 0 ? color : '#94A3B8';

      // Label pill
      const labelEl = document.getElementById('readinessLabel');
      if (D.readiness && D.readiness.label) {
        const cls = getStatusClass(score, 'readiness_score');
        labelEl.className = `status-pill status-pill-${cls}`;
        labelEl.textContent = D.readiness.label;
      } else {
        labelEl.className = 'status-pill';
        labelEl.textContent = 'No Data';
      }

      // Confidence
      const conf = (D.readiness && D.readiness.confidence) || '';
      document.getElementById('readinessConfidence').textContent = conf ? conf + ' Confidence' : '';

      // EXPECT block
      const briefing = D.briefing || {};
      const expect = briefing.expect || { level: '', effects: [] };
      document.getElementById('expectLevel').textContent = expect.level || '';
      const effects = expect.effects || [];
      const effectsHtml = effects.map(e => {
        if (e.domain === 'Status') {
          return `<div class="expect-line"><span class="expect-domain" style="color:var(--text)">${escapeHtml(e.domain)}:</span><span>${escapeHtml(e.text)}</span></div>`;
        }
        const gradClass = e.domain === 'Mind' ? 'gradient-text-mind' : 'gradient-text-energy';
        return `<div class="expect-line"><span class="expect-domain gradient-text ${gradClass}">${escapeHtml(e.domain)}:</span><span>${escapeHtml(e.text)}</span></div>`;
      }).join('');
      document.getElementById('expectEffects').innerHTML = effectsHtml;

      // FLAGS
      const flags = (briefing.flags || []);
      const flagsHtml = flags.map(f =>
        `<div class="flag-item"><div class="flag-bullet"></div><span>${escapeHtml(f)}</span></div>`
      ).join('');
      document.getElementById('flagsList').innerHTML = flagsHtml;

      // DO
      const doItems = (briefing.do_items || []);
      const doHtml = doItems.map(d =>
        `<div class="do-item"><div class="do-icon"></div><span>${escapeHtml(d)}</span></div>`
      ).join('');
      document.getElementById('doList').innerHTML = doHtml;
    } catch (e) {
      console.error('[today] Readiness render failed:', e);
      document.getElementById('readinessScore').textContent = '--';
    }

    // --- Sleep Summary Card ---
    (function renderSleep() {
      const s = D.sleep;
      const targets = SAMPLE_DATA.sleep_stage_targets;

      // Score + verdict (pill matches score color)
      document.getElementById('sleepScore').textContent = s.analysis_score;
      const scoreColor = getStatusColor(s.analysis_score, 'sleep_analysis_score');
      document.getElementById('sleepScore').style.color = scoreColor;
      const verdict = document.getElementById('todaySleepVerdict');
      verdict.className = 'status-pill';
      verdict.style.color = scoreColor;
      verdict.style.background = `linear-gradient(135deg, ${scoreColor}1F, ${scoreColor}0F)`;
      verdict.style.border = `1px solid ${scoreColor}33`;
      verdict.textContent = s.sleep_feedback || '';
      verdict.style.fontWeight = '700';

      // Times row: bed · total · wake
      document.getElementById('totalSleep').textContent = formatHours(s.total_sleep_hrs);
      document.getElementById('bedtime').textContent = formatTime(s.bedtime);
      document.getElementById('wakeTime').textContent = formatTime(s.wake_time);


      // Stages bar with % labels inside
      const total = s.deep_min + s.light_min + s.rem_min + s.awake_min;
      const stages = [
        { min: s.deep_min, pct: s.deep_pct, color: 'var(--sleep-deep)' },
        { min: s.light_min, pct: Math.round(s.light_min / total * 100), color: 'var(--sleep-light)' },
        { min: s.rem_min, pct: s.rem_pct, color: 'var(--sleep-rem)' },
        { min: s.awake_min, pct: Math.round(s.awake_min / total * 100), color: 'var(--sleep-awake)' }
      ];
      const bar = document.getElementById('sleepStagesBar');
      bar.innerHTML = stages.map(st => {
        const widthPct = (st.min / total * 100).toFixed(1);
        const showLabel = widthPct > 12; // only show % if segment is wide enough
        return `<div class="sleep-stage" style="width:${widthPct}%;background:${st.color}">
          ${showLabel ? `<span class="sleep-stage-pct">${st.pct}%</span>` : ''}
        </div>`;
      }).join('');

      // Stage mini progress bars (actual vs target)
      const totalMin = Math.round(s.total_sleep_hrs * 60);
      const deepTarget = Math.round(totalMin * targets.deep_pct / 100);
      const remTarget = Math.round(totalMin * targets.rem_pct / 100);
      const lightTarget = totalMin - deepTarget - remTarget - targets.awake_max;
      const stageData = [
        { name: 'Deep', min: s.deep_min, target: deepTarget, color: 'var(--sleep-deep)', metric: 'deep_pct', pctVal: s.deep_pct },
        { name: 'Light', min: s.light_min, target: lightTarget, color: 'var(--sleep-light)', metric: null, pctVal: null },
        { name: 'REM', min: s.rem_min, target: remTarget, color: 'var(--sleep-rem)', metric: 'rem_pct', pctVal: s.rem_pct },
        { name: 'Awake', min: s.awake_min, target: targets.awake_max, color: 'var(--sleep-awake)', metric: 'awake_min', pctVal: null }
      ];

      document.getElementById('sleepStagesDetail').innerHTML = stageData.map(st => {
        let barMax, fillPct, valueText;
        if (st.target === null) {
          // Light — no target, just show the bar relative to total
          barMax = totalMin;
          fillPct = (st.min / barMax * 100).toFixed(1);
          valueText = `${st.min}m`;
        } else if (st.name === 'Awake') {
          // Awake — lower is better
          barMax = Math.max(st.target * 2, st.min);
          fillPct = (st.min / barMax * 100).toFixed(1);
          const met = st.min <= st.target;
          valueText = `${st.min}m / ${st.target}m ${met ? '<span style="color:var(--status-green)">&#10003;</span>' : ''}`;
        } else {
          // Deep, REM — higher is better
          barMax = Math.max(st.target, st.min);
          fillPct = (st.min / barMax * 100).toFixed(1);
          const met = st.min >= st.target;
          valueText = `${st.min}m / ${st.target}m ${met ? '<span style="color:var(--status-green)">&#10003;</span>' : ''}`;
        }

        return `<div class="stage-bar-row">
          <div class="stage-bar-label"><div class="stage-bar-dot" style="background:${st.color}"></div>${st.name}</div>
          <div class="stage-bar-track">
            <div class="stage-bar-fill" style="width:${fillPct}%;background:${st.color}"></div>
          </div>
          <div class="stage-bar-value">${valueText}</div>
        </div>`;
      }).join('');

      // Bottom metrics
      document.getElementById('hrvValue').textContent = s.overnight_hrv;
      document.getElementById('hrvDot').className = `status-dot status-dot-${getStatusClass(s.overnight_hrv, 'overnight_hrv_ms')}`;
      document.getElementById('bbGained').textContent = '+' + s.body_battery_gained;
      document.getElementById('bbDot').className = `status-dot status-dot-${getStatusClass(s.body_battery_gained, 'body_battery_gained')}`;
      document.getElementById('awakenings').textContent = s.awakenings;

      // 7-day context as structured stats
      const contextItems = D.briefing.sleep_context_items;
      document.getElementById('sleepContextStats').innerHTML = contextItems.map(item =>
        `<div class="context-stat">
          <span class="status-dot status-dot-${item.status}" style="width:6px;height:6px"></span>
          <span>${escapeHtml(item.label)}: <span class="context-stat-value">${escapeHtml(item.value)}</span></span>
        </div>`
      ).join('');
    })();

    // --- Body & Recovery Card ---
    (function renderBody() {
      const g = D.garmin;

      // Body Battery gauge — uses CSS grid centering
      const bb = g.body_battery;
      const bbColor = getStatusColor(bb, 'body_battery');
      const r = 40, sw = 8, w = 100;
      const circ = 2 * Math.PI * r;
      const offset = circ * (1 - bb / 100);
      const bbSvg = document.getElementById('bodyBatteryGaugeSvg');
      bbSvg.innerHTML = `
        <defs>
          <linearGradient id="bbGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#22C55E" />
            <stop offset="50%" stop-color="#06B6D4" />
            <stop offset="100%" stop-color="#8B5CF6" />
          </linearGradient>
        </defs>
        <circle cx="${w/2}" cy="${w/2}" r="${r}" class="gauge-track" stroke-width="${sw}" />
        <circle cx="${w/2}" cy="${w/2}" r="${r}" class="gauge-fill"
          style="--gauge-circumference:${circ}"
          stroke="url(#bbGrad)" stroke-width="${sw}"
          stroke-dasharray="${circ}" stroke-dashoffset="${offset}"
          stroke-linecap="round" />`;
      document.getElementById('bbValue').style.color = bbColor;

      // Metrics
      document.getElementById('rhrValue').textContent = g.resting_hr;
      document.getElementById('rhrDot').className = `status-dot status-dot-${getStatusClass(g.resting_hr, 'resting_hr')}`;
      document.getElementById('stressValue').textContent = g.avg_stress;
      document.getElementById('stressDot').className = `status-dot status-dot-${getStatusClass(g.avg_stress, 'avg_stress_level')}`;
      document.getElementById('hrv7dValue').textContent = g.hrv_7day_avg;

      // Steps
      const stepsColor = getStatusColor(g.steps, 'steps');
      document.getElementById('stepsValue').textContent = g.steps.toLocaleString();
      document.getElementById('stepsDot').className = `status-dot status-dot-${getStatusClass(g.steps, 'steps')}`;
      const pct = Math.min(g.steps / 10000 * 100, 100);
      const bar = document.getElementById('stepsBar');
      bar.style.width = pct + '%';
      bar.style.background = stepsColor;
    })();

    // --- Habits Card ---
    (function renderHabits() {
      const habits = [
        { key: 'wake_930', label: 'Wake', icon: '&#9788;' },
        { key: 'no_morning_screens', label: 'No AM', icon: '&#128241;' },
        { key: 'creatine_hydrate', label: 'Hydrate', icon: '&#128167;' },
        { key: 'walk_breathing', label: 'Walk', icon: '&#127939;' },
        { key: 'physical_activity', label: 'Active', icon: '&#9889;' },
        { key: 'no_screens_bed', label: 'No PM', icon: '&#128564;' },
        { key: 'bed_10pm', label: 'Bed 10', icon: '&#127769;' }
      ];

      const row = document.getElementById('habitsRow');
      row.innerHTML = habits.map(h => {
        const done = D.daily_log.habits[h.key];
        return `
          <div class="habit-item">
            <div class="habit-circle ${done ? 'habit-circle-done' : 'habit-circle-pending'}">
              ${done ? '&#10003;' : h.icon}
            </div>
            <div class="habit-label">${h.label}</div>
          </div>`;
      }).join('');

      document.getElementById('habitsCount').textContent = D.daily_log.habits_total + '/7';
    })();

    // --- Activity Card ---
    (function renderActivity() {
      const sessions = D.sessions;
      if (!sessions.length) {
        document.getElementById('activityCard').style.display = 'none';
        document.getElementById('trainingCard').style.display = 'none';
        return;
      }
      document.getElementById('activityCard').style.display = '';
      document.getElementById('trainingCard').style.display = '';

      const content = document.getElementById('activityContent');
      content.innerHTML = sessions.map(s => {
        const typeIcons = { running: '&#127939;', cycling: '&#128690;', swimming: '&#127946;', strength: '&#127947;', walking: '&#128694;' };
        const icon = typeIcons[s.activity_type] || '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="2,12 6,12 9,3 12,21 15,7 18,12 22,12"/></svg>';
        const totalZone = s.zone_1_min + s.zone_2_min + s.zone_3_min + s.zone_4_min + s.zone_5_min;

        return `
          <div class="activity-item">
            <div class="activity-info">
              <div class="activity-icon">${icon}</div>
              <div>
                <div class="activity-name">${escapeHtml(s.activity_name)}</div>
                <div class="activity-subtitle">${s.duration_min}min &bull; ${s.distance_mi}mi &bull; ${s.avg_hr} bpm avg</div>
              </div>
            </div>
            <div style="text-align:right">
              <div class="activity-calories">${s.calories}</div>
              <div class="activity-calories-label">cal</div>
            </div>
          </div>
          <div class="zone-bar">
            <div style="width:${(s.zone_1_min/totalZone*100)}%;background:var(--zone-1)"></div>
            <div style="width:${(s.zone_2_min/totalZone*100)}%;background:var(--zone-2)"></div>
            <div style="width:${(s.zone_3_min/totalZone*100)}%;background:var(--zone-3)"></div>
            <div style="width:${(s.zone_4_min/totalZone*100)}%;background:var(--zone-4)"></div>
            <div style="width:${(s.zone_5_min/totalZone*100)}%;background:var(--zone-5)"></div>
          </div>
          <div class="zone-labels">
            <span class="zone-label">Z1 ${s.zone_1_min}m</span>
            <span class="zone-label">Z2 ${s.zone_2_min}m</span>
            <span class="zone-label">Z3 ${s.zone_3_min}m</span>
            <span class="zone-label">Z4 ${s.zone_4_min}m</span>
            <span class="zone-label">Z5 ${s.zone_5_min}m</span>
          </div>`;
      }).join('');
    })();

    // --- Quick Insights + Recommendations Card ---
    (function renderInsights() {
      const cap = s => s ? s.charAt(0).toUpperCase() + s.slice(1) : s;

      const insights = D.readiness.key_insights.slice(0, 3);
      document.getElementById('insightsList').innerHTML = insights.map(i =>
        `<div class="flag-item"><div class="insight-bullet"></div><span style="font-size:var(--text-sm);">${escapeHtml(cap(i))}</span></div>`
      ).join('');

      const recs = (D.readiness.recommendations || []).slice(0, 3);
      const recsSection = document.getElementById('recommendationsSection');
      if (recs.length > 0) {
        recsSection.innerHTML =
          `<div class="recs-divider"></div>` +
          `<div class="recs-title">Recommendations</div>` +
          recs.map(r =>
            `<div class="flag-item"><div class="rec-bullet"></div><span style="font-size:var(--text-sm);">${escapeHtml(cap(r))}</span></div>`
          ).join('');
      }
    })();

    // --- Tonight Priorities Card ---
    (function renderTonight() {
      var card = document.getElementById('tonightCard');
      if (!card) return;

      var isToday = !_viewDate || _viewDate === _todayDateStr();
      var mode = D.day_mode || 'day';
      var show = isToday && (mode === 'evening' || mode === 'night');

      if (!show || !D.briefing.sleep_need_hrs) {
        card.style.display = 'none';
        return;
      }
      card.style.display = '';

      setText(document.getElementById('tonightSleepTarget'),
        formatHours(D.briefing.sleep_need_hrs));
      setText(document.getElementById('tonightBedtime'),
        D.briefing.recommended_bedtime || '--');
      setText(document.getElementById('tonightSleepDebt'),
        D.briefing.sleep_debt || '0h');

      var trustEl = document.getElementById('tonightTrust');
      if (D.trust_note) {
        trustEl.style.display = '';
        setText(trustEl, D.trust_note);
      } else {
        trustEl.style.display = 'none';
      }
    })();

    // Update day navigation arrows visibility
    _updateDayNavUI();

    }

    function renderViewTrends() {
    // ============================================
    // Render metric pills
    // ============================================

    (function renderPills() {
      document.getElementById('metricPills').innerHTML = metrics.map((m, i) =>
        `<div class="pill ${i === 0 ? 'pill-active' : ''}" data-metric="${m.key}">${m.label}</div>`
      ).join('');
    })();

    // ============================================
    // Render chart
    // ============================================

    renderChart = function() {
      const data = SAMPLE_DATA.history.slice(-currentRange);
      const values = data.map(d => d[currentMetric.field]);
      const t = SAMPLE_DATA.thresholds[currentMetric.threshold];

      const allVals = [...values, t.red, t.yellow || t.green, t.green].filter(v => v != null);
      const min = Math.min(...allVals) * 0.9;
      const max = Math.max(...allVals) * 1.1;

      const w = 340, h = 160, pad = 15;

      function yPos(v) {
        return h - pad - ((v - min) / (max - min)) * (h - 2 * pad);
      }

      let svg = '';

      // Threshold zones
      const yG = yPos(t.green);
      const yY = yPos(t.yellow || ((t.red + t.green) / 2));
      const yR = yPos(t.red);

      if (t.type === 'higher_better') {
        svg += `<rect x="${pad}" y="0" width="${w-2*pad}" height="${Math.max(0,yG)}" fill="rgba(34,197,94,0.06)" />`;
        svg += `<rect x="${pad}" y="${yG}" width="${w-2*pad}" height="${Math.max(0,yY-yG)}" fill="rgba(245,158,11,0.06)" />`;
        svg += `<rect x="${pad}" y="${yY}" width="${w-2*pad}" height="${h-yY-pad}" fill="rgba(248,113,113,0.06)" />`;
        svg += `<line x1="${pad}" y1="${yG}" x2="${w-pad}" y2="${yG}" stroke="var(--status-green)" stroke-width="0.5" stroke-dasharray="4"/>`;
        svg += `<line x1="${pad}" y1="${yY}" x2="${w-pad}" y2="${yY}" stroke="var(--status-yellow)" stroke-width="0.5" stroke-dasharray="4"/>`;
      } else {
        svg += `<rect x="${pad}" y="0" width="${w-2*pad}" height="${Math.max(0,yR)}" fill="rgba(248,113,113,0.06)" />`;
        svg += `<rect x="${pad}" y="${yR}" width="${w-2*pad}" height="${Math.max(0,yG-yR)}" fill="rgba(245,158,11,0.06)" />`;
        svg += `<rect x="${pad}" y="${yG}" width="${w-2*pad}" height="${h-yG-pad}" fill="rgba(34,197,94,0.06)" />`;
        svg += `<line x1="${pad}" y1="${yG}" x2="${w-pad}" y2="${yG}" stroke="var(--status-green)" stroke-width="0.5" stroke-dasharray="4"/>`;
        svg += `<line x1="${pad}" y1="${yR}" x2="${w-pad}" y2="${yR}" stroke="var(--status-red)" stroke-width="0.5" stroke-dasharray="4"/>`;
      }

      // Data points
      const points = values.map((v, i) => ({
        x: pad + (i / Math.max(values.length - 1, 1)) * (w - 2 * pad),
        y: yPos(v),
        v
      }));

      // Area fill
      if (points.length > 1) {
        const areaPath = `M${points[0].x},${points[0].y} ` +
          points.slice(1).map(p => `L${p.x},${p.y}`).join(' ') +
          ` L${points[points.length-1].x},${h-pad} L${points[0].x},${h-pad} Z`;
        svg += `<path d="${areaPath}" fill="var(--primary)" opacity="0.08"/>`;
      }

      // Line
      if (points.length > 1) {
        const linePath = points.map((p, i) => (i === 0 ? 'M' : 'L') + p.x + ',' + p.y).join(' ');
        svg += `<path d="${linePath}" fill="none" stroke="var(--primary)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>`;
      }

      // Dots
      points.forEach(p => {
        const color = getStatusColor(p.v, currentMetric.threshold);
        svg += `<circle cx="${p.x}" cy="${p.y}" r="4.5" fill="${color}" stroke="white" stroke-width="2"/>`;
      });

      document.getElementById('trendsSvg').innerHTML = svg;

      // X labels
      const labelIndices = [0, Math.floor(data.length / 2), data.length - 1];
      document.getElementById('chartXLabels').innerHTML = data.map((d, i) => {
        if (!labelIndices.includes(i)) return '<span></span>';
        const date = new Date(d.date + 'T12:00:00');
        return `<span>${date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>`;
      }).join('');

      // Stats
      const avg = values.reduce((a, b) => a + b, 0) / values.length;
      const best = t.type === 'higher_better' ? Math.max(...values) : Math.min(...values);
      const worst = t.type === 'higher_better' ? Math.min(...values) : Math.max(...values);

      // Clean number formatting — drop .0
      function fmt(v) {
        const fixed = v.toFixed(1);
        return fixed.endsWith('.0') ? String(Math.round(v)) : fixed;
      }

      document.getElementById('statAvg').textContent = fmt(avg);
      document.getElementById('statAvg').style.color = getStatusColor(avg, currentMetric.threshold);
      document.getElementById('statBest').textContent = fmt(best);
      document.getElementById('statBest').style.color = getStatusColor(best, currentMetric.threshold);
      document.getElementById('statWorst').textContent = fmt(worst);
      document.getElementById('statWorst').style.color = getStatusColor(worst, currentMetric.threshold);

      // Metric-aware labels
      const unit = currentMetric.label;
      const labelMap = {
        'Readiness': ['Avg Score', 'Best', 'Worst'],
        'Sleep Score': ['Avg Score', 'Best', 'Worst'],
        'Sleep Hrs': ['Avg Sleep (hrs)', 'Best', 'Worst'],
        'HRV': ['Avg HRV (ms)', 'Best', 'Worst'],
        'Resting HR': ['Avg RHR (bpm)', 'Best', 'Worst'],
        'Body Battery': ['Avg Battery', 'Best', 'Worst'],
        'Steps': ['Avg Steps', 'Best', 'Worst'],
        'Stress': ['Avg Stress', 'Best', 'Worst'],
        'AM Energy': ['Avg Energy', 'Best', 'Worst'],
        'Day Rating': ['Avg Rating', 'Best', 'Worst'],
        'Cognition': ['Avg Cognition', 'Best', 'Worst'],
        'Habits': ['Avg Habits', 'Best', 'Worst'],
      };
      const labels = labelMap[unit] || ['Average', 'Best', 'Worst'];
      const labelEls = document.querySelectorAll('#statsRow .stat-label');
      if (labelEls.length >= 3) {
        labelEls[0].textContent = labels[0];
        labelEls[1].textContent = labels[1];
        labelEls[2].textContent = labels[2];
      }

      // Trend (simple linear regression direction)
      const n = values.length;
      const xMean = (n - 1) / 2;
      const yMean = avg;
      let num = 0, den = 0;
      values.forEach((v, i) => { num += (i - xMean) * (v - yMean); den += (i - xMean) ** 2; });
      const slope = den ? num / den : 0;

      const trendEl = document.getElementById('statTrend');
      if (Math.abs(slope) < 0.1) {
        trendEl.textContent = 'Stable';
        trendEl.className = 'stat-trend trend-flat';
      } else if ((slope > 0 && t.type === 'higher_better') || (slope < 0 && t.type === 'lower_better')) {
        trendEl.textContent = 'Improving';
        trendEl.className = 'stat-trend trend-up';
      } else {
        trendEl.textContent = 'Declining';
        trendEl.className = 'stat-trend trend-down';
      }
    }

    // ============================================
    // Calendar Heatmap
    // ============================================

    renderHeatmap = function() {
      const monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];
      const dayNames = ['S','M','T','W','T','F','S'];

      document.getElementById('heatmapMetricLabel').textContent = '— ' + currentMetric.label;
      document.getElementById('calMonthLabel').textContent = monthNames[calViewMonth] + ' ' + calViewYear;

      // Disable forward arrow if at current month
      const now = new Date();
      const nextBtn = document.getElementById('calMonthNext');
      if (calViewYear === now.getFullYear() && calViewMonth === now.getMonth()) {
        nextBtn.style.opacity = '0.25';
        nextBtn.style.pointerEvents = 'none';
      } else {
        nextBtn.style.opacity = '';
        nextBtn.style.pointerEvents = '';
      }

      // Build date lookup
      const dateMap = {};
      SAMPLE_DATA.history.forEach(d => { dateMap[d.date] = d[currentMetric.field]; });

      // Weekday headers
      document.getElementById('calWeekdayRow').innerHTML = dayNames.map((d, i) => {
        const isWeekend = i === 0 || i === 6;
        return `<div class="trends-cal-weekday${isWeekend ? ' weekend' : ''}">${d}</div>`;
      }).join('');

      // Day grid
      const daysInMonth = new Date(calViewYear, calViewMonth + 1, 0).getDate();
      const firstDow = new Date(calViewYear, calViewMonth, 1).getDay();
      const todayStr = _todayStr();

      let html = '';

      // Empty leading cells for day-of-week offset
      for (let i = 0; i < firstDow; i++) {
        html += '<div class="trends-cal-day trends-cal-day-empty"></div>';
      }

      // Day cells
      for (let d = 1; d <= daysInMonth; d++) {
        const dateStr = `${calViewYear}-${String(calViewMonth + 1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
        const isFuture = new Date(calViewYear, calViewMonth, d) > now;
        const isToday = dateStr === todayStr;

        if (isFuture) {
          html += `<div class="trends-cal-day trends-cal-day-future">${d}</div>`;
        } else {
          const val = dateMap[dateStr];
          if (val !== undefined && val !== null && !isNaN(val)) {
            const color = getStatusColor(val, currentMetric.threshold);
            const textColor = isLightColor(color) ? '#333' : '#fff';
            html += `<div class="trends-cal-day${isToday ? ' trends-cal-day-today' : ''}" style="background:${color};color:${textColor}" title="${currentMetric.label}: ${val}">${d}</div>`;
          } else {
            html += `<div class="trends-cal-day trends-cal-day-nodata${isToday ? ' trends-cal-day-today' : ''}">${d}</div>`;
          }
        }
      }

      document.getElementById('calGrid').innerHTML = html;
    }

    // ============================================
    // Initial render
    // ============================================

    renderChart();
    renderHeatmap();

    }

    function renderViewLog() {
    const D = SAMPLE_DATA.today;

    // Initialize cognition color
    document.getElementById('cognitionVal').style.color = getStatusColor(8, 'cognition');

    renderHabits('morningHabits');
    renderHabits('eveningHabits');

    // ============================================
    // Initialize slider colors
    // ============================================

    document.querySelectorAll('.big-slider-value').forEach(el => {
      const val = parseInt(el.textContent);
      if (!isNaN(val)) {
        el.style.color = getStatusColor(val, 'morning_energy');
      }
    });

    // Special: stress is inverted
    const stressEl = document.getElementById('eveStressVal');
    if (stressEl) {
      stressEl.style.color = getStatusColor(parseInt(stressEl.textContent), 'avg_stress_level');
    }

    }

    function renderViewActivity() {
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
    }

    function renderProfileStats() {
      const history = SAMPLE_DATA.history || [];
      if (!history.length) return;

      // Days tracked — days with any readiness or sleep data
      const daysTracked = history.filter(d => d.readiness > 0 || d.sleep_score > 0).length;

      // Streak — consecutive days ending at today (or most recent day)
      const today = new Date().toISOString().slice(0, 10);
      const datesWithData = new Set(history.filter(d => d.readiness > 0 || d.sleep_score > 0).map(d => d.date));
      let streak = 0;
      let checkDate = new Date(today);
      while (true) {
        const ds = checkDate.toISOString().slice(0, 10);
        if (datesWithData.has(ds)) {
          streak++;
          checkDate.setDate(checkDate.getDate() - 1);
        } else {
          break;
        }
      }

      // Averages (only from days with data)
      const readinessVals = history.map(d => d.readiness).filter(v => v > 0);
      const sleepVals = history.map(d => d.total_sleep).filter(v => v > 0);
      const avgReadiness = readinessVals.length ? (readinessVals.reduce((a, b) => a + b, 0) / readinessVals.length) : 0;
      const avgSleep = sleepVals.length ? (sleepVals.reduce((a, b) => a + b, 0) / sleepVals.length) : 0;

      // Render values
      const elDays = document.getElementById('stat-days-tracked');
      const elReadiness = document.getElementById('stat-avg-readiness');
      const elSleep = document.getElementById('stat-avg-sleep');
      const elStreak = document.getElementById('stat-streak');

      if (elDays) elDays.textContent = daysTracked;
      if (elStreak) elStreak.textContent = streak + ' day streak';

      if (elReadiness) {
        elReadiness.textContent = avgReadiness.toFixed(1);
        elReadiness.style.color = getStatusColor(avgReadiness, 'readiness_score');
      }
      if (elSleep) {
        elSleep.textContent = avgSleep.toFixed(1);
        elSleep.style.color = getStatusColor(avgSleep, 'total_sleep_hrs');
      }
    }

    function renderViewSleep() {
    const S = SAMPLE_DATA.today.sleep;

    // --- Nav title with date ---
    (function() {
      const today = SAMPLE_DATA.today.date || new Date().toISOString().slice(0, 10);
      const d = new Date(today + 'T12:00:00');
      const formatted = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
      document.getElementById('sleepNavTitle').textContent = `Sleep: ${formatted}`;
    })();

    // --- Hero gauge ---
    (function() {
      const score = S.analysis_score;
      const color = getStatusColor(score, 'sleep_analysis_score');
      const r = 52, sw = 10, w = 130;
      const circ = 2 * Math.PI * r;
      const offset = circ * (1 - score / 100);
      const svg = document.getElementById('sleepGaugeSvg');
      svg.innerHTML = `
        <defs>
          <linearGradient id="sleepGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#4338CA" />
            <stop offset="50%" stop-color="#8B5CF6" />
            <stop offset="100%" stop-color="#A78BFA" />
          </linearGradient>
        </defs>
        <circle cx="${w/2}" cy="${w/2}" r="${r}" class="gauge-track" stroke-width="${sw}" />
        <circle cx="${w/2}" cy="${w/2}" r="${r}" class="gauge-fill"
          style="--gauge-circumference:${circ}"
          stroke="url(#sleepGrad)" stroke-width="${sw}"
          stroke-dasharray="${circ}" stroke-dashoffset="${offset}"
          stroke-linecap="round" />`;
      const heroEl = document.getElementById('heroScore');
      heroEl.textContent = score > 0 ? score : '--';
      heroEl.style.color = color;

      const cls = getStatusClass(score, 'sleep_analysis_score');
      const pill = document.getElementById('sleepVerdict');
      pill.className = `status-pill status-pill-${cls}`;
      pill.textContent = S.sleep_feedback;

      const garminBadge = document.getElementById('garminScoreBadge');
      if (garminBadge) garminBadge.textContent = S.garmin_score > 0 ? `Garmin: ${S.garmin_score}` : 'Garmin: --';

      document.getElementById('analysisText').textContent = S.analysis_text;
    })();

    // --- Timeline ---
    document.getElementById('tlBedtime').textContent = formatTime(S.bedtime);
    document.getElementById('tlWake').textContent = formatTime(S.wake_time);
    document.getElementById('tlDuration').textContent = formatHours(S.time_in_bed_hrs) + ' in bed';

    // Timeline bar: simulate sleep stages as alternating blocks
    (function() {
      const stages = [
        { type: 'light', dur: 25 }, { type: 'deep', dur: 35 },
        { type: 'light', dur: 30 }, { type: 'rem', dur: 20 },
        { type: 'light', dur: 20 }, { type: 'deep', dur: 30 },
        { type: 'light', dur: 35 }, { type: 'rem', dur: 25 },
        { type: 'awake', dur: 5 },  { type: 'light', dur: 25 },
        { type: 'deep', dur: 27 },  { type: 'light', dur: 30 },
        { type: 'rem', dur: 25 },   { type: 'light', dur: 33 },
        { type: 'awake', dur: 10 }, { type: 'rem', dur: 15 }
      ];
      const colors = { deep: 'var(--sleep-deep)', light: 'var(--sleep-light)', rem: 'var(--sleep-rem)', awake: 'var(--sleep-awake)' };
      const total = stages.reduce((s, st) => s + st.dur, 0);
      document.getElementById('timelineBar').innerHTML = stages.map(st =>
        `<div class="timeline-segment" style="width:${(st.dur/total*100).toFixed(1)}%;background:${colors[st.type]}"></div>`
      ).join('');
    })();

    // --- Stage Rows ---
    (function() {
      const total = S.deep_min + S.light_min + S.rem_min + S.awake_min;
      const stages = [
        { name: 'Deep', min: S.deep_min, pct: S.deep_pct, color: 'var(--sleep-deep)', maxBar: 120 },
        { name: 'Light', min: S.light_min, pct: Math.round(S.light_min/total*100), color: 'var(--sleep-light)', maxBar: 250 },
        { name: 'REM', min: S.rem_min, pct: S.rem_pct, color: 'var(--sleep-rem)', maxBar: 150 },
        { name: 'Awake', min: S.awake_min, pct: Math.round(S.awake_min/total*100), color: 'var(--sleep-awake)', maxBar: 60 },
      ];

      document.getElementById('stageRows').innerHTML = stages.map(st => `
        <div class="stage-row">
          <div class="stage-dot" style="background:${st.color}"></div>
          <div class="stage-name">${st.name}</div>
          <div class="stage-minutes">${st.min}m</div>
          <div class="stage-pct">${st.pct}%</div>
          <div class="stage-bar-wrap">
            <div class="stage-bar-fill" style="width:${(st.min/st.maxBar*100).toFixed(0)}%;background:${st.color}"></div>
          </div>
        </div>
      `).join('');
    })();

    // --- Vitals ---
    (function() {
      const vitals = [
        { label: 'Avg HR', value: S.avg_hr, unit: 'bpm', metric: 'resting_hr' },
        { label: 'Respiration', value: S.avg_respiration, unit: 'br/min', metric: null },
        { label: 'Overnight HRV', value: S.overnight_hrv, unit: 'ms', metric: 'overnight_hrv_ms' },
        { label: 'Body Battery Gained', value: '+' + S.body_battery_gained, rawValue: S.body_battery_gained, metric: 'body_battery_gained' },
        { label: 'Sleep Cycles', value: S.sleep_cycles, unit: '', metric: null },
        { label: 'Awakenings', value: S.awakenings, unit: '', metric: null },
      ];

      document.getElementById('vitalsGrid').innerHTML = vitals.map(v => {
        const dotHtml = v.metric ? `<span class="status-dot status-dot-${getStatusClass(v.rawValue || parseFloat(v.value), v.metric)}"></span>` : '';
        return `
          <div class="vital-item">
            <div class="vital-value">${v.value}${v.unit ? ' <span style="font-size:var(--text-sm);color:var(--text-secondary);font-weight:400">' + v.unit + '</span>' : ''} ${dotHtml}</div>
            <div class="vital-label">${v.label}</div>
          </div>`;
      }).join('');
    })();

    // --- Consistency ---
    document.getElementById('bedVar').textContent = S.bedtime_var_7d + ' min';
    document.getElementById('bedVarDot').className = `status-dot status-dot-${getStatusClass(S.bedtime_var_7d, 'bedtime_var')}`;
    document.getElementById('wakeVar').textContent = S.wake_var_7d + ' min';
    document.getElementById('wakeVarDot').className = `status-dot status-dot-${getStatusClass(S.wake_var_7d, 'wake_var')}`;

    // --- Notes ---
    if (S.notes) {
      document.getElementById('notesCard').style.display = 'block';
      document.getElementById('sleepNotes').textContent = S.notes;
    }

    // --- 7-Day Trend ---
    (function() {
      const hist = SAMPLE_DATA.history.slice(-7);
      const scores = hist.map(d => d.sleep_score);
      const min = Math.min(...scores) - 5;
      const max = Math.max(...scores) + 5;
      const w = 340, h = 100, pad = 10;

      const points = scores.map((s, i) => {
        const x = pad + (i / (scores.length - 1)) * (w - 2 * pad);
        const y = h - pad - ((s - min) / (max - min)) * (h - 2 * pad);
        return { x, y, s };
      });

      // Threshold zones
      const yGreen = h - pad - ((80 - min) / (max - min)) * (h - 2 * pad);
      const yYellow = h - pad - ((65 - min) / (max - min)) * (h - 2 * pad);

      let svg = '';
      // Green zone
      svg += `<rect x="${pad}" y="0" width="${w-2*pad}" height="${Math.max(0,yGreen)}" fill="rgba(34,197,94,0.06)" rx="4"/>`;
      // Yellow zone
      svg += `<rect x="${pad}" y="${yGreen}" width="${w-2*pad}" height="${Math.max(0,yYellow-yGreen)}" fill="rgba(245,158,11,0.06)" rx="0"/>`;
      // Red zone
      svg += `<rect x="${pad}" y="${yYellow}" width="${w-2*pad}" height="${h-yYellow-pad}" fill="rgba(248,113,113,0.06)" rx="4"/>`;

      // Threshold lines
      svg += `<line x1="${pad}" y1="${yGreen}" x2="${w-pad}" y2="${yGreen}" stroke="var(--status-green)" stroke-width="0.5" stroke-dasharray="4"/>`;
      svg += `<line x1="${pad}" y1="${yYellow}" x2="${w-pad}" y2="${yYellow}" stroke="var(--status-yellow)" stroke-width="0.5" stroke-dasharray="4"/>`;

      // Line
      const linePath = points.map((p, i) => (i === 0 ? 'M' : 'L') + p.x + ',' + p.y).join(' ');
      svg += `<path d="${linePath}" fill="none" stroke="var(--primary)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>`;

      // Points
      points.forEach(p => {
        const color = getStatusColor(p.s, 'sleep_analysis_score');
        svg += `<circle cx="${p.x}" cy="${p.y}" r="5" fill="${color}" stroke="white" stroke-width="2"/>`;
      });

      document.getElementById('sleepTrendSvg').innerHTML = svg;

      // Labels
      document.getElementById('sleepTrendLabels').innerHTML = hist.map(d => {
        const date = new Date(d.date + 'T12:00:00');
        return `<span>${date.toLocaleDateString('en-US', { weekday: 'short' })}</span>`;
      }).join('');
    })();
    }

    function renderViewCalendar() {
    console.log('[calendar] initData resolved — history:', SAMPLE_DATA.history.length, 'days, error:', SAMPLE_DATA._error);

    // Show empty state if no history data
    if (SAMPLE_DATA.history.length === 0) {
      var calEmptyEl = document.getElementById('calMonths');
      calEmptyEl.textContent = '';
      var calEmptyDiv = document.createElement('div');
      calEmptyDiv.style.cssText = 'text-align:center;padding:48px 24px;color:var(--text-muted);';
      var calEmptyIcon = document.createElement('div');
      calEmptyIcon.style.cssText = 'font-size:40px;margin-bottom:16px;';
      calEmptyIcon.textContent = '\uD83D\uDCC5';
      var calEmptyTitle = document.createElement('div');
      calEmptyTitle.style.cssText = 'font-size:16px;font-weight:600;margin-bottom:8px;';
      calEmptyTitle.textContent = 'No Data Available';
      var calEmptyMsg = document.createElement('div');
      calEmptyMsg.style.cssText = 'font-size:13px;';
      calEmptyMsg.textContent = SAMPLE_DATA._error || 'Check your connection and try again';
      calEmptyDiv.appendChild(calEmptyIcon);
      calEmptyDiv.appendChild(calEmptyTitle);
      calEmptyDiv.appendChild(calEmptyMsg);
      calEmptyEl.appendChild(calEmptyDiv);
      return;
    }

    // Build date lookup
    SAMPLE_DATA.history.forEach(d => { calDateMap[d.date] = d; });

    // ============================================
    // Metric pills
    // ============================================

    (function renderCalPills() {
      document.getElementById('calMetricPills').innerHTML = calMetrics.map((m, i) =>
        `<div class="pill ${i === 0 ? 'pill-active' : ''}" data-cal-metric="${m.key}">${m.label}</div>`
      ).join('');
    })();

    // ============================================
    // Render calendar — oldest at top, scroll down to newest
    // ============================================

    const _now = new Date();
    const todayStr = _now.getFullYear() + '-' + String(_now.getMonth()+1).padStart(2,'0') + '-' + String(_now.getDate()).padStart(2,'0');
    const todayDate = new Date(_now.getFullYear(), _now.getMonth(), _now.getDate());

    const _activityTypeColor = { running: '#22C55E', cycling: '#3B82F6', swimming: '#06B6D4', strength: '#F59E0B', walking: '#A78BFA' };
    function _activityDots(sessions) {
      if (!sessions || sessions.length === 0) return '';
      const dots = sessions.slice(0, 3).map(s => {
        const c = _activityTypeColor[s.type] || 'var(--primary)';
        return `<span class="cal-activity-dot" style="background:${c}"></span>`;
      }).join('');
      return `<span class="cal-activity-dots">${dots}</span>`;
    }

    renderCalendar = function() {
      const container = document.getElementById('calMonths');
      const dayNames = ['S','M','T','W','T','F','S'];

      // Build months dynamically from history data range
      const months = [];
      if (SAMPLE_DATA.history.length > 0) {
        const firstDate = new Date(SAMPLE_DATA.history[0].date + 'T12:00:00');
        const lastDate = todayDate;
        let d = new Date(firstDate.getFullYear(), firstDate.getMonth(), 1);
        while (d <= lastDate) {
          const mNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];
          months.push({ year: d.getFullYear(), month: d.getMonth(), name: mNames[d.getMonth()] + ' ' + d.getFullYear() });
          d.setMonth(d.getMonth() + 1);
        }
      }

      let html = '';

      months.forEach((m, mi) => {
        if (mi > 0) html += '<div class="cal-divider"></div>';

        html += `<div class="cal-month">`;
        html += `<div class="cal-month-title">${m.name}</div>`;

        // Weekday headers
        html += `<div class="cal-weekday-row">`;
        dayNames.forEach((d, i) => {
          const isWeekend = i === 0 || i === 6;
          html += `<div class="cal-weekday${isWeekend ? ' weekend' : ''}">${d}</div>`;
        });
        html += `</div>`;

        // Calendar grid
        const daysInMonth = new Date(m.year, m.month + 1, 0).getDate();
        const firstDow = new Date(m.year, m.month, 1).getDay();

        html += `<div class="cal-grid">`;

        // Empty leading cells
        for (let i = 0; i < firstDow; i++) {
          html += `<div class="cal-day cal-day-empty"></div>`;
        }

        // Day cells
        for (let d = 1; d <= daysInMonth; d++) {
          const dateStr = `${m.year}-${String(m.month + 1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
          const thisDate = new Date(m.year, m.month, d);
          const isFuture = thisDate > todayDate;
          const isToday = dateStr === todayStr;
          const record = calDateMap[dateStr];

          if (isFuture) {
            // Don't render future days
            html += `<div class="cal-day cal-day-empty"></div>`;
          } else if (record) {
            const val = record[currentCalMetric.field];
            const color = getStatusColor(val, currentCalMetric.threshold);
            const textColor = isLightColor(color) ? '#333' : '#fff';
            const dots = _activityDots(record.sessions);
            html += `<div class="cal-day${isToday ? ' cal-day-today' : ''}" style="background:${color};color:${textColor}" data-cal-date="${dateStr}">
              ${d}${dots}
            </div>`;
          } else {
            html += `<div class="cal-day cal-day-nodata${isToday ? ' cal-day-today' : ''}">
              ${d}
            </div>`;
          }
        }

        html += `</div></div>`;
      });

      container.innerHTML = html;

      // Scroll to bottom (current month) on load
      requestAnimationFrame(() => {
        const scroll = document.getElementById('calScroll');
        scroll.scrollTop = scroll.scrollHeight;
      });
    };

    // Determine if a color is light (for text contrast)
    function isLightColor(hslStr) {
      const match = hslStr.match(/hsl\(([\d.]+),\s*([\d.]+)%,\s*([\d.]+)%\)/);
      if (!match) return true;
      return parseFloat(match[3]) > 55;
    }

    // ============================================
    // Day detail bottom sheet
    // ============================================

    showDetail = function(dateStr) {
      const record = calDateMap[dateStr];
      if (!record) return;

      const date = new Date(dateStr + 'T12:00:00');
      const dateLabel = date.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
      document.getElementById('detailDate').textContent = dateLabel;

      const items = [
        { label: 'Readiness', value: record.readiness, threshold: 'readiness_score', suffix: '/10' },
        { label: 'Sleep Score', value: record.sleep_score, threshold: 'sleep_analysis_score', suffix: '' },
        { label: 'Total Sleep', value: record.total_sleep, threshold: 'total_sleep_hrs', suffix: 'h' },
        { label: 'HRV', value: record.hrv, threshold: 'overnight_hrv_ms', suffix: ' ms' },
        { label: 'Resting HR', value: record.rhr, threshold: 'resting_hr', suffix: ' bpm' },
        { label: 'Body Battery', value: record.body_battery, threshold: 'body_battery', suffix: '' },
        { label: 'Steps', value: record.steps, threshold: 'steps', suffix: '', format: v => v != null ? v.toLocaleString() : '--' },
        { label: 'Stress', value: record.stress, threshold: 'avg_stress_level', suffix: '' },
        { label: 'Habits', value: record.habits, threshold: 'habits_total', suffix: '/7' },
        { label: 'Cognition', value: record.cognition, threshold: 'cognition', suffix: '/10' },
        { label: 'Day Rating', value: record.day_rating, threshold: 'day_rating', suffix: '/10' },
        { label: 'AM Energy', value: record.morning_energy, threshold: 'morning_energy', suffix: '/10' },
      ];

      let html = '<div class="cal-detail-grid">';
      items.forEach(item => {
        const color = getStatusColor(item.value, item.threshold);
        const displayVal = item.format ? item.format(item.value) : item.value;
        html += `<div class="cal-detail-item">
          <div class="cal-detail-label">${item.label}</div>
          <div class="cal-detail-value" style="color:${color}">${displayVal}${item.suffix}</div>
        </div>`;
      });
      html += '</div>';

      // Activity section — mirrors Activity tab session card layout
      if (record.sessions && record.sessions.length > 0) {
        const _typeIcons = { running: '&#127939;', cycling: '&#128690;', swimming: '&#127946;', strength: '&#127947;', walking: '&#128694;' };
        html += '<div style="margin-top:var(--space-lg);border-top:1px solid var(--border);padding-top:var(--space-md)">';
        html += '<div style="font-size:var(--text-sm);font-weight:700;color:var(--text-secondary);margin-bottom:var(--space-sm)">Activities</div>';
        record.sessions.forEach(s => {
          const icon = _typeIcons[s.type] || '&#9889;';
          const dur = s.duration_min ? Math.round(s.duration_min) + ' min' : '';
          const dist = s.distance_mi ? s.distance_mi.toFixed(1) + ' mi' : '';
          const subtitle = [dur, dist].filter(Boolean).join(' \u00B7 ');
          html += `<div style="background:var(--card-bg);border-radius:var(--radius-lg);padding:var(--space-md);margin-bottom:var(--space-sm)">
            <div style="display:flex;align-items:center;justify-content:space-between">
              <div style="display:flex;align-items:center;gap:var(--space-sm)">
                <div style="width:36px;height:36px;border-radius:var(--radius-md);background:var(--primary-bg);display:flex;align-items:center;justify-content:center;font-size:18px">${icon}</div>
                <div>
                  <div style="font-size:var(--text-base);font-weight:600">${escapeHtml(s.activity_name)}</div>
                  <div style="font-size:var(--text-xs);color:var(--text-muted)">${subtitle}</div>
                </div>
              </div>
              <div style="text-align:right">
                <div style="font-size:var(--text-lg);font-weight:700;color:var(--primary)">${s.calories || '--'}</div>
                <div style="font-size:var(--text-xs);color:var(--text-muted)">calories</div>
              </div>
            </div>
            <div style="display:flex;justify-content:space-around;margin-top:var(--space-md);padding-top:var(--space-sm);border-top:1px solid var(--border)">
              <div style="text-align:center">
                <div style="font-size:var(--text-base);font-weight:600">${s.avg_hr || '--'}</div>
                <div style="font-size:var(--text-xs);color:var(--text-muted)">Avg HR</div>
              </div>
              <div style="text-align:center">
                <div style="font-size:var(--text-base);font-weight:600">${s.max_hr || '--'}</div>
                <div style="font-size:var(--text-xs);color:var(--text-muted)">Max HR</div>
              </div>
              <div style="text-align:center">
                <div style="font-size:var(--text-base);font-weight:600">${dist || '--'}</div>
                <div style="font-size:var(--text-xs);color:var(--text-muted)">Distance</div>
              </div>
            </div>
          </div>`;
        });
        html += '</div>';
      }

      document.getElementById('detailContent').innerHTML = html;
      document.getElementById('detailOverlay').classList.add('visible');
    };

    // Swipe-to-dismiss on the detail sheet
    (function() {
      let startY = 0, currentY = 0, isDragging = false;
      const overlay = document.getElementById('detailOverlay');

      overlay.addEventListener('touchstart', function(e) {
        const sheet = document.querySelector('.cal-detail-sheet');
        // Only start drag if sheet is scrolled to top or touching the handle area
        if (sheet.scrollTop <= 0) {
          startY = e.touches[0].clientY;
          currentY = startY;
          isDragging = true;
          sheet.style.transition = 'none';
        }
      }, { passive: true });

      overlay.addEventListener('touchmove', function(e) {
        if (!isDragging) return;
        currentY = e.touches[0].clientY;
        const dy = currentY - startY;
        if (dy > 0) {
          const sheet = document.querySelector('.cal-detail-sheet');
          sheet.style.transform = 'translateY(' + dy + 'px)';
          e.preventDefault();
        }
      }, { passive: false });

      overlay.addEventListener('touchend', function() {
        if (!isDragging) return;
        isDragging = false;
        const dy = currentY - startY;
        const sheet = document.querySelector('.cal-detail-sheet');
        sheet.style.transition = 'transform 0.25s ease';
        if (dy > 80) {
          dismissSheet();
        } else {
          sheet.style.transform = '';
        }
      }, { passive: true });
    })();

    // ============================================
    // Initial render
    // ============================================

    renderCalendar();
    console.log('[calendar] renderCalendar done');
    }

    // ============================================
    // Auth Button (dynamic Sign In / Sign Out)
    // ============================================
    function _updateAuthButton() {
      const btn = document.getElementById('auth-menu-btn');
      const label = document.getElementById('auth-menu-label');
      if (!btn || !label) return;
      if (isAuthenticated()) {
        label.textContent = 'Sign Out';
        label.style.color = '#F87171';
        btn.onclick = async () => { await logout(); _updateAuthButton(); };
      } else {
        label.textContent = 'Sign In';
        label.style.color = '#8B5CF6';
        btn.onclick = async () => { await requireAuth(); _updateAuthButton(); };
      }
    }
    // Listen for logout events to update button
    window.addEventListener('ht-auth-logout', () => _updateAuthButton());
    window.addEventListener('ht-auth-ready', () => _updateAuthButton());

    // ============================================
    // Boot Sequence
    // ============================================
    window._dataReady = false;

    initData().then(() => {
      window._dataReady = true;
      const hash = location.hash.replace('#', '') || 'today';
      renderView(hash === 'today' ? 'today' : hash);
      if (hash !== 'today') {
        navigate(hash);
      } else {
        updateTabBar('today');
        viewRendered['today'] = true;
      }
      // Update auth button state
      _updateAuthButton();
    }).catch(err => {
      console.error('[SPA] initData failed:', err);
    });

    // ============================================
    // Event Listeners (replaces all inline handlers)
    // ============================================
    // Script is loaded at end of <body> so DOM is already ready; run immediately.
    (function () {

      // --- Day navigation arrows ---
      document.getElementById('dayNavPrev').addEventListener('click', function () { navDay(-1); });
      document.getElementById('dayNavNext').addEventListener('click', function () { navDay(1); });

      // --- Readiness card expand (delegate from #view-today) ---
      document.getElementById('view-today').addEventListener('click', function (e) {
        const card = e.target.closest('[data-action="toggle-expand"]');
        if (card) toggleExpand(card);
      });

      // --- Sleep card navigate to sleep view ---
      document.getElementById('sleepCard').addEventListener('click', function () { navigate('sleep'); });

      // --- Trends range pills (delegate from #rangePills) ---
      document.getElementById('rangePills').addEventListener('click', function (e) {
        const pill = e.target.closest('[data-range]');
        if (pill) setRange(parseInt(pill.dataset.range), pill);
      });

      // --- Trends/calendar month nav arrows (delegate from document) ---
      document.addEventListener('click', function (e) {
        const arrow = e.target.closest('[data-cal-nav]');
        if (arrow) navigateCalMonth(parseInt(arrow.dataset.calNav));
      });

      // --- Log hub: category cards ---
      document.getElementById('hubView').addEventListener('click', function (e) {
        const card = e.target.closest('[data-form]');
        if (card) showForm(card.dataset.form);
      });

      // --- Log forms: back buttons ---
      document.getElementById('view-log').addEventListener('click', function (e) {
        if (e.target.closest('[data-action="show-hub"]')) showHub();
      });

      // --- Form save buttons ---
      document.getElementById('saveMorningBtn').addEventListener('click', function () {
        saveForm('morning', 'Morning check-in saved');
      });
      document.getElementById('saveMiddayBtn').addEventListener('click', function () {
        saveForm('midday', 'Midday check-in saved');
      });
      document.getElementById('saveEveningBtn').addEventListener('click', function () {
        saveForm('evening', 'Evening review saved');
      });
      document.getElementById('saveNutritionBtn').addEventListener('click', function () {
        saveForm('nutrition', 'Nutrition saved');
      });
      document.getElementById('saveCognitionBtn').addEventListener('click', function () {
        saveForm('cognition', 'Cognition saved');
      });
      document.getElementById('saveSleepNotesBtn').addEventListener('click', function () {
        saveForm('sleep_notes', 'Sleep notes saved');
      });

      // --- Sliders: delegate from #view-log ---
      document.getElementById('view-log').addEventListener('input', function (e) {
        const el = e.target;
        if (el.tagName !== 'INPUT' || el.type !== 'range') return;
        if (el.dataset.sliderInverted) {
          updateSliderInverted(el, el.dataset.sliderTarget);
        } else if (el.dataset.sliderTarget) {
          updateSlider(el, el.dataset.sliderTarget, el.dataset.sliderMetric);
        } else if (el.id === 'rpeSlider' && el.dataset.rpeDisplay) {
          document.getElementById(el.dataset.rpeDisplay).textContent = el.value;
        }
      });

      // --- Cognition stepper ---
      document.getElementById('cognitionDown').addEventListener('click', function () { stepCognition(-1); });
      document.getElementById('cognitionUp').addEventListener('click', function () { stepCognition(1); });

      // --- Activity segment control ---
      document.getElementById('segSessions').addEventListener('click', function () { showView('sessions'); });
      document.getElementById('segStrength').addEventListener('click', function () { showView('strength'); });

      // --- Add exercise toggle ---
      document.getElementById('addBtn').addEventListener('click', toggleAddForm);
      document.getElementById('doneAddFormBtn').addEventListener('click', toggleAddForm);
      document.getElementById('addSetBtn').addEventListener('click', addStrengthSet);

      // --- Muscle group pills (delegate from #muscleGroupPills) ---
      document.getElementById('muscleGroupPills').addEventListener('click', function (e) {
        const pill = e.target.closest('.pill');
        if (pill) selectPill(pill);
      });

      // --- Stepper buttons (delegate from #addForm) ---
      document.getElementById('addForm').addEventListener('click', function (e) {
        const btn = e.target.closest('[data-step-target]');
        if (btn) stepValue(btn.dataset.stepTarget, parseInt(btn.dataset.stepDelta));
      });

      // --- RPE slider ---
      document.getElementById('rpeSlider').addEventListener('input', function () {
        document.getElementById('rpeDisplay').textContent = this.value;
      });

      // --- Profile menu items with data-nav ---
      document.getElementById('view-profile').addEventListener('click', function (e) {
        const item = e.target.closest('[data-nav]');
        if (item) { navigate(item.dataset.nav); return; }
        const alertItem = e.target.closest('[data-alert]');
        if (alertItem) { alert(alertItem.dataset.alert); return; }
        if (e.target.closest('[data-action="toggle-notifications"]')) {
          toggleNotifications(e.target.closest('[data-action="toggle-notifications"]'));
        }
      });

      // --- Sleep detail nav back ---
      document.getElementById('view-sleep').addEventListener('click', function (e) {
        if (e.target.closest('[data-nav="today"]')) navigate('today');
      });

      // --- Calendar view back ---
      document.getElementById('view-calendar').addEventListener('click', function (e) {
        if (e.target.closest('[data-nav="profile"]')) navigate('profile');
      });

      // --- Tab bar (delegate from #tabBar) ---
      document.getElementById('tabBar').addEventListener('click', function (e) {
        const tabItem = e.target.closest('.tab-item');
        if (!tabItem) return;
        // Center log button uses data-nav
        if (tabItem.dataset.nav) { navigate(tabItem.dataset.nav); return; }
        // Regular tabs use data-view
        if (tabItem.dataset.view) navigate(tabItem.dataset.view);
      });

      // --- Calendar day detail overlay ---
      document.getElementById('detailOverlay').addEventListener('click', function (e) {
        if (e.target === this) dismissSheet();
      });
      document.getElementById('calDetailSheet').addEventListener('click', function (e) {
        e.stopPropagation();
      });
      document.getElementById('calDetailHandle').addEventListener('click', dismissSheet);

      // --- Session detail overlay ---
      document.getElementById('sessionDetailOverlay').addEventListener('click', function (e) {
        if (e.target === this) dismissSessionDetail();
      });
      document.getElementById('sessionDetailSheet').addEventListener('click', function (e) {
        e.stopPropagation();
      });
      document.getElementById('sessionDetailHandle').addEventListener('click', dismissSessionDetail);

      // --- Metric pills in Trends view (delegate from #metricPills — dynamically rendered) ---
      document.getElementById('metricPills').addEventListener('click', function (e) {
        const pill = e.target.closest('[data-metric]');
        if (pill) setMetric(pill.dataset.metric, pill);
      });

      // --- Calendar metric pills (delegate from #calMetricPills — dynamically rendered) ---
      document.getElementById('calMetricPills').addEventListener('click', function (e) {
        const pill = e.target.closest('[data-cal-metric]');
        if (pill) setCalMetric(pill.dataset.calMetric, pill);
      });

      // --- Calendar day cells (delegate from #calMonths — dynamically rendered) ---
      document.getElementById('calMonths').addEventListener('click', function (e) {
        const day = e.target.closest('[data-cal-date]');
        if (day) showDetail(day.dataset.calDate);
      });

      // --- Week session rows (delegate from #weekSessions — dynamically rendered) ---
      document.getElementById('weekSessions').addEventListener('click', function (e) {
        const row = e.target.closest('[data-session-idx]');
        if (row) showSessionDetail(parseInt(row.dataset.sessionIdx));
      });

      // --- Habit toggle switches (delegate from #view-log for renderHabits output) ---
      document.getElementById('view-log').addEventListener('click', function (e) {
        const toggle = e.target.closest('[data-action="toggle-self"]');
        if (toggle) toggle.classList.toggle('active');
      });

    }());
