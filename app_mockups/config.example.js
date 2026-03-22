// Health Tracker PWA — Configuration
// 1. Copy this file to config.js
// 2. Replace the placeholder values with your credentials
// 3. config.js is gitignored and will NOT be committed

const SUPABASE_URL = 'https://YOUR_PROJECT_ID.supabase.co';
const SUPABASE_ANON_KEY = 'your-supabase-anon-key-here';
const USER_NAME = 'Your Name';

// Cloud refresh — GitHub Actions workflow_dispatch (pull-to-refresh)
// Create a fine-grained PAT at github.com/settings/tokens with Actions: Read & Write on this repo
const GITHUB_PAT = '';  // Fine-grained PAT — actions:write on this repo only
const GITHUB_REPO = 'owner/repo-name';
