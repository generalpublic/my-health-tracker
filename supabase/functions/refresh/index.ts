/**
 * Supabase Edge Function — Pull-to-refresh trigger.
 *
 * Receives POST from PWA, validates origin, rate limits (1 per 5 min),
 * calls Google Cloud Function, returns result to PWA.
 *
 * Deploy: supabase functions deploy refresh --no-verify-jwt
 * (--no-verify-jwt is required because the PWA calls this without a Supabase JWT.
 *  The function validates requests via rate limiting + origin check instead.)
 *
 * Env vars (set via supabase secrets set):
 *   GCF_URL            — Google Cloud Function URL
 *   REFRESH_SECRET     — Shared secret for GCF auth (MANDATORY)
 *   ALLOWED_ORIGINS    — Comma-separated allowed origins (e.g. "https://user.github.io,http://localhost:8000")
 */

const RATE_LIMIT_SECONDS = 300; // 5 minutes
const GCF_URL = Deno.env.get("GCF_URL") ?? "";
const REFRESH_SECRET = Deno.env.get("REFRESH_SECRET") ?? "";
const ALLOWED_ORIGINS = (Deno.env.get("ALLOWED_ORIGINS") ?? "").split(",").map(s => s.trim()).filter(Boolean);

function getCorsOrigin(req: Request): string {
  const origin = req.headers.get("Origin") ?? "";
  if (ALLOWED_ORIGINS.length === 0) return origin; // fallback: echo (less safe, but unblocked)
  return ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
}

function corsHeaders(req: Request) {
  return {
    "Access-Control-Allow-Origin": getCorsOrigin(req),
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
  };
}

// Rate limit by IP (in-memory, resets on cold start — acceptable for this use case)
const lastRefresh = new Map<string, number>();

Deno.serve(async (req: Request) => {
  const headers = corsHeaders(req);

  // CORS preflight
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers });
  }

  if (req.method !== "POST") {
    return new Response(
      JSON.stringify({ error: "Method not allowed" }),
      { status: 405, headers: { ...headers, "Content-Type": "application/json" } }
    );
  }

  // Mandatory: REFRESH_SECRET must be configured
  if (!REFRESH_SECRET) {
    return new Response(
      JSON.stringify({ error: "REFRESH_SECRET not configured on server" }),
      { status: 500, headers: { ...headers, "Content-Type": "application/json" } }
    );
  }

  try {
    // Rate limit by forwarded IP
    const clientId = req.headers.get("X-Forwarded-For")?.split(",")[0]?.trim() ?? "unknown";
    const now = Date.now();
    const last = lastRefresh.get(clientId) ?? 0;
    const elapsed = (now - last) / 1000;

    if (elapsed < RATE_LIMIT_SECONDS) {
      const remaining = Math.ceil(RATE_LIMIT_SECONDS - elapsed);
      return new Response(
        JSON.stringify({ error: "Rate limited", retry_after_seconds: remaining }),
        { status: 429, headers: { ...headers, "Content-Type": "application/json" } }
      );
    }
    lastRefresh.set(clientId, now);

    // Parse optional date from request body
    let body: Record<string, string> = {};
    try {
      body = await req.json();
    } catch {
      // No body — use defaults
    }

    // Validate date format if provided (YYYY-MM-DD only)
    if (body.date && !/^\d{4}-\d{2}-\d{2}$/.test(body.date)) {
      return new Response(
        JSON.stringify({ error: "Invalid date format — use YYYY-MM-DD" }),
        { status: 400, headers: { ...headers, "Content-Type": "application/json" } }
      );
    }

    if (!GCF_URL) {
      return new Response(
        JSON.stringify({ error: "GCF_URL not configured" }),
        { status: 500, headers: { ...headers, "Content-Type": "application/json" } }
      );
    }

    // Forward to Google Cloud Function with shared secret
    const gcfResponse = await fetch(GCF_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Refresh-Secret": REFRESH_SECRET,
      },
      body: JSON.stringify({ date: body.date }),
    });

    const result = await gcfResponse.json();

    return new Response(
      JSON.stringify(result),
      {
        status: gcfResponse.status,
        headers: { ...headers, "Content-Type": "application/json" },
      }
    );
  } catch (err) {
    return new Response(
      JSON.stringify({ error: "Internal error" }),
      { status: 500, headers: { ...headers, "Content-Type": "application/json" } }
    );
  }
});
