/* ft-frontpage.jsx — portada editorial Noticias 2.0 (desktop + mobile).
   <FrontPage mode="desktop" /> · <FrontPage mode="mobile" />  */
const { useState: useStateFP } = React;

function groupRiver(activeCat, perGroup) {
  const river = window.NEWS2.filter((n) => n.tier === 'river');
  const order = window.CAT2_ORDER;
  let groups = order.map((c) => ({ cat: c, items: river.filter((n) => n.category === c) })).filter((g) => g.items.length);
  if (activeCat && activeCat !== 'all') groups = groups.filter((g) => g.cat === activeCat);
  if (perGroup) groups = groups.map((g) => ({ cat: g.cat, items: g.items.slice(0, perGroup), more: g.items.length - perGroup }));
  return groups;
}

// ── franjas reutilizables ──
function Utility({ lang, setLang }) {
  return <div className="ft-utility">
    <span className="ft-date">martes 3 de junio de 2026 · La Paz, Bolivia</span>
    <span className="ft-upd"><span className="ft-live"></span><span className="lbl">Actualizado</span> 09:09</span>
    <span className="ft-langtoggle">
      <button className={lang === 'es' ? 'on' : ''} onClick={() => setLang('es')}>ES</button>
      <button className={lang === 'en' ? 'on' : ''} onClick={() => setLang('en')}>EN</button>
    </span>
  </div>;
}

function Masthead() {
  return <header className="ft-masthead">
    <div className="ft-nameplate" style={{ fontWeight: "500" }}>Finanzas<b style={{ fontWeight: "600" }}>Bo</b></div>
    <div className="ft-tagline">Inteligencia económica de Bolivia</div>
    <div className="ft-masthead-rules"><div className="r1"></div><div className="r2"></div></div>
  </header>;
}

function Nav({ mode }) {
  const tabs = ['Noticias', 'Macro', 'Dólar', 'Rendimientos DPF', 'BBV'];
  const active = window.FB_ACTIVE_TAB || 'Noticias';
  const NAV = window.FB_NAV || {};
  const go = (t) => {if (NAV[t]) {try {location.href = NAV[t];} catch (e) {}}};
  return <nav className="ft-nav">
    <div className="ft-nav-tabs">
      {tabs.map((t) => <button key={t} className={`ft-nav-tab ${t === active ? 'active' : ''}`} onClick={() => go(t)}>{t}</button>)}
    </div>
    <div className="ft-nav-ctrls">
      {mode === 'desktop' && <div className="ft-search"><window.FtSearchIcon /><span>Buscar en Noticias…</span></div>}
      <button className="ft-iconbtn"><window.FtBookmarkIcon />{mode === 'desktop' && 'Guardadas'}</button>
      <button className="ft-hamburger"><window.FtMenuIcon /></button>
    </div>
  </nav>;
}

function Chips({ active, setActive, mode }) {
  const order = window.CAT2_ORDER;
  return <div className="ft-chips">
    {mode === 'desktop' && <span className="ft-chips-lab">Categorías</span>}
    <button className={`ft-chip ${active === 'all' ? 'on' : ''}`} onClick={() => setActive('all')}>Todas</button>
    {order.map((c) => <button key={c} className={`ft-chip ${active === c ? 'on' : ''}`} onClick={() => setActive(c)}>{window.CATS2[c].name}</button>)}
  </div>;
}

function DayNav() {
  const [active, setActive] = useStateFP(0);
  return <div className="ft-daynav">
    {window.DAYS2.map((d, i) => <button key={d} className={i === active ? 'on' : ''} onClick={() => setActive(i)}>{i === 0 ? 'Hoy' : d}</button>)}
  </div>;
}

// ── bloque líder + secundarias ──
function TopBlock() {
  const lead = window.NEWS2.find((n) => n.tier === 'lead');
  const secs = window.NEWS2.filter((n) => n.tier === 'sec');
  return <section className="ft-top">
    <article className="ft-lead">
      <div className="ft-lead-kicker">
        <window.Kicker cat={lead.category} />
        <window.Impact2 level={lead.impact} />
      </div>
      <h1 className="ft-lead-title">{lead.title}</h1>
      <window.ImgPh label="Mercado cambiario · La Paz" cap="Operadores del mercado P2P siguen la cotización del paralelo. Imagen de referencia." />
      <p className="ft-lead-stand">{lead.standfirst}</p>
      <window.Dateline item={lead} />
    </article>
    <div className="ft-secs">
      {secs.map((s, i) =>
      <article className="ft-sec" key={s.id}>
          <div className="ft-sec-kicker"><window.Kicker cat={s.category} /></div>
          {i === 0 ?
        <div className="ft-sec-row">
              <div className="ft-sec-main">
                <h2 className="ft-sec-title">{s.title}</h2>
                <p className="ft-sec-stand">{s.standfirst}</p>
                <window.Dateline item={s} />
              </div>
              <window.ImgPh sm label="Energía" />
            </div> :

        <>
              <h2 className="ft-sec-title">{s.title}</h2>
              <p className="ft-sec-stand">{s.standfirst}</p>
              <window.Dateline item={s} />
            </>
        }
        </article>
      )}
    </div>
  </section>;
}

// ── río principal ──
function River({ active, mode, layout }) {
  // modo LISTA densa (columnas de texto, agrupado por categoría)
  if (layout === 'list') {
    const groups = groupRiver(active, mode === 'mobile' ? 2 : 0);
    return <section>
      <div className="ft-section-head">
        <h2>Río de titulares</h2>
        <span className="meta">Selección automática por relevancia · top 10/día</span>
      </div>
      <div className="ft-river">
        {groups.map((g) =>
        <div className="ft-catgroup" key={g.cat}>
            <div className="ft-catgroup-head">
              <span className="lab">{window.CATS2[g.cat].name}</span>
              <span className="ln"></span>
              <span className="ct">{g.items.length}</span>
            </div>
            {g.items.map((it) => <window.Story key={it.id} item={it} />)}
            {mode === 'mobile' && g.more > 0 && <button className="ft-morelink">+ {g.more} más en {window.CATS2[g.cat].name}</button>}
          </div>
        )}
      </div>
    </section>;
  }
  // modo TARJETAS con foto (default — estilo FT / Eju), grilla plana
  let items = window.NEWS2.filter((n) => n.tier === 'river');
  if (active && active !== 'all') items = items.filter((n) => n.category === active);
  const total = items.length;
  if (mode === 'mobile') items = items.slice(0, 10);
  return <section>
    <div className="ft-section-head">
      <h2>Río de titulares</h2>
      <span className="meta">Selección automática por relevancia · {total} notas hoy</span>
    </div>
    <div className="ft-river-cards">
      {items.map((it) => <window.StoryCard key={it.id} item={it} />)}
    </div>
    {mode === 'mobile' && total > items.length && <button className="ft-morelink">+ {total - items.length} notas más del día</button>}
  </section>;
}

// ── right rail ──
function Rail({ mode }) {
  const compact = mode === 'mobile';
  const top = window.NEWS2.filter((n) => n.impact === 'alto').slice(0, compact ? 3 : 5);
  return <aside className="ft-rail">
    <div className="ft-railcard">
      <h3>Lo más relevante hoy <span className="sub">por impacto</span></h3>
      {top.map((t, i) =>
      <div className="ft-rank" key={t.id}>
          <span className="num">{i + 1}</span>
          <div className="rk-main">
            <div className="rk-title">{t.title}</div>
            <div className="rk-meta">{window.PORTALS2[t.source].name} · {t.time}</div>
          </div>
        </div>
      )}
    </div>
    <div className="ft-railcard ft-agenda">
      <h3>Agenda · próximo hecho</h3>
      {window.AGENDA2.map((a) =>
      <div className="ft-agenda-item" key={a.id}>
          <div className="ft-agenda-when">
            <span className="d">en</span><span className="n">{a.inDays}</span><span className="u">días</span>
          </div>
          <div className="ft-agenda-txt">{a.title}</div>
        </div>
      )}
      <div className="ft-agenda-note">Dato de ejemplo · agenda editorial</div>
    </div>
    <div className="ft-railcard ft-digest" style={compact ? { display: 'none' } : undefined}>
      <h3>Digest Latam <span className="sub">Bloomberg Línea</span></h3>
      {window.LATAM2.slice(0, 5).map((l) =>
      <div className="dg" key={l.id}>
          <span className="ctry">{l.country}</span>
          <span className="tx">{l.title}</span>
        </div>
      )}
    </div>
  </aside>;
}

// ── banda Latam / Internacional ──
function LatamBand() {
  return <section className="ft-latam">
    <div className="ft-latam-head">
      <h2>Latam / Internacional</h2>
      <span className="by"><span className="dot"></span>Selección editorial · Bloomberg Línea · hasta 5/día</span>
    </div>
    <div className="ft-latam-grid">
      {window.LATAM2.map((l) =>
      <article className="ft-latam-card" key={l.id}>
          <div className="ft-latam-flag">{l.country}</div>
          <h3 className="ft-latam-title">{l.title}</h3>
          <p className="ft-latam-stand">{l.standfirst}</p>
          <div className="ft-latam-time">{l.time}</div>
        </article>
      )}
    </div>
  </section>;
}

// ── footer ──
function Footer() {
  const portals = window.PORTAL2_ORDER;
  const goMacro = () => {try {location.href = window.FB_NAV && window.FB_NAV.Macro || 'Macroeconomia.html';} catch (e) {}};
  return <footer className="ft-footer">
    <div className="ft-foot-sources">
      <div className="ft-foot-lab">Fuentes monitoreadas</div>
      <div className="ft-foot-portals">
        {portals.map((p) =>
        <span key={p} className={`ft-foot-portal ${p === 'bloomberg' ? 'linea' : ''}`}>{window.PORTALS2[p].name}</span>
        )}
      </div>
    </div>
    <div className="ft-foot-grid">
      <div className="ft-method">
        <b>Metodología.</b> Las notas bolivianas se agregan de forma automática desde 13 portales y se ordenan por relevancia económica (selección top ~10/día). El carril <b>Latam / Internacional</b> es una selección editorial de Bloomberg Línea, hasta 5 notas por día. Más del 80% del contenido se genera automáticamente; cada nota enlaza al original.
        <div className="ft-disc">Contenido de ejemplo, ilustrativo. FinanzasBo agrega y enlaza a las fuentes originales; los derechos pertenecen a cada medio. Indicadores con fines informativos, no constituyen asesoría financiera.</div>
      </div>
      <div className="ft-foot-tabs">
        <span className="lab">Explorar el panel</span>
        <a>Dólar paralelo</a>
        <a onClick={goMacro}>Macroeconomía</a>
        <a>Bolsa BBV</a>
        <a>Rendimientos DPF</a>
      </div>
    </div>
    <div className="ft-foot-copy">© 2026 FinanzasBo · Inteligencia económica de Bolivia · La Paz</div>
  </footer>;
}

// ── ensamblaje ──
function FrontPage({ mode = 'desktop', layout = 'cards' }) {
  const [lang, setLang] = useStateFP('es');
  const [active, setActive] = useStateFP('all');
  return <div className={`ft-page ${mode === 'mobile' ? 'ft-m' : ''}`}>
    <Utility lang={lang} setLang={setLang} />
    <Masthead />
    <Nav mode={mode} />
    <window.MarketsStrip />
    <div className="ft-body">
      <TopBlock />
      <div className="ft-main">
        <River active={active} mode={mode} layout={layout} />
        <Rail mode={mode} />
      </div>
    </div>
    <LatamBand />
    <Footer />
  </div>;
}

Object.assign(window, { FrontPage });