/* ════════════════════════════════════════════════════════════════
   Noticias 2.0 — dataset de ejemplo (contexto Bolivia · jun 2026)
   Portada editorial estilo Financial Times con paleta FinanzasBo.
   Contenido ILUSTRATIVO. Agrega 13 portales bolivianos + Bloomberg
   Línea (carril Latam). NO toca news-data.js (usado por Noticias.html).
   ════════════════════════════════════════════════════════════════ */

// ── Portales bolivianos (los 13 del brief) + Bloomberg Línea (Latam) ──
window.PORTALS2 = {
  eldeber:   { id:'eldeber',   name:'El Deber',       city:'Santa Cruz' },
  lostiempos:{ id:'lostiempos',name:'Los Tiempos',    city:'Cochabamba' },
  larazon:   { id:'larazon',   name:'La Razón',       city:'La Paz' },
  brujula:   { id:'brujula',   name:'Brújula Digital',city:'La Paz' },
  erbol:     { id:'erbol',     name:'Erbol',          city:'La Paz' },
  eju:       { id:'eju',       name:'Eju!',           city:'Santa Cruz' },
  eldia:     { id:'eldia',     name:'El Día',         city:'Santa Cruz' },
  correosur: { id:'correosur', name:'Correo del Sur', city:'Sucre' },
  unitel:    { id:'unitel',    name:'Unitel',         city:'Nacional' },
  fides:     { id:'fides',     name:'Noticias Fides', city:'La Paz' },
  urgente:   { id:'urgente',   name:'Urgente.bo',     city:'La Paz' },
  opinion:   { id:'opinion',   name:'Opinión',        city:'Cochabamba' },
  bloomberg: { id:'bloomberg', name:'Bloomberg Línea',city:'Latam' },
};
window.PORTAL2_ORDER = ['eldeber','lostiempos','larazon','brujula','erbol','eju','eldia','correosur','unitel','fides','urgente','opinion','bloomberg'];

// ── Categorías (taxonomía del brief) ──
window.CATS2 = {
  economia:  { id:'economia',  name:'Economía' },
  cambiario: { id:'cambiario', name:'Dólar / Cambiario' },
  energia:   { id:'energia',   name:'Hidrocarburos / Energía' },
  agro:      { id:'agro',      name:'Agro / Exportaciones' },
  mercados:  { id:'mercados',  name:'Empresas / Mercados' },
  politica:  { id:'politica',  name:'Política / Regulación' },
  regional:  { id:'regional',  name:'Regional' },
  latam:     { id:'latam',     name:'Latam / Internacional' },
};
window.CAT2_ORDER = ['economia','cambiario','energia','agro','mercados','politica','regional'];

// kicker corto (versalita) por categoría
window.CAT2_KICKER = {
  economia:'Economía', cambiario:'Dólar', energia:'Hidrocarburos', agro:'Agro',
  mercados:'Mercados', politica:'Política', regional:'Regional', latam:'Latam',
};

// ── Franja de indicadores (markets strip) — placeholders ──
window.INDICATORS2 = [
  { id:'p2p',   label:'Dólar P2P',   value:'11,28', unit:'Bs/USD', sub:'prima +62%',  dir:'up',   note:'sobre oficial' },
  { id:'bcb',   label:'BCB oficial', value:'6,96',  unit:'Bs/USD', sub:'sin cambios', dir:'flat', note:'tipo de cambio fijo' },
  { id:'riesgo',label:'Riesgo país', value:'1.912', unit:'pb',     sub:'+18 pb',      dir:'up',   note:'EMBI soberano' },
  { id:'ipc',   label:'IPC interan.',value:'20,5',  unit:'%',      sub:'+0,4 pp',     dir:'up',   note:'a mayo 2026' },
  { id:'ipp',   label:'IPP',         value:'18,3',  unit:'%',      sub:'-0,2 pp',     dir:'down', note:'precios al productor' },
];

/* ── Notas curadas (placeholders exactos del brief + ampliación) ──
   tier: 'lead' | 'sec' | 'river' ; impact: 'alto' | 'medio' */
window.NEWS2 = [
  { id:'n1', source:'brujula', category:'cambiario', tier:'lead', impact:'alto', time:'hace 2 h', hour:'07:42',
    title:'El paralelo toca Bs 11,2 y la prima sobre el oficial supera el 60%',
    standfirst:'El dólar P2P se negocia con una prima cercana al 62% frente al tipo de cambio oficial de 6,96, en medio de cupos restringidos y demanda canalizada a stablecoins.',
    section:'Brújula Digital · Mercados', topics:['Dólar','Prima','P2P'] },

  { id:'n2', source:'lostiempos', category:'energia', tier:'sec', impact:'alto', time:'hace 3 h', hour:'06:30',
    title:'YPFB reporta caída interanual en la producción de gas natural',
    standfirst:'La estatal admite menores volúmenes y una factura récord por importación de diésel.',
    section:'Los Tiempos · Energía', topics:['Gas','YPFB'] },
  { id:'n3', source:'larazon', category:'economia', tier:'sec', impact:'medio', time:'hace 1 h', hour:'08:50',
    title:'El BCB publica nuevas tasas referenciales de compra y venta',
    standfirst:'La autoridad monetaria ajusta las referencias para operaciones del sistema financiero.',
    section:'La Razón · Economía', topics:['BCB','Tasas'] },
  { id:'n4', source:'eldeber', category:'agro', tier:'sec', impact:'medio', time:'hace 4 h', hour:'05:55',
    title:'Exportadores de soya advierten menor cosecha por sequía',
    standfirst:'El sector agroindustrial cruceño anticipa riesgos en la campaña de verano.',
    section:'El Deber · Economía', topics:['Soya','Sequía'] },

  // Río principal — agrupado por categoría
  { id:'r1', source:'eldia', category:'mercados', tier:'river', impact:'medio', time:'hace 2 h', hour:'07:10',
    title:'Bonos corporativos lideran las rotaciones del día en la BBV', section:'El Día', topics:['BBV','Renta fija'] },
  { id:'r2', source:'eldeber', category:'regional', tier:'river', impact:'medio', time:'hace 6 h', hour:'03:40',
    title:'Comercio en Santa Cruz reporta caída de ventas por escasez de divisas', section:'El Deber', region:'Santa Cruz', topics:['Comercio','Divisas'] },
  { id:'r3', source:'erbol', category:'politica', tier:'river', impact:'medio', time:'hace 5 h', hour:'04:35',
    title:'La Asamblea debate un proyecto de financiamiento externo', section:'Erbol', topics:['Asamblea','Crédito'] },

  { id:'r4', source:'larazon', category:'economia', tier:'river', impact:'alto', time:'hace 1 h', hour:'08:20',
    title:'El INE confirma una inflación interanual de 20,5%, la más alta en dos décadas', section:'La Razón', topics:['Inflación','INE'] },
  { id:'r5', source:'fides', category:'economia', tier:'river', impact:'medio', time:'hace 3 h', hour:'06:05',
    title:'El BCB monetiza oro por USD 60 millones para sostener las reservas', section:'Noticias Fides', topics:['Reservas','Oro'] },
  { id:'r6', source:'bloomberg', category:'economia', tier:'river', impact:'alto', time:'hace 2 h', hour:'07:00',
    title:'El riesgo país de Bolivia cierra cerca de 1.912 pb, el más alto de la región', section:'Bloomberg Línea', topics:['Riesgo país','Deuda'] },
  { id:'r7', source:'opinion', category:'economia', tier:'river', impact:'medio', time:'hace 4 h', hour:'05:30',
    title:'Los depósitos en dólares del sistema financiero caen 6% en lo que va del año', section:'Opinión', topics:['Banca','Dólar'] },

  { id:'r8', source:'urgente', category:'cambiario', tier:'river', impact:'alto', time:'hace 2 h', hour:'07:25',
    title:'Bancos ajustan a USD 300 semanales el cupo de retiro en dólares', section:'Urgente.bo', topics:['Cupos','Banca'] },
  { id:'r9', source:'eldeber', category:'cambiario', tier:'river', impact:'alto', time:'hace 3 h', hour:'06:15',
    title:'Largas filas de importadores por el racionamiento de dólares al tipo oficial', section:'El Deber', topics:['Importación','Dólar'] },
  { id:'r10', source:'larazon', category:'cambiario', tier:'river', impact:'medio', time:'hace 5 h', hour:'04:10',
    title:'El Ejecutivo descarta modificar el tipo de cambio oficial de Bs 6,96', section:'La Razón', topics:['Política cambiaria'] },

  { id:'r11', source:'unitel', category:'energia', tier:'river', impact:'alto', time:'hace 2 h', hour:'07:05',
    title:'Surtidores racionan diésel en cuatro departamentos y reaparecen las filas', section:'Unitel', topics:['Diésel','Racionamiento'] },
  { id:'r12', source:'eldeber', category:'energia', tier:'river', impact:'alto', time:'hace 4 h', hour:'05:20',
    title:'La subvención a combustibles ya supera los USD 800 millones en el año', section:'El Deber', topics:['Subvención','Fiscal'] },
  { id:'r13', source:'lostiempos', category:'energia', tier:'river', impact:'medio', time:'hace 6 h', hour:'03:15',
    title:'YPFB despacha 32 cisternas de diésel a Cochabamba para normalizar la provisión', section:'Los Tiempos', topics:['Diésel','YPFB'] },

  { id:'r14', source:'eldeber', category:'agro', tier:'river', impact:'medio', time:'hace 3 h', hour:'06:40',
    title:'Las exportaciones de soya caen 9% por la falta de diésel y los bloqueos', section:'El Deber', topics:['Soya','Exportación'] },
  { id:'r15', source:'correosur', category:'agro', tier:'river', impact:'medio', time:'hace 5 h', hour:'04:25',
    title:'Heladas afectan 3.200 hectáreas de cultivos en el altiplano', section:'Correo del Sur', topics:['Clima','Altiplano'] },
  { id:'r16', source:'eju', category:'agro', tier:'river', impact:'medio', time:'hace 7 h', hour:'02:50',
    title:'La sequía en el Chaco golpea la ganadería y eleva el precio de la carne', section:'Eju!', topics:['Ganadería','Sequía'] },

  { id:'r17', source:'eldia', category:'mercados', tier:'river', impact:'medio', time:'hace 3 h', hour:'06:20',
    title:'El índice de la BBV avanza 0,8% impulsado por emisiones de DPF', section:'El Día', topics:['BBV','DPF'] },
  { id:'r18', source:'brujula', category:'mercados', tier:'river', impact:'medio', time:'hace 4 h', hour:'05:45',
    title:'Una financiera coloca bonos por Bs 120 millones con sobredemanda', section:'Brújula Digital', topics:['Bonos','Emisión'] },
  { id:'r19', source:'eldia', category:'mercados', tier:'river', impact:'medio', time:'hace 6 h', hour:'03:30',
    title:'Empresas cruceñas anticipan menor inversión por la incertidumbre cambiaria', section:'El Día', topics:['Empresas','Inversión'] },

  { id:'r20', source:'erbol', category:'politica', tier:'river', impact:'medio', time:'hace 2 h', hour:'07:35',
    title:'La Asamblea posterga el tratamiento de créditos externos por USD 900 millones', section:'Erbol', topics:['Crédito','Asamblea'] },
  { id:'r21', source:'unitel', category:'politica', tier:'river', impact:'medio', time:'hace 4 h', hour:'05:10',
    title:'Gobierno y transportistas instalan una mesa de diálogo por el diésel', section:'Unitel', topics:['Diálogo','Transporte'] },
  { id:'r22', source:'fides', category:'politica', tier:'river', impact:'medio', time:'hace 6 h', hour:'03:05',
    title:'Comisión legislativa pide un informe al BCB sobre el nivel de reservas', section:'Noticias Fides', topics:['Reservas','Asamblea'] },

  { id:'r23', source:'lostiempos', category:'regional', tier:'river', impact:'medio', time:'hace 3 h', hour:'06:50',
    title:'Cochabamba: comerciantes reportan alza de precios en la canasta básica', section:'Los Tiempos', region:'Cochabamba', topics:['Precios','Canasta'] },
  { id:'r24', source:'larazon', category:'regional', tier:'river', impact:'medio', time:'hace 5 h', hour:'04:40',
    title:'La Paz: el transporte público advierte ajuste de tarifas por el diésel', section:'La Razón', region:'La Paz', topics:['Transporte','Tarifas'] },
  { id:'r25', source:'correosur', category:'regional', tier:'river', impact:'medio', time:'hace 7 h', hour:'02:30',
    title:'Potosí: cooperativas mineras bloquean por el precio del oro y las regalías', section:'Correo del Sur', region:'Potosí', topics:['Minería','Regalías'] },
];

// ── Carril Latam / Internacional (Bloomberg Línea, hasta 5/día) ──
window.LATAM2 = [
  { id:'l1', source:'bloomberg', category:'latam', impact:'medio', time:'hace 7 h', hour:'02:40', country:'Argentina',
    title:'Argentina coloca deuda y los spreads soberanos se comprimen',
    standfirst:'La emisión supera la demanda esperada y el riesgo país argentino retrocede a mínimos del año.', topics:['Deuda','Spreads'] },
  { id:'l2', source:'bloomberg', category:'latam', impact:'medio', time:'hace 9 h', hour:'00:30', country:'Brasil',
    title:'El Banco Central de Brasil mantiene la Selic y vigila la inflación de servicios',
    standfirst:'El real se aprecia tras la decisión y mueve el comercio de frontera con Bolivia.', topics:['Selic','Real'] },
  { id:'l3', source:'bloomberg', category:'latam', impact:'medio', time:'hace 11 h', hour:'22:15', country:'EE.UU.',
    title:'La Fed sostiene tasas y presiona a las monedas emergentes de la región',
    standfirst:'El dólar fuerte encarece el financiamiento externo de las economías andinas.', topics:['Fed','Tasas'] },
  { id:'l4', source:'bloomberg', category:'latam', impact:'medio', time:'hace 12 h', hour:'21:00', country:'Chile',
    title:'El cobre marca nuevo máximo y mejora los términos de intercambio de Chile',
    standfirst:'El metal industrial sube por la demanda china y dinamiza las exportaciones del Pacífico.', topics:['Cobre','Exportación'] },
  { id:'l5', source:'bloomberg', category:'latam', impact:'medio', time:'hace 14 h', hour:'19:20', country:'Perú',
    title:'Perú recorta su proyección de crecimiento por la menor inversión minera',
    standfirst:'El menor gasto de capital del sector extractivo pesa sobre el PIB regional.', topics:['PIB','Minería'] },
];

// ── Agenda · próximos hechos (DATO DE EJEMPLO) ──
window.AGENDA2 = [
  { id:'a1', category:'economia',  inDays:5,  date:'8 jun',  title:'INE publica el IPC de mayo (dato definitivo)' },
  { id:'a2', category:'energia',   inDays:7,  date:'10 jun', title:'YPFB presenta su informe de producción y subvención' },
  { id:'a3', category:'agro',      inDays:9,  date:'12 jun', title:'Cierre de la campaña de verano de soya en Santa Cruz' },
  { id:'a4', category:'politica',  inDays:12, date:'15 jun', title:'La Asamblea trata el crédito externo por USD 1.800 M' },
];

// ── Navegación por día (últimos 30 días, abreviado) ──
window.DAYS2 = ['03 jun','02 jun','01 jun','31 may','30 may','29 may','28 may'];
