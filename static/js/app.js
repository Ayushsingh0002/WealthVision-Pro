/* ============================================================
   WealthVision Pro — Frontend Application
   ============================================================ */
"use strict";

// ── State ──────────────────────────────────────────────────
const State = {
  portfolios: [],
  activePortfolioId: null,
  summary: null,
  perfPeriod: 365,
  charts: {},
};

// ── Constants ──────────────────────────────────────────────
const SECTOR_COLORS = {
  Technology: "#3b82f6", Healthcare: "#10b981", Finance: "#8b5cf6",
  Consumer: "#f59e0b", Energy: "#ef4444", Industrial: "#06b6d4",
  Materials: "#ec4899", Utilities: "#eab308", "Real Estate": "#f97316",
  Other: "#64748b",
};
const RISK_COLORS = { Conservative:"#10b981", Moderate:"#f59e0b", Aggressive:"#ef4444" };

// ── Utilities ──────────────────────────────────────────────
const fmt  = (n, d=0) => Number(n).toLocaleString("en-IN",{minimumFractionDigits:d,maximumFractionDigits:d});
const fmtP = (n, d=1) => (n>=0?"+":"")+Number(n).toFixed(d)+"%";
const el   = id => document.getElementById(id);

function toast(msg, type="info") {
  const t = document.createElement("div");
  t.className = `toast ${type}`;
  t.textContent = msg;
  el("toast-container").appendChild(t);
  setTimeout(() => t.remove(), 4500);
}

// ── API fetch — NEVER sets Content-Type for FormData ───────
async function api(url, opts={}) {
  const isForm = opts.body instanceof FormData;
  const headers = isForm ? {} : {"Content-Type":"application/json"};
  const res  = await fetch(url, {headers, ...opts});
  const ct   = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json().catch(()=>({})) : {};
  if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
  return data;
}

// ── Chart defaults ─────────────────────────────────────────
Chart.defaults.color = "#94a3b8";
Chart.defaults.font.family = "'Plus Jakarta Sans',sans-serif";
Chart.defaults.font.size = 12;
function destroyChart(k){ if(State.charts[k]){State.charts[k].destroy();delete State.charts[k];} }

// ══════════════════════════════════════════════════════════
// PORTFOLIO SIDEBAR
// ══════════════════════════════════════════════════════════

async function loadPortfolios() {
  try {
    State.portfolios = await api("/api/portfolios");
    const sel = el("portfolioSelect");
    sel.innerHTML = '<option value="">— select portfolio —</option>';
    State.portfolios.forEach(p => {
      const o = document.createElement("option");
      o.value = p.id; o.textContent = p.name;
      sel.appendChild(o);
    });
    // Set value AFTER all options are in the DOM — reliable across all browsers
    if (State.activePortfolioId) sel.value = State.activePortfolioId;
    el("deletePortfolioSection").style.display = State.activePortfolioId ? "block" : "none";
  } catch(e){ toast("Could not load portfolios: "+e.message,"error"); }
}

// Select portfolio
el("portfolioSelect").addEventListener("change", async e => {
  const id = parseInt(e.target.value);
  if (!id){ State.activePortfolioId=null; hideDashboard(); return; }
  State.activePortfolioId = id;
  el("deletePortfolioSection").style.display = "block";
  showDashboard();
  await refreshSummary();
});

// New portfolio toggle
el("btnNewPortfolio").addEventListener("click", () => {
  el("newPortfolioForm").classList.toggle("open");
  if (el("newPortfolioForm").classList.contains("open")) el("newPortfolioName").focus();
});

el("btnCreatePortfolio").addEventListener("click", createPortfolio);
el("newPortfolioName").addEventListener("keydown", e => { if(e.key==="Enter") createPortfolio(); });

async function createPortfolio(){
  const name = el("newPortfolioName").value.trim();
  if (!name){ toast("Enter a portfolio name.","error"); return; }
  try {
    const p = await api("/api/portfolios",{method:"POST",body:JSON.stringify({name})});
    toast(`"${name}" created.`,"success");
    State.activePortfolioId = p.id;
    el("newPortfolioName").value = "";
    el("newPortfolioForm").classList.remove("open");
    await loadPortfolios();
    showDashboard();
    await refreshSummary();
  } catch(e){ toast(e.message,"error"); }
}

// Delete portfolio (two-click confirm)
let _delPort = false;
el("btnDeletePortfolio").addEventListener("click", async () => {
  const btn = el("btnDeletePortfolio");
  if (!_delPort){
    btn.textContent = "⚠️ Click again to confirm";
    _delPort = true;
    setTimeout(()=>{ _delPort=false; if(btn) btn.textContent="🗑️ Delete Portfolio"; }, 3000);
    return;
  }
  try {
    await api(`/api/portfolios/${State.activePortfolioId}`,{method:"DELETE"});
    toast("Portfolio deleted.","info");
    State.activePortfolioId = null; State.summary = null; _delPort = false;
    btn.textContent = "🗑️ Delete Portfolio";
    await loadPortfolios(); hideDashboard();
  } catch(e){ toast(e.message,"error"); }
});

// Load demo
async function loadDemo(){
  try {
    await loadPortfolios();                                       // refresh list first
    let demo = State.portfolios.find(p => p.name==="Demo");
    if (!demo){
      const p = await api("/api/portfolios",{method:"POST",body:JSON.stringify({name:"Demo"})});
      State.activePortfolioId = p.id;                           // FIX: set id from new portfolio
    } else {
      State.activePortfolioId = demo.id;                        // FIX: was missing before
    }
    await api(`/api/portfolios/${State.activePortfolioId}/demo`,{method:"POST"});
    toast("Demo portfolio loaded.","success");
    await loadPortfolios(); showDashboard(); await refreshSummary();
  } catch(e){ toast("Demo failed: "+e.message,"error"); }
}
el("btnLoadDemo").addEventListener("click", loadDemo);
el("btnGetStarted").addEventListener("click", loadDemo);

// Refresh data
el("btnRefreshData").addEventListener("click", async () => {
  if (!State.activePortfolioId){ toast("Select a portfolio first.","error"); return; }
  toast("Refreshing…","info");
  await refreshSummary();
});

// Export CSV
el("btnExportCSV").addEventListener("click", () => {
  if (!State.activePortfolioId){ toast("Select a portfolio first.","error"); return; }
  window.location.href = `/api/portfolios/${State.activePortfolioId}/export`;
});

// Show / hide dashboard
function showDashboard(){
  el("noPortfolioState").style.display="none";
  el("dashboardArea").style.display="block";
}
function hideDashboard(){
  el("noPortfolioState").style.display="flex";
  el("dashboardArea").style.display="none";
  ["perfChart","allocChart","riskContribChart","drawdownChart"].forEach(destroyChart);
}

// Tabs
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click",()=>{
    const tab = btn.dataset.tab;
    document.querySelectorAll(".tab-btn").forEach(b=>b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p=>p.classList.remove("active"));
    btn.classList.add("active");
    el(`tab-${tab}`).classList.add("active");
    if (tab==="risk"     && State.activePortfolioId) loadRiskData();
    if (tab==="scenario" && State.summary)           buildScenarioSliders();
  });
});

// Period buttons
document.querySelectorAll(".period-btn").forEach(btn => {
  btn.addEventListener("click",()=>{
    document.querySelectorAll(".period-btn").forEach(b=>b.classList.remove("active"));
    btn.classList.add("active");
    State.perfPeriod = parseInt(btn.dataset.period);
    if (State.summary) renderPerfChart(State.summary.history);
  });
});

// ══════════════════════════════════════════════════════════
// ADD HOLDING
// ══════════════════════════════════════════════════════════

el("btnAddHolding").addEventListener("click", addHolding);
el("addSymbol").addEventListener("keydown", e=>{ if(e.key==="Enter") addHolding(); });

async function addHolding(){
  // Guard: need an active portfolio
  if (!State.activePortfolioId){
    toast("Select or create a portfolio first.","error"); return;
  }

  const symbol  = el("addSymbol").value.trim().toUpperCase();
  const shares  = parseFloat(el("addShares").value);
  const cost    = parseFloat(el("addCost").value);
  const errEl   = el("symbolError");
  errEl.classList.remove("visible"); errEl.textContent="";

  if (!symbol)             { errEl.textContent="Enter a ticker symbol."; errEl.classList.add("visible"); return; }
  if (!shares || shares<=0){ toast("Shares must be > 0.","error"); return; }
  if (!cost   || cost<=0)  { toast("Purchase price must be > 0.","error"); return; }

  // Show loading state
  const btn      = el("btnAddHolding");
  const btnText  = el("addBtnText");
  const spinner  = el("addBtnSpinner");
  btn.disabled=true; btnText.textContent="Validating…"; spinner.style.display="inline-block";

  try {
    await api(`/api/portfolios/${State.activePortfolioId}/holdings`,{
      method:"POST",
      body: JSON.stringify({symbol, shares, cost_basis:cost}),
    });
    toast(`✅ ${symbol} added.`,"success");
    el("addSymbol").value=""; el("addShares").value=""; el("addCost").value="";
    await refreshSummary();
  } catch(e){
    errEl.textContent = e.message;
    errEl.classList.add("visible");
  } finally {
    btn.disabled=false; btnText.textContent="Add to Portfolio →"; spinner.style.display="none";
  }
}

// ══════════════════════════════════════════════════════════
// CSV IMPORT  (key fix: FormData — no Content-Type header)
// ══════════════════════════════════════════════════════════

el("csvFileInput").addEventListener("change", async e => {
  const file = e.target.files[0];
  if (!file) return;

  // Guard: need an active portfolio
  if (!State.activePortfolioId){
    toast("Select or create a portfolio before importing.","error");
    e.target.value=""; return;
  }

  const statusEl = el("csvStatus");
  statusEl.style.color="var(--text-muted)"; statusEl.textContent="⏳ Importing…";

  const fd = new FormData();
  fd.append("file", file);   // browser sets Content-Type + boundary — do NOT override

  try {
    const res  = await fetch(`/api/portfolios/${State.activePortfolioId}/import`,{method:"POST",body:fd});
    const data = await res.json().catch(()=>({}));
    if (!res.ok) throw new Error(data.error || `Error ${res.status}`);

    const n = data.imported || 0;
    if (n===0){
      statusEl.style.color="var(--yellow)";
      statusEl.textContent="⚠️ No valid rows — check columns: symbol, shares, cost_basis";
      toast("Nothing imported. Check CSV format.","error");
    } else {
      statusEl.style.color="var(--green)";
      statusEl.textContent=`✅ ${n} holding(s) imported.`;
      toast(`Imported ${n} holding(s).`,"success");
      await refreshSummary();
    }
  } catch(err){
    statusEl.style.color="var(--red)";
    statusEl.textContent="❌ "+err.message;
    toast("Import failed: "+err.message,"error");
  } finally {
    e.target.value="";   // reset so same file can be re-tried after a fix
  }
});

// ══════════════════════════════════════════════════════════
// SUMMARY
// ══════════════════════════════════════════════════════════

async function refreshSummary(){
  if (!State.activePortfolioId) return;
  el("headerStatus").textContent="⏳ Loading…";
  try {
    const data = await api(`/api/portfolios/${State.activePortfolioId}/summary`);
    State.summary = data;

    if (!data.holdings || !data.holdings.length){
      renderEmpty(); el("headerStatus").textContent="No holdings yet"; return;
    }

    renderKPIs(data);
    renderHoldingsTable(data);
    renderPerfChart(data.history);
    renderAllocChart(data.holdings);
    renderSectorBars(data.sectors, data.total_value);
    renderInsights(data.insights);

    const fa = data.holdings[0]?.fetched_at || "";
    if (fa) el("dataFreshness").textContent="⏱ "+fa.slice(0,16).replace("T"," ")+" UTC";

    if (data.failed_symbols?.length)
      toast("⚠️ No data for: "+data.failed_symbols.join(", "),"error");

    el("headerStatus").textContent="Delayed / EOD data";
  } catch(e){
    toast("Load failed: "+e.message,"error");
    el("headerStatus").textContent="Error";
  }
}

function renderEmpty(){
  el("holdingsTbody").innerHTML=
    `<tr><td colspan="9" style="text-align:center;padding:40px;color:var(--text-muted)">
       No holdings yet — add a stock above or import a CSV.
     </td></tr>`;
  ["kpiValue","kpiReturn","kpiVol","kpiSharpe","kpiRisk"].forEach(id=>{
    const e=el(id); if(e){e.textContent="—";e.className="kpi-value";e.style.color="";}
  });
  ["kpiPnl","kpiDailyPnl","kpiRiskScore"].forEach(id=>{ const e=el(id); if(e) e.textContent="—"; });
}

// ── KPIs ───────────────────────────────────────────────────
function renderKPIs(d){
  el("kpiValue").textContent = fmt(d.total_value,2);

  const ret=el("kpiReturn");
  ret.textContent=fmtP(d.total_pnl_pct);
  ret.className=`kpi-value ${d.total_pnl_pct>=0?"positive":"negative"}`;

  const pnl=el("kpiPnl");
  pnl.textContent=(d.total_pnl>=0?"+":"")+fmt(d.total_pnl,2)+" all time";
  pnl.style.color=d.total_pnl>=0?"var(--green)":"var(--red)";

  const dp=el("kpiDailyPnl");
  dp.textContent=(d.daily_pnl>=0?"+":"")+fmt(d.daily_pnl,2)+" today";
  dp.style.color=d.daily_pnl>=0?"var(--green)":"var(--red)";

  const rk=el("kpiRisk");
  rk.textContent=d.risk_profile; rk.className="kpi-value";
  rk.style.color=RISK_COLORS[d.risk_profile]||"var(--text-primary)";

  el("kpiRiskScore").textContent=`${d.risk_score}/100 score`;
  el("kpiVol").textContent=d.volatility.toFixed(1)+"%";
  el("kpiSharpe").textContent=d.sharpe.toFixed(2);
}

// ══════════════════════════════════════════════════════════
// HOLDINGS TABLE
// ══════════════════════════════════════════════════════════

function renderHoldingsTable(d){
  const tbody=el("holdingsTbody");
  tbody.innerHTML="";

  d.holdings.forEach(h=>{
    const sc=SECTOR_COLORS[h.sector]||"#64748b";
    const rc=d.risk_contribution?.[h.symbol]??0;
    const pCls=h.pnl>=0?"text-positive":"text-negative";

    // data row
    const tr=document.createElement("tr");
    tr.innerHTML=`
      <td>
        <div class="td-symbol">
          <div class="symbol-badge" style="background:${sc}22;border:1px solid ${sc}55;color:${sc}">
            ${h.symbol.replace(/\.(NS|BO)$/,"").slice(0,4)}
          </div>
          <div>
            <div class="symbol-name">${h.symbol}</div>
            <div class="symbol-sector">${h.sector}</div>
          </div>
        </div>
      </td>
      <td>${fmt(h.price,2)}<div class="${h.change_pct>=0?"text-positive":"text-negative"}" style="font-size:11px">${fmtP(h.change_pct,2)}</div></td>
      <td>${fmt(h.value,0)}</td>
      <td>
        <div style="font-weight:600">${h.weight.toFixed(1)}%</div>
        <div style="height:3px;background:${sc}33;border-radius:2px;margin-top:4px;width:56px">
          <div style="width:${Math.min(h.weight,100)}%;height:100%;background:${sc};border-radius:2px"></div>
        </div>
      </td>
      <td class="${pCls}">${fmtP(h.pnl_pct)}<div style="font-size:11px">${h.pnl>=0?"+":""}${fmt(h.pnl,0)}</div></td>
      <td>${h.volatility.toFixed(1)}%</td>
      <td>${h.sharpe.toFixed(2)}</td>
      <td>${rc.toFixed(1)}%</td>
      <td style="text-align:center">
        <div style="display:flex;gap:4px;justify-content:center">
          <button class="btn btn-secondary btn-sm btn-edit" data-id="${h.id}">✏️</button>
          <button class="btn btn-danger btn-sm btn-del" data-id="${h.id}">🗑️</button>
        </div>
      </td>`;

    // edit row
    const etr=document.createElement("tr");
    etr.className="edit-row"; etr.id=`editRow-${h.id}`;
    etr.innerHTML=`
      <td colspan="9">
        <div class="edit-form">
          <strong style="color:var(--text-primary);min-width:90px">${h.symbol}</strong>
          <input type="number" class="form-input edit-shares" value="${h.shares}" placeholder="Shares" step="any" min="0.001" style="width:110px"/>
          <input type="number" class="form-input edit-cost" value="${h.cost_basis}" placeholder="Cost basis" step="any" min="0.01" style="width:130px"/>
          <button class="btn btn-primary btn-sm btn-save-edit" data-id="${h.id}">Save</button>
          <button class="btn btn-secondary btn-sm btn-cancel-edit" data-id="${h.id}">Cancel</button>
        </div>
      </td>`;

    // confirm-delete row
    const dtr=document.createElement("tr");
    dtr.className="confirm-row"; dtr.id=`delRow-${h.id}`;
    dtr.innerHTML=`
      <td colspan="9">
        Remove <strong>${h.symbol}</strong>?
        <button class="btn btn-danger btn-sm btn-confirm-del" data-id="${h.id}" style="margin-left:10px">Yes, remove</button>
        <button class="btn btn-secondary btn-sm btn-cancel-del" data-id="${h.id}" style="margin-left:4px">Cancel</button>
      </td>`;

    tbody.appendChild(tr);
    tbody.appendChild(etr);
    tbody.appendChild(dtr);
  });

  // wire events
  tbody.querySelectorAll(".btn-edit").forEach(b=>b.addEventListener("click",()=>{
    closeEdits(); closeDels();
    el(`editRow-${b.dataset.id}`).classList.add("open");
  }));
  tbody.querySelectorAll(".btn-cancel-edit").forEach(b=>b.addEventListener("click",()=>
    el(`editRow-${b.dataset.id}`).classList.remove("open")));
  tbody.querySelectorAll(".btn-save-edit").forEach(b=>b.addEventListener("click",async()=>{
    const row=el(`editRow-${b.dataset.id}`);
    const shares=parseFloat(row.querySelector(".edit-shares").value);
    const cost=parseFloat(row.querySelector(".edit-cost").value);
    if (!shares||shares<=0||!cost||cost<=0){toast("Shares and cost must be > 0.","error");return;}
    try{
      await api(`/api/holdings/${b.dataset.id}`,{method:"PUT",body:JSON.stringify({shares,cost_basis:cost})});
      toast("Updated.","success"); row.classList.remove("open"); await refreshSummary();
    }catch(e){toast(e.message,"error");}
  }));
  tbody.querySelectorAll(".btn-del").forEach(b=>b.addEventListener("click",()=>{
    closeEdits(); closeDels();
    el(`delRow-${b.dataset.id}`).classList.add("open");
  }));
  tbody.querySelectorAll(".btn-cancel-del").forEach(b=>b.addEventListener("click",()=>
    el(`delRow-${b.dataset.id}`).classList.remove("open")));
  tbody.querySelectorAll(".btn-confirm-del").forEach(b=>b.addEventListener("click",async()=>{
    try{
      await api(`/api/holdings/${b.dataset.id}`,{method:"DELETE"});
      toast("Removed.","info"); await refreshSummary();
    }catch(e){toast(e.message,"error");}
  }));
}

function closeEdits(){ document.querySelectorAll(".edit-row").forEach(r=>r.classList.remove("open")); }
function closeDels() { document.querySelectorAll(".confirm-row").forEach(r=>r.classList.remove("open")); }

// Clear all
let _clearOk=false;
el("btnClearAll").addEventListener("click", async()=>{
  if (!State.activePortfolioId) return;
  const btn=el("btnClearAll");
  if (!_clearOk){
    btn.textContent="⚠️ Confirm?"; _clearOk=true;
    setTimeout(()=>{ _clearOk=false; if(btn) btn.textContent="🗑️ Clear All"; },3000);
    return;
  }
  try {
    const list=await api(`/api/portfolios/${State.activePortfolioId}/holdings`);
    await Promise.all(list.map(h=>api(`/api/holdings/${h.id}`,{method:"DELETE"})));
    toast("All holdings cleared.","info"); _clearOk=false; btn.textContent="🗑️ Clear All";
    await refreshSummary();
  }catch(e){toast(e.message,"error");}
});

// ══════════════════════════════════════════════════════════
// CHARTS
// ══════════════════════════════════════════════════════════

function renderPerfChart(history){
  destroyChart("perfChart");
  if (!history?.length) return;
  const cutoff=Date.now()-State.perfPeriod*86400*1000;
  const pts=history.filter(p=>new Date(p.date).getTime()>=cutoff);
  if (!pts.length) return;
  const ctx=el("perfChart").getContext("2d");
  const g=ctx.createLinearGradient(0,0,0,280);
  g.addColorStop(0,"rgba(59,130,246,0.22)"); g.addColorStop(1,"rgba(59,130,246,0)");
  State.charts["perfChart"]=new Chart(ctx,{
    type:"line",
    data:{ labels:pts.map(p=>p.date), datasets:[{
      data:pts.map(p=>p.value), borderColor:"#3b82f6", borderWidth:2.5,
      backgroundColor:g, fill:true, tension:0.35, pointRadius:0, pointHoverRadius:5
    }]},
    options:{
      responsive:true, maintainAspectRatio:false,
      interaction:{mode:"index",intersect:false},
      plugins:{ legend:{display:false},
        tooltip:{backgroundColor:"rgba(13,13,16,0.96)",borderColor:"rgba(255,255,255,0.08)",borderWidth:1,
          callbacks:{label:c=>" "+fmt(c.parsed.y,2)}}},
      scales:{
        x:{type:"time",time:{unit:"month"},grid:{display:false},border:{display:false},ticks:{color:"#555b6e",maxTicksLimit:7}},
        y:{grid:{color:"rgba(255,255,255,0.04)"},border:{display:false},ticks:{color:"#555b6e",callback:v=>fmt(v,0)}},
      },
    },
  });
}

function renderAllocChart(holdings){
  destroyChart("allocChart");
  if (!holdings?.length) return;
  const ctx=el("allocChart").getContext("2d");
  State.charts["allocChart"]=new Chart(ctx,{
    type:"doughnut",
    data:{
      labels:holdings.map(h=>h.symbol),
      datasets:[{
        data:holdings.map(h=>h.value),
        backgroundColor:holdings.map(h=>SECTOR_COLORS[h.sector]||"#64748b"),
        borderColor:"rgba(0,0,0,0.45)", borderWidth:2, hoverOffset:7,
      }],
    },
    options:{
      responsive:true, maintainAspectRatio:true, cutout:"62%",
      plugins:{
        legend:{display:true,position:"right",
          labels:{color:"#94a3b8",boxWidth:10,boxHeight:10,padding:9,font:{size:11}}},
        tooltip:{backgroundColor:"rgba(13,13,16,0.96)",borderColor:"rgba(255,255,255,0.08)",borderWidth:1,
          callbacks:{label:c=>{
            const tot=c.dataset.data.reduce((a,b)=>a+b,0);
            return ` ${c.label}: ${fmt(c.parsed,0)} (${(c.parsed/tot*100).toFixed(1)}%)`;
          }}},
      },
    },
  });
}

function renderSectorBars(sectors, total){
  const box=el("sectorBars");
  if (!sectors||!total){box.innerHTML="";return;}
  box.innerHTML=Object.entries(sectors).sort((a,b)=>b[1]-a[1]).map(([n,v])=>{
    const pct=(v/total*100).toFixed(1);
    const c=SECTOR_COLORS[n]||"#64748b";
    return `<div class="sector-row">
      <div class="sector-header">
        <div class="sector-name"><div class="sector-dot" style="background:${c}"></div>${n}</div>
        <div class="sector-pct">${pct}%</div>
      </div>
      <div class="sector-bar-track">
        <div class="sector-bar-fill" style="width:${pct}%;background:${c}"></div>
      </div>
    </div>`;
  }).join("");
}

function renderInsights(insights){
  const box=el("insightList");
  if (!insights?.length){box.innerHTML="";return;}
  box.innerHTML=insights.map(i=>`
    <div class="insight-card ${i.type}">
      <div class="insight-icon">${i.icon}</div>
      <div><div class="insight-title">${i.title}</div>
           <div class="insight-desc">${i.desc}</div></div>
    </div>`).join("");
}

// ══════════════════════════════════════════════════════════
// RISK ANALYTICS TAB
// ══════════════════════════════════════════════════════════

async function loadRiskData(){
  if (!State.activePortfolioId) return;
  try {
    const d=await api(`/api/portfolios/${State.activePortfolioId}/risk`);
    el("riskVol").textContent =(d.volatility  ??0).toFixed(1);
    el("riskMdd").textContent =(d.max_drawdown??0).toFixed(1);
    el("riskVar").textContent =(d.var_95      ??0).toFixed(2);
    el("riskCvar").textContent=(d.cvar_95     ??0).toFixed(2);
    renderCorrelation(d.correlation);
    renderRiskContrib();
    renderDrawdownChart(d.drawdown_series);
  }catch(e){toast("Risk error: "+e.message,"error");}
}

function renderCorrelation(corr){
  const box=el("correlationArea");
  if (!corr){
    box.innerHTML=`<p style="font-size:13px;color:var(--text-muted)">Needs ≥ 2 holdings with 30+ common trading days.</p>`;
    return;
  }
  const {symbols,matrix}=corr;
  let h=`<div style="overflow-x:auto"><table class="heatmap-table">
    <thead><tr><th></th>${symbols.map(s=>`<th>${s.replace(/\.(NS|BO)$/,"")}</th>`).join("")}</tr></thead><tbody>`;
  matrix.forEach((row,i)=>{
    h+=`<tr><th style="text-align:right;padding-right:8px">${symbols[i].replace(/\.(NS|BO)$/,"")}</th>`;
    row.forEach(v=>{
      const a=Math.abs(v), r=v>0?Math.round(60*a):0, b=v<0?Math.round(60*a):0;
      h+=`<td class="heatmap-cell" style="background:rgba(${r+10},30,${b+40},${0.2+a*0.6});color:${a>0.5?"#fff":"#94a3b8"}">${v.toFixed(2)}</td>`;
    });
    h+=`</tr>`;
  });
  box.innerHTML=h+`</tbody></table></div>`;
}

function renderRiskContrib(){
  destroyChart("riskContribChart");
  const rc=State.summary?.risk_contribution;
  if (!rc||!Object.keys(rc).length) return;
  const entries=Object.entries(rc).sort((a,b)=>b[1]-a[1]);
  const ctx=el("riskContribChart").getContext("2d");
  State.charts["riskContribChart"]=new Chart(ctx,{
    type:"bar",
    data:{
      labels:entries.map(e=>e[0]),
      datasets:[{
        data:entries.map(e=>e[1]),
        backgroundColor:entries.map(([s])=>{ const h=State.summary?.holdings?.find(h=>h.symbol===s); return SECTOR_COLORS[h?.sector]||"#64748b"; }),
        borderRadius:5, borderWidth:0,
      }],
    },
    options:{
      indexAxis:"y", responsive:true, maintainAspectRatio:false,
      plugins:{legend:{display:false},
        tooltip:{backgroundColor:"rgba(13,13,16,0.96)",borderColor:"rgba(255,255,255,0.08)",borderWidth:1,
          callbacks:{label:c=>` ${c.parsed.x.toFixed(1)}% of portfolio variance`}}},
      scales:{
        x:{grid:{color:"rgba(255,255,255,0.04)"},border:{display:false},ticks:{color:"#555b6e",callback:v=>v+"%"}},
        y:{grid:{display:false},border:{display:false},ticks:{color:"#94a3b8"}},
      },
    },
  });
}

function renderDrawdownChart(series){
  destroyChart("drawdownChart");
  if (!series?.length) return;
  const ctx=el("drawdownChart").getContext("2d");
  const g=ctx.createLinearGradient(0,0,0,220);
  g.addColorStop(0,"rgba(239,68,68,0.2)"); g.addColorStop(1,"rgba(239,68,68,0)");
  State.charts["drawdownChart"]=new Chart(ctx,{
    type:"line",
    data:{labels:series.map(p=>p.date),datasets:[{
      data:series.map(p=>p.drawdown),borderColor:"#ef4444",borderWidth:1.5,
      backgroundColor:g,fill:true,tension:0.3,pointRadius:0,
    }]},
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{legend:{display:false},
        tooltip:{backgroundColor:"rgba(13,13,16,0.96)",borderColor:"rgba(255,255,255,0.08)",borderWidth:1,
          callbacks:{label:c=>` ${c.parsed.y.toFixed(2)}%`}}},
      scales:{
        x:{type:"time",time:{unit:"month"},grid:{display:false},border:{display:false},ticks:{color:"#555b6e",maxTicksLimit:7}},
        y:{grid:{color:"rgba(255,255,255,0.04)"},border:{display:false},ticks:{color:"#555b6e",callback:v=>v+"%"}},
      },
    },
  });
}

// ══════════════════════════════════════════════════════════
// SCENARIO TAB
// ══════════════════════════════════════════════════════════

function buildScenarioSliders(){
  const box=el("scenarioSliders");
  if (!State.summary?.holdings?.length){
    box.innerHTML=`<p style="color:var(--text-muted);font-size:13px">No holdings to simulate.</p>`;
    return;
  }
  box.innerHTML=State.summary.holdings.map(h=>{
    const short=h.symbol.replace(/\.(NS|BO)$/,"");
    return `<div class="slider-row">
      <div class="slider-symbol">${short}
        <div style="font-size:10px;color:var(--text-muted)">${fmt(h.price,2)}</div>
      </div>
      <input type="range" min="-50" max="100" value="0" step="1"
        id="sc_${h.symbol}"
        oninput="
          document.getElementById('scv_${h.symbol}').textContent=this.value+'%';
          const p=(parseInt(this.value)+50)/150*100;
          this.style.background=this.value==0?'var(--bg-elevated)':this.value>0
            ?'linear-gradient(to right,rgba(34,197,94,.4) 0%,rgba(34,197,94,.4) '+p+'%,var(--bg-elevated) '+p+'%)'
            :'linear-gradient(to right,var(--bg-elevated) 0%,var(--bg-elevated) '+p+'%,rgba(239,68,68,.4) '+p+'%,rgba(239,68,68,.4) 100%)';
        "/>
      <span class="slider-val" id="scv_${h.symbol}">0%</span>
    </div>`;
  }).join("");
  el("scenarioResults").classList.remove("visible");
}

el("btnRunScenario").addEventListener("click", async()=>{
  if (!State.activePortfolioId||!State.summary){toast("Load a portfolio first.","error");return;}
  const changes={};
  State.summary.holdings.forEach(h=>{
    const s=el(`sc_${h.symbol}`);
    if(s) changes[h.symbol]=parseFloat(s.value);
  });
  try{
    const r=await api(`/api/portfolios/${State.activePortfolioId}/scenario`,{method:"POST",body:JSON.stringify({changes})});
    el("scSimTotal").textContent=fmt(r.sim_total,0);
    const ie=el("scImpact");
    ie.textContent=(r.impact>=0?"+":"")+fmt(r.impact,0);
    ie.className=`kpi-value ${r.impact>=0?"positive":"negative"}`;
    const ipe=el("scImpactPct");
    ipe.textContent=fmtP(r.impact_pct);
    ipe.className=`kpi-value ${r.impact_pct>=0?"positive":"negative"}`;
    el("scenarioTbody").innerHTML=r.rows.map(row=>`
      <tr>
        <td><strong>${row.symbol}</strong></td>
        <td><span class="badge ${row.change_pct>=0?"badge-green":"badge-red"}">${fmtP(row.change_pct,0)}</span></td>
        <td>${fmt(row.orig_price,2)}</td>
        <td style="font-weight:600">${fmt(row.sim_price,2)}</td>
        <td>${fmt(row.sim_value,0)}</td>
        <td class="${row.sim_pnl>=0?"text-positive":"text-negative"}">${row.sim_pnl>=0?"+":""}${fmt(row.sim_pnl,0)}</td>
        <td>${row.new_weight.toFixed(1)}%</td>
      </tr>`).join("");
    el("scenarioResults").classList.add("visible");
  }catch(e){toast("Scenario error: "+e.message,"error");}
});

// ══════════════════════════════════════════════════════════
// AI ASSISTANT TAB
// ══════════════════════════════════════════════════════════

el("btnAskAI").addEventListener("click", askAI);
el("aiQuestion").addEventListener("keydown", e=>{ if(e.key==="Enter") askAI(); });
document.querySelectorAll(".suggestion-chip").forEach(chip=>
  chip.addEventListener("click",()=>{ el("aiQuestion").value=chip.textContent.trim(); askAI(); })
);

async function askAI(){
  const q=el("aiQuestion").value.trim();
  const btn=el("btnAskAI");
  if (!q){toast("Enter a question.","error");return;}
  if (!State.activePortfolioId){toast("Select a portfolio first.","error");return;}
  btn.disabled=true; btn.textContent="…";
  el("aiAnswer").classList.remove("visible");
  try{
    const res=await api(`/api/portfolios/${State.activePortfolioId}/ask`,{
      method:"POST", body:JSON.stringify({question:q}),
    });
    el("aiAnswer").textContent=res.answer;
    el("aiAnswer").classList.add("visible");
  }catch(e){toast("AI error: "+e.message,"error");}
  finally{ btn.disabled=false; btn.textContent="Ask →"; }
}

// ══════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════

async function init(){
  await loadPortfolios();
  if (State.portfolios.length>0){
    State.activePortfolioId = State.portfolios[0].id;
    el("portfolioSelect").value = State.activePortfolioId;
    el("deletePortfolioSection").style.display="block";
    showDashboard();
    await refreshSummary();
  }
}

init();
