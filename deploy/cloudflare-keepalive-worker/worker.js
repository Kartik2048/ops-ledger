/**
 * Cloudflare Worker: 12-Minute Keep-Alive Cron
 * Pings Render backend and Supabase pooler via /api/health to prevent:
 * 1. Render Free-Tier Web Service idle spin-down (15-minute inactivity limit).
 * 2. Supabase Free-Tier database auto-pause (7-day inactivity pause).
 */

export default {
  async scheduled(event, env, ctx) {
    const healthUrl = env.BACKEND_HEALTH_URL || "https://your-render-app.onrender.com/api/health";
    console.log(`[Keep-Alive Cron Triggered] Pinging: ${healthUrl}`);

    try {
      const response = await fetch(healthUrl, {
        method: "GET",
        headers: {
          "User-Agent": "Newtonite-KeepAlive-Worker/1.0",
          "Accept": "application/json",
        },
      });

      const responseText = await response.text();
      console.log(`[Keep-Alive Response] Status: ${response.status} ${response.statusText} - Body: ${responseText.slice(0, 150)}`);
    } catch (error) {
      console.error(`[Keep-Alive Error] Failed to ping ${healthUrl}:`, error);
    }
  },

  async fetch(request, env, ctx) {
    const healthUrl = env.BACKEND_HEALTH_URL || "https://your-render-app.onrender.com/api/health";
    return new Response(
      JSON.stringify(
        {
          service: "newtonite-cloudflare-keepalive-worker",
          status: "active",
          schedule: "*/12 * * * * (Every 12 minutes)",
          target_health_url: healthUrl,
        },
        null,
        2
      ),
      {
        headers: { "Content-Type": "application/json" },
      }
    );
  },
};
