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
        const ticker = historyMatch[1].toUpperCase();
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
        const ticker = infoMatch[1].toUpperCase();
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
        const ticker = chainMatch[1].toUpperCase();
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
        const ticker = optionsMatch[1].toUpperCase();
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

// --- Yahoo Finance fetchers ---

async function yahooFetch(url) {
  const resp = await fetch(url, {
    headers: {
      "User-Agent": USER_AGENT,
      "Accept": "application/json",
    },
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Yahoo returned ${resp.status}: ${text.substring(0, 200)}`);
  }
  return resp.json();
}

async function fetchHistory(ticker, period) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?range=${encodeURIComponent(period)}&interval=1d&includePrePost=false`;
  const data = await yahooFetch(url);

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
    const data = await yahooFetch(url);
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
  const data = await yahooFetch(url);

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
  const data = await yahooFetch(url);

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
