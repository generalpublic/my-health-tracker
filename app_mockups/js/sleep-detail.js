// --- Navigation helper ---
    function navigateTo(page) { window.location.href = page; }
    function formatTime(t) {
      const [h, m] = t.split(':').map(Number);
      return (h === 0 ? 12 : h > 12 ? h - 12 : h) + ':' + String(m).padStart(2,'0') + ' ' + (h >= 12 ? 'PM' : 'AM');
    }
    function formatHours(hrs) {
      return Math.floor(hrs) + 'h ' + Math.round((hrs % 1) * 60) + 'm';
    }

    // --- Render after data loads ---
    initData().then(() => {

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
          stroke="url(#sleepGrad)" stroke-width="${sw}"
          stroke-dasharray="${circ}" stroke-dashoffset="${offset}"
          stroke-linecap="round" />`;
      document.getElementById('heroScore').style.color = color;

      const cls = getStatusClass(score, 'sleep_analysis_score');
      const pill = document.getElementById('sleepVerdict');
      pill.className = `status-pill status-pill-${cls}`;
      pill.textContent = S.sleep_feedback;

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

      document.getElementById('trendChart').innerHTML = svg;

      // Labels
      document.getElementById('trendLabels').innerHTML = hist.map(d => {
        const date = new Date(d.date + 'T12:00:00');
        return `<span>${date.toLocaleDateString('en-US', { weekday: 'short' })}</span>`;
      }).join('');
    })();

    }); // end initData().then()

// --- Event listeners (DOM ready) ---
document.addEventListener('DOMContentLoaded', function() {
  // Back button
  document.querySelector('.nav-back').addEventListener('click', function() {
    navigateTo('today.html');
  });

  // Tab bar — delegate from .tab-bar
  document.querySelector('.tab-bar').addEventListener('click', function(e) {
    const item = e.target.closest('[data-page]');
    if (item) {
      navigateTo(item.dataset.page);
    }
  });
});