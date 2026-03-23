# Garmin Data Processing Rules (Non-Negotiable)

Rules for processing Garmin data from both export files and the Connect API. Learned from real bugs.

---

## Unit Conversions (Export File)
- Distance: stored in centimeters -> divide by 160,934.4 for miles
- Duration: stored in milliseconds -> divide by 60,000 for minutes
- Speed: stored as (m/s) * 10 -> multiply by 2.23694 for mph (or / 44.704 for mph directly)
- Elevation: stored in centimeters -> divide by 100 for meters
- HR zone time: stored in seconds -> divide by 60 for minutes

## Timezone Handling — Export File (String Timestamps)
- `sleepStartTimestampGMT` and `sleepEndTimestampGMT` are TRUE UTC — always convert to local before displaying
- Compute per-day UTC offset from UDS record: `wellnessStartTimeLocal - wellnessStartTimeGmt` in hours
- This automatically handles EST (-5) vs EDT (-4) DST transitions — never hardcode a single offset
- Default fallback if UDS record missing: -5 (EST)

## Timezone Handling — Connect API (Epoch Timestamps)
- NEVER use `sleepStartTimestampLocal` / `sleepEndTimestampLocal` — these are NOT reliable local times
- ALWAYS use `sleepStartTimestampGMT` / `sleepEndTimestampGMT` with `datetime.fromtimestamp(epoch_ms / 1000)` (no tz arg)
- `fromtimestamp()` without a tz argument converts UTC epoch to system local time — this is the correct behavior
- Bug history: v2.1 used "Local" fields without `tz=timezone.utc`, producing bedtime/wake times shifted by the timezone offset (4-5h). Downstream impact: +/-15 point sleep analysis score swing, inverted color grading, wrong analysis text

## Field Locations (Export File)
- HR zones: `hrTimeInZone_1` through `hrTimeInZone_5` on activity records (in seconds)
- Body battery gained during sleep: `statsType == "DURINGSLEEP"` in `wellnessBodBattStat` array
- Sleep bedtime/wake time: `sleepStartTimestampGMT` / `sleepEndTimestampGMT` on sleep records
- Stress qualifier: `averageStressLevel` on UDS records (sentinel -1 or -2 = no data, replace with "")
- Resting HR: sentinel 0 = no data, replace with ""

## Duplicate Detection for Multi-Activity Days
- Do NOT use date-only as duplicate key for Session Log — multiple workouts per day are valid
- Use `(date, activity_name)` as the composite key for deduplication
