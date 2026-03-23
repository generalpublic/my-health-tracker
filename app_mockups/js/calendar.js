// --- Navigation helper ---
    function navigateTo(page) { window.location.href = page; }
    function setCalMetric(key, el) {
      currentCalMetric = calMetrics.find(m => m.key === key);
      document.querySelectorAll('#calMetricPills .pill').forEach(p => p.classList.remove('pill-active'));
      el.classList.add('pill-active');
      renderCalendar();
    }
    function closeDetail(e) {
      if (e.target === document.getElementById('detailOverlay')) {
        dismissSheet();
      }
    }
    function dismissSheet() {
      const sheet = document.querySelector('.cal-detail-sheet');
      sheet.style.transform = 'translateY(100%)';
      setTimeout(() => {
        document.getElementById('detailOverlay').classList.remove('visible');
        sheet.style.transform = '';
      }, 250);
    }

    // --- Metrics ---
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

    // Declare globals used by onclick handlers
    var dateMap = {};
    var renderCalendar, showDetail;

    // --- Render after data loads ---
    initData().then(() => {

    console.log('[calendar] initData resolved — history:', SAMPLE_DATA.history.length, 'days, error:', SAMPLE_DATA._error);

    // Show empty state if no history data
    if (SAMPLE_DATA.history.length === 0) {
      var emptyEl = document.getElementById('calMonths');
      emptyEl.textContent = '';
      var emptyDiv = document.createElement('div');
      emptyDiv.style.cssText = 'text-align:center;padding:48px 24px;color:var(--text-muted);';
      var emptyIcon = document.createElement('div');
      emptyIcon.style.cssText = 'font-size:40px;margin-bottom:16px;';
      emptyIcon.textContent = '\uD83D\uDCC5';
      var emptyTitle = document.createElement('div');
      emptyTitle.style.cssText = 'font-size:16px;font-weight:600;margin-bottom:8px;';
      emptyTitle.textContent = 'No Data Available';
      var emptyMsg = document.createElement('div');
      emptyMsg.style.cssText = 'font-size:13px;';
      emptyMsg.textContent = SAMPLE_DATA._error || 'Check your connection and try again';
      emptyDiv.appendChild(emptyIcon);
      emptyDiv.appendChild(emptyTitle);
      emptyDiv.appendChild(emptyMsg);
      emptyEl.appendChild(emptyDiv);
      return;
    }

    // Build date lookup
    SAMPLE_DATA.history.forEach(d => { dateMap[d.date] = d; });

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
          const record = dateMap[dateStr];

          if (isFuture) {
            // Don't render future days
            html += `<div class="cal-day cal-day-empty"></div>`;
          } else if (record) {
            const val = record[currentCalMetric.field];
            const color = getStatusColor(val, currentCalMetric.threshold);
            const textColor = isLightColor(color) ? '#333' : '#fff';
            html += `<div class="cal-day${isToday ? ' cal-day-today' : ''}" style="background:${color};color:${textColor}" data-cal-date="${dateStr}">
              ${d}
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
      const record = dateMap[dateStr];
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

    }).catch(err => {
      console.error('[calendar] Rendering error:', err);
      var errContainer = document.getElementById('calMonths');
      errContainer.textContent = '';
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
      errContainer.appendChild(errDiv);
    }); // end initData().then()

// --- Event listeners (DOM ready) ---
document.addEventListener('DOMContentLoaded', function() {
  // Back button
  document.querySelector('.cal-back').addEventListener('click', function() {
    navigateTo('profile.html');
  });

  // Detail overlay backdrop — close on click outside sheet
  document.getElementById('detailOverlay').addEventListener('click', function(e) {
    closeDetail(e);
  });

  // Detail sheet — stop propagation so clicks inside don't close
  document.querySelector('.cal-detail-sheet').addEventListener('click', function(e) {
    e.stopPropagation();
  });

  // Handle — dismiss sheet
  document.querySelector('.cal-detail-handle').addEventListener('click', function() {
    dismissSheet();
  });

  // Metric pills — delegate from #calMetricPills
  document.getElementById('calMetricPills').addEventListener('click', function(e) {
    var pill = e.target.closest('[data-cal-metric]');
    if (pill) setCalMetric(pill.getAttribute('data-cal-metric'), pill);
  });

  // Calendar day cells — delegate from .cal-scroll for dynamically rendered days
  document.querySelector('.cal-scroll').addEventListener('click', function(e) {
    var day = e.target.closest('[data-cal-date]');
    if (day) showDetail(day.getAttribute('data-cal-date'));
  });
});