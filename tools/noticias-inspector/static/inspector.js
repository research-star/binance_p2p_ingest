"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const api = (p, m = "GET") => fetch(p, { method: m }).then(r => r.json());

let LANE = "bolivia";
let LAST = null;          // last /api/last-run payload
let GALLERY_LOADED = false, SYNC_LOADED = false;

// ── header / status ──────────────────────────────────────────────────────────
function renderStatus(d) {
  const run = d.run, st = d.state, cron = d.cron, deps = d.deps;
  $("#st-running").hidden = !st.running;
  if (run) {
    $("#st-run").innerHTML = `corrida <b>${esc(run.ts)}</b> · modo <b>${esc(run.mode)}</b>`;
    $("#st-scoring").innerHTML = `scoring <b>${esc(run.scoring)}</b>`;
    const h = run.hermetic && run.hermetic.ok;
    const sc = $("#st-hermetic"); sc.className = "chip " + (h ? "ok" : "bad");
    sc.innerHTML = h ? "hermético ✓ (DBs reales intactas)" : "⚠ DBs reales cambiaron";
  } else {
    $("#st-run").textContent = st.last_error ? "última corrida falló" : "sin corridas aún";
  }
  const cc = $("#st-cron"); cc.className = "chip " + (cron.cron_on ? "ok" : "");
  cc.innerHTML = cron.cron_on ? `cron 1h ON · próx ${esc(cron.next_run || "?")}` : "cron OFF";
  const miss = (deps.missing || []);
  const dc = $("#st-deps"); dc.className = "chip " + (miss.length ? "warn" : "ok");
  dc.innerHTML = miss.length ? `deps faltan: ${miss.map(m => esc(m.import)).join(", ")}` : "deps OK";
}

// ── tab 1: funnel ────────────────────────────────────────────────────────────
function renderFunnel() {
  const host = $("#funnel");
  if (!LAST || !LAST.run) { host.innerHTML = `<div class="empty">Sin corridas. Tocá «Correr ahora» (live) o «Replay».</div>`; return; }
  const lane = LAST.run[LANE];
  if (!lane) { host.innerHTML = `<div class="empty">carril sin datos</div>`; return; }
  if (lane.error) host.innerHTML = `<div class="empty">carril: ${esc(lane.error)}</div>`; else host.innerHTML = "";
  const stages = lane.stages || [];
  let html = "";
  for (const s of stages) {
    const opaque = s.kind === "scraper" && s.out == null;
    const cls = ["stage", s.kind === "scraper" ? "scraper" : "", s.seam ? "seam" : "", opaque ? "opaque" : ""].join(" ");
    const out = s.out == null ? "·" : s.out;
    const killN = s.killed_n || 0;
    const killBtn = killN ? `<span class="kill" data-kill="${s.i}-${LANE}">▾ −${killN}</span>` : "";
    html += `<div class="${cls}">
      <div class="row">
        <span class="idx">${s.i}.</span>
        <span class="nm">${esc(s.name)}</span><span class="fn">${esc(s.fn)}</span>
        <span class="dots"></span>
        <span class="out">${out}</span> ${killBtn}
      </div>
      <div class="killed" id="killed-${s.i}-${LANE}">${(s.killed || []).map(k => killRow(k)).join("")}</div>
    </div>`;
  }
  // final set X
  const fin = lane.final || [];
  html += `<div class="final-head">▣ set X (${fin.length}) — lo que se publicaría</div><div class="final">`;
  for (const n of fin) {
    html += `<div class="f">· <span class="pj">${n.puntaje != null ? Number(n.puntaje).toFixed(1) : "—"}</span>
      <span class="cat">[${esc(n.category || "")}]</span> ${esc(n.title)}
      <span class="src">${esc(n.source || "")}</span>${n.tambien_en && n.tambien_en.length ? ` <span class="src">+${n.tambien_en.length} también-en</span>` : ""}</div>`;
  }
  html += `</div>`;
  host.innerHTML = html;
  $$(".kill", host).forEach(b => b.onclick = () => { const id = "killed-" + b.dataset.kill; $("#" + id).classList.toggle("open"); });
}
function killRow(k) {
  return `<div class="k">✕ <span class="why">${esc(k.reason)}</span>
    ${k.puntaje != null ? `<span class="pj">${Number(k.puntaje).toFixed(1)}</span>` : ""}
    ${esc(k.title)} <span class="src">${esc(k.source || "")}</span>${k.tema ? ` · ${esc(k.tema)}` : ""}</div>`;
}

// ── tab 2: prod preview ──────────────────────────────────────────────────────
function renderProd() {
  const host = $("#prodview");
  if (!LAST || !LAST.run) { host.innerHTML = `<div class="empty">Sin corridas.</div>`; return; }
  const rows = LAST.run.prod_preview || [];
  if (!rows.length) { host.innerHTML = `<div class="empty">Set X vacío.</div>`; return; }
  let html = "", lastCarril = null;
  for (const p of rows) {
    if (p.carril !== lastCarril) { html += `<div class="lane-label">${p.carril === "latam" ? "Latam / Internacional" : "Bolivia"}</div>`; lastCarril = p.carril; }
    html += `<div class="pcard"><div class="pimg">${imgBlock(p.image)}</div>
      <div class="pbody"><div class="sect">${esc(p.section)}</div>
      <div class="ptitle">${esc(p.title)}</div>
      <div class="pmeta">${esc(p.source || "")}${p.category ? " · " + esc(p.category) : ""}${p.tema ? " · " + esc(p.tema) : ""}</div>
      </div></div>`;
  }
  host.innerHTML = html;
}
function imgBlock(img) {
  if (!img) return `<span class="imgtag ph">?</span>`;
  if (img.kind === "og:image") return `<span class="imgtag og">og:image</span><img src="${esc(img.url)}" loading="lazy" onerror="this.style.display='none'">`;
  if (img.kind === "galeria") return `<span class="imgtag gal">galería · ${esc(img.slug)}${img.prod_nulled_og ? " (og anulado)" : ""}</span><img src="/gal/${esc(img.file)}" loading="lazy">`;
  return `<span class="imgtag ph">placeholder${img.prod_nulled_og ? " (og anulado)" : ""}</span>`;
}

// ── tab 3: gallery ───────────────────────────────────────────────────────────
function renderGallery() {
  const host = $("#galleryview");
  api("/api/gallery").then(g => {
    let html = "";
    for (const s of g.slugs) {
      html += `<div class="gcard ${s.valid ? "" : "bad-slug"}">
        ${s.exists ? `<img src="/gal/${esc(s.webp)}" loading="lazy">` : `<div style="aspect-ratio:16/10;display:flex;align-items:center;justify-content:center;color:#777">sin webp</div>`}
        <div class="gbody"><div class="gslug">${esc(s.slug)}</div>
        <div class="grow"><b>temas:</b> ${s.temas.length ? s.temas.map(esc).join(", ") : "—"}</div>
        <div class="grow"><b>keywords:</b> ${s.keyword_rules.length ? s.keyword_rules.flatMap(r => r.keywords).map(k => `<span class="kw">${esc(k)}</span>`).join("") : "—"}</div>
        </div></div>`;
    }
    host.innerHTML = `<div class="hint">${g.n_valid_slugs} slugs válidos · ${g.n_webp_present} webp · ${g.n_keyword_rules} reglas keyword · ${g.n_temas} temas mapeados${g.orphans.length ? " · ⚠ orphans: " + g.orphans.join(",") : ""}${g.missing_webp.length ? " · ⚠ sin webp: " + g.missing_webp.join(",") : ""}</div>` + `<div class="gallerygrid">${html}</div>`;
  });
}

// ── tab sync ─────────────────────────────────────────────────────────────────
function renderSync() {
  api("/api/constants").then(c => {
    const rowset = (arr, cls = "") => arr.map(r => `<tr class="${cls}"><td>${esc(r.name)}</td><td class="v">${esc(r.value)}</td></tr>`).join("");
    let html = `<table><thead><tr><th>constante (importada viva — auto-sync)</th><th>valor</th></tr></thead><tbody>${rowset(c.importable)}</tbody></table>`;
    html += `<h3 style="margin:18px 0 6px;font-size:13px;color:#e3b341">Sync-MANUAL (literales inline / superficie de paridad)</h3>`;
    html += `<table><tbody>${rowset(c.manual_sync, "manual")}</tbody></table>`;
    if (c.errors && c.errors.length) html += `<h3 style="color:#f25b5b;margin-top:14px;font-size:13px">⚠ no importables (revisar Sync Contract)</h3><table><tbody>${c.errors.map(e => `<tr><td>${esc(e.name)}</td><td class="v">${esc(e.error)}</td></tr>`).join("")}</tbody></table>`;
    $("#syncview").innerHTML = html;
  });
}

// ── wiring ───────────────────────────────────────────────────────────────────
function switchTab(name) {
  $$(".tab").forEach(t => t.classList.toggle("on", t.dataset.tab === name));
  $$(".tabpane").forEach(p => p.classList.toggle("on", p.id === "tab-" + name));
  if (name === "galeria" && !GALLERY_LOADED) { renderGallery(); GALLERY_LOADED = true; }
  if (name === "sync" && !SYNC_LOADED) { renderSync(); SYNC_LOADED = true; }
}
function poll() {
  api("/api/last-run").then(d => {
    LAST = d; renderStatus(d); renderFunnel(); renderProd();
    [...$$("#btn-run-live,#btn-run-replay")].forEach(b => b.disabled = d.state.running);
  }).catch(() => {});
}
window.addEventListener("DOMContentLoaded", () => {
  $$(".tab").forEach(t => t.onclick = () => switchTab(t.dataset.tab));
  $$(".lane").forEach(l => l.onclick = () => { LANE = l.dataset.lane; $$(".lane").forEach(x => x.classList.toggle("on", x === l)); renderFunnel(); });
  $("#btn-run-live").onclick = () => api("/api/run-now?mode=live", "POST").then(poll);
  $("#btn-run-replay").onclick = () => api("/api/run-now?mode=replay", "POST").then(poll);
  $("#btn-cron-start").onclick = () => api("/api/cron/start", "POST").then(poll);
  $("#btn-cron-stop").onclick = () => api("/api/cron/stop", "POST").then(poll);
  poll(); setInterval(poll, 3000);
});
