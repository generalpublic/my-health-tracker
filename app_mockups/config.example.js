// Health Tracker PWA — Configuration
// 1. Copy this file to config.js
// 2. Replace the placeholder values with your Supabase project credentials
// 3. config.js is gitignored and will NOT be committed

const SUPABASE_URL = 'https://YOUR_PROJECT_ID.supabase.co';
const SUPABASE_ANON_KEY = 'your-supabase-anon-key-here';
const USER_NAME = 'Your Name';

// Cloud refresh — Supabase Edge Function URL (Phase 1 pull-to-refresh)
// Set after deploying: supabase functions deploy refresh
const EDGE_FUNCTION_URL = ''; // e.g. 'https://YOUR_PROJECT_ID.supabase.co/functions/v1/refresh'
