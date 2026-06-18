/* ft-components.jsx — átomos editoriales para Noticias 2.0.
   Exporta a window para los scripts babel de la portada. */
const { useState: useStateFT } = React;

function portal2(id) {return window.PORTALS2[id];}
function cat2(id) {return window.CATS2[id];}

// kicker de categoría (versalita)
function Kicker({ cat, label }) {
  return <span className="ft-kicker">{label || window.CAT2_KICKER[cat] || ''}</span>;
}

// tag de impacto (barras)
function Impact2({ level }) {
  const n = level === 'alto' ? 3 : level === 'medio' ? 2 : 1;
  return <span className={`ft-impact ${level}`}>
    <span className="bars">{[0, 1, 2].map((i) => <i key={i} className={i < n ? 'on' : ''}></i>)}</span>
    {level === 'alto' ? 'Alto' : level === 'medio' ? 'Medio' : 'Bajo'}
  </span>;
}

// fuente (portal) con punto celeste
function Src({ id, withCity }) {
  const p = portal2(id);if (!p) return null;
  return <span className="ft-src"><span className="dot"></span>{p.name}{withCity && p.city !== 'Nacional' && p.city !== 'Latam' ? ` · ${p.city}` : ''}</span>;
}

// dateline completo: fuente · hora · impacto
function Dateline({ item, showImpact = true }) {
  return <div className="ft-dateline">
    <Src id={item.source} />
    <span className="sep">·</span>
    <span className="ft-time">{item.time}</span>
    {showImpact && <><span className="sep">·</span><Impact2 level={item.impact} /></>}
  </div>;
}

// placeholder de imagen editorial
function ImgPh({ label = 'Fotografía', cap, sm, slotId }) {
  return <figure className="ft-figure">
    <div className={`ft-imgph ${sm ? 'sm' : ''}`}>
      <span className="ft-imglabel">{label}</span>
    </div>
    {cap && <figcaption className="ft-figcap">{cap}</figcaption>}
  </figure>;
}

// flecha desaturada de la franja de indicadores
function IndArrow({ dir }) {
  const g = dir === 'up' ? '▲' : dir === 'down' ? '▼' : '■';
  return <span className={`ft-arrow ${dir}`}>{g}</span>;
}
function Indicator({ ind }) {
  return <div className="ft-ind">
    <span className="ft-ind-lab">{ind.label}</span>
    <div className="ft-ind-row">
      <span className="ft-ind-val">{ind.value}</span>
      <span className="ft-ind-unit">{ind.unit}</span>
    </div>
    <span className="ft-ind-sub"><IndArrow dir={ind.dir} />{ind.sub}</span>
  </div>;
}
function MarketsStrip() {
  return <div className="ft-markets">
    <div className="ft-markets-lab">
      <span className="ft-ml-kick">Mercados</span>
      <span className="ft-ml-title">El día<br />en cifras</span>
    </div>
    {window.INDICATORS2.map((ind) => <Indicator key={ind.id} ind={ind} />)}
  </div>;
}

// item compacto del río (modo lista densa)
function Story({ item }) {
  return <article className="ft-story">
    <div className="ft-story-kicker"><Kicker cat={item.category} label={item.region ? `Regional · ${item.region}` : undefined} /></div>
    <h3 className="ft-story-title">{item.title}</h3>
    <div className="ft-story-meta">
      <Src id={item.source} />
      <span className="sep">·</span>
      <span className="ft-time">{item.time}</span>
      <span className="sep">·</span>
      <Impact2 level={item.impact} />
    </div>
  </article>;
}

// iconos de compartir (estilo Eju)
const IconWA = () => <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2 22l5.25-1.38a9.9 9.9 0 0 0 4.79 1.22h.01c5.46 0 9.91-4.45 9.91-9.91 0-2.65-1.03-5.14-2.9-7.01A9.82 9.82 0 0 0 12.04 2zm0 1.82c2.16 0 4.18.84 5.71 2.37a8.02 8.02 0 0 1 2.37 5.72c0 4.45-3.62 8.08-8.08 8.08a8.2 8.2 0 0 1-4.18-1.15l-.3-.18-3.11.82.83-3.04-.2-.31a8.13 8.13 0 0 1-1.26-4.35c0-4.46 3.63-8.08 8.42-8.08zm4.62 11.55c-.25-.13-1.48-.73-1.71-.81-.23-.08-.4-.13-.56.13-.17.25-.64.81-.79.97-.14.17-.29.18-.54.06-.25-.13-1.06-.39-2.01-1.24-.74-.66-1.24-1.48-1.39-1.73-.14-.25-.01-.39.11-.51.11-.11.25-.29.37-.43.13-.14.17-.25.25-.41.08-.17.04-.31-.02-.43-.06-.13-.56-1.35-.77-1.85-.2-.48-.41-.42-.56-.42l-.48-.01c-.17 0-.43.06-.66.31-.23.25-.86.85-.86 2.07 0 1.22.89 2.4 1.01 2.56.13.17 1.75 2.67 4.23 3.74.59.26 1.05.41 1.41.52.59.19 1.13.16 1.56.1.48-.07 1.48-.6 1.69-1.19.21-.58.21-1.08.14-1.19-.06-.1-.22-.16-.47-.29z" /></svg>;
const IconFB = () => <svg viewBox="0 0 24 24" fill="currentColor"><path d="M13.5 21v-7.5h2.5l.4-2.9h-2.9V8.7c0-.84.23-1.41 1.44-1.41h1.54V4.7c-.27-.04-1.18-.12-2.24-.12-2.22 0-3.74 1.36-3.74 3.84v2.14H8v2.9h2.5V21h3z" /></svg>;
const IconX = () => <svg viewBox="0 0 24 24" fill="currentColor"><path d="M17.53 3h3.05l-6.66 7.61L21.75 21h-6.13l-4.8-6.28L5.32 21H2.27l7.12-8.14L2.5 3h6.28l4.34 5.74L17.53 3zm-1.07 16.2h1.69L7.62 4.71H5.81L16.46 19.2z" /></svg>;

function CardShare() {
  return <div className="ft-card-share">
    <button className="ft-shr" aria-label="Compartir en WhatsApp"><IconWA /></button>
    <button className="ft-shr" aria-label="Compartir en Facebook"><IconFB /></button>
    <button className="ft-shr" aria-label="Compartir en X"><IconX /></button>
  </div>;
}

// tarjeta con foto del río (estilo FT / Eju)
function StoryCard({ item }) {
  const c = cat2(item.category);
  const kick = item.region ? `Regional · ${item.region}` : c.name;
  return <article className="ft-card">
    <div className="ft-imgph ft-card-img">
      <span className="ft-imglabel">{window.CAT2_KICKER[item.category]}</span>
    </div>
    <div className="ft-card-body">
      <div className="ft-card-kicker">{kick}</div>
      <h3 className="ft-card-title">{item.title}</h3>
      <div className="ft-card-meta">
        <Src id={item.source} />
        <span className="sep">·</span>
        <span className="ft-time">{item.time}</span>
        <span className="sep">·</span>
        <Impact2 level={item.impact} />
      </div>
      <CardShare />
    </div>
  </article>;
}

// iconos UI (Inter chrome)
const FtSearchIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.5" y2="16.5" /></svg>;
const FtBookmarkIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" /></svg>;
const FtMenuIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></svg>;

Object.assign(window, {
  portal2, cat2, Kicker, Impact2, Src, Dateline, ImgPh, Story, StoryCard, CardShare,
  Indicator, MarketsStrip, IndArrow,
  FtSearchIcon, FtBookmarkIcon, FtMenuIcon, IconWA, IconFB, IconX
});