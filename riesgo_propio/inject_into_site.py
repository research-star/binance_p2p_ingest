#!/usr/bin/env python3
"""
inject_into_site.py - patch the locally-served FinanzasBo gh-pages index.html to
add the Bolivia own-math lines to the Riesgo Pais chart:

  * "Bolivia — cálc. propio"          historical reconstruction (line), anchored to
                                       the latest REAL live point.
  * "Bolivia — cálc. propio (en vivo)" the genuine price-driven own-math points
                                       recorded daily by live_bolivia.py (markers);
                                       diverges from EMBI and grows over time.

Re-runnable: caller restores a clean index.html from git first. No push.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Target index.html: argv[1] or $RIESGO_INJECT_TARGET (used by the VPS publish
# pipeline), else the local gh-pages worktree (interactive/dev use).
SITE = (sys.argv[1] if len(sys.argv) > 1
        else os.environ.get("RIESGO_INJECT_TARGET")
        or r"C:\Users\RodrigoRosasGuzman\finanzasbo_site\index.html")

data = json.load(open(os.path.join(HERE, "riesgo_propio.json"), encoding="utf-8"))
html = open(SITE, encoding="utf-8").read()
if "/*BOL2*/" in html:
    print("already injected; restore clean index.html first"); sys.exit(1)

payload = json.dumps({"fechas": data["fechas"], "v": data["bolivia_propio"],
                      "live": data.get("live_points", []),
                      "anchor": data["live_anchor_bp"],
                      "anchor_date": data["live_anchor_date"]}, separators=(",", ":"))

aug = """
/*BOL2*/ // ── Bolivia 2 (cálculo propio) — inyección local FinanzasBo ──
(function(){
  try{
    if(typeof DATA!=='object'||!DATA.embi_data) return;
    var ED=DATA.embi_data; if(!ED.fechas||!ED.fechas.length) return;
    var P=__RIESGO_PROPIO__;
    var fk=P.fechas, fv=P.v, m={};
    for(var i=0;i<fk.length;i++) m[fk[i]]=fv[i];
    var out=new Array(ED.fechas.length), j=0, cur=null, first=fk[0];
    for(var d=0;d<ED.fechas.length;d++){
      var fd=ED.fechas[d];
      while(j<fk.length && fk[j]<=fd){ cur=fv[j]; j++; }
      out[d]= (fd<first)? null : cur;
    }
    ED.series.bolivia_propio=out;
    document.documentElement.style.setProperty('--chart-color-bolivia_propio','#0E7C7B');
    document.documentElement.style.setProperty('--chart-color-bolivia_propio_live','#0F6E56');
    function applyLive(arr){
      if(!Array.isArray(arr)||!arr.length) return;
      ED._liveX = arr.map(function(r){ return r.ts || r.date; });
      ED._liveY = arr.map(function(r){ return r.bp; });
      var lm={}; arr.forEach(function(r){ lm[(r.date)||((r.ts||'').slice(0,10))]=r.bp; });
      ED.series.bolivia_propio_live = ED.fechas.map(function(fd){ return (fd in lm)? lm[fd] : null; });
    }
    applyLive(P.live||[]);
    window.__bolTicker = {bp:null, ts:null};
    function updateTicker(){ var lv=ED._liveY||[], lx=ED._liveX||[]; if(lv.length){ window.__bolTicker={bp:lv[lv.length-1], ts:lx.length?(''+lx[lx.length-1]):null}; } }
    updateTicker();
    setInterval(updateTicker, 720000);
    function renderBreakdown(){
      try{
        var el=document.getElementById('rpBreakdown'); if(!el) return;
        var st=window.__rpStore||[]; if(!st.length) return;
        var last=st[st.length-1], px=last.prices||{};
        var be=ED.series.bolivia||[], embiEod=null;
        for(var i=be.length-1;i>=0;i--){ if(be[i]!=null){ embiEod=be[i]; break; } }
        var byday={}; st.forEach(function(p){ byday[(p.date)||((p.ts||'').slice(0,10))]=p; });
        var dk=Object.keys(byday).sort();
        // EOD struck at JPMorgan's mark: NY bond close 15:00 ET. DST-aware via
        // Intl (America/New_York) -> 19:00 UTC in EDT, 20:00 UTC in EST, automatically.
        function etMin(dt){ try{ var ps=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour12:false,hour:'2-digit',minute:'2-digit'}).formatToParts(dt); var h=0,mn=0; ps.forEach(function(p){ if(p.type==='hour')h=parseInt(p.value,10); if(p.type==='minute')mn=parseInt(p.value,10); }); if(h===24)h=0; return h*60+mn; }catch(e){ return dt.getUTCHours()*60+dt.getUTCMinutes()-240; } }
        var ld=dk.length?dk[dk.length-1]:null, eod=null, best=1e9;
        st.forEach(function(p){ if(((p.date)||((p.ts||'').slice(0,10)))!==ld) return; var dt=new Date(p.ts); if(isNaN(dt)) return; var df=Math.abs(etMin(dt)-900); if(df<best){best=df; eod=p;} });
        if(!eod&&ld) eod=byday[ld];
        var order=['USP37878AC26','USP37878AE81','USP37878AF56'], rows='';
        order.forEach(function(isin){ var r=px[isin]; if(!r) return;
          var src=(r.src==='deutsche_boerse')?'DB bid':(r.src==='snapshot'?'snapshot':r.src);
          var sc=(r.src==='snapshot')?'var(--orange)':'var(--text-muted)';
          rows+='<tr><td style="padding:2px 12px 2px 0">'+(r.name||isin)+'</td>'
            +'<td style="text-align:right;padding:2px 12px;font-variant-numeric:tabular-nums">'+(r.clean!=null?(+r.clean).toFixed(2):'-')+'</td>'
            +'<td style="padding:2px 12px;color:'+sc+'">'+src+'</td>'
            +'<td style="text-align:right;padding:2px 0;font-variant-numeric:tabular-nums"><b>'+Math.round(r.zspread_bp)+' pb</b></td></tr>';
        });
        var own=last.bp, gap=(own!=null&&embiEod!=null)?Math.round(own-embiEod):null;
        var ev=eod?eod.bp:null, eg=(ev!=null&&embiEod!=null)?Math.round(ev-embiEod):null;
        function sgn(x){ return (x>=0?'+':'')+x; }
        el.innerHTML='<div style="font-size:12px;color:var(--text-muted);margin:2px 0 5px">Descomposición · cálculo propio (Z-spread por bono)</div>'
          +'<table style="font-size:12px;border-collapse:collapse"><tbody>'+rows+'</tbody></table>'
          +'<div style="font-size:12px;margin-top:7px">MV-ponderado <b>'+Math.round(own)+' pb</b> · EMBI EOD <b>'+Math.round(embiEod)+' pb</b> · brecha en vivo <b style="color:'+(gap<0?'var(--green)':'var(--orange)')+'">'+sgn(gap)+' pb</b></div>'
          +'<div style="font-size:12px;margin-top:2px">EOD propio <b>'+(ev!=null?Math.round(ev)+' pb':'-')+'</b> <span style="color:var(--text-muted)">(15:00 ET · base JPMorgan)</span> vs EMBI EOD '+Math.round(embiEod)+' pb · brecha EOD <b style="color:'+(eg<0?'var(--green)':'var(--orange)')+'">'+(eg!=null?sgn(eg)+' pb':'-')+'</b></div>'
          +'<div style="font-size:11px;color:var(--text-muted);margin-top:5px">JPMorgan marca el EMBI al cierre de NY (15:00 ET · PricingDirect · precios bid). Alineamos el EOD propio a esa hora y usamos el lado bid (como EMBI); el precio del bono es el bid de Frankfurt al cierre (~11:30 ET) → base de timing residual ~3,5h.</div>'
          +'<div style="font-size:11px;color:var(--text-muted);margin-top:3px">La brecha la genera el 2028 corto (~2a) cotizando ajustado; el 2030 usa snapshot (sin venue en vivo), consistente con la curva.</div>';
      }catch(e){}
    }
    window.__rpRenderBreakdown = renderBreakdown;
    function renderTrial(){
      try{
        var el=document.getElementById('rpTrial'); if(!el) return;
        var st=window.__rpStore||[]; if(!st.length) return;
        var last=st[st.length-1], px=last.prices||{};
        if(last.bp_stripped==null) return;
        var be=ED.series.bolivia||[], embiEod=null;
        for(var i=be.length-1;i>=0;i--){ if(be[i]!=null){ embiEod=be[i]; break; } }
        var rep=last.bp_stripped, own=last.bp;
        var gap=(embiEod!=null)?Math.round(rep-embiEod):null;
        var order=['USP37878AC26','USP37878AE81','USP37878AF56'], rows='';
        order.forEach(function(isin){ var r=px[isin]; if(!r||r.stripped_bp==null) return;
          rows+='<tr><td style="padding:1px 12px 1px 0">'+(r.name||isin)+'</td><td style="text-align:right;padding:1px 0;font-variant-numeric:tabular-nums">'+Math.round(r.stripped_bp)+' pb</td></tr>';
        });
        function sgn(x){ return (x>=0?'+':'')+x; }
        el.innerHTML='<div style="border:1px solid #0E7C7B;border-radius:8px;padding:10px 12px;background:rgba(14,124,123,0.05)">'
          +'<div style="font-size:12px;font-weight:600;margin-bottom:2px">Réplica EMBI · trial (todos los ajustes)</div>'
          +'<div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">bid · spread stripped (YTM − UST emparejado) · ponderación MV (EMBIGD) · 15:00 ET</div>'
          +'<table style="font-size:12px;border-collapse:collapse"><tbody>'+rows+'</tbody></table>'
          +'<div style="font-size:13px;margin-top:6px">Réplica <b>'+Math.round(rep)+' pb</b> · EMBI <b>'+Math.round(embiEod)+' pb</b> · residual <b style="color:'+(Math.abs(gap)<=8?'var(--green)':'var(--orange)')+'">'+sgn(gap)+' pb</b></div>'
          +'<div style="font-size:12px;margin-top:3px">+ ajuste de base (Path C '+sgn(-gap)+' pb) → <b>'+Math.round(embiEod)+' pb</b> = EMBI <span style="color:var(--text-muted)">(anclado, no independiente)</span></div>'
          +'<div style="font-size:11px;color:var(--text-muted);margin-top:5px">Spread stripped ≈ Z-spread (curva plana) → la definición no era el driver; el bid sí. Residual restante = 2030 snapshot (sin bid) + timing ~3,5h; solo se cierra con bid del 2030 (feed pago) o precios al cierre de NY.</div>'
          +'</div>';
      }catch(e){}
    }
    window.__rpRenderTrial = renderTrial;
    function renderMethodology(){
      var el=document.getElementById('rpMethodology'); if(!el||el.dataset.done) return; el.dataset.done='1';
      el.innerHTML='<details style="border:0.5px solid var(--border,rgba(33,30,27,.15));border-radius:8px;padding:8px 12px">'
        +'<summary style="cursor:pointer;font-size:13px;font-weight:600">Metodología y fuentes</summary>'
        +'<div style="font-size:12px;color:var(--text-muted);line-height:1.65;margin-top:8px">'
        +'<b>Qué mide.</b> Riesgo soberano de Bolivia calculado con cálculo propio desde precios de bonos crudos; el EMBI de J.P. Morgan es contraste, no la fuente.<br>'
        +'<b>Número.</b> Z-spread ponderado por valor de mercado de los bonos USD vigentes (2028/2030/2031), sobre la curva cero del Tesoro de EE.UU., lado <b>bid</b>. Bandas: BAJO &lt;350 · MEDIO 350–700 · ALTO &gt;700 pb.<br>'
        +'<b>Fórmula.</b> Z-spread s: P<sub>dirty</sub> = Σ CF<sub>k</sub> / (1+(z(τ<sub>k</sub>)+s)/2)<sup>2τ<sub>k</sub></sup>; país = Σ w<sub>i</sub>·s<sub>i</sub> / Σ w<sub>i</sub>, con w<sub>i</sub> = monto·P<sub>dirty</sub>/100. Día 30/360, liquidación T+2.<br>'
        +'<b>Fuentes.</b> Precios 2028/2031: Deutsche Börse (bid, en vivo); 2030: snapshot validado (sin venue en vivo); curva UST: Tesoro EE.UU.; EMBI: BCRD redistribuyendo J.P. Morgan (cierre NY, lag ~1 día hábil).<br>'
        +'<b>Convenciones.</b> Precio <b>bid</b> (como EMBI/PricingDirect); EOD fijado a las <b>15:00 ET</b> (cierre NY, DST-aware); base de timing residual ~3,5h (cierre Frankfurt 11:30 ET).<br>'
        +'<b>Brecha vs EMBI.</b> El bid cerró ~30 de ~40 pb; el spread <i>stripped</i> ≈ Z-spread (curva plana) y la ponderación EMBIGD = MV intra-país, así que ni la definición ni el peso eran el driver. Residual ~−10 pb = 2030 snapshot + timing; solo se cierra con bid del 2030 (feed pago) o precios al cierre de NY.<br>'
        +'<b>Histórico.</b> Reconstrucción anclada a EMBI (no hay precios históricos por bono gratuitos); la señal independiente vive en el borde vivo (bid real) y se acumula hacia adelante.<br>'
        +'<span style="font-size:11px">Documento completo: METHODOLOGY.md · Informativo, no es asesoría financiera.</span>'
        +'</div></details>';
    }
    renderMethodology();
    function refreshLive(){
      fetch('/riesgo_propio_live.json?t='+Date.now()).then(function(r){ return r.ok? r.json(): null; })
        .then(function(arr){ if(!arr) return; applyLive(arr); window.__rpStore=arr; updateTicker(); renderBreakdown(); renderTrial();
          var c=document.getElementById('riesgoChart');
          if(c && c.offsetParent!==null && typeof window.renderRiesgoPais==='function' && !window.__rpBusy){
            window.__rpBusy=true; try{ window.renderRiesgoPais(); } finally{ window.__rpBusy=false; }
          }
        }).catch(function(){});
    }
    window.__rpRefreshLive = refreshLive;
    setInterval(refreshLive, 60000);
    setTimeout(refreshLive, 4000);
  }catch(e){ if(window.console)console.warn('BOL2 inject',e); }
})();
""".replace("__RIESGO_PROPIO__", payload)

anchor = "// ═══ RIESGO PAÍS TAB ═══"
assert anchor in html, "riesgo anchor not found"
html = html.replace(anchor, aug + "\n" + anchor, 1)

edits = [
 ("var SERIES_ORDER = ['bolivia','latino','global','argentina','brasil','chile','colombia','mexico','peru','ecuador'];",
  "var SERIES_ORDER = ['bolivia','bolivia_propio','bolivia_propio_live','latino','global','argentina','brasil','chile','colombia','mexico','peru','ecuador'];"),
 ("var DEFAULT_ACTIVE = ['bolivia','latino'];",
  "var DEFAULT_ACTIVE = ['bolivia','bolivia_propio','bolivia_propio_live','latino'];"),
 ("    bolivia:'Bolivia', latino:'LATINO', global:'Global',",
  "    bolivia:'Bolivia', bolivia_propio:'Bolivia — cálc. propio', bolivia_propio_live:'Bolivia — cálc. propio (en vivo)', latino:'LATINO', global:'Global',"),
 ("var DEFAULT_RANGE = '1Y';", "var DEFAULT_RANGE = 'Max';"),
 ('<div id="riesgoKpis"></div>',
  '<div id="riesgoKpis"></div>\n    <div id="rpBreakdown" style="padding:2px 18px 8px"></div>\n    <div id="rpTrial" style="padding:0 18px 12px"></div>\n    <div id="rpMethodology" style="padding:0 18px 16px"></div>'),
 ('fb-kpi-wrap"><div class="fb-kpi-grid" style="grid-template-columns:repeat(3,1fr)">',
  'fb-kpi-wrap"><div class="fb-kpi-grid" style="grid-template-columns:repeat(4,1fr)">'),
 ("          deltaColor(lat1d))\n      + '</div></div>';",
  "          deltaColor(lat1d))\n      + (function(){var T=window.__bolTicker||{},lb=(T.bp!=null)?T.bp:null,lt=T.ts||'',em=bolLast?bolLast.val:null,df=(lb!=null&&em!=null)?(lb-em):null,dot='<span style=\"display:inline-block;width:7px;height:7px;border-radius:50%;background:#0F6E56;margin-right:6px;vertical-align:1px\"></span>',hhmm=lt.length>=16?lt.slice(11,16):'';return card(dot+'Bolivia en vivo',lb!=null?fmtBps(lb):'—','cálculo propio · bid · en vivo'+(hhmm?(' · '+hhmm):'')+(df!=null?(' · '+(df>=0?'+':'')+Math.round(df)+' vs EMBI'):''),deltaColor(df));})()\n      + '</div></div>';"),
 ("      var isBolivia = k==='bolivia';\n      return {",
  "      var isBolivia = k==='bolivia';\n      var isPropio = k==='bolivia_propio';\n      var isLive = k==='bolivia_propio_live';\n      var tr = {"),
 ("        type: 'scatter',\n        mode: 'lines',",
  "        type: 'scatter',\n        mode: isLive?'lines+markers':'lines',"),
 ("        line: {color: getColor(k), width: isBolivia ? 2.8 : 1.4},\n        opacity: isBolivia ? 1 : 0.85,",
  "        line: {color: getColor(k), width: isBolivia ? 2.8 : (isPropio?2.4:1.4), dash:'solid'},\n        opacity: isBolivia ? 1 : (isPropio||isLive?1:0.85),"),
 ("        hovertemplate: COUNTRY_LABELS[k]+': %{y:.0f} bps<extra></extra>'\n      };",
  "        hovertemplate: COUNTRY_LABELS[k]+': %{y:.0f} bps<extra></extra>'\n      };\n      if(isLive){ tr.marker={size:8,color:getColor(k),line:{color:'#fff',width:1}}; var lo=sl.fechas[0]||''; var lx=EMBI._liveX||[], ly=EMBI._liveY||[], fx=[], fy=[]; for(var q=0;q<lx.length;q++){ if(lx[q]>=lo){ fx.push(lx[q]); fy.push(ly[q]); } } tr.x=fx; tr.y=fy; }\n      return tr;"),
]
for old, new in edits:
    assert old in html, f"edit target not found: {old[:60]!r}"
    html = html.replace(old, new, 1)

open(SITE, "w", encoding="utf-8").write(html)
print(f"injected: reconstruction {len(data['fechas'])} pts "
      f"{data['fechas'][0]}..{data['fechas'][-1]}; anchor {data['live_anchor_bp']} bp; "
      f"live points {len(data.get('live_points',[]))}")
