const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

// Cache TTLs in seconds
const CACHE_TTL = {
  history: 15 * 60, // 15 minutes
  info: 30 * 60, // 30 minutes
  options: 5 * 60, // 5 minutes
};

/**
 * Outer loop of the dead-man's switch (spec A3 Layer 2).
 *
 * The inner loop lives on Hetzner, which is also where the app it checks runs.
 * A checker on the same box as the thing it checks cannot report that the box
 * is gone. This one is on Cloudflare: different provider, different failure
 * domain, free cron triggers, and — unlike GitHub Actions — no auto-disable
 * after 60 days of repo inactivity, which is the mechanism that silently
 * switched off all seven scheduled workflows during the outage.
 *
 * It is deliberately the dumbest thing that can work: one request, look at the
 * status code, push on anything that is not 200. That only became possible when
 * /api/cron/health started returning 503 on failure instead of 200 with
 * {"status":"fail"} in the body.
 *
 * A timeout counts as a failure. From out here, "Hetzner is unreachable" and
 * "the monitor is dead" are the same fact: nobody is watching the positions.
 *
 * Secrets (wrangler secret put): HEALTH_CRON_SECRET, PUSHOVER_TOKEN, PUSHOVER_USER.
 */
const HEALTH_URL = "https://options.imprevista.com/api/cron/health";
const HEALTH_TIMEOUT_MS = 20000;

async function pushover(env, title, message, priority) {
  if (!env.PUSHOVER_TOKEN || !env.PUSHOVER_USER) {
    console.error(`[watchdog] Pushover unconfigured — "${title}" NOT DELIVERED`);
    return false;
  }
  const body = new URLSearchParams({
    token: env.PUSHOVER_TOKEN,
    user: env.PUSHOVER_USER,
    title,
    message,
    priority: String(priority),
  });
  if (priority === 2) {
    body.set("retry", "60");
    body.set("expire", "600");
  }
  const resp = await fetch("https://api.pushover.net/1/messages.json", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!resp.ok) {
    console.error(`[watchdog] Pushover ${resp.status} — "${title}" NOT DELIVERED`);
    return false;
  }
  return true;
}

async function discord(env, title, message) {
  if (!env.DISCORD_WEBHOOK) {
    console.error(`[watchdog] Discord unconfigured — "${title}" NOT DELIVERED`);
    return false;
  }
  const resp = await fetch(env.DISCORD_WEBHOOK, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: `🚨 **${title}**\n${message}` }),
  });
  if (!resp.ok) {
    console.error(`[watchdog] Discord ${resp.status} — "${title}" NOT DELIVERED`);
    return false;
  }
  return true;
}

async function checkHealth(env) {
  if (!env.HEALTH_CRON_SECRET) {
    // Refuse to be a watchdog that cannot authenticate: every poll would 401,
    // which is indistinguishable from a real outage and would page continuously.
    console.error("[watchdog] HEALTH_CRON_SECRET unset — cannot check health");
    return { ok: false, detail: "watchdog misconfigured: HEALTH_CRON_SECRET unset" };
  }

  try {
    const resp = await fetch(HEALTH_URL, {
      headers: { Authorization: `Bearer ${env.HEALTH_CRON_SECRET}` },
      signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
    });
    if (resp.status === 200) return { ok: true, detail: "healthy" };
    const body = (await resp.text()).slice(0, 300);
    return { ok: false, detail: `HTTP ${resp.status}: ${body}` };
  } catch (e) {
    return { ok: false, detail: `unreachable (${e})` };
  }
}

export default {
  async fetch(request, env, ctx) {
    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    const path = url.pathname;

    try {
      // Route matching
      if (path === "/health") {
        return jsonResponse({ status: "ok", timestamp: new Date().toISOString() });
      }

      // /stock/{ticker}/history?period=1y
      const historyMatch = path.match(/^\/stock\/([^/]+)\/history$/);
      if (historyMatch) {
        const ticker = decodeURIComponent(historyMatch[1]).toUpperCase();
        const period = url.searchParams.get("period") || "1y";
        return await cachedFetch(
          request,
          ctx,
          `history:${ticker}:${period}`,
          CACHE_TTL.history,
          () => fetchHistory(ticker, period)
        );
      }

      // /stock/{ticker}/info
      const infoMatch = path.match(/^\/stock\/([^/]+)\/info$/);
      if (infoMatch) {
        const ticker = decodeURIComponent(infoMatch[1]).toUpperCase();
        return await cachedFetch(
          request,
          ctx,
          `info:${ticker}`,
          CACHE_TTL.info,
          () => fetchInfo(ticker)
        );
      }

      // /stock/{ticker}/options/{expiration}
      const chainMatch = path.match(/^\/stock\/([^/]+)\/options\/(.+)$/);
      if (chainMatch) {
        const ticker = decodeURIComponent(chainMatch[1]).toUpperCase();
        const expiration = chainMatch[2];
        return await cachedFetch(
          request,
          ctx,
          `chain:${ticker}:${expiration}`,
          CACHE_TTL.options,
          () => fetchOptionChain(ticker, expiration)
        );
      }

      // /stock/{ticker}/options (list expirations)
      const optionsMatch = path.match(/^\/stock\/([^/]+)\/options$/);
      if (optionsMatch) {
        const ticker = decodeURIComponent(optionsMatch[1]).toUpperCase();
        return await cachedFetch(
          request,
          ctx,
          `expirations:${ticker}`,
          CACHE_TTL.options,
          () => fetchExpirations(ticker)
        );
      }

      return jsonResponse({ error: "Not found", endpoints: [
        "/health",
        "/stock/{ticker}/history?period=1y",
        "/stock/{ticker}/info",
        "/stock/{ticker}/options",
        "/stock/{ticker}/options/{expiration}",
      ]}, 404);

    } catch (err) {
      return jsonResponse({ error: "Internal server error", message: err.message }, 500);
    }
  },

  // Cron-triggered watchdog. Declared here so Cloudflare invokes it; the body
  // lives in scheduledHandler above.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(scheduledHandler(event, env, ctx));
  },
};

// --- Cached fetch wrapper using Cache API ---

async function cachedFetch(request, ctx, cacheKey, ttlSeconds, fetchFn) {
  const cache = caches.default;
  // Build a deterministic cache URL
  const cacheUrl = new URL(request.url);
  cacheUrl.pathname = "/__cache/" + cacheKey;
  const cacheRequest = new Request(cacheUrl.toString());

  // Check cache
  let response = await cache.match(cacheRequest);
  if (response) {
    // Add header to indicate cache hit
    const headers = new Headers(response.headers);
    headers.set("X-Cache", "HIT");
    return new Response(response.body, { status: response.status, headers });
  }

  // Cache miss — fetch from Yahoo
  const data = await fetchFn();
  response = jsonResponse(data);
  response.headers.set("X-Cache", "MISS");
  response.headers.set("Cache-Control", `public, max-age=${ttlSeconds}`);

  // Store in cache (non-blocking)
  ctx.waitUntil(cache.put(cacheRequest, response.clone()));

  return response;
}

// --- Yahoo Finance auth (cookie + crumb) ---

let cachedAuth = null;
let authExpiry = 0;

async function getAuth() {
  // Reuse cached auth for 10 minutes
  if (cachedAuth && Date.now() < authExpiry) {
    return cachedAuth;
  }

  // Step 1: Get cookie from fc.yahoo.com
  const cookieResp = await fetch("https://fc.yahoo.com/", {
    headers: { "User-Agent": USER_AGENT },
    redirect: "manual",
  });
  // Extract Set-Cookie header
  const setCookie = cookieResp.headers.get("set-cookie") || "";
  // We need the full cookie string to send back
  const cookies = setCookie.split(",").map(c => c.split(";")[0].trim()).join("; ");

  // Step 2: Get crumb using the cookie
  const crumbResp = await fetch("https://query2.finance.yahoo.com/v1/test/getcrumb", {
    headers: {
      "User-Agent": USER_AGENT,
      "Cookie": cookies,
    },
  });
  if (!crumbResp.ok) {
    throw new Error(`Failed to get crumb: ${crumbResp.status}`);
  }
  const crumb = await crumbResp.text();

  cachedAuth = { cookies, crumb };
  authExpiry = Date.now() + 10 * 60 * 1000; // 10 min
  return cachedAuth;
}

// --- Yahoo Finance fetchers ---

async function yahooFetch(url, needsAuth = false) {
  let headers = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
  };

  let finalUrl = url;
  if (needsAuth) {
    const auth = await getAuth();
    headers["Cookie"] = auth.cookies;
    // Append crumb to URL
    const separator = url.includes("?") ? "&" : "?";
    finalUrl = `${url}${separator}crumb=${encodeURIComponent(auth.crumb)}`;
  }

  const resp = await fetch(finalUrl, { headers });
  if (!resp.ok) {
    // If 401 and we used auth, invalidate cache and retry once
    if (resp.status === 401 && needsAuth) {
      cachedAuth = null;
      authExpiry = 0;
      const auth = await getAuth();
      headers["Cookie"] = auth.cookies;
      const sep = url.includes("?") ? "&" : "?";
      finalUrl = `${url}${sep}crumb=${encodeURIComponent(auth.crumb)}`;
      const retryResp = await fetch(finalUrl, { headers });
      if (!retryResp.ok) {
        const text = await retryResp.text();
        throw new Error(`Yahoo returned ${retryResp.status}: ${text.substring(0, 200)}`);
      }
      return retryResp.json();
    }
    const text = await resp.text();
    throw new Error(`Yahoo returned ${resp.status}: ${text.substring(0, 200)}`);
  }
  return resp.json();
}

async function fetchHistory(ticker, period) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?range=${encodeURIComponent(period)}&interval=1d&includePrePost=false`;
  const data = await yahooFetch(url, true);

  const result = data?.chart?.result?.[0];
  if (!result) {
    throw new Error(`No history data for ${ticker}`);
  }

  const timestamps = result.timestamp || [];
  const quote = result.indicators?.quote?.[0] || {};
  const adjClose = result.indicators?.adjclose?.[0]?.adjclose || [];

  // Build array of OHLCV rows
  const rows = timestamps.map((ts, i) => ({
    date: new Date(ts * 1000).toISOString().split("T")[0],
    open: quote.open?.[i] ?? null,
    high: quote.high?.[i] ?? null,
    low: quote.low?.[i] ?? null,
    close: quote.close?.[i] ?? null,
    adjClose: adjClose[i] ?? quote.close?.[i] ?? null,
    volume: quote.volume?.[i] ?? null,
  }));

  return {
    ticker,
    period,
    currency: result.meta?.currency || "USD",
    rows,
  };
}

async function fetchInfo(ticker) {
  const url = `https://query2.finance.yahoo.com/v10/finance/quoteSummary/${encodeURIComponent(ticker)}?modules=price,summaryDetail,calendarEvents,defaultKeyStatistics`;
  try {
    const data = await yahooFetch(url, true);
    const result = data?.quoteSummary?.result?.[0] || {};

    const price = result.price || {};
    const summary = result.summaryDetail || {};
    const calendar = result.calendarEvents || {};
    const keyStats = result.defaultKeyStatistics || {};

    return {
      ticker,
      shortName: price.shortName || null,
      longName: price.longName || null,
      currency: price.currency || "USD",
      exchange: price.exchange || null,
      marketCap: price.marketCap?.raw || null,
      regularMarketPrice: price.regularMarketPrice?.raw || null,
      regularMarketChange: price.regularMarketChange?.raw || null,
      regularMarketChangePercent: price.regularMarketChangePercent?.raw || null,
      fiftyTwoWeekHigh: summary.fiftyTwoWeekHigh?.raw || null,
      fiftyTwoWeekLow: summary.fiftyTwoWeekLow?.raw || null,
      dividendYield: summary.dividendYield?.raw || null,
      trailingPE: summary.trailingPE?.raw || null,
      forwardPE: summary.forwardPE?.raw || null,
      beta: keyStats.beta?.raw || null,
      earningsDate: calendar.earnings?.earningsDate?.map((d) => d.fmt) || [],
      exDividendDate: calendar.exDividendDate?.fmt || null,
    };
  } catch (err) {
    // v10 quoteSummary often needs a crumb — return minimal info on failure
    console.error(`Info fetch failed for ${ticker}: ${err.message}`);
    return {
      ticker,
      error: "Info endpoint unavailable (may require authentication)",
      shortName: null,
      longName: null,
    };
  }
}

async function fetchExpirations(ticker) {
  const url = `https://query1.finance.yahoo.com/v7/finance/options/${encodeURIComponent(ticker)}`;
  const data = await yahooFetch(url, true);

  const result = data?.optionChain?.result?.[0];
  if (!result) {
    throw new Error(`No options data for ${ticker}`);
  }

  // Convert unix timestamps to date strings
  const expirations = (result.expirationDates || []).map((ts) => {
    const d = new Date(ts * 1000);
    return d.toISOString().split("T")[0];
  });

  return {
    ticker,
    expirations,
    // Also include the unix timestamps for use in chain requests
    expirationTimestamps: result.expirationDates || [],
  };
}

async function fetchOptionChain(ticker, expiration) {
  // expiration can be a date string (2024-06-21) or unix timestamp
  let unixTs = expiration;
  if (expiration.includes("-")) {
    // Convert date string to unix timestamp (midnight UTC)
    unixTs = Math.floor(new Date(expiration + "T00:00:00Z").getTime() / 1000);
  }

  const url = `https://query1.finance.yahoo.com/v7/finance/options/${encodeURIComponent(ticker)}?date=${unixTs}`;
  const data = await yahooFetch(url, true);

  const result = data?.optionChain?.result?.[0];
  if (!result) {
    throw new Error(`No options chain data for ${ticker} at ${expiration}`);
  }

  const options = result.options?.[0] || {};

  // Clean up call/put data into flat objects
  const formatContract = (c) => ({
    contractSymbol: c.contractSymbol,
    strike: c.strike,
    lastPrice: c.lastPrice,
    bid: c.bid,
    ask: c.ask,
    change: c.change,
    percentChange: c.percentChange,
    volume: c.volume || 0,
    openInterest: c.openInterest || 0,
    impliedVolatility: c.impliedVolatility,
    inTheMoney: c.inTheMoney,
    expiration: expiration.includes("-") ? expiration : new Date(parseInt(expiration) * 1000).toISOString().split("T")[0],
    lastTradeDate: c.lastTradeDate ? new Date(c.lastTradeDate * 1000).toISOString() : null,
  });

  return {
    ticker,
    expiration: expiration.includes("-") ? expiration : new Date(parseInt(expiration) * 1000).toISOString().split("T")[0],
    underlyingPrice: result.quote?.regularMarketPrice || null,
    calls: (options.calls || []).map(formatContract),
    puts: (options.puts || []).map(formatContract),
  };
}

export async function scheduledHandler(event, env, ctx) {
  const result = await checkHealth(env);
  if (result.ok) {
    console.log(`[watchdog] ${new Date().toISOString()} healthy`);
    return;
  }
  console.error(`[watchdog] UNHEALTHY: ${result.detail}`);
  const title = "🚨 Options Copilot is not responding";
  const message =
    `The Cloudflare watchdog could not confirm the copilot is healthy.\n\n${result.detail}\n\n` +
    "This check runs outside Hetzner and outside GitHub, so it is still speaking " +
    "even if both are down. Positions may be unmonitored.";
  // Deliver on every configured channel; the invariant is at least one confirms.
  const delivered = [
    await pushover(env, title, message, 1),
    await discord(env, title, message),
  ].some(Boolean);
  if (!delivered) {
    console.error("[watchdog] ALERT UNDELIVERED on every channel — watchdog is mute");
  }
}

// --- Helpers ---

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...CORS_HEADERS,
    },
  });
}
