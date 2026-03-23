    // ============================================
    // Populate Today Dashboard from live data
    // ============================================

    // --- State ---
    window.currentViewDate = null; // set after initData
    window.habitState = {}; // tracks current toggle state for the viewed date

    const HABITS = [
      { key: 'wake_930', label: 'Wake', icon: '&#9788;' },
      { key: 'no_morning_screens', label: 'No AM', icon: '&#128241;' },
      { key: 'creatine_hydrate', label: 'Hydrate', icon: '&#128167;' },
      { key: 'walk_breathing', label: 'Walk', icon: '&#127939;' },
      { key: 'physical_activity', label: 'Active', icon: '&#9889;' },
      { key: 'no_screens_bed', label: 'No PM', icon: '&#128564;' },
      { key: 'bed_10pm', label: 'Bed 10', icon: '&#127769;' }
    ];

    // --- Helpers ---
    function toggleExpand(card) {
      const expand = card.querySelector('.card-expand-content');
      const chevron = card.querySelector('.card-chevron');
      if (expand) {
        expand.classList.toggle('expanded');
        if (chevron) chevron.classList.toggle('expanded');
      }
    }

    function navigateTo(page) { window.location.href = page; }

    function formatHours(hrs) {
      const h = Math.floor(hrs);
      const m = Math.round((hrs - h) * 60);
      return h + 'h ' + m + 'm';
    }

    function formatTime(time24) {
      if (!time24 || !time24.includes(':')) return '--';
      const [h, m] = time24.split(':').map(Number);
      const ampm = h >= 12 ? 'PM' : 'AM';
      const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
      return h12 + ':' + String(m).padStart(2, '0') + ' ' + ampm;
    }

    function _formatDateLabel(dateStr) {
      const d = new Date(dateStr + 'T12:00:00');
      const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
      const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      return days[d.getDay()] + ', ' + months[d.getMonth()] + ' ' + d.getDate();
    }

    function _shiftDate(dateStr, days) {
      const d = new Date(dateStr + 'T12:00:00');
      d.setDate(d.getDate() + days);
      return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }

    // ============================================
    // Date Navigation
    // ============================================

    function updateDateUI() {
      const today = _todayStr();
      const isToday = window.currentViewDate === today;
      document.getElementById('dateLabel').textContent = isToday ? 'Today' : _formatDateLabel(window.currentViewDate);
      document.getElementById('dateTodayLink').style.display = isToday ? 'none' : 'block';
      document.getElementById('dateNext').classList.toggle('disabled', isToday);
    }

    async function navigateDate(delta) {
      if (delta === 0) {
        window.currentViewDate = _todayStr();
      } else {
        window.currentViewDate = _shiftDate(window.currentViewDate, delta);
      }
      // Don't allow future dates
      if (window.currentViewDate > _todayStr()) {
        window.currentViewDate = _todayStr();
      }
      updateDateUI();

      // Fetch and re-render
      const newData = await fetchToday(window.currentViewDate);
      SAMPLE_DATA.today = newData;
      renderAll(newData);
    }

    // ============================================
    // Habit Toggle
    // ============================================

    function toggleHabit(index) {
      if (window.currentViewDate !== _todayStr()) return;
      const h = HABITS[index];
      const newVal = !window.habitState[h.key];
      window.habitState[h.key] = newVal;

      // Update circle visually
      const circle = document.querySelectorAll('#habitsRow .habit-circle')[index];
      if (circle) {
        circle.className = 'habit-circle ' + (newVal ? 'habit-circle-done' : 'habit-circle-pending');
        circle.innerHTML = newVal ? '&#10003;' : h.icon;
        // Tap animation
        circle.classList.add('habit-tap');
        setTimeout(() => circle.classList.remove('habit-tap'), 400);
      }

      // Update count
      const total = HABITS.filter(hab => window.habitState[hab.key]).length;
      document.getElementById('habitsCount').textContent = total + '/7';

      // Save to Supabase (debounced)
      if (typeof saveHabitToggle === 'function') {
        saveHabitToggle(window.currentViewDate, h.key, newVal, total);
      }
    }

    // ============================================
    // Render Functions
    // ============================================

    function renderAll(D) {
      renderIllnessBanner(D);
      renderReadiness(D);
      renderSleep(D);
      renderBody(D);
      renderHabits(D);
      renderActivity(D);
      renderInsights(D);
    }

    function renderIllnessBanner(D) {
      const banner = document.getElementById('illnessBanner');
      if (!banner) return;
      const illness = (D.illness) || {};
      const label = illness.label || 'normal';
      if (label === 'normal') {
        banner.style.display = 'none';
        return;
      }
      banner.style.display = 'block';
      const titleEl = document.getElementById('illnessBannerTitle');
      const subtitleEl = document.getElementById('illnessBannerSubtitle');
      const confirmBtn = document.getElementById('btnConfirmSick');
      const recoverBtn = document.getElementById('btnConfirmRecovery');
      if (label === 'illness_ongoing' || label === 'likely_illness') {
        titleEl.textContent = 'Illness Mode Active';
        subtitleEl.textContent = 'Low readiness scores are expected during recovery';
        confirmBtn.style.display = illness.confirmed ? 'none' : 'block';
        recoverBtn.style.display = 'block';
      } else if (label === 'recovering') {
        titleEl.textContent = 'Recovering';
        subtitleEl.textContent = 'Biometrics stabilizing. Confirm when you feel better.';
        confirmBtn.style.display = 'none';
        recoverBtn.style.display = 'block';
      } else if (label === 'possible_illness') {
        titleEl.textContent = 'Feeling off?';
        subtitleEl.textContent = 'Your biometrics look unusual -- pay attention to how you feel';
        confirmBtn.style.display = 'block';
        recoverBtn.style.display = 'none';
      }
    }

    async function confirmIllness() {
      try {
        if (typeof supabaseMutate === 'function') {
          await supabaseMutate('illness_state', {
            onset_date: _todayStr(),
            confirmed_date: new Date().toISOString(),
          }, 'onset_date');
        }
        document.getElementById('btnConfirmSick').style.display = 'none';
        document.getElementById('btnConfirmRecovery').style.display = 'block';
        document.getElementById('illnessBannerTitle').textContent = 'Illness Confirmed';
        document.getElementById('illnessBannerSubtitle').textContent = 'Rest and recover. Tap "I\'m better" when ready.';
      } catch (e) { console.error('[illness] confirm failed:', e); }
    }

    async function confirmRecovery() {
      try {
        if (typeof supabaseMutate === 'function') {
          await supabaseMutate('illness_state', {
            onset_date: SAMPLE_DATA.today.illness?.onset_date || _todayStr(),
            resolved_date: new Date().toISOString(),
            resolution_method: 'user_confirmed',
          }, 'onset_date');
        }
        document.getElementById('illnessBanner').style.display = 'none';
      } catch (e) { console.error('[illness] recovery failed:', e); }
    }

    function renderReadiness(D) {
      try {
        const score = (D.readiness && D.readiness.score) || 0;
        const color = getStatusColor(score, 'readiness_score');

        const r = 56, sw = 13, w = 140;
        const circ = 2 * Math.PI * r;
        const offset = circ * (1 - score / 10);
        const svg = document.getElementById('readinessGaugeSvg');
        svg.innerHTML = `
          <circle cx="${w/2}" cy="${w/2}" r="${r}" class="gauge-track" stroke-width="${sw}" />
          <circle cx="${w/2}" cy="${w/2}" r="${r}" class="gauge-fill"
            stroke="${color}" stroke-width="${sw}"
            stroke-dasharray="${circ}" stroke-dashoffset="${offset}"
            stroke-linecap="round" />`;
        document.getElementById('readinessScore').textContent = score > 0 ? score.toFixed(1) : '--';
        document.getElementById('readinessScore').style.color = score > 0 ? color : '#94A3B8';

        const labelEl = document.getElementById('readinessLabel');
        if (D.readiness && D.readiness.label) {
          const cls = getStatusClass(score, 'readiness_score');
          labelEl.className = `status-pill status-pill-${cls}`;
          labelEl.textContent = D.readiness.label;
        } else {
          labelEl.className = 'status-pill';
          labelEl.textContent = 'No Data';
        }

        const conf = (D.readiness && D.readiness.confidence) || '';
        document.getElementById('readinessConfidence').textContent = conf ? conf + ' Confidence' : '';

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

        const flags = (briefing.flags || []);
        document.getElementById('flagsList').innerHTML = flags.map(f =>
          `<div class="flag-item"><div class="flag-bullet"></div><span>${escapeHtml(f)}</span></div>`
        ).join('');

        const doItems = (briefing.do_items || []);
        document.getElementById('doList').innerHTML = doItems.map(d =>
          `<div class="do-item"><div class="do-icon"></div><span>${escapeHtml(d)}</span></div>`
        ).join('');
      } catch (e) {
        console.error('[today] Readiness render failed:', e);
        document.getElementById('readinessScore').textContent = '--';
      }
    }

    function renderSleep(D) {
      const s = D.sleep;
      const targets = SAMPLE_DATA.sleep_stage_targets;

      document.getElementById('sleepScore').textContent = s.analysis_score;
      const scoreColor = getStatusColor(s.analysis_score, 'sleep_analysis_score');
      document.getElementById('sleepScore').style.color = scoreColor;
      const verdict = document.getElementById('sleepVerdict');
      verdict.className = 'status-pill';
      verdict.style.color = scoreColor;
      verdict.style.background = `linear-gradient(135deg, ${scoreColor}1F, ${scoreColor}0F)`;
      verdict.style.border = `1px solid ${scoreColor}33`;
      verdict.textContent = s.sleep_feedback || '';
      verdict.style.fontWeight = '700';

      document.getElementById('totalSleep').textContent = formatHours(s.total_sleep_hrs);
      document.getElementById('bedtime').textContent = formatTime(s.bedtime);
      document.getElementById('wakeTime').textContent = formatTime(s.wake_time);

      const total = s.deep_min + s.light_min + s.rem_min + s.awake_min;
      const stages = [
        { min: s.deep_min, pct: s.deep_pct, color: 'var(--sleep-deep)' },
        { min: s.light_min, pct: total ? Math.round(s.light_min / total * 100) : 0, color: 'var(--sleep-light)' },
        { min: s.rem_min, pct: s.rem_pct, color: 'var(--sleep-rem)' },
        { min: s.awake_min, pct: total ? Math.round(s.awake_min / total * 100) : 0, color: 'var(--sleep-awake)' }
      ];
      const bar = document.getElementById('sleepStagesBar');
      bar.innerHTML = total ? stages.map(st => {
        const widthPct = (st.min / total * 100).toFixed(1);
        const showLabel = widthPct > 12;
        return `<div class="sleep-stage" style="width:${widthPct}%;background:${st.color}">
          ${showLabel ? `<span class="sleep-stage-pct">${st.pct}%</span>` : ''}
        </div>`;
      }).join('') : '';

      const totalMin = Math.round(s.total_sleep_hrs * 60);
      const deepTarget = Math.round(totalMin * targets.deep_pct / 100);
      const remTarget = Math.round(totalMin * targets.rem_pct / 100);
      const lightTarget = totalMin - deepTarget - remTarget - targets.awake_max;
      const stageData = [
        { name: 'Deep', min: s.deep_min, target: deepTarget, color: 'var(--sleep-deep)' },
        { name: 'Light', min: s.light_min, target: lightTarget, color: 'var(--sleep-light)' },
        { name: 'REM', min: s.rem_min, target: remTarget, color: 'var(--sleep-rem)' },
        { name: 'Awake', min: s.awake_min, target: targets.awake_max, color: 'var(--sleep-awake)' }
      ];

      document.getElementById('sleepStagesDetail').innerHTML = stageData.map(st => {
        let barMax, fillPct, valueText;
        if (st.name === 'Light') {
          barMax = totalMin || 1;
          fillPct = (st.min / barMax * 100).toFixed(1);
          valueText = `${st.min}m`;
        } else if (st.name === 'Awake') {
          barMax = Math.max(st.target * 2, st.min) || 1;
          fillPct = (st.min / barMax * 100).toFixed(1);
          const met = st.min <= st.target;
          valueText = `${st.min}m / ${st.target}m ${met ? '<span style="color:var(--status-green)">&#10003;</span>' : ''}`;
        } else {
          barMax = Math.max(st.target, st.min) || 1;
          fillPct = (st.min / barMax * 100).toFixed(1);
          const met = st.min >= st.target;
          valueText = `${st.min}m / ${st.target}m ${met ? '<span style="color:var(--status-green)">&#10003;</span>' : ''}`;
        }
        return `<div class="stage-bar-row">
          <div class="stage-bar-label"><div class="stage-bar-dot" style="background:${st.color}"></div>${st.name}</div>
          <div class="stage-bar-track"><div class="stage-bar-fill" style="width:${fillPct}%;background:${st.color}"></div></div>
          <div class="stage-bar-value">${valueText}</div>
        </div>`;
      }).join('');

      document.getElementById('hrvValue').textContent = s.overnight_hrv;
      document.getElementById('hrvDot').className = `status-dot status-dot-${getStatusClass(s.overnight_hrv, 'overnight_hrv_ms')}`;
      document.getElementById('bbGained').textContent = '+' + s.body_battery_gained;
      document.getElementById('bbDot').className = `status-dot status-dot-${getStatusClass(s.body_battery_gained, 'body_battery_gained')}`;
      document.getElementById('awakenings').textContent = s.awakenings;

      const contextItems = D.briefing.sleep_context_items;
      document.getElementById('sleepContextStats').innerHTML = contextItems.map(item =>
        `<div class="context-stat">
          <span class="status-dot status-dot-${item.status}" style="width:6px;height:6px"></span>
          <span>${escapeHtml(item.label)}: <span class="context-stat-value">${escapeHtml(item.value)}</span></span>
        </div>`
      ).join('');
    }

    function renderBody(D) {
      const g = D.garmin;
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
          stroke="url(#bbGrad)" stroke-width="${sw}"
          stroke-dasharray="${circ}" stroke-dashoffset="${offset}"
          stroke-linecap="round" />`;
      document.getElementById('bbValue').style.color = bbColor;

      document.getElementById('rhrValue').textContent = g.resting_hr;
      document.getElementById('rhrDot').className = `status-dot status-dot-${getStatusClass(g.resting_hr, 'resting_hr')}`;
      document.getElementById('stressValue').textContent = g.avg_stress;
      document.getElementById('stressDot').className = `status-dot status-dot-${getStatusClass(g.avg_stress, 'avg_stress_level')}`;
      document.getElementById('hrv7dValue').textContent = g.hrv_7day_avg;

      const stepsColor = getStatusColor(g.steps, 'steps');
      document.getElementById('stepsValue').textContent = g.steps.toLocaleString();
      document.getElementById('stepsDot').className = `status-dot status-dot-${getStatusClass(g.steps, 'steps')}`;
      const pct = Math.min(g.steps / 10000 * 100, 100);
      const sbar = document.getElementById('stepsBar');
      sbar.style.width = pct + '%';
      sbar.style.background = stepsColor;
    }

    function renderHabits(D) {
      // Sync local state from loaded data
      window.habitState = {};
      HABITS.forEach(h => {
        window.habitState[h.key] = !!D.daily_log.habits[h.key];
      });

      const isToday = window.currentViewDate === _todayStr();
      const row = document.getElementById('habitsRow');
      row.innerHTML = HABITS.map((h, i) => {
        const done = window.habitState[h.key];
        const clickAttr = isToday ? `onclick="toggleHabit(${i})"` : '';
        const lockedClass = isToday ? '' : ' habit-circle-locked';
        return `
          <div class="habit-item">
            <div class="habit-circle ${done ? 'habit-circle-done' : 'habit-circle-pending'}${lockedClass}" ${clickAttr}>
              ${done ? '&#10003;' : h.icon}
            </div>
            <div class="habit-label">${h.label}</div>
          </div>`;
      }).join('');

      const total = HABITS.filter(h => window.habitState[h.key]).length;
      document.getElementById('habitsCount').textContent = total + '/7';
    }

    function renderActivity(D) {
      const sessions = D.sessions;
      const card = document.getElementById('activityCard');
      if (!sessions.length) {
        card.style.display = 'none';
        return;
      }
      card.style.display = '';

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
            <div style="width:${totalZone ? (s.zone_1_min/totalZone*100) : 0}%;background:var(--zone-1)"></div>
            <div style="width:${totalZone ? (s.zone_2_min/totalZone*100) : 0}%;background:var(--zone-2)"></div>
            <div style="width:${totalZone ? (s.zone_3_min/totalZone*100) : 0}%;background:var(--zone-3)"></div>
            <div style="width:${totalZone ? (s.zone_4_min/totalZone*100) : 0}%;background:var(--zone-4)"></div>
            <div style="width:${totalZone ? (s.zone_5_min/totalZone*100) : 0}%;background:var(--zone-5)"></div>
          </div>
          <div class="zone-labels">
            <span class="zone-label">Z1 ${s.zone_1_min}m</span>
            <span class="zone-label">Z2 ${s.zone_2_min}m</span>
            <span class="zone-label">Z3 ${s.zone_3_min}m</span>
            <span class="zone-label">Z4 ${s.zone_4_min}m</span>
            <span class="zone-label">Z5 ${s.zone_5_min}m</span>
          </div>`;
      }).join('');
    }

    function renderInsights(D) {
      const cap = s => s ? s.charAt(0).toUpperCase() + s.slice(1) : s;

      const insights = (D.readiness.key_insights || []).slice(0, 3);
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
      } else {
        recsSection.innerHTML = '';
      }
    }

    // ============================================
    // Init
    // ============================================

    initData().then(() => {
      const D = SAMPLE_DATA.today;
      window.currentViewDate = D.date || _todayStr();

      // Greeting
      const _name = (typeof USER_NAME !== 'undefined' && USER_NAME) ? USER_NAME : '';
      document.getElementById('greeting').textContent = 'Howdy, ' + (_name || '');

      updateDateUI();
      renderAll(D);

      // Show "Preliminary" badge if readiness_score is 0 but raw Garmin data exists
      if (D.readiness.score === 0 && D.garmin.steps > 0) {
        const est = estimateReadiness(D.garmin, D.sleep);
        if (est) {
          const scoreEl = document.querySelector('.readiness-score-value, .score-big');
          if (scoreEl) {
            scoreEl.textContent = est;
            scoreEl.insertAdjacentHTML('afterend',
              '<span class="preliminary-badge">Preliminary</span>');
          }
        }
      }
    });

    // ============================================
    // Pull-to-Refresh Gesture Handler
    // ============================================
    (function initPullToRefresh() {
      const content = document.getElementById('screenContent');
      const indicator = document.getElementById('ptrIndicator');
      const ptrText = document.getElementById('ptrText');
      if (!content || !indicator) return;

      let startY = 0;
      let pulling = false;
      const THRESHOLD = 80; // pixels to pull before triggering

      content.addEventListener('touchstart', (e) => {
        if (content.scrollTop <= 0) {
          startY = e.touches[0].clientY;
          pulling = true;
        }
      }, { passive: true });

      content.addEventListener('touchmove', (e) => {
        if (!pulling) return;
        const dy = e.touches[0].clientY - startY;
        if (dy > 10 && content.scrollTop <= 0) {
          indicator.classList.add('pulling');
          ptrText.textContent = dy > THRESHOLD ? 'Release to refresh' : 'Pull to refresh';
        }
      }, { passive: true });

      content.addEventListener('touchend', async () => {
        if (!pulling) return;
        pulling = false;

        if (indicator.classList.contains('pulling')) {
          const wasRelease = ptrText.textContent === 'Release to refresh';
          if (wasRelease) {
            // Trigger refresh via GitHub Actions
            indicator.classList.remove('pulling');
            indicator.classList.add('refreshing');
            ptrText.textContent = 'Starting sync...';

            const result = await triggerCloudRefresh();

            if (result.status === 'success') {
              ptrText.textContent = 'Fetching updated data...';
              await initData();
              ptrText.textContent = 'Data updated';
              setTimeout(() => {
                indicator.classList.remove('refreshing');
                location.reload();
              }, 1000);
            } else if (result.error && result.error.includes('not configured')) {
              ptrText.textContent = 'Cloud sync not configured yet';
              setTimeout(() => indicator.classList.remove('refreshing'), 2000);
            } else {
              ptrText.textContent = 'Sync failed — ' + (result.error || 'unknown error');
              setTimeout(() => indicator.classList.remove('refreshing'), 2000);
            }
          } else {
            indicator.classList.remove('pulling');
          }
        }
      });
    })();