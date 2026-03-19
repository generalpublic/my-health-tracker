// ============================================
// Health Tracker App — Sample Data
// Realistic values for March 2026 mockups
// Thresholds from thresholds.json
// ============================================

const SAMPLE_DATA = {

  // --- Thresholds (from thresholds.json) ---
  thresholds: {
    readiness_score:      { type: "higher_better", red: 4, yellow: 5.5, green: 7 },
    sleep_analysis_score: { type: "higher_better", red: 50, yellow: 65, green: 75 },
    total_sleep_hrs:      { type: "higher_better", red: 5, yellow: 7, green: 8 },
    overnight_hrv_ms:     { type: "higher_better", red: 30, yellow: 40, green: 48 },
    body_battery:         { type: "higher_better", red: 20, yellow: 50, green: 80 },
    body_battery_gained:  { type: "higher_better", red: 15, yellow: 40, green: 65 },
    resting_hr:           { type: "lower_better",  green: 48, yellow: 55, red: 65 },
    avg_stress_level:     { type: "lower_better",  green: 15, yellow: 30, red: 50 },
    steps:                { type: "higher_better", red: 3000, yellow: 7000, green: 10000 },
    habits_total:         { type: "higher_better", red: 2, yellow: 4, green: 6 },
    day_rating:           { type: "higher_better", red: 1, yellow: 5.5, green: 10 },
    morning_energy:       { type: "higher_better", red: 1, yellow: 5.5, green: 10 },
    cognition:            { type: "higher_better", red: 1, yellow: 5, green: 10 },
    deep_pct:             { type: "higher_better", red: 12, yellow: 18, green: 22 },
    rem_pct:              { type: "higher_better", red: 15, yellow: 20, green: 25 },
    bedtime_var:          { type: "lower_better",  green: 30, yellow: 60, red: 90 },
    wake_var:             { type: "lower_better",  green: 30, yellow: 60, red: 90 },
    workout_duration:     { type: "higher_better", red: 15, yellow: 35, green: 60 },
    workout_calories:     { type: "higher_better", red: 100, yellow: 400, green: 900 },
    aerobic_te:           { type: "higher_better", red: 1, yellow: 2.5, green: 4 },
    awake_min:            { type: "lower_better",  green: 15, yellow: 30, red: 60 },
  },

  // Sleep stage target percentages (green thresholds from thresholds.json)
  // Used for mini progress bars: target_min = total_sleep_min × (pct / 100)
  sleep_stage_targets: {
    deep_pct: 22,   // deep_pct green threshold
    rem_pct: 25,    // rem_pct green threshold
    awake_max: 15,  // awake_min green threshold (fixed, not %)
    // light has no explicit target — fills remainder
  },

  // --- Today's data (March 18, 2026) ---
  today: {
    date: "2026-03-18",
    day: "Wed",

    // Overall Analysis
    readiness: {
      score: 7.8,
      label: "Good",
      confidence: "High",
      cognitive_assessment: "Above baseline. Mind: attention fully available, working memory intact. Energy: strong recovery, expect sustained output through afternoon.",
      sleep_context: "Solid 7.5h with good deep sleep architecture. HRV recovering above 7-day mean. Second consecutive night above target bedtime — consistency building.",
      key_insights: [
        "HRV trending upward (+4ms vs 7-day avg) — recovery on track",
        "Deep sleep 21% meets clinical threshold for memory consolidation",
        "Body Battery gained 62 — strong overnight recharge",
        "Bedtime variability down to 18min — best consistency this month"
      ],
      recommendations: [
        "Prioritize rest and recovery. Light walking or NSDR (non-sleep deep rest) only — avoid high-intensity training. Cognitive capacity is likely reduced; defer important decisions if possible.",
        "Plan to be off screens by 8 PM and in bed by 9-9:30 PM tonight to begin recovering sleep debt."
      ],
      training_load: "ACWR: 1.08 — Sweet Spot",
      cognition: 8,
      cognition_notes: "Sharp focus, good recall"
    },

    // Sleep
    sleep: {
      garmin_score: 82,
      analysis_score: 78,
      total_sleep_hrs: 7.5,
      bedtime: "22:34",
      wake_time: "6:15",
      time_in_bed_hrs: 7.68,
      deep_min: 92,
      light_min: 198,
      rem_min: 85,
      awake_min: 15,
      deep_pct: 21,
      rem_pct: 19,
      sleep_cycles: 5,
      awakenings: 2,
      avg_hr: 54,
      avg_respiration: 15.8,
      overnight_hrv: 46,
      body_battery_gained: 62,
      bedtime_var_7d: 18,
      wake_var_7d: 24,
      notes: "",
      sleep_feedback: "GOOD",
      analysis_text: "GOOD — Sufficient deep sleep preserved recovery. Strong sleep architecture with 5 complete cycles. Bedtime consistency improving — 3rd night under 11 PM this week."
    },

    // Garmin daily
    garmin: {
      hrv_overnight: 46,
      hrv_7day_avg: 42,
      resting_hr: 52,
      body_battery: 82,
      body_battery_wake: 78,
      body_battery_high: 85,
      body_battery_low: 34,
      steps: 8742,
      floors: 6,
      total_calories: 2380,
      active_calories: 680,
      bmr_calories: 1700,
      avg_stress: 22,
      stress_qualifier: "Low",
      moderate_intensity_min: 25,
      vigorous_intensity_min: 18
    },

    // Daily Log
    daily_log: {
      morning_energy: 7,
      habits: {
        wake_930: true,
        no_morning_screens: true,
        creatine_hydrate: true,
        walk_breathing: true,
        physical_activity: true,
        no_screens_bed: false,
        bed_10pm: false
      },
      habits_total: 5,
      midday: { energy: 7, focus: 8, mood: 7, body_feel: 7, notes: "" },
      evening: { energy: 6, focus: 7, mood: 7 },
      perceived_stress: 3,
      day_rating: 7,
      evening_notes: ""
    },

    // Sessions (today)
    sessions: [
      {
        activity_name: "Morning Run",
        activity_type: "running",
        duration_min: 42,
        distance_mi: 3.8,
        avg_hr: 148,
        max_hr: 172,
        calories: 480,
        aerobic_te: 3.6,
        anaerobic_te: 1.2,
        zone_1_min: 3,
        zone_2_min: 8,
        zone_3_min: 18,
        zone_4_min: 11,
        zone_5_min: 2,
        perceived_effort: 6,
        post_workout_energy: 7,
        notes: "Felt easy, good pace"
      }
    ],

    // Strength (today)
    strength: [
      { muscle_group: "Chest", exercise: "Bench Press", weight: 155, reps: 8, rpe: 7, notes: "" },
      { muscle_group: "Chest", exercise: "Bench Press", weight: 155, reps: 8, rpe: 8, notes: "" },
      { muscle_group: "Chest", exercise: "Incline DB Press", weight: 50, reps: 10, rpe: 7, notes: "" },
      { muscle_group: "Back", exercise: "Barbell Row", weight: 135, reps: 10, rpe: 7, notes: "" },
      { muscle_group: "Back", exercise: "Barbell Row", weight: 135, reps: 10, rpe: 8, notes: "" }
    ],

    // Nutrition
    nutrition: {
      total_calories_burned: 2380,
      active_calories: 680,
      bmr_calories: 1700,
      breakfast: "3 eggs scrambled, whole wheat toast, avocado, coffee",
      lunch: "Grilled chicken salad, quinoa, mixed greens, olive oil dressing",
      dinner: "",
      snacks: "Greek yogurt, banana, almonds",
      total_calories_consumed: 1650,
      protein_g: 95,
      carbs_g: 180,
      fats_g: 62,
      water_l: 2.5,
      calorie_balance: -730,
      notes: ""
    },

    // Briefing (what would have been the Pushover notification)
    briefing: {
      expect: {
        level: "Above baseline",
        effects: [
          { domain: "Mind", text: "attention fully available, working memory intact" },
          { domain: "Energy", text: "strong recovery, expect sustained output through afternoon" }
        ]
      },
      sleep_line: "GOOD | 7.5h | Deep 21% | REM 19% | HRV 46ms | Bed 10:34pm",
      sleep_debt: "0h",
      sleep_context_items: [
        { label: "Sleep debt", value: "0h", status: "green" },
        { label: "Bed variability", value: "±18min", status: "green" },
        { label: "Deep sleep streak", value: ">20% for 3 nights", status: "green" }
      ],
      sleep_context: "7d: Bed +-18min | debt 0h | Deep held above 20% for 3 consecutive nights",
      flags: [
        "HRV recovering: +4ms vs 7-day avg (42ms) — parasympathetic rebound",
        "Body Battery Gained 62 — strong overnight recharge",
        "Bedtime consistency best this month (18min variability)",
        "Habits: missed No Screens, Bed at 10 PM"
      ],
      do_items: [
        "Normal training load is appropriate — body is ready for intensity",
        "Hold 10:30 PM bedtime tonight to lock in consistency gains"
      ]
    }
  },

  // --- Historical data (Jan–Mar 2026 for calendar + trends) ---
  history: [
    // January 2026 — rough month, poor sleep, inconsistent habits
    { date: "2026-01-01", readiness: 4.2, sleep_score: 42, total_sleep: 4.8, hrv: 25, rhr: 64, body_battery: 28, steps: 2100, stress: 48, habits: 1, day_rating: 3, morning_energy: 3, cognition: 4 },
    { date: "2026-01-02", readiness: 4.8, sleep_score: 48, total_sleep: 5.2, hrv: 27, rhr: 63, body_battery: 35, steps: 3200, stress: 44, habits: 2, day_rating: 3, morning_energy: 3, cognition: 4 },
    { date: "2026-01-03", readiness: 5.0, sleep_score: 50, total_sleep: 5.5, hrv: 28, rhr: 62, body_battery: 38, steps: 3500, stress: 42, habits: 2, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-01-04", readiness: 4.5, sleep_score: 44, total_sleep: 4.9, hrv: 24, rhr: 65, body_battery: 30, steps: 2800, stress: 46, habits: 1, day_rating: 3, morning_energy: 3, cognition: 4 },
    { date: "2026-01-05", readiness: 5.2, sleep_score: 52, total_sleep: 5.6, hrv: 29, rhr: 61, body_battery: 42, steps: 4200, stress: 40, habits: 2, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-01-06", readiness: 5.5, sleep_score: 55, total_sleep: 5.8, hrv: 30, rhr: 60, body_battery: 45, steps: 5100, stress: 38, habits: 3, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-01-07", readiness: 5.8, sleep_score: 58, total_sleep: 6.2, hrv: 32, rhr: 59, body_battery: 50, steps: 5500, stress: 36, habits: 3, day_rating: 5, morning_energy: 5, cognition: 5 },
    { date: "2026-01-08", readiness: 4.9, sleep_score: 46, total_sleep: 5.0, hrv: 26, rhr: 63, body_battery: 33, steps: 3000, stress: 45, habits: 1, day_rating: 3, morning_energy: 3, cognition: 4 },
    { date: "2026-01-09", readiness: 5.1, sleep_score: 50, total_sleep: 5.4, hrv: 28, rhr: 62, body_battery: 40, steps: 3800, stress: 42, habits: 2, day_rating: 4, morning_energy: 4, cognition: 4 },
    { date: "2026-01-10", readiness: 5.6, sleep_score: 56, total_sleep: 6.0, hrv: 31, rhr: 60, body_battery: 48, steps: 4800, stress: 38, habits: 3, day_rating: 5, morning_energy: 5, cognition: 5 },
    { date: "2026-01-11", readiness: 4.6, sleep_score: 43, total_sleep: 4.7, hrv: 23, rhr: 65, body_battery: 28, steps: 2500, stress: 48, habits: 1, day_rating: 3, morning_energy: 2, cognition: 3 },
    { date: "2026-01-12", readiness: 5.3, sleep_score: 54, total_sleep: 5.7, hrv: 30, rhr: 61, body_battery: 44, steps: 4400, stress: 39, habits: 2, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-01-13", readiness: 5.7, sleep_score: 57, total_sleep: 6.1, hrv: 32, rhr: 59, body_battery: 50, steps: 5200, stress: 36, habits: 3, day_rating: 5, morning_energy: 5, cognition: 5 },
    { date: "2026-01-14", readiness: 6.0, sleep_score: 60, total_sleep: 6.4, hrv: 34, rhr: 58, body_battery: 54, steps: 5800, stress: 34, habits: 3, day_rating: 5, morning_energy: 5, cognition: 6 },
    { date: "2026-01-15", readiness: 5.0, sleep_score: 48, total_sleep: 5.1, hrv: 26, rhr: 63, body_battery: 36, steps: 3100, stress: 44, habits: 2, day_rating: 3, morning_energy: 3, cognition: 4 },
    { date: "2026-01-16", readiness: 5.4, sleep_score: 53, total_sleep: 5.6, hrv: 29, rhr: 61, body_battery: 42, steps: 4000, stress: 40, habits: 2, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-01-17", readiness: 5.9, sleep_score: 59, total_sleep: 6.3, hrv: 33, rhr: 59, body_battery: 52, steps: 5600, stress: 35, habits: 3, day_rating: 5, morning_energy: 5, cognition: 6 },
    { date: "2026-01-18", readiness: 6.2, sleep_score: 62, total_sleep: 6.5, hrv: 35, rhr: 58, body_battery: 56, steps: 6200, stress: 32, habits: 4, day_rating: 5, morning_energy: 5, cognition: 6 },
    { date: "2026-01-19", readiness: 5.1, sleep_score: 49, total_sleep: 5.2, hrv: 27, rhr: 62, body_battery: 38, steps: 3400, stress: 43, habits: 2, day_rating: 4, morning_energy: 3, cognition: 4 },
    { date: "2026-01-20", readiness: 5.5, sleep_score: 55, total_sleep: 5.9, hrv: 30, rhr: 60, body_battery: 46, steps: 4600, stress: 38, habits: 3, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-01-21", readiness: 6.0, sleep_score: 60, total_sleep: 6.4, hrv: 34, rhr: 58, body_battery: 55, steps: 5900, stress: 33, habits: 3, day_rating: 5, morning_energy: 5, cognition: 6 },
    { date: "2026-01-22", readiness: 5.3, sleep_score: 52, total_sleep: 5.5, hrv: 28, rhr: 61, body_battery: 40, steps: 3600, stress: 41, habits: 2, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-01-23", readiness: 5.7, sleep_score: 57, total_sleep: 6.0, hrv: 31, rhr: 60, body_battery: 48, steps: 5000, stress: 37, habits: 3, day_rating: 5, morning_energy: 5, cognition: 5 },
    { date: "2026-01-24", readiness: 6.1, sleep_score: 61, total_sleep: 6.5, hrv: 35, rhr: 58, body_battery: 56, steps: 6300, stress: 32, habits: 4, day_rating: 6, morning_energy: 5, cognition: 6 },
    { date: "2026-01-25", readiness: 4.8, sleep_score: 45, total_sleep: 4.9, hrv: 25, rhr: 64, body_battery: 32, steps: 2700, stress: 46, habits: 1, day_rating: 3, morning_energy: 3, cognition: 4 },
    { date: "2026-01-26", readiness: 5.4, sleep_score: 54, total_sleep: 5.7, hrv: 30, rhr: 61, body_battery: 44, steps: 4300, stress: 39, habits: 2, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-01-27", readiness: 5.8, sleep_score: 58, total_sleep: 6.2, hrv: 33, rhr: 59, body_battery: 52, steps: 5500, stress: 35, habits: 3, day_rating: 5, morning_energy: 5, cognition: 5 },
    { date: "2026-01-28", readiness: 6.3, sleep_score: 63, total_sleep: 6.6, hrv: 36, rhr: 57, body_battery: 58, steps: 6800, stress: 30, habits: 4, day_rating: 6, morning_energy: 6, cognition: 6 },
    { date: "2026-01-29", readiness: 5.2, sleep_score: 51, total_sleep: 5.3, hrv: 28, rhr: 62, body_battery: 38, steps: 3600, stress: 42, habits: 2, day_rating: 4, morning_energy: 4, cognition: 4 },
    { date: "2026-01-30", readiness: 5.6, sleep_score: 56, total_sleep: 5.9, hrv: 31, rhr: 60, body_battery: 46, steps: 4800, stress: 38, habits: 3, day_rating: 5, morning_energy: 4, cognition: 5 },
    { date: "2026-01-31", readiness: 6.0, sleep_score: 60, total_sleep: 6.3, hrv: 34, rhr: 58, body_battery: 54, steps: 5600, stress: 34, habits: 3, day_rating: 5, morning_energy: 5, cognition: 6 },
    // February 2026 — improving, building consistency
    { date: "2026-02-01", readiness: 5.8, sleep_score: 58, total_sleep: 6.1, hrv: 32, rhr: 59, body_battery: 50, steps: 5200, stress: 36, habits: 3, day_rating: 5, morning_energy: 5, cognition: 5 },
    { date: "2026-02-02", readiness: 6.2, sleep_score: 62, total_sleep: 6.5, hrv: 35, rhr: 58, body_battery: 56, steps: 6000, stress: 33, habits: 3, day_rating: 5, morning_energy: 5, cognition: 6 },
    { date: "2026-02-03", readiness: 6.5, sleep_score: 65, total_sleep: 6.8, hrv: 37, rhr: 57, body_battery: 60, steps: 6800, stress: 30, habits: 4, day_rating: 6, morning_energy: 6, cognition: 6 },
    { date: "2026-02-04", readiness: 5.5, sleep_score: 54, total_sleep: 5.6, hrv: 29, rhr: 61, body_battery: 42, steps: 4000, stress: 40, habits: 2, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-02-05", readiness: 6.0, sleep_score: 60, total_sleep: 6.3, hrv: 34, rhr: 58, body_battery: 54, steps: 5500, stress: 34, habits: 3, day_rating: 5, morning_energy: 5, cognition: 6 },
    { date: "2026-02-06", readiness: 6.6, sleep_score: 66, total_sleep: 6.9, hrv: 38, rhr: 56, body_battery: 62, steps: 7200, stress: 28, habits: 4, day_rating: 6, morning_energy: 6, cognition: 7 },
    { date: "2026-02-07", readiness: 7.0, sleep_score: 70, total_sleep: 7.2, hrv: 40, rhr: 55, body_battery: 68, steps: 7800, stress: 25, habits: 5, day_rating: 7, morning_energy: 7, cognition: 7 },
    { date: "2026-02-08", readiness: 5.8, sleep_score: 56, total_sleep: 5.8, hrv: 31, rhr: 60, body_battery: 46, steps: 3800, stress: 38, habits: 2, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-02-09", readiness: 6.3, sleep_score: 63, total_sleep: 6.6, hrv: 36, rhr: 57, body_battery: 58, steps: 6200, stress: 32, habits: 4, day_rating: 6, morning_energy: 5, cognition: 6 },
    { date: "2026-02-10", readiness: 6.8, sleep_score: 68, total_sleep: 7.0, hrv: 39, rhr: 56, body_battery: 64, steps: 7500, stress: 27, habits: 4, day_rating: 6, morning_energy: 6, cognition: 7 },
    { date: "2026-02-11", readiness: 5.6, sleep_score: 55, total_sleep: 5.7, hrv: 30, rhr: 60, body_battery: 44, steps: 4200, stress: 39, habits: 2, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-02-12", readiness: 6.4, sleep_score: 64, total_sleep: 6.7, hrv: 37, rhr: 57, body_battery: 60, steps: 6600, stress: 30, habits: 4, day_rating: 6, morning_energy: 6, cognition: 6 },
    { date: "2026-02-13", readiness: 7.0, sleep_score: 70, total_sleep: 7.1, hrv: 41, rhr: 55, body_battery: 68, steps: 8000, stress: 24, habits: 5, day_rating: 7, morning_energy: 7, cognition: 7 },
    { date: "2026-02-14", readiness: 7.3, sleep_score: 73, total_sleep: 7.4, hrv: 43, rhr: 54, body_battery: 72, steps: 8500, stress: 22, habits: 5, day_rating: 7, morning_energy: 7, cognition: 7 },
    { date: "2026-02-15", readiness: 5.9, sleep_score: 57, total_sleep: 5.9, hrv: 32, rhr: 59, body_battery: 48, steps: 4500, stress: 37, habits: 3, day_rating: 5, morning_energy: 4, cognition: 5 },
    { date: "2026-02-16", readiness: 6.5, sleep_score: 65, total_sleep: 6.8, hrv: 38, rhr: 56, body_battery: 62, steps: 7000, stress: 29, habits: 4, day_rating: 6, morning_energy: 6, cognition: 6 },
    { date: "2026-02-17", readiness: 7.1, sleep_score: 71, total_sleep: 7.2, hrv: 42, rhr: 54, body_battery: 70, steps: 8200, stress: 23, habits: 5, day_rating: 7, morning_energy: 7, cognition: 7 },
    { date: "2026-02-18", readiness: 6.7, sleep_score: 67, total_sleep: 6.9, hrv: 38, rhr: 56, body_battery: 62, steps: 6800, stress: 28, habits: 4, day_rating: 6, morning_energy: 6, cognition: 7 },
    { date: "2026-02-19", readiness: 6.1, sleep_score: 60, total_sleep: 6.2, hrv: 34, rhr: 58, body_battery: 52, steps: 5400, stress: 34, habits: 3, day_rating: 5, morning_energy: 5, cognition: 6 },
    { date: "2026-02-20", readiness: 6.8, sleep_score: 68, total_sleep: 7.0, hrv: 40, rhr: 55, body_battery: 66, steps: 7600, stress: 26, habits: 4, day_rating: 6, morning_energy: 6, cognition: 7 },
    { date: "2026-02-21", readiness: 7.2, sleep_score: 72, total_sleep: 7.3, hrv: 42, rhr: 54, body_battery: 70, steps: 8400, stress: 23, habits: 5, day_rating: 7, morning_energy: 7, cognition: 7 },
    { date: "2026-02-22", readiness: 6.0, sleep_score: 58, total_sleep: 6.0, hrv: 33, rhr: 59, body_battery: 48, steps: 4600, stress: 36, habits: 3, day_rating: 5, morning_energy: 4, cognition: 5 },
    { date: "2026-02-23", readiness: 6.6, sleep_score: 66, total_sleep: 6.9, hrv: 39, rhr: 56, body_battery: 64, steps: 7200, stress: 28, habits: 4, day_rating: 6, morning_energy: 6, cognition: 7 },
    { date: "2026-02-24", readiness: 7.0, sleep_score: 70, total_sleep: 7.1, hrv: 41, rhr: 55, body_battery: 68, steps: 8000, stress: 24, habits: 5, day_rating: 7, morning_energy: 7, cognition: 7 },
    { date: "2026-02-25", readiness: 6.3, sleep_score: 62, total_sleep: 6.4, hrv: 35, rhr: 58, body_battery: 54, steps: 5800, stress: 33, habits: 3, day_rating: 5, morning_energy: 5, cognition: 6 },
    { date: "2026-02-26", readiness: 6.9, sleep_score: 69, total_sleep: 7.0, hrv: 40, rhr: 55, body_battery: 66, steps: 7500, stress: 26, habits: 4, day_rating: 6, morning_energy: 6, cognition: 7 },
    { date: "2026-02-27", readiness: 7.2, sleep_score: 72, total_sleep: 7.3, hrv: 43, rhr: 54, body_battery: 72, steps: 8600, stress: 22, habits: 5, day_rating: 7, morning_energy: 7, cognition: 7 },
    { date: "2026-02-28", readiness: 6.5, sleep_score: 64, total_sleep: 6.6, hrv: 36, rhr: 57, body_battery: 58, steps: 6200, stress: 31, habits: 4, day_rating: 6, morning_energy: 5, cognition: 6 },
    // March 2026 — continued improvement, current month
    { date: "2026-03-01", readiness: 5.5, sleep_score: 52, total_sleep: 5.4, hrv: 30, rhr: 61, body_battery: 40, steps: 3800, stress: 40, habits: 2, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-03-02", readiness: 6.0, sleep_score: 58, total_sleep: 6.0, hrv: 33, rhr: 59, body_battery: 50, steps: 4500, stress: 35, habits: 3, day_rating: 5, morning_energy: 5, cognition: 5 },
    { date: "2026-03-03", readiness: 5.9, sleep_score: 56, total_sleep: 5.8, hrv: 31, rhr: 60, body_battery: 46, steps: 4100, stress: 37, habits: 2, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-03-04", readiness: 6.2, sleep_score: 62, total_sleep: 6.1, hrv: 35, rhr: 58, body_battery: 55, steps: 5200, stress: 32, habits: 3, day_rating: 5, morning_energy: 5, cognition: 6 },
    { date: "2026-03-05", readiness: 5.8, sleep_score: 55, total_sleep: 5.5, hrv: 32, rhr: 60, body_battery: 42, steps: 4800, stress: 38, habits: 2, day_rating: 4, morning_energy: 4, cognition: 5 },
    { date: "2026-03-06", readiness: 6.8, sleep_score: 68, total_sleep: 7.0, hrv: 38, rhr: 56, body_battery: 62, steps: 6500, stress: 28, habits: 4, day_rating: 6, morning_energy: 6, cognition: 7 },
    { date: "2026-03-07", readiness: 7.2, sleep_score: 72, total_sleep: 7.2, hrv: 41, rhr: 54, body_battery: 70, steps: 8100, stress: 24, habits: 5, day_rating: 7, morning_energy: 7, cognition: 7 },
    { date: "2026-03-08", readiness: 6.5, sleep_score: 60, total_sleep: 6.3, hrv: 36, rhr: 57, body_battery: 58, steps: 3200, stress: 35, habits: 3, day_rating: 5, morning_energy: 5, cognition: 6 },
    { date: "2026-03-09", readiness: 7.0, sleep_score: 70, total_sleep: 7.5, hrv: 40, rhr: 55, body_battery: 68, steps: 9200, stress: 25, habits: 5, day_rating: 7, morning_energy: 6, cognition: 7 },
    { date: "2026-03-10", readiness: 7.5, sleep_score: 74, total_sleep: 7.3, hrv: 43, rhr: 53, body_battery: 72, steps: 7800, stress: 22, habits: 5, day_rating: 7, morning_energy: 7, cognition: 8 },
    { date: "2026-03-11", readiness: 6.9, sleep_score: 66, total_sleep: 6.8, hrv: 39, rhr: 55, body_battery: 64, steps: 6100, stress: 30, habits: 4, day_rating: 6, morning_energy: 6, cognition: 6 },
    { date: "2026-03-12", readiness: 7.4, sleep_score: 75, total_sleep: 7.6, hrv: 44, rhr: 53, body_battery: 74, steps: 8900, stress: 20, habits: 6, day_rating: 8, morning_energy: 7, cognition: 8 },
    { date: "2026-03-13", readiness: 8.1, sleep_score: 80, total_sleep: 7.8, hrv: 47, rhr: 51, body_battery: 80, steps: 10200, stress: 18, habits: 6, day_rating: 8, morning_energy: 8, cognition: 8 },
    { date: "2026-03-14", readiness: 7.6, sleep_score: 76, total_sleep: 7.4, hrv: 44, rhr: 53, body_battery: 75, steps: 7600, stress: 23, habits: 5, day_rating: 7, morning_energy: 7, cognition: 7 },
    { date: "2026-03-15", readiness: 6.4, sleep_score: 58, total_sleep: 5.8, hrv: 34, rhr: 58, body_battery: 48, steps: 4500, stress: 36, habits: 3, day_rating: 5, morning_energy: 4, cognition: 5 },
    { date: "2026-03-16", readiness: 7.1, sleep_score: 71, total_sleep: 7.1, hrv: 42, rhr: 54, body_battery: 68, steps: 7200, stress: 26, habits: 5, day_rating: 6, morning_energy: 6, cognition: 7 },
    { date: "2026-03-17", readiness: 7.5, sleep_score: 76, total_sleep: 7.3, hrv: 44, rhr: 53, body_battery: 73, steps: 8400, stress: 21, habits: 5, day_rating: 7, morning_energy: 7, cognition: 7 },
    { date: "2026-03-18", readiness: 7.8, sleep_score: 78, total_sleep: 7.5, hrv: 46, rhr: 52, body_battery: 82, steps: 8742, stress: 22, habits: 5, day_rating: 7, morning_energy: 7, cognition: 8 },
  ],

  // --- Weekly sessions history ---
  sessions_history: [
    { date: "2026-03-14", activity_name: "Evening Walk", type: "walking", duration: 35, distance: 1.8, calories: 180, avg_hr: 105 },
    { date: "2026-03-15", activity_name: "Cycling", type: "cycling", duration: 55, distance: 14.2, calories: 520, avg_hr: 138 },
    { date: "2026-03-16", activity_name: "Morning Run", type: "running", duration: 38, distance: 3.4, calories: 420, avg_hr: 152 },
    { date: "2026-03-17", activity_name: "Strength Training", type: "strength", duration: 48, distance: 0, calories: 350, avg_hr: 122 },
    { date: "2026-03-18", activity_name: "Morning Run", type: "running", duration: 42, distance: 3.8, calories: 480, avg_hr: 148 },
  ]
};

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
    h = 12 + p * 33;
    s = 62 + p * 8;
    l = 60 + p * 0;
  } else {
    const p = (ratio - 0.5) / 0.5;
    h = 45 + p * 95;
    s = 70 - p * 25;
    l = 46 + p * 4;
  }
  return `hsl(${h}, ${s}%, ${l}%)`;
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
      <circle cx="${s.w/2}" cy="${s.w/2}" r="${s.r}" class="gauge-track" stroke-width="${s.sw}" />
      <circle cx="${s.w/2}" cy="${s.w/2}" r="${s.r}" class="gauge-fill"
        stroke="${strokeAttr}" stroke-width="${s.sw}"
        stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"
        stroke-linecap="round" />
    </svg>`;
}
