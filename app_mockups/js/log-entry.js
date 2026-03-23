    // --- Global functions for onclick handlers ---
    function showHub() {
      document.querySelectorAll('.form-view').forEach(v => v.classList.remove('active'));
      document.getElementById('hubView').classList.add('active');
      document.querySelector('.screen-content').scrollTop = 0;
    }

    function showForm(name) {
      document.querySelectorAll('.form-view').forEach(v => v.classList.remove('active'));
      document.getElementById(name + 'Form').classList.add('active');
      document.querySelector('.screen-content').scrollTop = 0;
    }

    function navigateTo(page) {
      window.location.href = page;
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
            <div class="toggle-switch ${done ? 'active' : ''}" data-action="toggle"></div>
          </div>`;
      }).join('');
    }

    // --- Render after data loads ---
    initData().then(() => {

    const D = SAMPLE_DATA.today;

    // Populate Nutrition form from today's live data
    const nut = D.nutrition || {};
    document.getElementById('nutBreakfast').value = nut.breakfast || '';
    document.getElementById('nutLunch').value = nut.lunch || '';
    document.getElementById('nutDinner').value = nut.dinner || '';
    document.getElementById('nutSnacks').value = nut.snacks || '';
    document.getElementById('nutCalories').value = nut.total_calories_consumed || '';
    document.getElementById('nutProtein').value = nut.protein_g || '';
    document.getElementById('nutCarbs').value = nut.carbs_g || '';
    document.getElementById('nutFats').value = nut.fats_g || '';
    document.getElementById('nutWater').value = nut.water_l || '';

    // Calorie summary
    const burned = nut.total_calories_burned || 0;
    const consumed = nut.total_calories_consumed || 0;
    const balance = consumed ? consumed - burned : 0;
    document.getElementById('calBurned').textContent = burned ? burned.toLocaleString() : '--';
    document.getElementById('calConsumed').textContent = consumed ? consumed.toLocaleString() : '--';
    if (consumed) {
      const balEl = document.getElementById('calBalance');
      balEl.textContent = (balance >= 0 ? '+' : '') + balance.toLocaleString();
      balEl.style.color = balance >= 0 ? 'var(--status-green)' : 'var(--status-red)';
    }

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

    }); // end initData().then()

// ============================================
// Event delegation — replaces all inline handlers
// ============================================
document.addEventListener('DOMContentLoaded', function () {

  // --- Category cards: data-form="X" -> showForm('X') ---
  document.querySelector('.category-grid').addEventListener('click', function (e) {
    const card = e.target.closest('.category-card[data-form]');
    if (card) showForm(card.dataset.form);
  });

  // --- Back buttons: .form-back -> showHub() ---
  document.querySelector('.screen-content').addEventListener('click', function (e) {
    if (e.target.closest('.form-back')) showHub();
  });

  // --- Save buttons: btn-primary with data-form + data-msg -> saveForm('X', 'msg') ---
  document.querySelector('.screen-content').addEventListener('click', function (e) {
    const btn = e.target.closest('.btn-primary[data-form]');
    if (btn) saveForm(btn.dataset.form, btn.dataset.msg);
  });

  // --- Range sliders: data-display + data-key -> updateSlider() ---
  //     Inverted sliders: data-display + data-inverted="true" -> updateSliderInverted() ---
  document.querySelector('.screen-content').addEventListener('input', function (e) {
    const input = e.target;
    if (input.type !== 'range') return;
    if (input.dataset.inverted === 'true') {
      updateSliderInverted(input, input.dataset.display);
    } else if (input.dataset.display) {
      updateSlider(input, input.dataset.display, input.dataset.key);
    }
  });

  // --- Cognition stepper: data-delta="-1"|"1" -> stepCognition(delta) ---
  document.getElementById('cognitionForm').addEventListener('click', function (e) {
    const btn = e.target.closest('.cognition-btn[data-delta]');
    if (btn) stepCognition(parseInt(btn.dataset.delta, 10));
  });

  // --- Toggle switches rendered by renderHabits(): data-action="toggle" ---
  document.querySelector('.screen-content').addEventListener('click', function (e) {
    const toggle = e.target.closest('.toggle-switch[data-action="toggle"]');
    if (toggle) toggle.classList.toggle('active');
  });

  // --- Tab bar: data-page="X.html" -> navigateTo('X.html') ---
  //             data-action="hub"   -> showHub() ---
  document.querySelector('.tab-bar').addEventListener('click', function (e) {
    const tabItem = e.target.closest('[data-page]');
    if (tabItem) { navigateTo(tabItem.dataset.page); return; }
    const hubBtn = e.target.closest('[data-action="hub"]');
    if (hubBtn) showHub();
  });

});