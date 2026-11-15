<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>تحلیل کل بورس (۷۰۰+ نماد) و کل کریپتو</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css" rel="stylesheet" />
  <style>body{font-family:'Vazirmatn',sans-serif;background:#090e1a;color:#e2e8f0}.card{background:#111827;border:1px solid #1f2937;border-radius:14px}</style>
</head>
<body class="p-3 md:p-6 max-w-7xl mx-auto space-y-5">

  <header class="card p-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-2">
    <div>
      <h1 class="text-xl font-bold text-emerald-400">سامانه جامع بورس و کریپتو</h1>
      <p class="text-xs text-slate-400">جست‌وجوی فارسی و انگلیسی | ۴ بازه: روزانه، هفتگی، ماهانه، ۱۲۰ روزه</p>
    </div>
    <div id="sys-badge" class="text-[11px] bg-slate-800 px-3 py-1.5 rounded-lg text-sky-300">در حال بررسی اتصال...</div>
  </header>

  <div id="bourse-alert" class="hidden bg-amber-950/60 border border-amber-700/60 text-amber-200 text-xs p-3 rounded-xl leading-6"></div>

  <section class="card p-4 md:p-5 space-y-4">
    <h2 class="text-base font-bold text-amber-400">جست‌وجوی فوری (فارسی یا انگلیسی بنویسید: بیت کوین، سولانا، فولاد، اهرم، BTC...)</h2>
    <div class="relative">
      <div class="flex flex-wrap gap-2">
        <input id="search-box" type="text" oninput="liveSearch()" placeholder="مثلاً: بیت کوین / پپه / فولاد / عیار / BTC" class="bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-sm flex-1 min-w-[220px]" value="بیت کوین" />
        <select id="mkt-select" class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm">
          <option value="AUTO">همه بازارها (خودکار)</option>
          <option value="BOURSE">فقط بورس و صندوق</option>
          <option value="CRYPTO">فقط کریپتو</option>
        </select>
        <button onclick="runAnalyze()" class="bg-emerald-600 hover:bg-emerald-500 px-5 py-2 rounded-lg text-sm font-bold">تحلیل فوری</button>
      </div>
      <div id="autocomplete-list" class="hidden absolute z-30 w-full bg-slate-900 border border-slate-700 rounded-lg mt-1 max-h-60 overflow-y-auto shadow-2xl"></div>
    </div>

    <div id="analysis-area" class="space-y-4 hidden">
      <div id="speed-bar" class="text-xs bg-slate-900/90 border border-slate-800 px-3 py-2 rounded-lg flex flex-wrap justify-between gap-2"></div>
      <div id="horizons-grid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3"></div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div class="bg-slate-900 p-3 rounded-xl border border-slate-800 lg:col-span-2">
          <div class="text-xs text-slate-400 mb-1">نمودار قیمت + فیبوناچی</div>
          <canvas id="priceChart" height="140"></canvas>
        </div>
        <div class="bg-slate-900 p-3 rounded-xl border border-slate-800 space-y-2 text-xs">
          <div class="font-bold text-sky-400">پرایس اکشن، بنیادی و روانشناسی</div>
          <div id="pa-info" class="leading-6"></div>
          <div id="fund-info" class="pt-2 border-t border-slate-800 text-emerald-300 leading-6"></div>
          <div id="psych-info" class="pt-2 border-t border-slate-800 text-purple-300 leading-6"></div>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div class="bg-slate-900 p-3 rounded-xl border border-slate-800"><div class="text-xs text-slate-400 mb-1">RSI (14)</div><canvas id="rsiChart" height="90"></canvas></div>
        <div class="bg-slate-900 p-3 rounded-xl border border-slate-800"><div class="text-xs text-slate-400 mb-1">MACD</div><canvas id="macdChart" height="90"></canvas></div>
      </div>

      <div class="bg-slate-900 p-3 rounded-xl border border-amber-900/40 text-xs space-y-1.5">
        <div class="font-bold text-amber-400">استراتژی گذشته، حال و آینده:</div>
        <div id="st-past"></div><div id="st-present" class="text-emerald-300"></div><div id="st-future" class="text-sky-300"></div>
      </div>
    </div>
  </section>

  <section class="card p-4 space-y-3">
    <h2 class="text-base font-bold text-sky-400">۵ فرصت برتر در ۴ بازه (روزانه تا ۱۲۰ روزه)</h2>
    <div id="top5-grid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3"></div>
  </section>

  <section class="card p-4 space-y-3">
    <h2 class="text-base font-bold text-purple-400">پرتفوی شخصی</h2>
    <div class="grid grid-cols-1 sm:grid-cols-5 gap-2">
      <input id="pf-sym" placeholder="نماد (BTC / فولاد)" class="bg-slate-900 border border-slate-700 rounded px-3 py-2 text-xs" />
      <select id="pf-mkt" class="bg-slate-900 border border-slate-700 rounded px-3 py-2 text-xs"><option value="CRYPTO">کریپتو</option><option value="BOURSE">بورس</option></select>
      <input id="pf-qty" type="number" step="any" placeholder="تعداد" class="bg-slate-900 border border-slate-700 rounded px-3 py-2 text-xs" />
      <input id="pf-price" type="number" step="any" placeholder="قیمت خرید (تومان)" class="bg-slate-900 border border-slate-700 rounded px-3 py-2 text-xs" />
      <button onclick="addPf()" class="bg-purple-600 rounded px-3 py-2 text-xs font-bold">افزودن</button>
    </div>
    <div class="overflow-x-auto"><table class="w-full text-xs text-right"><thead class="text-slate-400 border-b border-slate-800"><tr><th class="py-2">نماد</th><th>بازار</th><th>تعداد</th><th>خرید</th><th>فعلی</th><th>سود/زیان</th><th>وضعیت</th><th>حذف</th></tr></thead><tbody id="pf-body"></tbody></table></div>
  </section>

  <section class="card p-4 space-y-3">
    <h2 class="text-base font-bold text-emerald-400">مقایسه قیمت امروز و دیروز</h2>
    <div class="flex flex-wrap gap-2">
      <button onclick="swTab('crypto')" class="tbtn bg-emerald-600 px-3 py-1 rounded text-xs font-bold" data-t="crypto">کریپتو</button>
      <button onclick="swTab('bourse')" class="tbtn bg-slate-800 px-3 py-1 rounded text-xs" data-t="bourse">بورس</button>
      <button onclick="swTab('metals')" class="tbtn bg-slate-800 px-3 py-1 rounded text-xs" data-t="metals">فلزات و سکه</button>
      <button onclick="swTab('etfs')" class="tbtn bg-slate-800 px-3 py-1 rounded text-xs" data-t="etfs">صندوق‌ها</button>
      <button onclick="swTab('forex')" class="tbtn bg-slate-800 px-3 py-1 rounded text-xs" data-t="forex">ارز کشورها</button>
    </div>
    <div class="overflow-x-auto"><table class="w-full text-xs text-right"><thead class="text-slate-400 border-b border-slate-800"><tr><th class="py-2">#</th><th>نماد</th><th>دیروز</th><th>امروز</th><th>تغییر</th></tr></thead><tbody id="wl-body"></tbody></table></div>
  </section>

<script>
let wl = {}, curTab = 'crypto', pC = null, rC = null, mC = null, searchTimer = null;
const fmt = n => (n === null || n === undefined) ? '-' : Number(n).toLocaleString('fa-IR', {maximumFractionDigits: 6});

async function loadSys() {
  const s = await (await fetch('/api/system-status')).json();
  document.getElementById('sys-badge').innerText = `کریپتو: ${s.crypto_count} رمزارز | بورس: ${s.bourse_count} نماد (${s.bourse_source})`;
  if (s.bourse_count < 50) {
    const ab = document.getElementById('bourse-alert');
    ab.classList.remove('hidden');
    ab.innerHTML = '⚠️ <b>نکته مهم درباره ۷۰۰+ نماد بورس:</b> سرورهای Vercel در آمریکا هستند و سایت بورس تهران دسترسی مستقیم را بسته است. برای فعال شدن فوری <b>همه ۷۰۰ نماد بورس، فرابورس و انواع صندوق‌ها</b>، یک کلید رایگان از سایت <b>BrsApi.ir</b> بگیرید و در تنظیمات Vercel (بخش Environment Variables) با نام <b>BRSAPI_KEY</b> ذخیره کنید.';
  }
}

async function liveSearch() {
  clearTimeout(searchTimer);
  const q = document.getElementById('search-box').value.trim();
  const list = document.getElementById('autocomplete-list');
  if (!q) { list.classList.add('hidden'); return; }
  searchTimer = setTimeout(async () => {
    const d = await (await fetch(`/api/search?q=${encodeURIComponent(q)}`)).json();
    if (!d.results.length) { list.classList.add('hidden'); return; }
    list.innerHTML = d.results.map(r => `
      <div onclick="pickSymbol('${r.symbol}','${r.market}')" class="px-3 py-2 hover:bg-slate-800 cursor-pointer flex justify-between text-xs border-b border-slate-800/50">
        <span><b>${r.symbol}</b> <span class="text-slate-400">${r.name}</span></span>
        <span class="text-emerald-400">${fmt(r.today)} ${r.unit} (${r.market === 'CRYPTO' ? 'کریپتو' : 'بورس'})</span>
      </div>`).join('');
    list.classList.remove('hidden');
  }, 100);
}

function pickSymbol(sym, mkt) {
  document.getElementById('search-box').value = sym;
  document.getElementById('mkt-select').value = mkt;
  document.getElementById('autocomplete-list').classList.add('hidden');
  runAnalyze();
}

async function runAnalyze() {
  document.getElementById('autocomplete-list').classList.add('hidden');
  const sym = document.getElementById('search-box').value;
  const mkt = document.getElementById('mkt-select').value;
  const d = await (await fetch(`/api/analyze?symbol=${encodeURIComponent(sym)}&market=${mkt}`)).json();
  const area = document.getElementById('analysis-area');
  area.classList.remove('hidden');

  if (!d.found) {
    document.getElementById('speed-bar').innerHTML = `<span class="text-rose-400">نماد «${sym}» پیدا نشد (${d.elapsed_ms} میلی‌ثانیه). وضعیت بورس: ${d.bourse_source}</span>`;
    return;
  }
  if (d.no_candles) {
    document.getElementById('speed-bar').innerHTML = `<span class="text-amber-400">نماد ${d.symbol} پیدا شد ولی تاریخچه ۱۸۰ روزه آن از سرور بورس برنگشت (${d.candle_source}).</span>`;
    return;
  }

  document.getElementById('speed-bar').innerHTML = `<span>نماد: <b>${d.symbol} (${d.display_name})</b> | قیمت: <b>${fmt(d.price)} ${d.unit}</b> | منبع: ${d.candle_source} (${d.bars_count} کندل)</span><span class="text-emerald-400">سرعت: ${d.elapsed_ms} میلی‌ثانیه</span>`;
  document.getElementById('horizons-grid').innerHTML = Object.values(d.contracts).map(h => {
    if (!h.evaluatable) return `<div class="bg-slate-900 border border-rose-900/50 p-3 rounded-xl text-xs"><b class="text-rose-400">${h.label}</b><div class="mt-1 text-rose-300">قابل ارزیابی نیست (${h.available_bars}/${h.required_min_bars})</div></div>`;
    return `<div class="bg-slate-900 border border-slate-800 p-3 rounded-xl text-xs space-y-1">
      <div class="font-bold text-sky-400">${h.label}</div>
      <div class="text-amber-300 font-bold">${h.action}</div>
      <div>هدف: <b>${fmt(h.target)}</b> (<span class="text-emerald-400">+${h.net_return_pct}%</span>)</div>
      <div>حد ضرر: <b>${fmt(h.stop)}</b> (<span class="text-rose-400">-${h.net_risk_pct}%</span>)</div>
      <div class="text-slate-400">R/R: ${h.rr}</div>
    </div>`;
  }).join('');

  const t = d.technical;
  document.getElementById('pa-info').innerHTML = `<div><b>ساختار:</b> ${t.structure}</div><div><b>حمایت ۰.۶۱۸:</b> ${fmt(t.fib['0.618'])} | <b>مقاومت ۰.۲۳۶:</b> ${fmt(t.fib['0.236'])}</div>`;
  document.getElementById('fund-info').innerText = `بنیادی/نقدشوندگی: ${d.fundamental}`;
  document.getElementById('psych-info').innerText = `روانشناس: ${d.psychology.mood} — ${d.psychology.advice}`;
  document.getElementById('st-past').innerText = '🔹 ' + d.strategies.past;
  document.getElementById('st-present').innerText = '🔸 ' + d.strategies.present;
  document.getElementById('st-future').innerText = '🔺 ' + d.strategies.future;

  if (pC) pC.destroy(); if (rC) rC.destroy(); if (mC) mC.destroy();
  pC = new Chart(document.getElementById('priceChart'), {
    type: 'line',
    data: { labels: t.dates, datasets: [
      {label:'قیمت', data:t.closes, borderColor:'#34d399', pointRadius:0},
      {label:'فیبو 0.236', data:Array(t.dates.length).fill(t.fib['0.236']), borderColor:'#f87171', borderDash:[4,4], pointRadius:0},
      {label:'فیبو 0.618', data:Array(t.dates.length).fill(t.fib['0.618']), borderColor:'#fbbf24', borderDash:[4,4], pointRadius:0}
    ]},
    options: {plugins:{legend:{labels:{color:'#cbd5e1',font:{size:10}}}}, scales:{x:{ticks:{color:'#64748b'}},y:{ticks:{color:'#64748b'}}}}
  });
  rC = new Chart(document.getElementById('rsiChart'), {type:'line', data:{labels:t.dates, datasets:[{data:t.rsi_series, borderColor:'#a78bfa', pointRadius:0}]}, options:{plugins:{legend:{display:false}}, scales:{y:{min:0,max:100}, x:{ticks:{display:false}}}}});
  mC = new Chart(document.getElementById('macdChart'), {data:{labels:t.dates, datasets:[{type:'line',label:'MACD',data:t.macd_series,borderColor:'#38bdf8',pointRadius:0},{type:'line',label:'Sig',data:t.signal_series,borderColor:'#fb923c',pointRadius:0},{type:'bar',label:'Hist',data:t.hist_series,backgroundColor:'#4ade80'}]}, options:{plugins:{legend:{labels:{color:'#cbd5e1',font:{size:10}}}}, scales:{x:{ticks:{display:false}}}}});
}

async function loadTop5() {
  const d = await (await fetch('/api/top5-scanner')).json();
  const names = {H1_DAILY:'۱) روزانه', H2_WEEKLY:'۲) هفتگی', H3_MONTHLY:'۳) ماهانه', H4_120D:'۴) ۱۲۰ روزه'};
  document.getElementById('top5-grid').innerHTML = Object.keys(names).map(k => `
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-3 space-y-1.5 text-xs">
      <div class="font-bold text-sky-400 border-b border-slate-800 pb-1">۵ برتر ${names[k]}</div>
      ${(d[k]||[]).map((x,i) => `<div onclick="pickSymbol('${x.symbol}','CRYPTO')" class="flex justify-between cursor-pointer hover:text-emerald-300"><span>${i+1}. <b>${x.symbol}</b></span><span class="text-emerald-400">+${x.net_return_pct}%</span></div>`).join('') || '<div class="text-slate-500">در حال بررسی...</div>'}
    </div>`).join('');
}

async function loadWL() { wl = await (await fetch('/api/watchlists')).json(); swTab(curTab); }
function swTab(t) {
  curTab = t;
  document.querySelectorAll('.tbtn').forEach(b => b.className = b.dataset.t === t ? 'tbtn bg-emerald-600 px-3 py-1 rounded text-xs font-bold' : 'tbtn bg-slate-800 px-3 py-1 rounded text-xs');
  document.getElementById('wl-body').innerHTML = (wl[t]||[]).map((it,i) => `<tr class="border-b border-slate-800/60"><td class="py-1.5 text-slate-500">${i+1}</td><td class="font-bold">${it.symbol} <span class="text-slate-400 font-normal">${it.name}</span></td><td class="text-slate-400">${fmt(it.yesterday)}</td><td class="font-bold">${fmt(it.today)} ${it.unit}</td><td class="${it.change_pct>=0?'text-emerald-400':'text-rose-400'} font-bold" dir="ltr">${it.change_pct}%</td></tr>`).join('');
}

async function loadPf() {
  const rows = await (await fetch('/api/portfolio')).json();
  document.getElementById('pf-body').innerHTML = rows.map(r => `<tr class="border-b border-slate-800/60"><td class="py-1.5 font-bold">${r.symbol}</td><td>${r.market}</td><td>${fmt(r.quantity)}</td><td>${fmt(r.buy_price)}</td><td>${fmt(r.current_price)}</td><td class="${r.pnl_pct>=0?'text-emerald-400':'text-rose-400'} font-bold" dir="ltr">${r.pnl_pct}%</td><td>${r.signal}</td><td><button onclick="delPf(${r.id})" class="text-rose-400">حذف</button></td></tr>`).join('');
}
async function addPf() {
  await fetch('/api/portfolio', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({symbol:document.getElementById('pf-sym').value, market:document.getElementById('pf-mkt').value, quantity:parseFloat(document.getElementById('pf-qty').value||0), avg_buy_price_toman:parseFloat(document.getElementById('pf-price').value||0)})});
  loadPf();
}
async function delPf(id) { await fetch(`/api/portfolio/${id}`, {method:'DELETE'}); loadPf(); }

loadSys(); runAnalyze(); loadTop5(); loadWL(); loadPf();
</script>
</body>
</html>
