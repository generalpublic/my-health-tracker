// ============================================
// Health Tracker App — Live Data Loader (Supabase)
//
// Replaces static sample-data.js with live Supabase queries.
// HTML pages must call `await initData()` before rendering.
//
// Usage in HTML:
//   <script src="data-loader.js"></script>
//   <script>
//     initData().then(() => {
//       // SAMPLE_DATA is now populated — render your page
//     });
//   </script>
//
// Falls back to empty/default structure with _error flag if fetch fails.
// ============================================

// --- HTML Sanitization ---
function escapeHtml(str) {
  if (str == null) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// --- Supabase Config ---
// Loaded from config.js (must be included before this script)
// auth.js must also be loaded — it creates the `htSupabase` client singleton.
if (typeof SUPABASE_URL === 'undefined' || typeof SUPABASE_ANON_KEY === 'undefined') {
  document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;padding:2rem;text-align:center"><div><h2>Setup Required</h2><p>Copy <code>config.example.js</code> to <code>config.js</code> and add your Supabase credentials.</p></div></div>';
  throw new Error('Missing config.js — see config.example.js');
}

// ============================================
// Supabase Query — uses authenticated client from auth.js
// ============================================

async function supabaseQuery(table, params = {}) {
  // Build query using the supabase-js client (carries the user's JWT automatically)
  let query = htSupabase.from(table).select(params.select || '*');

  // Apply filters — translate PostgREST filter syntax to supabase-js
  for (const [key, value] of Object.entries(params)) {
    if (key === 'select' || key === 'order' || key === 'limit') continue;
    if (value.startsWith('eq.')) query = query.eq(key, value.substring(3));
    else if (value.startsWith('gte.')) query = query.gte(key, value.substring(4));
    else if (value.startsWith('lte.')) query = query.lte(key, value.substring(4));
    else if (value.startsWith('is.')) query = query.is(key, value.substring(3) === 'null' ? null : value.substring(3));
  }

  // Apply ordering
  if (params.order) {
    const parts = params.order.split(',');
    for (const part of parts) {
      const [col, dir] = part.split('.');
      query = query.order(col, { ascending: dir !== 'desc' });
    }
  }

  // Apply limit
  if (params.limit) query = query.limit(parseInt(params.limit));

  const { data, error } = await query;
  if (error) {
    console.error(`[data-loader] ${table} query failed:`, error.message);
    throw new Error(`Supabase ${table}: ${error.message}`);
  }
  return data || [];
}

// ============================================
// Supabase Write — authenticated via JWT
// ============================================

async function supabaseMutate(table, data, matchColumns = null) {
  // Lazy auth — prompt login on first write if not already signed in
  const user = await requireAuth();
  if (!user) {
    console.warn('[data-loader] Write cancelled — auth declined');
    return null;
  }

  try {
    // Inject authenticated user's ID for RLS-scoped writes
    const payload = { ...data, user_id: user.id };

    let result;
    if (matchColumns) {
      // UPSERT — merge on match columns
      const onConflict = matchColumns.replace(/\s/g, '');
      const { data: rows, error } = await htSupabase
        .from(table)
        .upsert(payload, { onConflict })
        .select();
      if (error) throw error;
      result = rows;
    } else {
      // Plain INSERT (e.g., strength_log with auto-increment id)
      const { data: rows, error } = await htSupabase
        .from(table)
        .insert(payload)
        .select();
      if (error) throw error;
      result = rows;
    }
    console.log(`[data-loader] ${table} write OK`, result);
    return result;
  } catch (err) {
    console.error(`[data-loader] ${table} write failed:`, err.message);
    // Queue for offline retry
    await _enqueueOffline(table, data, matchColumns);
    return null;
  }
}

// ============================================
// Sync Status UI — shows write state to the user
// ============================================

let _syncStatusTimer = null;

function _updateSyncStatus(state, count = 0) {
  let el = document.getElementById('ht-sync-status');
  if (!el) {
    el = document.createElement('div');
    el.id = 'ht-sync-status';
    document.body.appendChild(el);
  }
  el.className = 'ht-sync-status';
  clearTimeout(_syncStatusTimer);

  if (state === 'synced') {
    el.textContent = 'Synced';
    el.classList.add('ht-sync-synced');
    el.classList.add('ht-sync-visible');
    _syncStatusTimer = setTimeout(() => el.classList.remove('ht-sync-visible'), 2000);
  } else if (state === 'syncing') {
    el.textContent = `Syncing ${count} item${count > 1 ? 's' : ''}...`;
    el.classList.add('ht-sync-syncing');
    el.classList.add('ht-sync-visible');
  } else if (state === 'queued') {
    el.textContent = `${count} queued`;
    el.classList.add('ht-sync-queued');
    el.classList.add('ht-sync-visible');
    _syncStatusTimer = setTimeout(() => el.classList.remove('ht-sync-visible'), 3000);
  } else if (state === 'retry_failed') {
    el.textContent = `${count} failed — will retry`;
    el.classList.add('ht-sync-failed');
    el.classList.add('ht-sync-visible');
    _syncStatusTimer = setTimeout(() => el.classList.remove('ht-sync-visible'), 5000);
  }
}

// ============================================
// Offline Queue — retries failed writes when back online
// ============================================

async function _enqueueOffline(table, data, matchColumns) {
  try {
    const queue = await CryptoStore.getItem('ht_offline_queue', []);
    queue.push({ table, data, matchColumns, ts: Date.now() });
    await CryptoStore.setItem('ht_offline_queue', queue);
    console.log(`[data-loader] Queued offline write for ${table}`);
    _updateSyncStatus('queued', queue.length);
  } catch {}
}

/**
 * Direct write to Supabase — used by flushOfflineQueue to avoid
 * re-enqueuing failed replays (supabaseMutate would re-enqueue on failure).
 */
async function _directWrite(table, data, matchColumns) {
  const user = getCurrentUser();
  if (!user) throw new Error('Not authenticated');
  const payload = { ...data, user_id: user.id };

  if (matchColumns) {
    const onConflict = matchColumns.replace(/\s/g, '');
    const { data: rows, error } = await htSupabase
      .from(table)
      .upsert(payload, { onConflict })
      .select();
    if (error) throw error;
    return rows;
  } else {
    const { data: rows, error } = await htSupabase
      .from(table)
      .insert(payload)
      .select();
    if (error) throw error;
    return rows;
  }
}

async function flushOfflineQueue() {
  if (!isAuthenticated()) return;
  try {
    const queue = await CryptoStore.getItem('ht_offline_queue', []);
    if (queue.length === 0) return;
    console.log(`[data-loader] Flushing ${queue.length} offline writes`);
    _updateSyncStatus('syncing', queue.length);
    const remaining = [];
    for (const item of queue) {
      try {
        await _directWrite(item.table, item.data, item.matchColumns);
      } catch {
        remaining.push(item);
      }
    }
    if (remaining.length > 0) {
      await CryptoStore.setItem('ht_offline_queue', remaining);
      _updateSyncStatus('retry_failed', remaining.length);
    } else {
      CryptoStore.removeItem('ht_offline_queue');
      _updateSyncStatus('synced');
    }
  } catch {}
}

// Auto-retry when coming back online
if (typeof window !== 'undefined') {
  window.addEventListener('online', () => {
    console.log('[data-loader] Back online — flushing offline queue');
    flushOfflineQueue();
  });
}

// ============================================
// PWA Write Functions — one per form type
// ============================================

/**
 * Collect habit toggle states from a container element.
 * Returns object with Supabase column names as keys.
 */
function _collectHabits(containerId) {
  const toggles = document.querySelectorAll(`#${containerId} .toggle-switch`);
  const keys = ['wake_at_930', 'no_morning_screens', 'creatine_hydrate',
                'walk_breathing', 'physical_activity', 'no_screens_before_bed', 'bed_at_10pm'];
  const result = {};
  toggles.forEach((t, i) => {
    if (keys[i]) result[keys[i]] = t.classList.contains('active') ? 1 : 0;
  });
  return result;
}

/**
 * Save a single habit toggle from the Today page.
 * Debounces rapid taps — batches all pending toggles into one write after 500ms.
 */
let _habitDebounceTimer = null;
let _habitPendingData = {};

function saveHabitToggle(dateStr, habitKey, value, habitsTotal) {
  // Map today.html habit keys to Supabase column names
  const keyMap = {
    'wake_930': 'wake_at_930',
    'no_morning_screens': 'no_morning_screens',
    'creatine_hydrate': 'creatine_hydrate',
    'walk_breathing': 'walk_breathing',
    'physical_activity': 'physical_activity',
    'no_screens_bed': 'no_screens_before_bed',
    'bed_10pm': 'bed_at_10pm',
  };
  const supabaseKey = keyMap[habitKey] || habitKey;

  // Accumulate pending changes
  _habitPendingData.date = dateStr;
  _habitPendingData.day = _dayOfWeek(dateStr);
  _habitPendingData[supabaseKey] = value ? 1 : 0;
  _habitPendingData.habits_total = habitsTotal;
  _habitPendingData.manual_source = 'pwa';

  // Debounce — flush after 500ms of no taps
  clearTimeout(_habitDebounceTimer);
  _habitDebounceTimer = setTimeout(() => {
    const data = { ..._habitPendingData };
    _habitPendingData = {};
    supabaseMutate('daily_log', data, 'user_id,date');
  }, 500);
}

/** Morning Check-in -> daily_log (morning_energy + habits) */
async function saveMorningCheckin() {
  const date = _todayStr();
  const habits = _collectHabits('morningHabits');
  const habitsTotal = Object.values(habits).filter(v => v === 1).length;
  const data = {
    date,
    day: _dayOfWeek(date),
    morning_energy: parseInt(document.getElementById('morningEnergyVal').textContent),
    ...habits,
    habits_total: habitsTotal,
    manual_source: 'pwa',
  };
  return supabaseMutate('daily_log', data, 'user_id,date');
}

/** Midday Check-in -> daily_log (midday fields) */
async function saveMiddayCheckin() {
  const date = _todayStr();
  const textarea = document.querySelector('#middayForm textarea');
  const data = {
    date,
    day: _dayOfWeek(date),
    midday_energy: parseInt(document.getElementById('midEnergyVal').textContent),
    midday_focus: parseInt(document.getElementById('midFocusVal').textContent),
    midday_mood: parseInt(document.getElementById('midMoodVal').textContent),
    midday_body_feel: parseInt(document.getElementById('midBodyVal').textContent),
    midday_notes: (textarea && textarea.value) || null,
    manual_source: 'pwa',
  };
  return supabaseMutate('daily_log', data, 'user_id,date');
}

/** Evening Review -> daily_log (evening fields + habits + day_rating + stress) */
async function saveEveningReview() {
  const date = _todayStr();
  const habits = _collectHabits('eveningHabits');
  const habitsTotal = Object.values(habits).filter(v => v === 1).length;
  const textarea = document.querySelector('#eveningForm textarea');
  const data = {
    date,
    day: _dayOfWeek(date),
    evening_energy: parseInt(document.getElementById('eveEnergyVal').textContent),
    evening_focus: parseInt(document.getElementById('eveFocusVal').textContent),
    evening_mood: parseInt(document.getElementById('eveMoodVal').textContent),
    perceived_stress: parseInt(document.getElementById('eveStressVal').textContent),
    day_rating: parseInt(document.getElementById('eveDayRating').textContent),
    ...habits,
    habits_total: habitsTotal,
    evening_notes: (textarea && textarea.value) || null,
    manual_source: 'pwa',
  };
  return supabaseMutate('daily_log', data, 'user_id,date');
}

/** Nutrition -> nutrition (meals + macros) */
async function saveNutrition() {
  const date = _todayStr();
  const mealTextareas = document.querySelectorAll('#nutritionForm .meal-card textarea');
  const macroInputs = document.querySelectorAll('#nutritionForm .macro-input');
  const calories = parseFloat(macroInputs[0]?.value) || 0;
  const burned = _num(SAMPLE_DATA.today?.nutrition?.total_calories_burned);
  // Last textarea in nutritionForm (not inside a meal-card) is the notes field
  const notesTextarea = document.querySelector('#nutritionForm > textarea, #nutritionForm .text-input:last-of-type');
  const notes = (notesTextarea && !notesTextarea.closest('.meal-card')) ? notesTextarea.value : null;
  const data = {
    date,
    day: _dayOfWeek(date),
    breakfast: mealTextareas[0]?.value || null,
    lunch: mealTextareas[1]?.value || null,
    dinner: mealTextareas[2]?.value || null,
    snacks: mealTextareas[3]?.value || null,
    total_calories_consumed: calories,
    protein_g: parseFloat(macroInputs[1]?.value) || null,
    carbs_g: parseFloat(macroInputs[2]?.value) || null,
    fats_g: parseFloat(macroInputs[3]?.value) || null,
    water_l: parseFloat(macroInputs[4]?.value) || null,
    calorie_balance: calories > 0 ? calories - burned : null,
    notes: notes || null,
    manual_source: 'pwa',
  };
  return supabaseMutate('nutrition', data, 'user_id,date');
}

/** Cognition -> overall_analysis (cognition + cognition_notes only) */
async function saveCognition() {
  const date = _todayStr();
  const textarea = document.querySelector('#cognitionForm textarea');
  const data = {
    date,
    day: _dayOfWeek(date),
    cognition: typeof cognitionScore !== 'undefined' ? cognitionScore : parseInt(document.getElementById('cognitionVal').textContent),
    cognition_notes: (textarea && textarea.value) || null,
    manual_source: 'pwa',
  };
  return supabaseMutate('overall_analysis', data, 'user_id,date');
}

/** Sleep Notes -> sleep (notes column only) */
async function saveSleepNotes() {
  const date = _todayStr();
  const textarea = document.querySelector('#sleep_notesForm textarea');
  const data = {
    date,
    notes: (textarea && textarea.value) || null,
    manual_source: 'pwa',
  };
  return supabaseMutate('sleep', data, 'user_id,date');
}

/** Strength Set -> strength_log (upsert on set_id for offline replay dedup) */
async function saveStrengthSet(muscleGroup, exercise, weight, reps, rpe) {
  const date = _todayStr();
  const data = {
    date,
    day: _dayOfWeek(date),
    muscle_group: muscleGroup,
    exercise: exercise,
    set_id: crypto.randomUUID(),
    weight_lbs: weight,
    reps: reps,
    rpe: rpe,
    manual_source: 'pwa',
  };
  // Upsert on set_id — each set gets a unique ID, but offline replays reuse it
  return supabaseMutate('strength_log', data, 'user_id,set_id');
}

/** Session manual fields -> session_log (perceived_effort, post_workout_energy, notes) */
async function saveSessionManualFields(activityName, perceivedEffort, postWorkoutEnergy, notes) {
  const date = _todayStr();
  const data = {
    date,
    activity_name: activityName,
    day: _dayOfWeek(date),
    perceived_effort: perceivedEffort || null,
    post_workout_energy: postWorkoutEnergy || null,
    notes: notes || null,
    manual_source: 'pwa',
  };
  return supabaseMutate('session_log', data, 'user_id,date,activity_name');
}

// ============================================
// Thresholds (static config — from thresholds.json)
// ============================================

const THRESHOLDS = {
  readiness_score: { type: "higher_better", red: 4, yellow: 5.5, green: 8.5 },
  sleep_analysis_score: { type: "higher_better", red: 50, yellow: 65, green: 80 },
  total_sleep_hrs: { type: "higher_better", red: 5, yellow: 7, green: 8 },
  overnight_hrv_ms: { type: "higher_better", red: 37, yellow: 40, green: 44 },
  body_battery: { type: "higher_better", red: 20, yellow: 50, green: 80 },
  body_battery_gained: { type: "higher_better", red: 15, yellow: 40, green: 65 },
  resting_hr: { type: "lower_better", green: 48, yellow: 55, red: 65 },
  avg_stress_level: { type: "lower_better", green: 15, yellow: 30, red: 50 },
  steps: { type: "higher_better", red: 3000, yellow: 7000, green: 10000 },
  habits_total: { type: "higher_better", red: 2, yellow: 4, green: 6 },
  day_rating: { type: "higher_better", red: 1, yellow: 5.5, green: 10 },
  morning_energy: { type: "higher_better", red: 1, yellow: 5.5, green: 10 },
  cognition: { type: "higher_better", red: 1, yellow: 5, green: 10 },
  deep_pct: { type: "higher_better", red: 12, yellow: 18, green: 22 },
  rem_pct: { type: "higher_better", red: 15, yellow: 20, green: 25 },
  bedtime_var: { type: "lower_better", green: 30, yellow: 60, red: 90 },
  wake_var: { type: "lower_better", green: 30, yellow: 60, red: 90 },
  workout_duration: { type: "higher_better", red: 15, yellow: 35, green: 60 },
  workout_calories: { type: "higher_better", red: 100, yellow: 400, green: 900 },
  aerobic_te: { type: "higher_better", red: 1, yellow: 2.5, green: 4 },
  awake_min: { type: "lower_better", green: 15, yellow: 30, red: 60 },
  session_avg_hr: { type: "higher_better", red: 90, yellow: 120, green: 150 },
  session_distance: { type: "higher_better", red: 1, yellow: 5, green: 15 },
};

const SLEEP_STAGE_TARGETS = {
  deep_pct: 22,
  rem_pct: 25,
  awake_max: 15,
};

// ============================================
// SAMPLE_DATA — initialized with static parts,
// live data filled by initData()
// ============================================

let SAMPLE_DATA = {
  thresholds: THRESHOLDS,
  sleep_stage_targets: SLEEP_STAGE_TARGETS,
  today: null,
  history: [],
  sessions_history: [],
  profile: { name: (typeof USER_NAME !== 'undefined' ? USER_NAME : 'User') },
  _error: null,
  _loaded: false,
};

// ============================================
// Date helpers
// ============================================

function _todayStr() {
  const d = new Date();
  return d.getFullYear() + '-' +
    String(d.getMonth() + 1).padStart(2, '0') + '-' +
    String(d.getDate()).padStart(2, '0');
}

function _dayOfWeek(dateStr) {
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const d = new Date(dateStr + 'T12:00:00');
  return days[d.getDay()];
}

function _daysAgoStr(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.getFullYear() + '-' +
    String(d.getMonth() + 1).padStart(2, '0') + '-' +
    String(d.getDate()).padStart(2, '0');
}

// Safe numeric accessor — returns the value or a fallback
function _num(val, fallback = 0) {
  if (val === null || val === undefined || val === '') return fallback;
  const n = Number(val);
  return isNaN(n) ? fallback : n;
}

// ============================================
// Fetch functions
// ============================================

/**
 * Fetch today's data from all relevant tables.
 * Returns the SAMPLE_DATA.today object structure.
 */
async function fetchDateData(dateStr) {
  return fetchToday(dateStr);
}

// ============================================
// RPC-based fetch (2 round-trips instead of 14)
// Falls back to per-table queries if RPCs not deployed
// ============================================

async function _fetchViaRpc() {
  const today = _todayStr();
  const startDate = _daysAgoStr(90);

  const [todayRpc, histRpc] = await Promise.allSettled([
    htSupabase.rpc('get_dashboard_today', { target_date: today }),
    htSupabase.rpc('get_dashboard_history', { start_date: startDate, recent_sessions_limit: 5 }),
  ]);

  if (todayRpc.status === 'rejected' || todayRpc.value?.error) throw new Error('RPC not available');
  if (histRpc.status === 'rejected' || histRpc.value?.error) throw new Error('RPC not available');

  const todayData = _parseTodayRpc(todayRpc.value.data, today);
  const { history, sessions_history } = _parseHistoryRpc(histRpc.value.data);

  // Fallback: if today is empty, try yesterday (same logic as fetchToday)
  if (_isDataEmpty(todayData)) {
    const yesterday = _daysAgoStr(1);
    const { data: ydayData, error: ydayErr } = await htSupabase.rpc('get_dashboard_today', { target_date: yesterday });
    if (!ydayErr && ydayData) {
      const ydayParsed = _parseTodayRpc(ydayData, yesterday);
      if (!_isDataEmpty(ydayParsed)) {
        ydayParsed._fallbackDate = today;
        return { today: ydayParsed, history, sessions_history };
      }
    }
  }

  return { today: todayData, history, sessions_history };
}

function _parseTodayRpc(rpc, dateStr) {
  const day = _dayOfWeek(dateStr);
  const g = rpc.garmin || {};
  const sl = rpc.sleep || {};
  const oa = rpc.overall_analysis || {};
  const dl = rpc.daily_log || {};
  const nut = rpc.nutrition || {};
  const sessionRows = rpc.session_log || [];
  const strengthRows = rpc.strength_log || [];
  const illnessRows = rpc.illness_state ? [rpc.illness_state] : [];

  const _polishText = t => t.replace(/ -- /g, '. ').replace(/^TODAY:\s*/i, '').replace(/^(.)/, (_, c) => c.toUpperCase());
  let keyInsights = _parseBulletText(oa.key_insights).map(_polishText);
  let recommendations = _parseBulletText(oa.recommendations).map(_polishText);

  const readinessScore = _num(oa.readiness_score);
  const readinessLabel = oa.readiness_label || _readinessLabel(readinessScore);
  const confidence = oa.confidence || 'Medium';
  const cogAssessment = oa.cognitive_energy_assessment || '';
  const sleepContext = oa.sleep_context || '';
  const expectBlock = _parseExpectBlock(cogAssessment);
  const sleepAnalysis = sl.sleep_analysis || '';
  const sleepFeedback = sl.sleep_feedback || _sleepFeedbackFromScore(_num(sl.sleep_analysis_score));
  const flags = keyInsights.length > 0 ? keyInsights : [];
  const doItems = recommendations.length > 0 ? recommendations : [];
  const sleepContextItems = _buildSleepContextItems(sl);
  const sleepLine = `${sleepFeedback} | ${_num(sl.total_sleep_hrs)}h | Deep ${_num(sl.deep_pct)}% | REM ${_num(sl.rem_pct)}% | HRV ${_num(sl.overnight_hrv_ms)}ms | Bed ${sl.bedtime || '--'}`;

  const sessions = sessionRows.map(s => ({
    activity_name: s.activity_name || '',
    activity_type: (s.session_type || s.activity_name || '').toLowerCase().replace(/\s+/g, '_'),
    duration_min: _num(s.duration_min), distance_mi: _num(s.distance_mi),
    avg_hr: _num(s.avg_hr), max_hr: _num(s.max_hr), calories: _num(s.calories),
    aerobic_te: _num(s.aerobic_te), anaerobic_te: _num(s.anaerobic_te),
    zone_1_min: _num(s.zone_1_min), zone_2_min: _num(s.zone_2_min),
    zone_3_min: _num(s.zone_3_min), zone_4_min: _num(s.zone_4_min),
    zone_5_min: _num(s.zone_5_min),
    perceived_effort: _num(s.perceived_effort),
    post_workout_energy: _num(s.post_workout_energy), notes: s.notes || '',
  }));

  const strength = strengthRows.map(s => ({
    muscle_group: s.muscle_group || '', exercise: s.exercise || '',
    weight: _num(s.weight_lbs), reps: _num(s.reps), rpe: _num(s.rpe), notes: s.notes || '',
  }));

  return {
    date: dateStr, day: day,
    readiness: {
      score: readinessScore, label: readinessLabel, confidence: confidence,
      cognitive_assessment: cogAssessment, sleep_context: sleepContext,
      key_insights: keyInsights, recommendations: recommendations,
      training_load: oa.training_load_status || '',
      cognition: _num(oa.cognition), cognition_notes: oa.cognition_notes || '',
    },
    sleep: {
      garmin_score: _num(g.sleep_score), analysis_score: _num(sl.sleep_analysis_score),
      total_sleep_hrs: _num(sl.total_sleep_hrs), bedtime: sl.bedtime || '', wake_time: sl.wake_time || '',
      time_in_bed_hrs: _num(sl.time_in_bed_hrs),
      deep_min: _num(sl.deep_sleep_min), light_min: _num(sl.light_sleep_min),
      rem_min: _num(sl.rem_min), awake_min: _num(sl.awake_during_sleep_min),
      deep_pct: _num(sl.deep_pct), rem_pct: _num(sl.rem_pct),
      sleep_cycles: _num(sl.sleep_cycles), awakenings: _num(sl.awakenings),
      avg_hr: _num(sl.avg_hr), avg_respiration: _num(sl.avg_respiration),
      overnight_hrv: _num(sl.overnight_hrv_ms), body_battery_gained: _num(sl.body_battery_gained),
      bedtime_var_7d: _num(sl.bedtime_variability_7d), wake_var_7d: _num(sl.wake_variability_7d),
      notes: sl.notes || '', sleep_feedback: sleepFeedback, analysis_text: sleepAnalysis,
    },
    garmin: {
      hrv_overnight: _num(sl.overnight_hrv_ms || g.hrv_overnight_avg),
      hrv_7day_avg: _num(g.hrv_7day_avg), resting_hr: _num(g.resting_hr),
      body_battery: _num(g.body_battery), body_battery_wake: _num(g.body_battery_at_wake),
      body_battery_high: _num(g.body_battery_high), body_battery_low: _num(g.body_battery_low),
      steps: _num(g.steps), floors: _num(g.floors_ascended),
      total_calories: _num(g.total_calories_burned), active_calories: _num(g.active_calories_burned),
      bmr_calories: _num(g.bmr_calories), avg_stress: _num(g.avg_stress_level),
      stress_qualifier: g.stress_qualifier || '',
      moderate_intensity_min: _num(g.moderate_intensity_min),
      vigorous_intensity_min: _num(g.vigorous_intensity_min),
    },
    daily_log: {
      morning_energy: _num(dl.morning_energy),
      habits: {
        wake_930: !!dl.wake_at_930, no_morning_screens: !!dl.no_morning_screens,
        creatine_hydrate: !!dl.creatine_hydrate, walk_breathing: !!dl.walk_breathing,
        physical_activity: !!dl.physical_activity, no_screens_bed: !!dl.no_screens_before_bed,
        bed_10pm: !!dl.bed_at_10pm,
      },
      habits_total: _num(dl.habits_total),
      midday: { energy: _num(dl.midday_energy), focus: _num(dl.midday_focus), mood: _num(dl.midday_mood), body_feel: _num(dl.midday_body_feel), notes: dl.midday_notes || '' },
      evening: { energy: _num(dl.evening_energy), focus: _num(dl.evening_focus), mood: _num(dl.evening_mood) },
      perceived_stress: _num(dl.perceived_stress), day_rating: _num(dl.day_rating),
      evening_notes: dl.evening_notes || '',
    },
    sessions: sessions, strength: strength,
    nutrition: {
      total_calories_burned: _num(nut.total_calories_burned || g.total_calories_burned),
      active_calories: _num(nut.active_calories_burned || g.active_calories_burned),
      bmr_calories: _num(nut.bmr_calories || g.bmr_calories),
      breakfast: nut.breakfast || '', lunch: nut.lunch || '', dinner: nut.dinner || '',
      snacks: nut.snacks || '', total_calories_consumed: _num(nut.total_calories_consumed),
      protein_g: _num(nut.protein_g), carbs_g: _num(nut.carbs_g), fats_g: _num(nut.fats_g),
      water_l: _num(nut.water_l), calorie_balance: _num(nut.calorie_balance), notes: nut.notes || '',
    },
    illness: (() => {
      const ill = illnessRows[0];
      if (!ill) return { label: 'normal' };
      const dailyLabel = (oa.key_insights || '').includes('illness episode active') ? 'illness_ongoing'
        : (oa.key_insights || '').includes('possible illness') ? 'possible_illness' : 'normal';
      return { label: dailyLabel !== 'normal' ? dailyLabel : 'illness_ongoing', onset_date: ill.onset_date, confirmed: !!ill.confirmed_date, peak_score: ill.peak_score };
    })(),
    briefing: {
      expect: expectBlock, sleep_line: sleepLine, sleep_debt: '0h',
      sleep_context_items: sleepContextItems, sleep_context: sleepContext,
      flags: flags, do_items: doItems,
    },
    data_status: {
      has_garmin: !!g.date, has_analysis: readinessScore > 0,
      analysis_pending: !!g.date && readinessScore === 0,
      stale_steps: _num(g.steps) > 0 && _num(g.steps) < 500,
      last_sync: g.updated_at || g.date || null,
    },
  };
}

function _parseHistoryRpc(rpc) {
  const garminRows = rpc.garmin || [];
  const sleepRows = rpc.sleep || [];
  const analysisRows = rpc.overall_analysis || [];
  const dailyLogRows = rpc.daily_log || [];
  const sessionRows = rpc.session_log || [];
  const recentSessions = rpc.recent_sessions || [];

  // Index by date for merging
  const garminMap = {}; garminRows.forEach(r => { garminMap[r.date] = r; });
  const sleepMap = {}; sleepRows.forEach(r => { sleepMap[r.date] = r; });
  const analysisMap = {}; analysisRows.forEach(r => { analysisMap[r.date] = r; });
  const dailyLogMap = {}; dailyLogRows.forEach(r => { dailyLogMap[r.date] = r; });
  const sessionMap = {};
  sessionRows.forEach(r => {
    if (!sessionMap[r.date]) sessionMap[r.date] = [];
    sessionMap[r.date].push({
      activity_name: r.activity_name || '',
      type: (r.session_type || r.activity_name || '').toLowerCase().replace(/\s+/g, '_'),
      duration_min: _num(r.duration_min), distance_mi: _num(r.distance_mi),
      calories: _num(r.calories), avg_hr: _num(r.avg_hr), max_hr: _num(r.max_hr),
    });
  });

  const allDates = new Set();
  [garminRows, sleepRows, analysisRows, dailyLogRows, sessionRows].forEach(rows => {
    rows.forEach(r => allDates.add(r.date));
  });

  const history = Array.from(allDates).sort().map(date => {
    const g = garminMap[date] || {};
    const s = sleepMap[date] || {};
    const a = analysisMap[date] || {};
    const dl = dailyLogMap[date] || {};
    return {
      date, readiness: _num(a.readiness_score), sleep_score: _num(s.sleep_analysis_score),
      total_sleep: _num(s.total_sleep_hrs), hrv: _num(s.overnight_hrv_ms || g.hrv_overnight_avg),
      rhr: _num(g.resting_hr), body_battery: _num(g.body_battery), steps: _num(g.steps),
      stress: _num(g.avg_stress_level), habits: _num(dl.habits_total),
      day_rating: _num(dl.day_rating), morning_energy: _num(dl.morning_energy),
      cognition: _num(a.cognition), sessions: sessionMap[date] || [],
    };
  });

  const sessions_history = recentSessions.map(s => ({
    date: s.date, activity_name: s.activity_name || '',
    type: (s.session_type || s.activity_name || '').toLowerCase().replace(/\s+/g, '_'),
    duration: _num(s.duration_min), distance: _num(s.distance_mi),
    calories: _num(s.calories), avg_hr: _num(s.avg_hr),
  }));

  return { history, sessions_history };
}

async function fetchToday(overrideDate, _depth = 0) {
  if (_depth > 3) return _buildFallbackToday();
  const today = overrideDate || _todayStr();
  const day = _dayOfWeek(today);

  // Parallel fetch from all tables for today's date — resilient to individual failures
  const _todayResults = await Promise.allSettled([
    supabaseQuery('garmin', { date: `eq.${today}`, limit: '1' }),
    supabaseQuery('sleep', { date: `eq.${today}`, limit: '1' }),
    supabaseQuery('overall_analysis', { date: `eq.${today}`, limit: '1' }),
    supabaseQuery('daily_log', { date: `eq.${today}`, limit: '1' }),
    supabaseQuery('session_log', { date: `eq.${today}`, order: 'activity_name.asc' }),
    supabaseQuery('nutrition', { date: `eq.${today}`, limit: '1' }),
    supabaseQuery('strength_log', { date: `eq.${today}`, order: 'id.asc' }),
    supabaseQuery('illness_state', { resolved_date: 'is.null', order: 'onset_date.desc', limit: '1' }),
  ]);

  const _todayTables = ['garmin', 'sleep', 'overall_analysis', 'daily_log', 'session_log', 'nutrition', 'strength_log', 'illness_state'];
  _todayResults.forEach((r, i) => {
    if (r.status === 'rejected') console.error('[data-loader] fetch failed:', r.reason);
  });

  const garminRows = _todayResults[0].status === 'fulfilled' ? _todayResults[0].value : [];
  const sleepRows = _todayResults[1].status === 'fulfilled' ? _todayResults[1].value : [];
  const analysisRows = _todayResults[2].status === 'fulfilled' ? _todayResults[2].value : [];
  const dailyLogRows = _todayResults[3].status === 'fulfilled' ? _todayResults[3].value : [];
  const sessionRows = _todayResults[4].status === 'fulfilled' ? _todayResults[4].value : [];
  const nutritionRows = _todayResults[5].status === 'fulfilled' ? _todayResults[5].value : [];
  const strengthRows = _todayResults[6].status === 'fulfilled' ? _todayResults[6].value : [];
  const illnessRows = _todayResults[7].status === 'fulfilled' ? _todayResults[7].value : [];

  const g = garminRows[0] || {};
  const sl = sleepRows[0] || {};
  const oa = analysisRows[0] || {};
  const dl = dailyLogRows[0] || {};
  const nut = nutritionRows[0] || {};

  // Parse key_insights and recommendations — stored as newline-separated "- " bullet text
  // Polish: clean historical artifacts (double-dashes, TODAY: prefix)
  const _polishText = t => t.replace(/ -- /g, '. ').replace(/^TODAY:\s*/i, '').replace(/^(.)/, (_, c) => c.toUpperCase());
  let keyInsights = _parseBulletText(oa.key_insights).map(_polishText);
  let recommendations = _parseBulletText(oa.recommendations).map(_polishText);

  // Determine readiness label from score
  const readinessScore = _num(oa.readiness_score);
  const readinessLabel = oa.readiness_label || _readinessLabel(readinessScore);
  const confidence = oa.confidence || 'Medium';

  // Parse cognitive/energy assessment
  const cogAssessment = oa.cognitive_energy_assessment || '';
  const sleepContext = oa.sleep_context || '';

  // Build expect block from cognitive assessment text
  const expectBlock = _parseExpectBlock(cogAssessment);

  // Build sleep feedback from analysis text
  const sleepAnalysis = sl.sleep_analysis || '';
  const sleepFeedback = sl.sleep_feedback || _sleepFeedbackFromScore(_num(sl.sleep_analysis_score));

  // Build flags and do_items from insights/recommendations
  const flags = keyInsights.length > 0 ? keyInsights : [];
  const doItems = recommendations.length > 0 ? recommendations : [];

  // Build sleep context items
  const sleepContextItems = _buildSleepContextItems(sl);

  // Build briefing sleep line
  const sleepLine = `${sleepFeedback} | ${_num(sl.total_sleep_hrs)}h | Deep ${_num(sl.deep_pct)}% | REM ${_num(sl.rem_pct)}% | HRV ${_num(sl.overnight_hrv_ms)}ms | Bed ${sl.bedtime || '--'}`;

  // Map sessions to expected format
  const sessions = sessionRows.map(s => ({
    activity_name: s.activity_name || '',
    activity_type: (s.session_type || s.activity_name || '').toLowerCase().replace(/\s+/g, '_'),
    duration_min: _num(s.duration_min),
    distance_mi: _num(s.distance_mi),
    avg_hr: _num(s.avg_hr),
    max_hr: _num(s.max_hr),
    calories: _num(s.calories),
    aerobic_te: _num(s.aerobic_te),
    anaerobic_te: _num(s.anaerobic_te),
    zone_1_min: _num(s.zone_1_min),
    zone_2_min: _num(s.zone_2_min),
    zone_3_min: _num(s.zone_3_min),
    zone_4_min: _num(s.zone_4_min),
    zone_5_min: _num(s.zone_5_min),
    perceived_effort: _num(s.perceived_effort),
    post_workout_energy: _num(s.post_workout_energy),
    notes: s.notes || '',
  }));

  // Map strength to expected format
  const strength = strengthRows.map(s => ({
    muscle_group: s.muscle_group || '',
    exercise: s.exercise || '',
    weight: _num(s.weight_lbs),
    reps: _num(s.reps),
    rpe: _num(s.rpe),
    notes: s.notes || '',
  }));

  const todayData = {
    date: today,
    day: day,

    readiness: {
      score: readinessScore,
      label: readinessLabel,
      confidence: confidence,
      cognitive_assessment: cogAssessment,
      sleep_context: sleepContext,
      key_insights: keyInsights,
      recommendations: recommendations,
      training_load: oa.training_load_status || '',
      cognition: _num(oa.cognition),
      cognition_notes: oa.cognition_notes || '',
    },

    sleep: {
      garmin_score: _num(g.sleep_score),
      analysis_score: _num(sl.sleep_analysis_score),
      total_sleep_hrs: _num(sl.total_sleep_hrs),
      bedtime: sl.bedtime || '',
      wake_time: sl.wake_time || '',
      time_in_bed_hrs: _num(sl.time_in_bed_hrs),
      deep_min: _num(sl.deep_sleep_min),
      light_min: _num(sl.light_sleep_min),
      rem_min: _num(sl.rem_min),
      awake_min: _num(sl.awake_during_sleep_min),
      deep_pct: _num(sl.deep_pct),
      rem_pct: _num(sl.rem_pct),
      sleep_cycles: _num(sl.sleep_cycles),
      awakenings: _num(sl.awakenings),
      avg_hr: _num(sl.avg_hr),
      avg_respiration: _num(sl.avg_respiration),
      overnight_hrv: _num(sl.overnight_hrv_ms),
      body_battery_gained: _num(sl.body_battery_gained),
      bedtime_var_7d: _num(sl.bedtime_variability_7d),
      wake_var_7d: _num(sl.wake_variability_7d),
      notes: sl.notes || '',
      sleep_feedback: sleepFeedback,
      analysis_text: sleepAnalysis,
    },

    garmin: {
      hrv_overnight: _num(sl.overnight_hrv_ms || g.hrv_overnight_avg),
      hrv_7day_avg: _num(g.hrv_7day_avg),
      resting_hr: _num(g.resting_hr),
      body_battery: _num(g.body_battery),
      body_battery_wake: _num(g.body_battery_at_wake),
      body_battery_high: _num(g.body_battery_high),
      body_battery_low: _num(g.body_battery_low),
      steps: _num(g.steps),
      floors: _num(g.floors_ascended),
      total_calories: _num(g.total_calories_burned),
      active_calories: _num(g.active_calories_burned),
      bmr_calories: _num(g.bmr_calories),
      avg_stress: _num(g.avg_stress_level),
      stress_qualifier: g.stress_qualifier || '',
      moderate_intensity_min: _num(g.moderate_intensity_min),
      vigorous_intensity_min: _num(g.vigorous_intensity_min),
    },

    daily_log: {
      morning_energy: _num(dl.morning_energy),
      habits: {
        wake_930: !!dl.wake_at_930,
        no_morning_screens: !!dl.no_morning_screens,
        creatine_hydrate: !!dl.creatine_hydrate,
        walk_breathing: !!dl.walk_breathing,
        physical_activity: !!dl.physical_activity,
        no_screens_bed: !!dl.no_screens_before_bed,
        bed_10pm: !!dl.bed_at_10pm,
      },
      habits_total: _num(dl.habits_total),
      midday: {
        energy: _num(dl.midday_energy),
        focus: _num(dl.midday_focus),
        mood: _num(dl.midday_mood),
        body_feel: _num(dl.midday_body_feel),
        notes: dl.midday_notes || '',
      },
      evening: {
        energy: _num(dl.evening_energy),
        focus: _num(dl.evening_focus),
        mood: _num(dl.evening_mood),
      },
      perceived_stress: _num(dl.perceived_stress),
      day_rating: _num(dl.day_rating),
      evening_notes: dl.evening_notes || '',
    },

    sessions: sessions,
    strength: strength,

    nutrition: {
      total_calories_burned: _num(nut.total_calories_burned || g.total_calories_burned),
      active_calories: _num(nut.active_calories_burned || g.active_calories_burned),
      bmr_calories: _num(nut.bmr_calories || g.bmr_calories),
      breakfast: nut.breakfast || '',
      lunch: nut.lunch || '',
      dinner: nut.dinner || '',
      snacks: nut.snacks || '',
      total_calories_consumed: _num(nut.total_calories_consumed),
      protein_g: _num(nut.protein_g),
      carbs_g: _num(nut.carbs_g),
      fats_g: _num(nut.fats_g),
      water_l: _num(nut.water_l),
      calorie_balance: _num(nut.calorie_balance),
      notes: nut.notes || '',
    },

    illness: (() => {
      const ill = illnessRows[0];
      if (!ill) return { label: 'normal' };
      // Also check illness_daily_log for today's label
      const dailyLabel = (oa.key_insights || '').includes('illness episode active') ? 'illness_ongoing'
        : (oa.key_insights || '').includes('possible illness') ? 'possible_illness'
        : 'normal';
      return {
        label: dailyLabel !== 'normal' ? dailyLabel : 'illness_ongoing',
        onset_date: ill.onset_date,
        confirmed: !!ill.confirmed_date,
        peak_score: ill.peak_score,
      };
    })(),

    briefing: {
      expect: expectBlock,
      sleep_line: sleepLine,
      sleep_debt: '0h',
      sleep_context_items: sleepContextItems,
      sleep_context: sleepContext,
      flags: flags,
      do_items: doItems,
    },

    // Data freshness indicators
    data_status: {
      has_garmin: !!g.date,
      has_analysis: readinessScore > 0,
      analysis_pending: !!g.date && readinessScore === 0,
      stale_steps: _num(g.steps) > 0 && _num(g.steps) < 500,
      last_sync: g.updated_at || g.date || null,
    },
  };

  // Fallback: if initial load (no overrideDate) and data is empty, try yesterday
  if (!overrideDate && _isDataEmpty(todayData)) {
    const yesterday = _daysAgoStr(1);
    console.log(`[data-loader] No data for ${today}, trying ${yesterday}`);
    const fallback = await fetchToday(yesterday, _depth + 1);
    fallback._fallbackDate = today;
    return fallback;
  }

  return todayData;
}

/**
 * Fetch history for the last N days from key tables.
 * Returns array matching SAMPLE_DATA.history structure.
 */
async function fetchHistory(days = 90) {
  const startDate = _daysAgoStr(days);

  const _histResults = await Promise.allSettled([
    supabaseQuery('garmin', {
      select: 'date,body_battery,steps,avg_stress_level,resting_hr,hrv_overnight_avg',
      date: `gte.${startDate}`,
      order: 'date.asc',
    }),
    supabaseQuery('sleep', {
      select: 'date,sleep_analysis_score,total_sleep_hrs,overnight_hrv_ms',
      date: `gte.${startDate}`,
      order: 'date.asc',
    }),
    supabaseQuery('overall_analysis', {
      select: 'date,readiness_score,cognition',
      date: `gte.${startDate}`,
      order: 'date.asc',
    }),
    supabaseQuery('daily_log', {
      select: 'date,habits_total,day_rating,morning_energy',
      date: `gte.${startDate}`,
      order: 'date.asc',
    }),
    supabaseQuery('session_log', {
      select: 'date,activity_name,session_type,duration_min,distance_mi,calories,avg_hr,max_hr',
      date: `gte.${startDate}`,
      order: 'date.asc',
    }),
  ]);

  const _histTables = ['garmin', 'sleep', 'overall_analysis', 'daily_log', 'session_log'];
  _histResults.forEach((r, i) => {
    if (r.status === 'rejected') console.error('[data-loader] fetch failed:', r.reason);
  });

  const garminRows = _histResults[0].status === 'fulfilled' ? _histResults[0].value : [];
  const sleepRows = _histResults[1].status === 'fulfilled' ? _histResults[1].value : [];
  const analysisRows = _histResults[2].status === 'fulfilled' ? _histResults[2].value : [];
  const dailyLogRows = _histResults[3].status === 'fulfilled' ? _histResults[3].value : [];
  const sessionRows = _histResults[4].status === 'fulfilled' ? _histResults[4].value : [];

  // Index by date for merging
  const garminMap = {};
  garminRows.forEach(r => { garminMap[r.date] = r; });
  const sleepMap = {};
  sleepRows.forEach(r => { sleepMap[r.date] = r; });
  const analysisMap = {};
  analysisRows.forEach(r => { analysisMap[r.date] = r; });
  const dailyLogMap = {};
  dailyLogRows.forEach(r => { dailyLogMap[r.date] = r; });
  const sessionMap = {};
  sessionRows.forEach(r => {
    if (!sessionMap[r.date]) sessionMap[r.date] = [];
    sessionMap[r.date].push({
      activity_name: r.activity_name || '',
      type: (r.session_type || r.activity_name || '').toLowerCase().replace(/\s+/g, '_'),
      duration_min: _num(r.duration_min),
      distance_mi: _num(r.distance_mi),
      calories: _num(r.calories),
      avg_hr: _num(r.avg_hr),
      max_hr: _num(r.max_hr),
    });
  });

  // Collect all unique dates
  const allDates = new Set();
  [garminRows, sleepRows, analysisRows, dailyLogRows, sessionRows].forEach(rows => {
    rows.forEach(r => allDates.add(r.date));
  });

  // Build merged history array sorted by date
  const history = Array.from(allDates).sort().map(date => {
    const g = garminMap[date] || {};
    const s = sleepMap[date] || {};
    const a = analysisMap[date] || {};
    const dl = dailyLogMap[date] || {};

    return {
      date: date,
      readiness: _num(a.readiness_score),
      sleep_score: _num(s.sleep_analysis_score),
      total_sleep: _num(s.total_sleep_hrs),
      hrv: _num(s.overnight_hrv_ms || g.hrv_overnight_avg),
      rhr: _num(g.resting_hr),
      body_battery: _num(g.body_battery),
      steps: _num(g.steps),
      stress: _num(g.avg_stress_level),
      habits: _num(dl.habits_total),
      day_rating: _num(dl.day_rating),
      morning_energy: _num(dl.morning_energy),
      cognition: _num(a.cognition),
      sessions: sessionMap[date] || [],
    };
  });

  return history;
}

/**
 * Fetch recent workout sessions for the sessions_history array.
 * Returns array matching SAMPLE_DATA.sessions_history structure.
 */
async function fetchSessions(days = 365) {
  const startDate = _daysAgoStr(days);

  const rows = await supabaseQuery('session_log', {
    date: `gte.${startDate}`,
    order: 'date.desc',
    limit: '5',
  });

  return rows.map(s => ({
    date: s.date,
    activity_name: s.activity_name || '',
    type: (s.session_type || s.activity_name || '').toLowerCase().replace(/\s+/g, '_'),
    duration: _num(s.duration_min),
    distance: _num(s.distance_mi),
    calories: _num(s.calories),
    avg_hr: _num(s.avg_hr),
  }));
}

// ============================================
// Internal helpers
// ============================================

function _parseBulletText(text) {
  if (!text) return [];
  // Try JSON first (legacy format)
  try { const arr = JSON.parse(text); if (Array.isArray(arr)) return arr; } catch (e) {}
  // Parse "- " bullet point text (one item per line starting with "- ")
  return text.split('\n')
    .map(line => line.trim())
    .filter(line => line.startsWith('- '))
    .map(line => line.substring(2).trim());
}

function _readinessLabel(score) {
  if (score >= 8.5) return 'Optimal';
  if (score >= 7) return 'Good';
  if (score >= 5.5) return 'Fair';
  if (score >= 4) return 'Low';
  return 'Poor';
}

function _sleepFeedbackFromScore(score) {
  if (score >= 80) return 'Solid Recovery';
  if (score >= 65) return 'Adequate Rest';
  if (score >= 50) return 'Fair Sleep';
  return 'Poor Quality';
}

function _parseExpectBlock(cogAssessment) {
  // Try to parse "Above baseline. Mind: ... Energy: ..." format
  const result = { level: '', effects: [] };
  if (!cogAssessment) return result;

  // Extract level (first sentence or phrase before first period)
  const firstDot = cogAssessment.indexOf('.');
  if (firstDot > 0) {
    result.level = cogAssessment.substring(0, firstDot).trim();
  } else {
    result.level = cogAssessment.trim();
    return result;
  }

  // Extract Mind and Energy domains
  const remainder = cogAssessment.substring(firstDot + 1);
  const mindMatch = remainder.match(/Mind:\s*([^.]*(?:\.[^A-Z])*)/i);
  const energyMatch = remainder.match(/Energy:\s*([^.]*(?:\.[^A-Z])*)/i);

  if (mindMatch) {
    result.effects.push({ domain: 'Mind', text: mindMatch[1].trim().replace(/\.$/, '') });
  }
  if (energyMatch) {
    result.effects.push({ domain: 'Energy', text: energyMatch[1].trim().replace(/\.$/, '') });
  }

  // If no domains parsed, put the full remainder as a single effect
  if (result.effects.length === 0 && remainder.trim()) {
    result.effects.push({ domain: 'Status', text: remainder.trim() });
  }

  return result;
}

function _isDataEmpty(data) {
  return (
    data.sleep.total_sleep_hrs === 0 &&
    data.garmin.steps === 0 &&
    data.readiness.score === 0
  );
}

function _buildSleepContextItems(sl) {
  const items = [];

  // Bedtime variability
  const bedVar = _num(sl.bedtime_variability_7d);
  if (bedVar > 0) {
    let status = 'green';
    if (bedVar > 60) status = 'red';
    else if (bedVar > 30) status = 'yellow';
    items.push({ label: 'Bed variability', value: `+-${bedVar}min`, status: status });
  }

  // Wake variability
  const wakeVar = _num(sl.wake_variability_7d);
  if (wakeVar > 0) {
    let status = 'green';
    if (wakeVar > 60) status = 'red';
    else if (wakeVar > 30) status = 'yellow';
    items.push({ label: 'Wake variability', value: `+-${wakeVar}min`, status: status });
  }

  // Body battery gained
  const bbGained = _num(sl.body_battery_gained);
  if (bbGained > 0) {
    let status = 'green';
    if (bbGained < 15) status = 'red';
    else if (bbGained < 40) status = 'yellow';
    items.push({ label: 'Battery gained', value: `+${bbGained}`, status: status });
  }

  // If no items could be built, return a placeholder
  if (items.length === 0) {
    items.push({ label: 'Sleep data', value: 'loading...', status: 'yellow' });
  }

  return items;
}

// ============================================
// Pull-to-Refresh — Cloud Sync via Edge Function
// ============================================

/**
 * Trigger a full data refresh via the Supabase Edge Function.
 * The Edge Function calls the Google Cloud Function which fetches Garmin data,
 * runs sleep analysis, and writes to Supabase. No secrets in the browser.
 *
 * @param {string|null} date - Optional "YYYY-MM-DD" (defaults to yesterday)
 * @returns {object} Result with status and sync info
 */
async function triggerCloudRefresh(date = null) {
  // Require auth — Edge Function validates JWT
  const user = await requireAuth();
  if (!user) {
    return { status: 'error', error: 'Authentication required for sync' };
  }

  const edgeFnUrl = (typeof EDGE_FUNCTION_URL !== 'undefined' && EDGE_FUNCTION_URL)
    ? EDGE_FUNCTION_URL
    : `${SUPABASE_URL}/functions/v1/refresh`;

  if (!edgeFnUrl || edgeFnUrl.includes('undefined')) {
    return { status: 'error', error: 'Edge Function URL not configured' };
  }

  const targetDate = date || new Date(Date.now() - 86400000).toISOString().slice(0, 10);

  try {
    // Force a token refresh if expired before hitting the Edge Function.
    // getSession() can return a stale JWT; refreshSession() ensures a valid one.
    let session;
    const { data: current } = await htSupabase.auth.getSession();
    if (current?.session?.expires_at && current.session.expires_at * 1000 < Date.now() + 30000) {
      // Token expires within 30s — refresh it
      const { data: refreshed } = await htSupabase.auth.refreshSession();
      session = refreshed?.session || current?.session;
    } else {
      session = current?.session;
    }

    const authHeaders = { 'Content-Type': 'application/json' };
    if (session?.access_token) {
      authHeaders['Authorization'] = `Bearer ${session.access_token}`;
      authHeaders['apikey'] = SUPABASE_ANON_KEY;
    }

    const res = await fetch(edgeFnUrl, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ date: targetDate }),
    });

    if (res.status === 429) {
      const body = await res.json().catch(() => ({}));
      return { status: 'error', error: `Rate limited — retry in ${body.retry_after_seconds || 300}s` };
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { status: 'error', error: body.error || `HTTP ${res.status}` };
    }

    const result = await res.json();
    return { status: 'success', date: targetDate, ...result };
  } catch (err) {
    return { status: 'error', error: err.message };
  }
}

/**
 * Quick readiness estimate from raw Garmin metrics (client-side).
 * Used for "Preliminary" readiness when full analysis hasn't run yet.
 * Mirrors cloud_function/main.py _estimate_readiness().
 *
 * @param {object} garmin - Garmin data object from SAMPLE_DATA.today.garmin
 * @param {object} sleep  - Sleep data object from SAMPLE_DATA.today.sleep
 * @returns {number|null} 1-10 score, or null if insufficient data
 */
function estimateReadiness(garmin, sleep) {
  const weights = {
    sleep_score:   { weight: 0.30, min: 40, max: 90, val: sleep?.garmin_score },
    hrv:           { weight: 0.25, min: 20, max: 80, val: garmin?.hrv_overnight },
    body_battery:  { weight: 0.20, min: 10, max: 80, val: garmin?.body_battery },
    resting_hr:    { weight: 0.15, min: 45, max: 75, val: garmin?.resting_hr, invert: true },
    avg_stress:    { weight: 0.10, min: 15, max: 60, val: garmin?.avg_stress, invert: true },
  };

  let totalWeight = 0;
  let weightedSum = 0;

  for (const [, cfg] of Object.entries(weights)) {
    const val = parseFloat(cfg.val);
    if (isNaN(val) || val === 0) continue;
    let normalized = Math.max(0, Math.min(1, (val - cfg.min) / (cfg.max - cfg.min)));
    if (cfg.invert) normalized = 1 - normalized;
    weightedSum += normalized * cfg.weight;
    totalWeight += cfg.weight;
  }

  if (totalWeight < 0.3) return null;
  const raw = weightedSum / totalWeight;
  return Math.max(1, Math.min(10, Math.round(raw * 9 + 1)));
}

// ============================================
// Initialization
// ============================================

/**
 * Fetch all live data from Supabase and populate SAMPLE_DATA.
 * Call this before rendering any page.
 *
 * Returns a promise that resolves when data is ready.
 * On failure, SAMPLE_DATA._error will contain the error message
 * and today/history/sessions will be null/empty (pages should
 * handle gracefully).
 */
async function initData() {
  // Require auth — shows login modal on first visit, silent restore after
  await checkAuth();

  // Initialize encrypted localStorage (derives key from user session)
  try {
    const { data: { session } } = await htSupabase.auth.getSession();
    if (session?.user?.id) {
      await CryptoStore.init(session.user.id);
    }
  } catch (e) {
    console.warn('[data-loader] CryptoStore init failed:', e.message);
  }

  // Flush any offline-queued writes if already authenticated
  await flushOfflineQueue();

  try {
    // Try RPC-based fetch first (2 round-trips instead of 14)
    let usedRpc = false;
    try {
      const rpcResult = await _fetchViaRpc();
      SAMPLE_DATA.today = rpcResult.today;
      SAMPLE_DATA.history = rpcResult.history;
      SAMPLE_DATA.sessions_history = rpcResult.sessions_history;
      SAMPLE_DATA._loaded = true;
      SAMPLE_DATA._error = null;
      usedRpc = true;
      console.log('[data-loader] Loaded via RPC (2 queries)');
    } catch (rpcErr) {
      console.log('[data-loader] RPC not available, falling back to per-table queries:', rpcErr.message);
    }

    // Fallback: per-table queries (14 round-trips)
    if (!usedRpc) {
      const results = await Promise.allSettled([
        fetchToday(),
        fetchHistory(90),
        fetchSessions(365),
      ]);

      const [todayResult, historyResult, sessionsResult] = results;

      if (todayResult.status === 'fulfilled') {
        SAMPLE_DATA.today = todayResult.value;
      } else {
        console.error('[data-loader] fetchToday failed:', todayResult.reason);
        SAMPLE_DATA.today = _buildFallbackToday();
      }

      if (historyResult.status === 'fulfilled') {
        SAMPLE_DATA.history = historyResult.value;
      } else {
        console.error('[data-loader] fetchHistory failed:', historyResult.reason);
      }

      if (sessionsResult.status === 'fulfilled') {
        SAMPLE_DATA.sessions_history = sessionsResult.value;
      } else {
        console.error('[data-loader] fetchSessions failed:', sessionsResult.reason);
      }

      SAMPLE_DATA._loaded = true;
      const anyFailed = results.some(r => r.status === 'rejected');
      if (anyFailed) {
        SAMPLE_DATA._error = 'Some queries failed — check console';
      } else {
        SAMPLE_DATA._error = null;
      }
    }

    // loaded
  } catch (err) {
    console.error('[data-loader] Critical failure:', err);
    SAMPLE_DATA._error = err.message;
    SAMPLE_DATA._loaded = false;
    SAMPLE_DATA.today = _buildFallbackToday();
  }

  // Show error banner if any queries failed
  _showDataError();

  return SAMPLE_DATA;
}

/**
 * Show a visible error banner at the top of the page if data loading failed.
 */
function _showDataError() {
  if (!SAMPLE_DATA._error) return;
  const banner = document.createElement('div');
  banner.style.cssText = 'position:fixed;top:0;left:0;right:0;padding:8px 16px;background:#F87171;color:white;font-size:12px;z-index:9999;text-align:center;font-family:system-ui,sans-serif;';
  banner.textContent = 'Data load error: ' + SAMPLE_DATA._error;
  document.body.prepend(banner);
}

/**
 * Build a minimal empty today object so pages don't throw on property access.
 */
function _buildFallbackToday() {
  const today = _todayStr();
  return {
    date: today,
    day: _dayOfWeek(today),
    readiness: { score: 0, label: '--', confidence: '--', cognitive_assessment: '', sleep_context: '', key_insights: [], recommendations: [], training_load: '', cognition: 0, cognition_notes: '' },
    sleep: { garmin_score: 0, analysis_score: 0, total_sleep_hrs: 0, bedtime: '', wake_time: '', time_in_bed_hrs: 0, deep_min: 0, light_min: 0, rem_min: 0, awake_min: 0, deep_pct: 0, rem_pct: 0, sleep_cycles: 0, awakenings: 0, avg_hr: 0, avg_respiration: 0, overnight_hrv: 0, body_battery_gained: 0, bedtime_var_7d: 0, wake_var_7d: 0, notes: '', sleep_feedback: '--', analysis_text: '' },
    garmin: { hrv_overnight: 0, hrv_7day_avg: 0, resting_hr: 0, body_battery: 0, body_battery_wake: 0, body_battery_high: 0, body_battery_low: 0, steps: 0, floors: 0, total_calories: 0, active_calories: 0, bmr_calories: 0, avg_stress: 0, stress_qualifier: '', moderate_intensity_min: 0, vigorous_intensity_min: 0 },
    daily_log: { morning_energy: 0, habits: { wake_930: false, no_morning_screens: false, creatine_hydrate: false, walk_breathing: false, physical_activity: false, no_screens_bed: false, bed_10pm: false }, habits_total: 0, midday: { energy: 0, focus: 0, mood: 0, body_feel: 0, notes: '' }, evening: { energy: 0, focus: 0, mood: 0 }, perceived_stress: 0, day_rating: 0, evening_notes: '' },
    sessions: [],
    strength: [],
    nutrition: { total_calories_burned: 0, active_calories: 0, bmr_calories: 0, breakfast: '', lunch: '', dinner: '', snacks: '', total_calories_consumed: 0, protein_g: 0, carbs_g: 0, fats_g: 0, water_l: 0, calorie_balance: 0, notes: '' },
    briefing: { expect: { level: '--', effects: [] }, sleep_line: '--', sleep_debt: '0h', sleep_context_items: [{ label: 'No data', value: '--', status: 'yellow' }], sleep_context: '', flags: [], do_items: [] },
  };
}

// ============================================
// Color Utility Functions
// Ported from dashboard_template.html getColor()
// ============================================

function getStatusColor(value, metric) {
  const t = SAMPLE_DATA.thresholds[metric];
  if (!t) return '#9CA3AF';

  let ratio;
  if (t.type === 'higher_better') {
    if (value <= t.red) ratio = 0;
    else if (value >= t.green) ratio = 1;
    else if (value <= t.yellow) ratio = (value - t.red) / (t.yellow - t.red) * 0.5;
    else ratio = 0.5 + (value - t.yellow) / (t.green - t.yellow) * 0.5;
  } else {
    if (value >= t.red) ratio = 0;
    else if (value <= t.green) ratio = 1;
    else if (value >= t.yellow) ratio = (t.red - value) / (t.red - t.yellow) * 0.5;
    else ratio = 0.5 + (t.yellow - value) / (t.yellow - t.green) * 0.5;
  }

  ratio = Math.max(0, Math.min(1, ratio));

  // HSL interpolation (from dashboard getColor)
  let h, s, l;
  if (ratio <= 0.5) {
    const p = ratio / 0.5;
    h = 0 + p * 45;       // coral red (0) -> yellow (45)
    s = 86 - p * 16;      // 86% -> 70%
    l = 71 - p * 11;      // 71% -> 60%
  } else {
    const p = (ratio - 0.5) / 0.5;
    h = 45 + p * 95;
    s = 70 - p * 25;
    l = 46 + p * 4;
  }
  return `hsl(${h}, ${s}%, ${l}%)`;
}

// Text color matching dashboard/Sheets color grading (same HSL curves as dashboard getColor)
function getStatusTextColor(value, metric) {
  const t = SAMPLE_DATA.thresholds[metric];
  if (!t) return '#6B7280';

  let ratio;
  if (t.type === 'higher_better') {
    if (value <= t.red) ratio = 0;
    else if (value >= t.green) ratio = 1;
    else if (value <= t.yellow) ratio = (value - t.red) / (t.yellow - t.red) * 0.5;
    else ratio = 0.5 + (value - t.yellow) / (t.green - t.yellow) * 0.5;
  } else {
    if (value >= t.red) ratio = 0;
    else if (value <= t.green) ratio = 1;
    else if (value >= t.yellow) ratio = (t.red - value) / (t.red - t.yellow) * 0.5;
    else ratio = 0.5 + (t.yellow - value) / (t.yellow - t.green) * 0.5;
  }

  ratio = Math.max(0, Math.min(1, ratio));

  // Match dashboard getColor() HSL curves exactly
  let h, s, l;
  if (ratio <= 0.5) {
    const p = ratio / 0.5;
    h = 0 + p * 45;       // red (0) -> yellow (45)
    s = 65 + p * 5;       // 65% -> 70%
    l = 38 + p * 8;       // 38% -> 46%
  } else {
    const p = (ratio - 0.5) / 0.5;
    h = 45 + p * 95;      // yellow (45) -> green (140)
    s = 70 - p * 15;      // 70% -> 55%
    l = 46 - p * 8;       // 46% -> 38%
  }
  return `hsl(${h}, ${s}%, ${l}%)`;
}

// Determine if a color is light (for text contrast on colored backgrounds)
function isLightColor(hslStr) {
  const match = hslStr.match(/hsl\(([\d.]+),\s*([\d.]+)%,\s*([\d.]+)%\)/);
  if (!match) return true;
  return parseFloat(match[3]) > 55;
}

// Simple status class (green/yellow/red)
function getStatusClass(value, metric) {
  const t = SAMPLE_DATA.thresholds[metric];
  if (!t) return '';

  if (t.type === 'higher_better') {
    if (value >= t.green) return 'green';
    if (value >= t.yellow) return 'yellow';
    return 'red';
  } else {
    if (value <= t.green) return 'green';
    if (value <= t.yellow) return 'yellow';
    return 'red';
  }
}

// Create SVG circular gauge with gradient stroke
// gradientId must be unique per gauge instance
let _gaugeCounter = 0;
function createGauge(value, max, color, size = 'lg', gradientColors = null) {
  const sizes = { lg: { r: 54, sw: 8, w: 130 }, md: { r: 36, sw: 7, w: 90 }, sm: { r: 24, sw: 6, w: 60 } };
  const s = sizes[size];
  const circumference = 2 * Math.PI * s.r;
  const pct = Math.min(value / max, 1);
  const offset = circumference * (1 - pct);
  const gId = `gaugeGrad${_gaugeCounter++}`;

  const gradDef = gradientColors
    ? `<defs><linearGradient id="${gId}" x1="0%" y1="0%" x2="100%" y2="100%">
        ${gradientColors.map((c, i) => `<stop offset="${Math.round(i / (gradientColors.length - 1) * 100)}%" stop-color="${c}" />`).join('')}
       </linearGradient></defs>`
    : '';
  const strokeAttr = gradientColors ? `url(#${gId})` : color;

  return `
    <svg width="${s.w}" height="${s.w}" viewBox="0 0 ${s.w} ${s.w}">
      ${gradDef}
      <circle cx="${s.w / 2}" cy="${s.w / 2}" r="${s.r}" class="gauge-track" stroke-width="${s.sw}" />
      <circle cx="${s.w / 2}" cy="${s.w / 2}" r="${s.r}" class="gauge-fill"
        stroke="${strokeAttr}" stroke-width="${s.sw}"
        stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"
        stroke-linecap="round" />
    </svg>`;
}
