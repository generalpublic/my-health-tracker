# Security & PHI Rules (Non-Negotiable)

Security rules for credentials and Protected Health Information.

---

## Credential Rules

### I Will NEVER:
- Ask the user to type or paste a password, API key, private key, or secret into this conversation
- Ask the user to share a new credential after they've rotated it
- Read a credentials file (JSON, .env, .pem, or similar) — doing so exposes its contents in the VSCode diff panel
- Ask the user to confirm what a new password or key is

### When Credentials Need to Be Created or Updated
- Tell the user exactly what to do and where, then have them do it themselves in a text editor or Command Prompt
- For passwords: provide the exact `keyring` command for them to run in Command Prompt — they run it, never paste the result back here
- For JSON key files: tell the user to update the filename in `.env` themselves using Notepad
- Verify everything works by running the script directly — never by reading credential files

### If a Credential Is Accidentally Exposed
1. Flag it immediately and clearly
2. Tell the user exactly what to rotate (password or key) and the steps to do it
3. Remind them NOT to share the new credential here
4. Confirm the fix by running the script

### The User Should Never:
- Paste passwords, keys, or secrets into this chat
- Share new credentials after rotating them
- Copy/paste the contents of any JSON key file here

---

## Security Check — Session Start
Before doing any work:
1. Confirm which credentials are in use (Garmin password in keyring, Google key filename in .env)
2. Check if any credentials were exposed in the previous session and flag any that still need rotating
3. Run `garmin_sync.py` to verify everything works without reading any credential files
4. Report the security status clearly before proceeding
5. If anything is unresolved, stop and address it before moving on

## Security Check — During Session
- Before editing any file, confirm it contains no credentials
- If a system reminder or diff reveals a credential, flag it immediately and follow the exposure protocol above

---

## Health Profile PHI Security

The `profiles/` directory contains Protected Health Information (PHI). These rules prevent PHI from leaking into tracked files, external services, or cross-project logs.

### PHI Boundaries
| Location | PHI Allowed? | Rule |
|----------|-------------|------|
| `profiles/` | Yes | Gitignored — the PHI boundary |
| Google Sheets | Yes | User's private cloud data store |
| Pushover notifications | **Sanitized only** | Use `sanitize_for_notification()` — strips condition/med names |
| `.claude/projects/*/memory/` | **NO** | Counts and categories only, never names or values |
| `.today_work.md`, `WORKLOG.md`, `BILLING.md` | **NO** | Generic: "Updated profile with lab results" |
| Commit messages | **NO** | "Updated health profile" not "Added ADHD diagnosis" |
| `SESSION.md` | **NO** | Capabilities built, not medical details |
| `CLAUDE.md` | **NO** | Rules and structure, not data |
| Terminal / stdout | **Counts only** | "2 conditions, 12 biomarkers" — never names or values |
| `reference/` (committed) | **NO** | `/update-intel` guard rejects medical docs |

### Skill Cross-Contamination Guards
| Skill | Guard | Action |
|-------|-------|--------|
| `/update-intel` | File from `profiles/` or `Priv -` dir | Reject -> redirect to `/update-profile` |
| `/update-profile` | File from `reference/transcripts/` or `reference/books/` | Reject -> redirect to `/update-intel` |
| `/verify-intel` | First-person medical claim ("my blood work", "I was diagnosed") | Warn -> redirect to `/update-profile` |

### Key Files
- `profile_loader.py` — committed loader module (no PHI, prints counts only)
- `profiles/<name>/profile.json` — gitignored master profile
- `profiles/<name>/profile_summary.md` — gitignored token-efficient summary
- `.claude/skills/update-profile/SKILL.md` — committed ingestion skill definition
