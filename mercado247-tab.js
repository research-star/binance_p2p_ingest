/* Mercado 24/7 — tab embebible para finanzasbo.com (o cualquier página).
 *
 * Un solo archivo: inyecta estilos namespaceados (.m247), markup y lógica.
 * Se conecta a la API pública de Hyperliquid (REST + WebSocket) desde el
 * navegador; no necesita backend.
 *
 * Integración (patrón de tabs de FinanzasBo):
 *   <div id="tab-mercado247" data-mercado247></div>
 *   <script src="mercado247-tab.js" defer></script>
 *   // en activateTab('mercado247'):  window.renderMercado247()
 *
 * window.renderMercado247() es idempotente: la primera llamada monta e
 * inicia el feed; las siguientes no hacen nada.
 */
(function () {
  "use strict";

  /* ================= estilos (todo namespaceado bajo .m247) ================= */
  const CSS = `
.m247 {
  /* Tema claro de FinanzasBo: consume los tokens del sitio (:root) para que el
     tab combine con el resto de la página. Fallbacks por si se usa aislado. */
  --m247-bg: var(--bg-primary, #F7E4D7);
  --m247-surface: var(--bg-secondary, #FFF7F0);
  --m247-surface-2: var(--bg-tertiary, #F3E0D2);
  --m247-border: var(--border-color, rgba(33,30,27,0.12));
  --m247-border-strong: var(--line-strong, rgba(33,30,27,0.24));
  --m247-ink: var(--text-primary, #211E1B);
  --m247-ink-2: var(--text-secondary, #6B6256);
  --m247-ink-3: var(--text-muted, #766C5C);
  /* Mismos verdes/rojos que los gráficos de mercado del sitio (subas/bajas). */
  --m247-up: #688470; --m247-down: #A57067; --m247-star: #C47E2A;
  --m247-font: var(--font-body, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif);
  --m247-font-display: var(--font-display, Georgia, serif);
  --m247-font-mono: var(--font-mono, "IBM Plex Mono", ui-monospace, monospace);
  --m247-radius: var(--radius-md, 8px);
  color: var(--m247-ink);
  font-family: var(--m247-font);
  font-size: 15px;
  line-height: 1.4;
  text-align: left;
}
.m247 *, .m247 *::before, .m247 *::after { box-sizing: border-box; }
.m247 [hidden] { display: none !important; }
.m247 button { font: inherit; }

.m247 .m247-pills { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }
.m247 .m247-pill {
  display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px;
  border: 1px solid var(--m247-border); border-radius: 999px;
  background: var(--m247-surface); color: var(--m247-ink-2);
  font-size: 0.78rem; white-space: nowrap;
}
.m247 .m247-pill b { color: var(--m247-ink); font-weight: 600; }
.m247 .m247-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--m247-ink-3); flex: none; }
.m247 .m247-dot.is-live { background: var(--m247-up); box-shadow: 0 0 6px var(--m247-up); }
.m247 .m247-dot.is-off { background: var(--m247-down); }
.m247 .m247-dot.is-poll { background: var(--m247-star); }

.m247 .m247-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.m247 .m247-tab {
  padding: 7px 16px; border: 1px solid var(--m247-border); border-radius: 999px;
  background: var(--m247-surface); color: var(--m247-ink-2);
  font-size: 0.85rem; cursor: pointer;
}
.m247 .m247-tab:hover { color: var(--m247-ink); border-color: var(--m247-border-strong); }
.m247 .m247-tab.is-active { background: var(--m247-ink); border-color: var(--m247-ink); color: var(--m247-surface); font-weight: 700; }

.m247 .m247-toolbar { display: flex; gap: 10px; margin-bottom: 12px; }
.m247 .m247-search {
  flex: 1; min-width: 0; padding: 10px 14px;
  border: 1px solid var(--m247-border); border-radius: var(--m247-radius);
  background: var(--m247-surface); color: var(--m247-ink);
  font-size: 0.9rem; outline: none;
}
.m247 .m247-search:focus { border-color: var(--m247-border-strong); }
.m247 .m247-search::placeholder { color: var(--m247-ink-3); }
.m247 .m247-sorts { display: flex; gap: 6px; }
.m247 .m247-sort {
  padding: 8px 14px; border: 1px solid var(--m247-border); border-radius: var(--m247-radius);
  background: var(--m247-surface); color: var(--m247-ink-2);
  font-size: 0.82rem; cursor: pointer; white-space: nowrap;
}
.m247 .m247-sort:hover { color: var(--m247-ink); }
.m247 .m247-sort.is-active { background: var(--m247-ink); border-color: var(--m247-ink); color: var(--m247-surface); font-weight: 700; }

.m247 .m247-summary {
  border: 1px solid var(--m247-border); border-radius: var(--m247-radius);
  background: var(--m247-surface); padding: 9px 14px 12px; margin-bottom: 16px;
}
.m247 .m247-summary-text {
  font-size: 0.8rem; color: var(--m247-ink-2);
  display: flex; flex-wrap: wrap; gap: 4px 18px; margin-bottom: 8px;
}
.m247 .m247-summary-text b { color: var(--m247-ink); font-weight: 600; }
.m247 .m247-summary-text .up { color: var(--m247-up); font-weight: 700; }
.m247 .m247-summary-text .down { color: var(--m247-down); font-weight: 700; }
.m247 .m247-meter { display: flex; height: 4px; border-radius: 2px; overflow: hidden; background: var(--m247-surface-2); gap: 2px; }
.m247 .m247-meter-up { background: var(--m247-up); transition: width 0.4s; }
.m247 .m247-meter-down { background: var(--m247-down); transition: width 0.4s; }

.m247 .m247-error {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 14px; border-radius: var(--m247-radius); margin-bottom: 14px;
  font-size: 0.85rem; border: 1px solid rgba(239,68,68,0.4);
  background: rgba(239,68,68,0.12); color: var(--m247-ink);
}
.m247 .m247-error button {
  padding: 6px 14px; border: 1px solid var(--m247-border-strong); border-radius: 8px;
  background: var(--m247-surface-2); color: var(--m247-ink); cursor: pointer;
}
.m247 .m247-empty { color: var(--m247-ink-2); text-align: center; padding: 48px 12px; font-size: 0.9rem; }

.m247 .m247-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
.m247 .m247-card {
  border: 1px solid var(--m247-border); border-radius: var(--m247-radius);
  background: var(--m247-surface); padding: 12px 12px 10px;
  display: flex; flex-direction: column; gap: 2px; min-width: 0;
}
.m247 .m247-card:hover { border-color: var(--m247-border-strong); }
.m247 .m247-card-top { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.m247 .m247-card-left { display: flex; align-items: baseline; gap: 7px; min-width: 0; }
.m247 .m247-star {
  background: none; border: none; padding: 0; font-size: 0.95rem; line-height: 1;
  color: var(--m247-ink-3); cursor: pointer; align-self: center;
}
.m247 .m247-star.is-fav, .m247 .m247-star:hover { color: var(--m247-star); }
.m247 .m247-sym { font-weight: 800; font-size: 0.98rem; letter-spacing: 0.02em; }
.m247 .m247-price {
  font-family: var(--m247-font-mono);
  font-weight: 600; font-size: 0.92rem; font-variant-numeric: tabular-nums;
  white-space: nowrap; transition: color 0.5s;
}
.m247 .m247-price.flash-up { color: var(--m247-up); transition: none; }
.m247 .m247-price.flash-down { color: var(--m247-down); transition: none; }
.m247 .m247-card-sub { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
.m247 .m247-name {
  color: var(--m247-ink-3); font-size: 0.74rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.m247 .m247-chg { font-family: var(--m247-font-mono); font-size: 0.8rem; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
.m247 .m247-chg.up { color: var(--m247-up); }
.m247 .m247-chg.down { color: var(--m247-down); }
.m247 .m247-chg.flat { color: var(--m247-ink-2); }
.m247 .m247-chart {
  position: relative; height: 158px; border-radius: 6px;
  background: var(--m247-surface-2); overflow: hidden;
}
.m247 .m247-chart canvas { display: block; width: 100%; height: 100%; cursor: crosshair; }
.m247 .m247-chart-loading {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: var(--m247-ink-3); font-size: 0.72rem;
}
.m247 .m247-card-foot {
  margin-top: 7px; color: var(--m247-ink-3); font-size: 0.7rem;
  font-family: var(--m247-font-mono);
  font-variant-numeric: tabular-nums; display: flex; justify-content: space-between; gap: 8px;
}
.m247 .m247-more {
  border: 1px dashed var(--m247-border-strong); border-radius: var(--m247-radius);
  background: transparent; color: var(--m247-ink-2); cursor: pointer;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
  min-height: 240px; font-family: var(--m247-font); transition: background 0.15s, color 0.15s;
}
.m247 .m247-more:hover { background: var(--m247-surface); color: var(--m247-ink); border-color: var(--m247-ink-3); }
.m247 .m247-more .plus { font-size: 2rem; line-height: 1; font-weight: 300; }
.m247 .m247-more .lbl { font-size: 0.82rem; font-weight: 600; }
.m247 .m247-more .cnt { font-size: 0.72rem; color: var(--m247-ink-3); }
.m247 .m247-note { margin-top: 20px; color: var(--m247-ink-3); font-size: 0.72rem; text-align: center; }
.m247 .m247-note a { color: var(--m247-ink-2); }

.m247-tooltip {
  position: fixed; z-index: 9999; pointer-events: none;
  background: var(--bg-secondary, #FFF7F0); border: 1px solid var(--line-strong, rgba(33,30,27,0.24)); border-radius: 8px;
  padding: 7px 10px; font-size: 0.72rem; color: var(--text-secondary, #6B6256);
  font-variant-numeric: tabular-nums; box-shadow: 0 6px 20px rgba(33,30,27,0.18); max-width: 220px;
  font-family: var(--font-mono, "IBM Plex Mono", ui-monospace, monospace);
}
.m247-tooltip b { color: var(--text-primary, #211E1B); font-weight: 600; }
.m247-tooltip .tt-time { color: var(--text-muted, #766C5C); display: block; margin-bottom: 3px; }
.m247-tooltip .up { color: #688470; }
.m247-tooltip .down { color: #A57067; }

@media (max-width: 640px) {
  .m247 .m247-toolbar { flex-direction: column; }
  .m247 .m247-sorts { justify-content: stretch; }
  .m247 .m247-sort { flex: 1; }
}
`;

  const HTML = `
<div class="fb-subheader">
  <div>
    <h1>Mercado 24/7</h1>
    <div class="fb-subtitle">Acciones, índices, commodities, forex y cripto en vivo 24/7 &middot; precios de perpetuos de la API pública de Hyperliquid</div>
  </div>
</div>
<div class="content">
<div class="m247-pills">
  <span class="m247-pill" data-m247="nyse-pill"><span class="m247-dot is-off"></span>NYSE / Nasdaq <b data-m247="nyse">—</b></span>
  <span class="m247-pill"><span class="m247-dot is-live"></span>Mercado HL <b>24/7</b></span>
  <span class="m247-pill"><span class="m247-dot" data-m247="live-dot"></span><span data-m247="updated">conectando…</span></span>
</div>
<div class="m247-tabs" data-m247="tabs">
  <button type="button" class="m247-tab" data-cat="fav">Favoritos</button>
  <button type="button" class="m247-tab" data-cat="stocks">Stocks</button>
  <button type="button" class="m247-tab" data-cat="indices">Índices</button>
  <button type="button" class="m247-tab" data-cat="commodities">Commodities</button>
  <button type="button" class="m247-tab" data-cat="forex">Forex</button>
  <button type="button" class="m247-tab" data-cat="crypto">Cripto</button>
</div>
<div class="m247-toolbar">
  <input type="search" class="m247-search" data-m247="search" placeholder="Buscar activo…" autocomplete="off" spellcheck="false" />
  <div class="m247-sorts" data-m247="sorts">
    <button type="button" class="m247-sort" data-sort="volume">Volumen</button>
    <button type="button" class="m247-sort" data-sort="gainers">▲ Subas</button>
    <button type="button" class="m247-sort" data-sort="losers">▼ Bajas</button>
  </div>
</div>
<div class="m247-summary" data-m247="summary" hidden>
  <div class="m247-summary-text" data-m247="summary-text"></div>
  <div class="m247-meter"><div class="m247-meter-up" data-m247="meter-up"></div><div class="m247-meter-down" data-m247="meter-down"></div></div>
</div>
<div class="m247-error" data-m247="error" hidden>
  <span data-m247="error-text"></span>
  <button type="button" data-m247="retry">Reintentar</button>
</div>
<div class="m247-grid" data-m247="grid"></div>
<p class="m247-empty" data-m247="empty" hidden></p>
<p class="m247-note">Precios mark de perpetuos de la API pública de
  <a href="https://hyperliquid.xyz" target="_blank" rel="noopener">Hyperliquid</a>
  (incl. mercados HIP-3 de acciones, índices, commodities y forex). No es asesoramiento financiero.</p>
</div>
`;

  /* ================= nombres y clasificación ================= */
  const DISPLAY_NAMES = {
    AAPL: "Apple", MSFT: "Microsoft", NVDA: "NVIDIA", AMZN: "Amazon",
    GOOGL: "Alphabet", GOOG: "Alphabet", META: "Meta", TSLA: "Tesla",
    AMD: "AMD", INTC: "Intel", MU: "Micron", AVGO: "Broadcom",
    QCOM: "Qualcomm", TSM: "TSMC", SMCI: "Supermicro", DELL: "Dell",
    ORCL: "Oracle", IBM: "IBM", CRM: "Salesforce", NFLX: "Netflix",
    COIN: "Coinbase", HOOD: "Robinhood", MSTR: "MicroStrategy",
    PLTR: "Palantir", UBER: "Uber", ABNB: "Airbnb", SHOP: "Shopify",
    SNOW: "Snowflake", NBIS: "Nebius", CRWV: "CoreWeave", SNDK: "SanDisk",
    WDC: "Western Digital", STX: "Seagate", KIOXIA: "Kioxia",
    SKHX: "SK Hynix", SMSN: "Samsung", BRK: "Berkshire", JPM: "JPMorgan",
    BAC: "Bank of America", GS: "Goldman Sachs", V: "Visa", MA: "Mastercard",
    DIS: "Disney", NKE: "Nike", KO: "Coca-Cola", PEP: "PepsiCo",
    WMT: "Walmart", MCD: "McDonald's", BA: "Boeing", GE: "GE",
    XOM: "Exxon", CVX: "Chevron", PFE: "Pfizer", JNJ: "J&J",
    LLY: "Eli Lilly", NVO: "Novo Nordisk", UNH: "UnitedHealth",
    SPCX: "SpaceX", OPENAI: "OpenAI", ANTHROPIC: "Anthropic",
    DRAM: "DRAM", RKLB: "Rocket Lab", ASML: "ASML", ARM: "Arm",
    RIVN: "Rivian", LCID: "Lucid", F: "Ford", GM: "GM",
    SP500: "S&P 500", SPX: "S&P 500", US500: "S&P 500", SPY: "S&P 500 ETF",
    NDX: "Nasdaq 100", NAS100: "Nasdaq 100", US100: "Nasdaq 100", QQQ: "Nasdaq 100 ETF",
    DJ30: "Dow Jones", US30: "Dow Jones", DIA: "Dow Jones ETF",
    RUT: "Russell 2000", IWM: "Russell 2000 ETF", VIX: "VIX",
    DAX: "DAX 40", FTSE: "FTSE 100", N225: "Nikkei 225", NIKKEI: "Nikkei 225",
    GOLD: "Oro", XAU: "Oro", SILVER: "Plata", XAG: "Plata",
    CL: "Petróleo WTI", WTI: "Petróleo WTI", OIL: "Petróleo WTI",
    BRENT: "Petróleo Brent", NG: "Gas natural", NATGAS: "Gas natural",
    HG: "Cobre", COPPER: "Cobre", PLATINUM: "Platino", PALLADIUM: "Paladio",
    URANIUM: "Uranio", COCOA: "Cacao", COFFEE: "Café", WHEAT: "Trigo",
    CORN: "Maíz", SUGAR: "Azúcar",
    EUR: "Euro / USD", EURUSD: "Euro / USD", GBP: "Libra / USD",
    GBPUSD: "Libra / USD", JPY: "USD / Yen", USDJPY: "USD / Yen",
    CHF: "USD / Franco", AUD: "Dólar australiano", CAD: "USD / Dólar canadiense",
    NZD: "Dólar neozelandés", CNH: "USD / Yuan", MXN: "USD / Peso mexicano",
    DXY: "Índice dólar",
    BTC: "Bitcoin", ETH: "Ethereum", SOL: "Solana", HYPE: "Hyperliquid",
    XRP: "XRP", DOGE: "Dogecoin", ADA: "Cardano", AVAX: "Avalanche",
    LINK: "Chainlink", BNB: "BNB", LTC: "Litecoin", SUI: "Sui",
    TON: "Toncoin", TRX: "Tron", DOT: "Polkadot", NEAR: "Near",
    APT: "Aptos", ARB: "Arbitrum", OP: "Optimism", WLD: "Worldcoin",
    PEPE: "Pepe", WIF: "dogwifhat", FARTCOIN: "Fartcoin", ENA: "Ethena",
    AAVE: "Aave", UNI: "Uniswap", TAO: "Bittensor", SEI: "Sei",
    TIA: "Celestia", JUP: "Jupiter", ONDO: "Ondo", PAXG: "Oro tokenizado",
  };
  const INDICES = new Set(["SP500","SPX","US500","SPY","NDX","NAS100","US100","QQQ","DJ30","US30","DIA","RUT","IWM","VIX","DAX","FTSE","N225","NIKKEI","ES","NQ","YM"]);
  const COMMODITIES = new Set(["GOLD","XAU","SILVER","XAG","CL","WTI","OIL","BRENT","NG","NATGAS","HG","COPPER","PLATINUM","PALLADIUM","URANIUM","COCOA","COFFEE","WHEAT","CORN","SUGAR","PAXG"]);
  const FOREX = new Set(["EUR","EURUSD","GBP","GBPUSD","JPY","USDJPY","CHF","USDCHF","AUD","AUDUSD","CAD","USDCAD","NZD","NZDUSD","CNH","USDCNH","MXN","USDMXN","BRL","USDBRL","DXY"]);

  function classify(symbol, dex) {
    const s = symbol.toUpperCase();
    if (INDICES.has(s)) return "indices";
    if (COMMODITIES.has(s)) return "commodities";
    if (FOREX.has(s)) return "forex";
    if (!dex) return "crypto";
    return "stocks";
  }
  function displayName(symbol) {
    const s = symbol.toUpperCase();
    if (DISPLAY_NAMES[s]) return DISPLAY_NAMES[s];
    if (/^k[A-Z]/.test(symbol) && DISPLAY_NAMES[s.slice(1)]) return DISPLAY_NAMES[s.slice(1)] + " (x1000)";
    const base = s.replace(/[-_/].*$/, "");
    if (DISPLAY_NAMES[base]) return DISPLAY_NAMES[base];
    return symbol;
  }

  /* ================= API Hyperliquid ================= */
  const API_URL = "https://api.hyperliquid.xyz/info";
  const WS_URL = "wss://api.hyperliquid.xyz/ws";

  async function info(body) {
    const res = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`API ${res.status} para ${body.type}`);
    return res.json();
  }

  async function fetchDexs() {
    try {
      const raw = await info({ type: "perpDexs" });
      const dexs = [{ name: "", fullName: "Hyperliquid" }];
      for (const d of raw || []) {
        if (d && d.name) dexs.push({ name: d.name, fullName: d.full_name || d.fullName || d.name });
      }
      return dexs;
    } catch (err) {
      console.warn("m247: perpDexs falló, uso solo el dex principal", err);
      return [{ name: "", fullName: "Hyperliquid" }];
    }
  }

  async function fetchAssetsOf(dex) {
    const body = { type: "metaAndAssetCtxs" };
    if (dex.name) body.dex = dex.name;
    const [meta, ctxs] = await info(body);
    const out = [];
    (meta.universe || []).forEach((u, i) => {
      const ctx = ctxs[i];
      if (!u || !ctx || u.isDelisted) return;
      const mark = parseFloat(ctx.markPx);
      const mid = parseFloat(ctx.midPx);
      // Los dexs HIP-3 devuelven el nombre del universo ya prefijado
      // ("xyz:SKHX"); el dex principal no ("BTC"). key = nombre exacto que
      // usa la API (para velas y mids); symbol = ticker limpio para mostrar.
      const rawName = u.name;
      const symbol = rawName.includes(":") ? rawName.slice(rawName.indexOf(":") + 1) : rawName;
      out.push({
        key: rawName,
        symbol: symbol,
        dex: dex.name,
        dexName: dex.fullName,
        price: Number.isFinite(mid) ? mid : mark,
        markPx: mark,
        prevDayPx: parseFloat(ctx.prevDayPx),
        volume24h: parseFloat(ctx.dayNtlVlm) || 0,
      });
    });
    return out;
  }

  async function fetchAllAssets() {
    const dexs = await fetchDexs();
    const results = await Promise.allSettled(dexs.map(fetchAssetsOf));
    const assets = [];
    results.forEach((r, i) => {
      if (r.status === "fulfilled") assets.push(...r.value);
      else console.warn(`m247: metaAndAssetCtxs falló para dex "${dexs[i].name}"`, r.reason);
    });
    return { dexs, assets };
  }

  async function fetchCandles(asset, interval, lookbackMs) {
    const end = Date.now();
    const req = (coin) => info({
      type: "candleSnapshot",
      req: { coin, interval, startTime: end - lookbackMs, endTime: end },
    });
    let rows = await req(asset.key);
    if ((!rows || !rows.length) && asset.key !== asset.symbol) {
      rows = await req(asset.symbol).catch(() => []);
    }
    return (rows || []).map((c) => ({
      t: c.t, o: parseFloat(c.o), h: parseFloat(c.h),
      l: parseFloat(c.l), c: parseFloat(c.c), v: parseFloat(c.v),
    }));
  }

  function createLiveFeed(onMids, onStatus) {
    let ws = null;
    let dexNames = [""];
    let retryMs = 1000;
    let pingTimer = null;
    let lastMsg = 0;
    let closedByUs = false;

    function subscribeAll() {
      for (const dex of dexNames) {
        const sub = { type: "allMids" };
        if (dex) sub.dex = dex;
        try { ws.send(JSON.stringify({ method: "subscribe", subscription: sub })); } catch (_) {}
      }
    }

    function connect() {
      if (closedByUs) return;
      try { ws = new WebSocket(WS_URL); }
      catch (err) {
        onStatus("offline");
        setTimeout(connect, retryMs);
        retryMs = Math.min(retryMs * 2, 30000);
        return;
      }
      ws.onopen = () => {
        retryMs = 1000;
        lastMsg = Date.now();
        onStatus("live");
        subscribeAll();
        clearInterval(pingTimer);
        pingTimer = setInterval(() => {
          if (ws.readyState !== WebSocket.OPEN) return;
          ws.send(JSON.stringify({ method: "ping" }));
          if (Date.now() - lastMsg > 45000) ws.close();
        }, 20000);
      };
      ws.onmessage = (ev) => {
        lastMsg = Date.now();
        let msg;
        try { msg = JSON.parse(ev.data); } catch (_) { return; }
        if (msg.channel === "allMids" && msg.data) {
          const mids = msg.data.mids || msg.data;
          if (mids && typeof mids === "object") onMids(mids, msg.data.dex || "");
        }
      };
      ws.onclose = () => {
        clearInterval(pingTimer);
        if (closedByUs) return;
        onStatus("offline");
        setTimeout(connect, retryMs);
        retryMs = Math.min(retryMs * 2, 30000);
      };
      ws.onerror = () => { try { ws.close(); } catch (_) {} };
    }

    connect();
    return {
      setDexs(names) {
        dexNames = names;
        if (ws && ws.readyState === WebSocket.OPEN) subscribeAll();
      },
      isLive() { return !!ws && ws.readyState === WebSocket.OPEN && Date.now() - lastMsg < 20000; },
      close() { closedByUs = true; clearInterval(pingTimer); try { ws && ws.close(); } catch (_) {} },
    };
  }

  /* ================= gráfico de velas ================= */
  const UP = "#688470", DOWN = "#A57067", REF = "#9E927C", PAD_Y = 8;

  function drawChart(canvas, candles, prevDayPx, hoverIdx) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!candles.length) return;

    let lo = Infinity, hi = -Infinity;
    for (const c of candles) { if (c.l < lo) lo = c.l; if (c.h > hi) hi = c.h; }
    if (Number.isFinite(prevDayPx)) { lo = Math.min(lo, prevDayPx); hi = Math.max(hi, prevDayPx); }
    if (hi === lo) { hi += 1; lo -= 1; }
    const y = (px) => PAD_Y + (hi - px) / (hi - lo) * (h - PAD_Y * 2);
    const step = w / candles.length;
    const bodyW = Math.max(2, Math.min(9, step * 0.62));

    if (Number.isFinite(prevDayPx)) {
      ctx.strokeStyle = REF; ctx.lineWidth = 1; ctx.setLineDash([3, 4]);
      ctx.beginPath(); ctx.moveTo(0, y(prevDayPx)); ctx.lineTo(w, y(prevDayPx)); ctx.stroke();
      ctx.setLineDash([]);
    }
    candles.forEach((c, i) => {
      const cx = step * i + step / 2;
      const color = c.c >= c.o ? UP : DOWN;
      ctx.globalAlpha = hoverIdx != null && hoverIdx !== i ? 0.45 : 1;
      ctx.strokeStyle = color; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(cx, y(c.h)); ctx.lineTo(cx, y(c.l)); ctx.stroke();
      const top = y(Math.max(c.o, c.c)), bot = y(Math.min(c.o, c.c));
      ctx.fillStyle = color;
      ctx.fillRect(cx - bodyW / 2, top, bodyW, Math.max(1, bot - top));
    });
    ctx.globalAlpha = 1;

    if (hoverIdx != null && candles[hoverIdx]) {
      const cx = step * hoverIdx + step / 2;
      ctx.strokeStyle = "rgba(33,30,27,0.30)"; ctx.lineWidth = 1; ctx.setLineDash([2, 3]);
      ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, h); ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  function attachHover(canvas, tooltipEl, getData) {
    let hoverIdx = null;
    canvas.addEventListener("mousemove", (ev) => {
      const { candles, prevDayPx, fmtPrice } = getData();
      if (!candles.length) return;
      const rect = canvas.getBoundingClientRect();
      const idx = Math.max(0, Math.min(candles.length - 1,
        Math.floor((ev.clientX - rect.left) / (rect.width / candles.length))));
      if (idx !== hoverIdx) { hoverIdx = idx; drawChart(canvas, candles, prevDayPx, hoverIdx); }
      const c = candles[idx];
      const up = c.c >= c.o;
      const when = new Date(c.t).toLocaleString("es-BO", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
      tooltipEl.innerHTML =
        `<span class="tt-time">${when}</span>` +
        `A <b>${fmtPrice(c.o)}</b> · Máx <b>${fmtPrice(c.h)}</b><br>` +
        `Mín <b>${fmtPrice(c.l)}</b> · C <b class="${up ? "up" : "down"}">${fmtPrice(c.c)}</b>`;
      tooltipEl.hidden = false;
      const ttw = tooltipEl.offsetWidth;
      let x = ev.clientX + 14;
      if (x + ttw > window.innerWidth - 8) x = ev.clientX - ttw - 14;
      tooltipEl.style.left = x + "px";
      tooltipEl.style.top = (ev.clientY + 14) + "px";
    });
    canvas.addEventListener("mouseleave", () => {
      hoverIdx = null;
      tooltipEl.hidden = true;
      const { candles, prevDayPx } = getData();
      drawChart(canvas, candles, prevDayPx, null);
    });
  }

  /* ================= app ================= */
  const CANDLE_INTERVAL = "30m";
  const CANDLE_MS = 30 * 60 * 1000;
  const CANDLE_LOOKBACK = 24 * 60 * 60 * 1000;
  const MAX_CANDLES = 48;
  const CTX_REFRESH_MS = 30000;
  const CANDLE_TTL_MS = 2 * 60 * 1000;
  const LS = { favs: "m247.favs", tab: "m247.tab", sort: "m247.sort" };
  const PAGE_SIZE = 12; // tarjetas por lote — limita cuántas velas se piden a la vez

  let mounted = false;

  function mount(target) {
    if (mounted) return;
    const root = typeof target === "string" ? document.querySelector(target) : target;
    if (!root) { console.warn("m247: no encuentro el contenedor", target); return; }
    mounted = true;

    const style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);

    root.classList.add("m247");
    root.innerHTML = HTML;

    const tooltip = document.createElement("div");
    tooltip.className = "m247-tooltip";
    tooltip.hidden = true;
    document.body.appendChild(tooltip);

    const $ = (name) => root.querySelector(`[data-m247="${name}"]`);
    const els = {
      grid: $("grid"), tabs: $("tabs"), search: $("search"), sorts: $("sorts"),
      summary: $("summary"), summaryText: $("summary-text"),
      meterUp: $("meter-up"), meterDown: $("meter-down"),
      error: $("error"), errorText: $("error-text"), retry: $("retry"),
      empty: $("empty"), updated: $("updated"), liveDot: $("live-dot"),
      nyse: $("nyse"), nysePill: $("nyse-pill"),
    };

    const assets = new Map();
    const symbolIndex = new Map();
    const cardEls = new Map();
    const visibleKeys = new Set();
    let favs = new Set(JSON.parse(localStorage.getItem(LS.favs) || "[]"));
    let tab = localStorage.getItem(LS.tab) || "fav";
    let sortMode = localStorage.getItem(LS.sort) || "volume";
    let search = "";
    let shownCount = PAGE_SIZE; // cuántas tarjetas de la lista actual se muestran
    let lastSig = "";           // firma de la vista (tab|sort|search): al cambiar, resetea el paginado
    let moreTileEl = null;
    let lastUpdate = 0;
    let feedStatus = "offline";
    let loaded = false;
    let feed = null;

    const fmtCache = new Map();
    function fmtPrice(v) {
      if (!Number.isFinite(v)) return "—";
      const dec = v >= 1000 ? 2 : v >= 1 ? 2 : v >= 0.01 ? 4 : 6;
      let f = fmtCache.get(dec);
      if (!f) {
        f = new Intl.NumberFormat("es-BO", { minimumFractionDigits: dec, maximumFractionDigits: dec });
        fmtCache.set(dec, f);
      }
      return "US$ " + f.format(v);
    }
    function fmtPct(v) {
      if (!Number.isFinite(v)) return "—";
      return (v > 0 ? "+" : "") + v.toFixed(2).replace(".", ",") + "%";
    }
    function fmtVol(v) {
      if (!Number.isFinite(v) || v <= 0) return "—";
      if (v >= 1e9) return "US$ " + (v / 1e9).toFixed(1).replace(".", ",") + " B";
      if (v >= 1e6) return "US$ " + Math.round(v / 1e6) + " M";
      if (v >= 1e3) return "US$ " + Math.round(v / 1e3) + " K";
      return "US$ " + Math.round(v);
    }
    function chgPct(a) {
      if (!Number.isFinite(a.prevDayPx) || a.prevDayPx <= 0) return NaN;
      return (a.price - a.prevDayPx) / a.prevDayPx * 100;
    }

    async function loadUniverse() {
      const { dexs, assets: rows } = await fetchAllAssets();
      for (const row of rows) {
        const prev = assets.get(row.key);
        if (prev) {
          prev.prevDayPx = row.prevDayPx;
          prev.volume24h = row.volume24h;
          prev.markPx = row.markPx;
          if (!feed || !feed.isLive()) prev.price = row.price;
        } else {
          row.category = classify(row.symbol, row.dex);
          row.name = displayName(row.symbol);
          row.candles = [];
          row.candlesAt = 0;
          assets.set(row.key, row);
          if (!symbolIndex.has(row.symbol)) symbolIndex.set(row.symbol, []);
          symbolIndex.get(row.symbol).push(row.key);
        }
      }
      lastUpdate = Date.now();
      if (feed) feed.setDexs(dexs.map((d) => d.name));
      return dexs;
    }

    const dirty = new Set();
    let rafPending = false;

    function resolveKey(k, dex) {
      if (assets.has(k)) return k;
      if (dex && assets.has(`${dex}:${k}`)) return `${dex}:${k}`;
      const cands = symbolIndex.get(k);
      return cands && cands.length === 1 ? cands[0] : null;
    }

    function onMids(mids, dex) {
      const now = Date.now();
      for (const k in mids) {
        if (k.startsWith("@")) continue;
        const key = resolveKey(k, dex);
        if (!key) continue;
        const px = parseFloat(mids[k]);
        if (!Number.isFinite(px)) continue;
        const a = assets.get(key);
        if (px === a.price) continue;
        a.lastDir = px > a.price ? 1 : -1;
        a.price = px;
        updateLastCandle(a, px, now);
        dirty.add(key);
      }
      lastUpdate = now;
      if (!rafPending) { rafPending = true; requestAnimationFrame(flushDirty); }
    }

    function flushDirty() {
      rafPending = false;
      for (const key of dirty) {
        const el = cardEls.get(key);
        if (el) updateCardData(el, assets.get(key), true);
      }
      dirty.clear();
      updateSummary();
    }

    function updateLastCandle(a, px, now) {
      if (!a.candles.length) return;
      const last = a.candles[a.candles.length - 1];
      if (now < last.t + CANDLE_MS) {
        last.c = px;
        if (px > last.h) last.h = px;
        if (px < last.l) last.l = px;
      } else {
        const t = last.t + Math.floor((now - last.t) / CANDLE_MS) * CANDLE_MS;
        a.candles.push({ t, o: px, h: px, l: px, c: px, v: 0 });
        while (a.candles.length > MAX_CANDLES) a.candles.shift();
      }
    }

    const candleQueue = [];
    const queued = new Set();
    let inflight = 0;

    function requestCandles(key, force) {
      const a = assets.get(key);
      if (!a || queued.has(key)) return;
      if (!force && Date.now() - a.candlesAt < CANDLE_TTL_MS) return;
      queued.add(key);
      candleQueue.push(key);
      pumpCandles();
    }

    function pumpCandles() {
      while (inflight < 5 && candleQueue.length) {
        const key = candleQueue.shift();
        inflight++;
        const a = assets.get(key);
        fetchCandles(a, CANDLE_INTERVAL, CANDLE_LOOKBACK)
          .then((rows) => {
            a.candles = rows.slice(-MAX_CANDLES);
            a.candlesAt = Date.now();
            const el = cardEls.get(key);
            if (el) drawCard(el, a);
          })
          .catch((err) => console.warn("m247: velas", key, err))
          .finally(() => { inflight--; queued.delete(key); pumpCandles(); });
      }
    }

    const observer = new IntersectionObserver((entries) => {
      for (const e of entries) {
        const key = e.target.dataset.key;
        if (e.isIntersecting) { visibleKeys.add(key); requestCandles(key, false); }
        else visibleKeys.delete(key);
      }
    }, { rootMargin: "200px" });

    function buildCard(a) {
      const el = document.createElement("article");
      el.className = "m247-card";
      el.dataset.key = a.key;
      el.innerHTML =
        '<div class="m247-card-top">' +
          '<div class="m247-card-left">' +
            '<button type="button" class="m247-star" aria-label="Favorito" title="Agregar a favoritos">★</button>' +
            '<span class="m247-sym"></span>' +
          "</div>" +
          '<span class="m247-price"></span>' +
        "</div>" +
        '<div class="m247-card-sub"><span class="m247-name"></span><span class="m247-chg"></span></div>' +
        '<div class="m247-chart"><canvas></canvas><div class="m247-chart-loading">cargando…</div></div>' +
        '<div class="m247-card-foot"><span class="m247-vol"></span><span class="m247-dex"></span></div>';

      el.querySelector(".m247-sym").textContent = a.symbol;
      el.querySelector(".m247-name").textContent = a.name;
      el.querySelector(".m247-name").title = a.dexName ? `${a.name} · dex ${a.dexName}` : a.name;
      el.querySelector(".m247-dex").textContent = a.dex ? a.dexName : "Perp";
      el.querySelector(".m247-star").addEventListener("click", () => toggleFav(a.key));

      attachHover(el.querySelector("canvas"), tooltip, () => ({
        candles: a.candles, prevDayPx: a.prevDayPx, fmtPrice,
      }));

      updateCardData(el, a, false);
      return el;
    }

    function updateCardData(el, a, flash) {
      const priceEl = el.querySelector(".m247-price");
      const prevText = priceEl.textContent;
      const nextText = fmtPrice(a.price);
      priceEl.textContent = nextText;
      if (flash && prevText !== nextText) {
        priceEl.classList.remove("flash-up", "flash-down");
        void priceEl.offsetWidth;
        priceEl.classList.add(a.lastDir >= 0 ? "flash-up" : "flash-down");
        setTimeout(() => priceEl.classList.remove("flash-up", "flash-down"), 350);
      }
      const pct = chgPct(a);
      const chgEl = el.querySelector(".m247-chg");
      chgEl.textContent = fmtPct(pct);
      chgEl.className = "m247-chg " + (pct > 0 ? "up" : pct < 0 ? "down" : "flat");
      el.querySelector(".m247-vol").textContent = "Vol 24h " + fmtVol(a.volume24h);
      el.querySelector(".m247-star").classList.toggle("is-fav", favs.has(a.key));
      if (a.candles.length && visibleKeys.has(a.key)) drawCard(el, a);
    }

    function drawCard(el, a) {
      const loading = el.querySelector(".m247-chart-loading");
      if (loading && a.candlesAt) {
        if (a.candles.length) loading.remove();
        else loading.textContent = "sin datos de velas";
      }
      drawChart(el.querySelector("canvas"), a.candles, a.prevDayPx, null);
    }

    function toggleFav(key) {
      if (favs.has(key)) favs.delete(key);
      else favs.add(key);
      localStorage.setItem(LS.favs, JSON.stringify([...favs]));
      const el = cardEls.get(key);
      if (el) el.querySelector(".m247-star").classList.toggle("is-fav", favs.has(key));
      if (tab === "fav") renderGrid();
      else updateSummary();
    }

    function visibleAssets() {
      const q = search.trim().toLowerCase();
      const list = [];
      for (const a of assets.values()) {
        if (tab === "fav" ? !favs.has(a.key) : a.category !== tab) continue;
        if (q && !(a.symbol.toLowerCase().includes(q) || a.name.toLowerCase().includes(q))) continue;
        if (!(a.volume24h > 0) && !Number.isFinite(a.price)) continue;
        list.push(a);
      }
      if (sortMode === "gainers") list.sort((x, y) => (chgPct(y) || -Infinity) - (chgPct(x) || -Infinity));
      else if (sortMode === "losers") list.sort((x, y) => (chgPct(x) || Infinity) - (chgPct(y) || Infinity));
      else list.sort((x, y) => y.volume24h - x.volume24h);
      return list;
    }

    function renderGrid() {
      const list = visibleAssets();

      // Al cambiar de pestaña/orden/búsqueda, volver al primer lote.
      const sig = tab + "|" + sortMode + "|" + search;
      if (sig !== lastSig) { shownCount = PAGE_SIZE; lastSig = sig; }

      const pageList = list.slice(0, shownCount);
      const wanted = new Set(pageList.map((a) => a.key));
      for (const [key, el] of cardEls) {
        if (!wanted.has(key)) {
          observer.unobserve(el);
          el.remove();
          cardEls.delete(key);
          visibleKeys.delete(key);
        }
      }
      let anchor = null;
      for (const a of pageList) {
        let el = cardEls.get(a.key);
        if (!el) {
          el = buildCard(a);
          cardEls.set(a.key, el);
          observer.observe(el);
        } else {
          updateCardData(el, a, false);
        }
        if (anchor) anchor.after(el);
        else els.grid.prepend(el);
        anchor = el;
      }

      // Tile "＋ mostrar más": revela el siguiente lote sin recargar todo.
      if (moreTileEl) { moreTileEl.remove(); moreTileEl = null; }
      const remaining = list.length - pageList.length;
      if (remaining > 0) {
        moreTileEl = document.createElement("button");
        moreTileEl.type = "button";
        moreTileEl.className = "m247-more";
        moreTileEl.innerHTML =
          '<span class="plus">+</span>' +
          '<span class="lbl">Mostrar más</span>' +
          `<span class="cnt">${remaining} activo${remaining === 1 ? "" : "s"} más</span>`;
        moreTileEl.addEventListener("click", () => {
          shownCount += PAGE_SIZE;
          renderGrid();
        });
        if (anchor) anchor.after(moreTileEl);
        else els.grid.appendChild(moreTileEl);
      }

      els.empty.hidden = list.length > 0 || !loaded;
      if (loaded && !list.length) {
        els.empty.textContent = tab === "fav" && !search
          ? "Todavía no tenés favoritos: tocá la ★ de cualquier activo para fijarlo acá."
          : "No hay activos que coincidan con la búsqueda en esta pestaña.";
      }
      updateSummary();
    }

    function updateSummary() {
      const list = visibleAssets();
      els.summary.hidden = !loaded || !list.length;
      if (els.summary.hidden) return;
      let ups = 0, downs = 0, best = null, worst = null;
      for (const a of list) {
        const p = chgPct(a);
        if (!Number.isFinite(p)) continue;
        if (p > 0) ups++;
        else if (p < 0) downs++;
        if (!best || p > chgPct(best)) best = a;
        if (!worst || p < chgPct(worst)) worst = a;
      }
      let html = `<span><b>${ups}</b> suben · <b>${downs}</b> bajan</span>`;
      if (best && chgPct(best) > 0) html += `<span>Mayor suba <b>${best.symbol}</b> <span class="up">${fmtPct(chgPct(best))}</span></span>`;
      if (worst && chgPct(worst) < 0) html += `<span>Mayor baja <b>${worst.symbol}</b> <span class="down">${fmtPct(chgPct(worst))}</span></span>`;
      els.summaryText.innerHTML = html;
      const total = ups + downs || 1;
      els.meterUp.style.width = (ups / total * 100).toFixed(1) + "%";
      els.meterDown.style.width = (downs / total * 100).toFixed(1) + "%";
    }

    function tickStatus() {
      const secs = lastUpdate ? Math.max(0, Math.round((Date.now() - lastUpdate) / 1000)) : null;
      const ago = secs == null ? "" : secs < 60 ? `hace ${secs}s` : `hace ${Math.floor(secs / 60)}m`;
      els.liveDot.className = "m247-dot";
      if (feedStatus === "live") {
        els.liveDot.classList.add("is-live");
        els.updated.textContent = `En vivo · actualizado ${ago}`;
      } else if (loaded) {
        els.liveDot.classList.add("is-poll");
        els.updated.textContent = `Sondeo (WS reconectando) · ${ago}`;
      } else {
        els.liveDot.classList.add("is-off");
        els.updated.textContent = "conectando…";
      }
      try {
        const parts = new Intl.DateTimeFormat("en-US", {
          timeZone: "America/New_York", weekday: "short", hour: "numeric", minute: "numeric", hour12: false,
        }).formatToParts(new Date());
        const get = (t) => parts.find((p) => p.type === t).value;
        const mins = parseInt(get("hour"), 10) % 24 * 60 + parseInt(get("minute"), 10);
        const open = !["Sat", "Sun"].includes(get("weekday")) && mins >= 570 && mins < 960;
        els.nyse.textContent = open ? "Abierto" : "Cerrado";
        els.nysePill.querySelector(".m247-dot").className = "m247-dot " + (open ? "is-live" : "is-off");
      } catch (_) { els.nyse.textContent = "—"; }
    }

    function showError(msg) {
      els.errorText.textContent = msg;
      els.error.hidden = false;
    }

    function syncControls() {
      els.tabs.querySelectorAll(".m247-tab").forEach((b) =>
        b.classList.toggle("is-active", b.dataset.cat === tab));
      els.sorts.querySelectorAll(".m247-sort").forEach((b) =>
        b.classList.toggle("is-active", b.dataset.sort === sortMode));
    }

    els.tabs.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".m247-tab");
      if (!btn) return;
      tab = btn.dataset.cat;
      localStorage.setItem(LS.tab, tab);
      syncControls();
      renderGrid();
    });
    els.sorts.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".m247-sort");
      if (!btn) return;
      sortMode = btn.dataset.sort;
      localStorage.setItem(LS.sort, sortMode);
      syncControls();
      renderGrid();
    });
    let searchTimer = null;
    els.search.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { search = els.search.value; renderGrid(); }, 120);
    });
    els.retry.addEventListener("click", () => { els.error.hidden = true; boot(); });
    window.addEventListener("resize", () => {
      for (const key of visibleKeys) {
        const a = assets.get(key);
        const el = cardEls.get(key);
        if (a && el && a.candles.length) drawCard(el, a);
      }
    });

    let booting = false;
    async function boot() {
      if (booting) return;
      booting = true;
      try {
        await loadUniverse();
        loaded = true;
        if (tab === "fav" && !favs.size) {
          const cats = new Set([...assets.values()].map((a) => a.category));
          tab = cats.has("stocks") ? "stocks" : "crypto";
        }
        syncControls();
        renderGrid();
        if (!feed) {
          feed = createLiveFeed(onMids, (st) => { feedStatus = st; tickStatus(); });
          feed.setDexs([...new Set([...assets.values()].map((a) => a.dex))]);
        }
      } catch (err) {
        console.error(err);
        showError("No se pudo conectar a la API de Hyperliquid (" + err.message + "). " +
          "Revisá tu conexión o si un bloqueador está frenando api.hyperliquid.xyz.");
      } finally {
        booting = false;
      }
    }

    setInterval(() => {
      if (loaded) loadUniverse().then(updateSummary).catch((e) => console.warn("m247: refresh", e));
    }, CTX_REFRESH_MS);
    setInterval(() => { for (const key of visibleKeys) requestCandles(key, false); }, 60000);
    setInterval(tickStatus, 1000);
    tickStatus();
    syncControls();
    boot();
  }

  /* API pública: patrón window.renderXxx de FinanzasBo + init explícito */
  window.renderMercado247 = function (target) {
    mount(target || document.querySelector("[data-mercado247]") || "#tab-mercado247");
  };
  window.initMercado247 = window.renderMercado247;

  // auto-init si el contenedor pide montarse solo (fuera de un sistema de tabs)
  function autoInit() {
    const el = document.querySelector("[data-mercado247-auto]");
    if (el) mount(el);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", autoInit);
  else autoInit();
})();
