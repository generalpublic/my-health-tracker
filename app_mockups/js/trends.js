    // --- Global functions for onclick handlers ---
    function navigateTo(page) { window.location.href = page; }
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

    // --- Metrics available for charting ---
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

    // Declare renderChart and renderHeatmap in outer scope so onclick handlers can call them
    let renderChart, renderHeatmap;

    // --- Date nav helpers (inline, self-contained) ---
    window.currentViewDate = null;

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

    function updateDateUI() {
      const today = _todayStr();
      const isToday = window.currentViewDate === today;
      const label = document.getElementById('dateLabel');
      const todayLink = document.getElementById('dateTodayLink');
      const nextBtn = document.getElementById('dateNext');
      if (label) label.textContent = isToday ? 'Today' : _formatDateLabel(window.currentViewDate);
      if (todayLink) todayLink.style.display = isToday ? 'none' : 'block';
      if (nextBtn) nextBtn.classList.toggle('disabled', isToday);
    }

    function trendNavigateDate(delta) {
      if (delta === 0) {
        window.currentViewDate = _todayStr();
      } else {
        window.currentViewDate = _shiftDate(window.currentViewDate, delta);
      }
      if (window.currentViewDate > _todayStr()) {
        window.currentViewDate = _todayStr();
      }
      updateDateUI();
      renderChart();
      renderHeatmap();
    }

    function getHistorySlice(range) {
      const endDate = window.currentViewDate || _todayStr();
      return SAMPLE_DATA.history.filter(d => d.date <= endDate).slice(-range);
    }

    // --- Render after data loads ---
    initData().then(() => {

    // ============================================
    // Render metric pills
    // ============================================

    (function renderPills() {
      document.getElementById('metricPills').innerHTML = metrics.map((m, i) =>
        `<div class="pill ${i === 0 ? 'pill-active' : ''}" data-metric="${m.key}" onclick="setMetric('${m.key}', this)">${m.label}</div>`
      ).join('');
    })();

    // ============================================
    // Render chart
    // ============================================

    renderChart = function() {
      const data = getHistorySlice(currentRange);
      const values = data.map(d => d[currentMetric.field]).filter(v => v != null && !isNaN(v));
      const t = SAMPLE_DATA.thresholds[currentMetric.threshold];

      if (!t || values.length === 0) {
        document.getElementById('trendChart').innerHTML = '<text x="170" y="90" text-anchor="middle" fill="#9CA3AF" font-size="14" font-family="system-ui">No data for this period</text>';
        document.getElementById('chartXLabels').innerHTML = '';
        ['statAvg','statBest','statWorst'].forEach(id => { document.getElementById(id).textContent = '--'; document.getElementById(id).style.color = ''; });
        const trendEl = document.getElementById('statTrend');
        trendEl.textContent = '--';
        trendEl.className = 'stat-trend trend-flat';
        return;
      }

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

      document.getElementById('trendChart').innerHTML = svg;

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

    // Initialize date nav
    window.currentViewDate = SAMPLE_DATA.today?.date || _todayStr();
    updateDateUI();

    renderChart();
    renderHeatmap();

    }).catch(err => {
      console.error('[trends] Init failed:', err);
    }); // end initData().then()