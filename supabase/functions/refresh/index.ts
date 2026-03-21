/**
 * Supabase Edge Function — Pull-to-refresh trigger.
 *
 * Receives POST from PWA, rate limits (1 per 5 min), calls Google Cloud Function,
 * returns result to PWA.
 *
 * Deploy: supabase functions deploy refresh --no-verify-jwt
 *
 * Env vars (set via supabase secrets set):
 *   GCF_URL          — Google Cloud Function URL
 *   REFRESH_SECRET   — Shared secret for GCF auth
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const RATE_LIMIT_SECONDS = 300; // 5 minutes
const GCF_URL = Deno.env.get("GCF_URL") ?? "";
const REFRESH_SECRET = Deno.env.get("REFRESH_SECRET") ?? "";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

// In-memory rate limit (resets on cold start — acceptable for this use case)
const lastRefresh = new Map<string, number>();

serve(async (req: Request) => {
  // CORS preflight
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  if (req.method !== "POST") {
    return new Response(
      JSON.stringify({ error: "Method not allowed" }),
      { status: 405, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }

  try {
    // Rate limit by Authorization header (user identity) or IP
    const clientId = req.headers.get("Authorization") ?? "anonymous";
    const now = Date.now();
    const last = lastRefresh.get(clientId) ?? 0;
    const elapsed = (now - last) / 1000;

    if (elapsed < RATE_LIMIT_SECONDS) {
      const remaining = Math.ceil(RATE_LIMIT_SECONDS - elapsed);
      return new Response(
        JSON.stringify({ error: "Rate limited", retry_after_seconds: remaining }),
        { status: 429, headers: { ...corsHeaders, "Content-Type": "application/json" } }
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

    if (!GCF_URL) {
      return new Response(
        JSON.stringify({ error: "GCF_URL not configured" }),
        { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // Forward to Google Cloud Function
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
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      }
    );
  } catch (err) {
    return new Response(
      JSON.stringify({ error: String(err) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
