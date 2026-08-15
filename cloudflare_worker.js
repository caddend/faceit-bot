// Cloudflare Worker: Telegram Mini App for Faceit Tracker (Black & White)

const FACEIT_API = "https://open.faceit.com/data/v4";

function jsonResp(obj, status) {
  if (!status) status = 200;
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, X-Auth-Secret',
    },
  });
}

async function validateInitData(initData, botToken) {
  if (!initData || !botToken) return null;
  const params = new URLSearchParams(initData);
  const hash = params.get('hash');
  if (!hash) return null;
  params.delete('hash');
  const entries = [...params.entries()].sort(function(a, b) { return a[0].localeCompare(b[0]); });
  const dataCheckString = entries.map(function(e) { return e[0] + '=' + e[1]; }).join('\n');
  const enc = new TextEncoder();
  const keyData = await crypto.subtle.importKey('raw', enc.encode('WebAppData'), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const secretKeyBuf = await crypto.subtle.sign('HMAC', keyData, enc.encode(botToken));
  const step2Key = await crypto.subtle.importKey('raw', secretKeyBuf, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const calcHashBuf = await crypto.subtle.sign('HMAC', step2Key, enc.encode(dataCheckString));
  const calcHash = [...new Uint8Array(calcHashBuf)].map(function(b) { return b.toString(16).padStart(2, '0'); }).join('');
  if (calcHash !== hash) return null;
  try {
    const user = JSON.parse(params.get('user') || '{}');
    return user.id || null;
  } catch {
    return null;
  }
}

async function getFaceitProfile(nickname, faceitToken) {
  try {
    const resp = await fetch(FACEIT_API + '/players?nickname=' + encodeURIComponent(nickname), {
      headers: { Authorization: 'Bearer ' + faceitToken },
    });
    if (!resp.ok) return null;
    return await resp.json();
  } catch {
    return null;
  }
}

async function getFaceitStats(playerId, faceitToken) {
  try {
    const resp = await fetch(FACEIT_API + '/players/' + playerId + '/stats/cs2', {
      headers: { Authorization: 'Bearer ' + faceitToken },
    });
    if (!resp.ok) return null;
    return await resp.json();
  } catch {
    return null;
  }
}

// NEW: Get match history
async function getMatchHistory(playerId, faceitToken, limit) {
  try {
    const resp = await fetch(FACEIT_API + '/players/' + playerId + '/history?game=cs2&offset=0&limit=' + (limit || 20), {
      headers: { Authorization: 'Bearer ' + faceitToken },
    });
    if (!resp.ok) return null;
    return await resp.json();
  } catch {
    return null;
  }
}

// NEW: Get match stats (scoreboard)
async function getMatchStats(matchId, faceitToken) {
  try {
    const resp = await fetch(FACEIT_API + '/matches/' + matchId + '/stats', {
      headers: { Authorization: 'Bearer ' + faceitToken },
    });
    if (!resp.ok) return null;
    return await resp.json();
  } catch {
    return null;
  }
}

// Determine if player won/lost a match from history item
function getMatchResultForPlayer(item, playerId) {
  let playerFaction = null;
  const teams = item.teams || {};
  for (const factionName of Object.keys(teams)) {
    const players = (teams[factionName] || {}).players || [];
    for (const p of players) {
      if (p.player_id === playerId) {
        playerFaction = factionName;
        break;
      }
    }
    if (playerFaction) break;
  }
  const winner = (item.results || {}).winner;
  if (!playerFaction || !winner) return null;
  return playerFaction === winner;
}

// Calculate performance score (0-100)
function calcPerfScore(stats) {
  var num = function(v) { var n = parseFloat(v); return isNaN(n) ? 0 : n; };
  var score = 0;
  score += Math.max(0, Math.min(30, (num(stats.kd) - 0.5) / 1.5 * 30));
  score += Math.max(0, Math.min(20, (num(stats.winrate) - 30) / 40 * 20));
  score += Math.max(0, Math.min(15, (num(stats.hs) - 20) / 50 * 15));
  score += Math.max(0, Math.min(15, (num(stats.adr) - 40) / 80 * 15));
  score += Math.max(0, Math.min(8, num(stats.v1_wr) / 100 * 8));
  score += Math.max(0, Math.min(4, num(stats.v2_wr) / 100 * 4));
  score += Math.max(0, Math.min(4, num(stats.entry_wr) / 100 * 4));
  score += Math.max(0, Math.min(2, num(stats.flash_wr) / 100 * 2));
  var rr = stats.recent_results || [];
  var rec = 0;
  rr.forEach(function(r) { rec += (r === '1') ? 1 : -0.5; });
  score += Math.max(-2, Math.min(2, rec));
  return Math.max(0, Math.min(100, Math.round(score)));
}

const HTML = `<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Faceit Tracker</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --bg:#000;--surface:#0a0a0a;--card:#141414;--card2:#1c1c1c;
  --text:#fff;--hint:#808080;--accent:#fff;
  --border:rgba(255,255,255,.06);
  --win-bg:#f0f0f0;--win-text:#000;--loss-bg:#2a2a2a;--loss-text:#888;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;min-height:100vh;overflow-x:hidden}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes scaleIn{from{transform:scale(.85);opacity:0}to{transform:scale(1);opacity:1}}
.fade-in{animation:fadeIn .3s ease forwards}

#loading{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:80vh;gap:16px}
.spinner{width:48px;height:48px;border:3px solid var(--card);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}
#loading p{color:var(--hint);font-size:14px}

#error{display:none;text-align:center;padding:60px 16px;animation:fadeIn .3s}
#error .icon{font-size:48px;margin-bottom:16px}
#error h2{font-size:18px;margin-bottom:8px}
#error p{color:var(--hint);font-size:14px;line-height:1.5}

#app{display:none;padding:16px;max-width:520px;margin:0 auto;padding-bottom:80px}

.header-card{background:var(--card);border:1px solid var(--border);border-radius:20px;padding:24px;display:flex;align-items:center;gap:20px;margin-bottom:16px;animation:fadeIn .4s ease}
.avatar-wrap{position:relative;width:88px;height:88px;flex-shrink:0}
.avatar{width:80px;height:80px;border-radius:50%;object-fit:cover;border:2px solid var(--card2);position:absolute;top:4px;left:4px;background:#222}
.perf-ring{position:absolute;top:0;left:0;width:88px;height:88px;transform:rotate(-90deg)}
.perf-ring circle{fill:none;stroke-width:4}
.perf-ring .bg{stroke:rgba(255,255,255,.06)}
.perf-ring .progress{stroke-linecap:round;transition:stroke-dashoffset 1s ease,stroke .3s ease}
.perf-pct{position:absolute;top:-8px;left:50%;transform:translateX(-50%);font-size:13px;font-weight:800;color:var(--text);background:var(--bg);padding:1px 6px;border-radius:8px;white-space:nowrap;z-index:2}
.player-info{flex:1;min-width:0}
.player-info .nick{font-size:20px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.player-info .country{color:var(--hint);font-size:13px;margin-top:4px}

.elo-card{background:var(--card);border:1px solid var(--border);border-radius:20px;padding:24px;text-align:center;margin-bottom:16px;animation:fadeIn .5s ease}
.elo-card .label{color:var(--hint);font-size:12px;text-transform:uppercase;letter-spacing:1.5px}
.elo-card .value{font-size:48px;font-weight:800;margin-top:6px;color:var(--text)}
.elo-card .streak{color:var(--hint);font-size:13px;margin-top:8px}

.tabs{display:flex;background:var(--card);border:1px solid var(--border);border-radius:16px;padding:4px;margin-bottom:16px;gap:2px}
.tab{flex:1;padding:12px 6px;text-align:center;border-radius:12px;font-size:13px;font-weight:600;color:var(--hint);cursor:pointer;transition:all .2s;border:none;background:none}
.tab.active{background:var(--accent);color:#000}
.tab:active{transform:scale(.95)}

.tab-content{display:none;animation:fadeIn .3s ease}
.tab-content.active{display:block}

.stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:18px;text-align:center;animation:scaleIn .3s ease}
.stat-card .label{color:var(--hint);font-size:11px;text-transform:uppercase;letter-spacing:1px}
.stat-card .value{font-size:26px;font-weight:700;margin-top:6px}

.recent-card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:18px;margin-bottom:16px}
.recent-card h3{font-size:12px;color:var(--hint);text-transform:uppercase;letter-spacing:1px;margin-bottom:14px}
.results{display:flex;flex-wrap:wrap;gap:8px}
.result-dot{width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;animation:scaleIn .3s ease}
.result-dot.win{background:var(--win-bg);color:var(--win-text)}
.result-dot.loss{background:var(--loss-bg);color:var(--loss-text)}

.map-row{display:flex;align-items:center;justify-content:space-between;padding:14px;background:var(--card);border:1px solid var(--border);border-radius:14px;margin-bottom:8px;animation:fadeIn .3s ease}
.map-name{font-weight:600;font-size:14px}
.map-stats{display:flex;gap:12px;font-size:12px;color:var(--hint)}
.map-stats b{color:var(--text)}
.map-bar{height:4px;border-radius:2px;margin-top:6px;overflow:hidden;background:rgba(255,255,255,.06)}
.map-bar-fill{height:100%;border-radius:2px;transition:width .6s ease}
.wr-good{background:#e0e0e0}
.wr-mid{background:#888}
.wr-bad{background:#444}

.clutch-card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:18px;margin-bottom:16px}
.clutch-card h3{font-size:12px;color:var(--hint);text-transform:uppercase;letter-spacing:1px;margin-bottom:14px}
.clutch-row{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border)}
.clutch-row:last-child{border:none}
.clutch-row .label{font-size:14px;color:var(--hint)}
.clutch-row .value{font-weight:700;font-size:15px}

.perf-label{text-align:center;font-size:12px;color:var(--hint);margin-top:12px;line-height:1.5}
.perf-label b{color:var(--text)}

/* ===== Matches tab ===== */
.match-card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px;margin-bottom:10px;cursor:pointer;transition:background .2s,border-color .2s;animation:fadeIn .3s ease}
.match-card:active{background:var(--card2);transform:scale(.98)}
.match-card .mc-top{display:flex;align-items:center;gap:12px;margin-bottom:8px}
.match-badge{padding:4px 10px;border-radius:8px;font-size:12px;font-weight:700;flex-shrink:0}
.match-badge.win{background:var(--win-bg);color:var(--win-text)}
.match-badge.loss{background:var(--loss-bg);color:var(--loss-text)}
.match-card .mc-map{font-weight:600;font-size:15px;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.match-card .mc-score{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums}
.match-card .mc-bottom{display:flex;justify-content:space-between;font-size:12px;color:var(--hint)}
.match-loading{text-align:center;padding:40px;color:var(--hint);font-size:14px}

/* ===== Match detail overlay ===== */
#match-detail{display:none;position:fixed;inset:0;background:var(--bg);z-index:100;overflow-y:auto;-webkit-overflow-scrolling:touch}
#match-detail.active{display:block;animation:fadeIn .3s ease}
.md-inner{max-width:520px;margin:0 auto;padding:16px;padding-bottom:60px}
.md-back{display:flex;align-items:center;gap:8px;padding:12px 0;margin-bottom:8px;color:var(--hint);font-size:15px;cursor:pointer;background:none;border:none}
.md-back:active{color:var(--text)}
.md-header{display:flex;align-items:center;gap:12px;margin-bottom:20px}
.md-header .md-map{font-size:22px;font-weight:800}
.md-header .md-result{font-size:14px;font-weight:700;padding:4px 12px;border-radius:8px}
.md-result.win{background:var(--win-bg);color:var(--win-text)}
.md-result.loss{background:var(--loss-bg);color:var(--loss-text)}
.md-score{font-size:28px;font-weight:800;font-variant-numeric:tabular-nums;margin-bottom:20px;text-align:center}
.team-section{margin-bottom:20px}
.team-section h3{font-size:13px;text-transform:uppercase;letter-spacing:1px;color:var(--hint);margin-bottom:10px}
.team-table{background:var(--card);border:1px solid var(--border);border-radius:14px;overflow:hidden}
.team-row{display:grid;grid-template-columns:1fr auto auto auto auto;padding:10px 12px;border-bottom:1px solid var(--border);align-items:center;gap:8px;font-size:13px}
.team-row:last-child{border:none}
.team-row.you{background:rgba(255,255,255,.04)}
.team-row .tr-nick{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.team-row .tr-num{text-align:center;font-variant-numeric:tabular-nums;min-width:28px}
.team-row .tr-hs{color:var(--hint);font-size:11px;min-width:36px;text-align:right}
.team-head{display:grid;grid-template-columns:1fr auto auto auto auto;padding:8px 12px;border-bottom:1px solid var(--border);gap:8px;font-size:11px;color:var(--hint);text-transform:uppercase;letter-spacing:.5px}
.team-head .th-num{text-align:center;min-width:28px}
.team-head .th-hs{min-width:36px;text-align:right}

.my-stats{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px;margin-bottom:16px}
.my-stats h3{font-size:13px;text-transform:uppercase;letter-spacing:1px;color:var(--hint);margin-bottom:14px}
.my-stats-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
.my-stat{text-align:center}
.my-stat .label{font-size:10px;color:var(--hint);text-transform:uppercase;letter-spacing:.5px}
.my-stat .value{font-size:18px;font-weight:700;margin-top:4px}
</style>
</head>
<body>
<div id="loading"><div class="spinner"></div><p>Загрузка...</p></div>
<div id="error"><div class="icon">⚠️</div><h2 id="error-title">Ошибка</h2><p id="error-text"></p></div>
<div id="app">
  <div class="header-card">
    <div class="avatar-wrap">
      <div class="perf-pct" id="perf-pct">-</div>
      <svg class="perf-ring" viewBox="0 0 88 88"><circle class="bg" cx="44" cy="44" r="42"></circle><circle class="progress" id="perf-ring-progress" cx="44" cy="44" r="42" stroke-dasharray="263.89" stroke-dashoffset="263.89" stroke="#444"></circle></svg>
      <img id="avatar" class="avatar" alt="">
    </div>
    <div class="player-info"><div class="nick" id="nickname"></div><div class="country" id="country"></div></div>
  </div>
  <div class="elo-card"><div class="label">Faceit ELO</div><div class="value" id="elo">-</div><div class="streak" id="streak"></div></div>
  <div class="perf-label" id="perf-label"></div>
  <div class="tabs">
    <button class="tab active" data-tab="overview">Обзор</button>
    <button class="tab" data-tab="matches">Матчи</button>
    <button class="tab" data-tab="maps">Карты</button>
    <button class="tab" data-tab="clutch">Детали</button>
  </div>
  <div class="tab-content active" id="tab-overview">
    <div class="stats-grid">
      <div class="stat-card"><div class="label">Матчей</div><div class="value" id="matches">-</div></div>
      <div class="stat-card"><div class="label">Винрейт</div><div class="value" id="winrate">-</div></div>
      <div class="stat-card"><div class="label">K/D</div><div class="value" id="kd">-</div></div>
      <div class="stat-card"><div class="label">HS%</div><div class="value" id="hs">-</div></div>
      <div class="stat-card"><div class="label">ADR</div><div class="value" id="adr">-</div></div>
      <div class="stat-card"><div class="label">Урон</div><div class="value" id="dmg">-</div></div>
      <div class="stat-card" id="card-rating" style="display:none"><div class="label">Rating 3.0</div><div class="value" id="rating">-</div></div>
      <div class="stat-card" id="card-swing" style="display:none"><div class="label">Swing</div><div class="value" id="swing">-</div></div>
    </div>
    <div class="recent-card"><h3>Последние игры</h3><div class="results" id="results"></div></div>
  </div>
  <div class="tab-content" id="tab-matches">
    <div id="matches-list" class="match-loading">Нажми на вкладку, чтобы загрузить матчи...</div>
  </div>
  <div class="tab-content" id="tab-maps"></div>
  <div class="tab-content" id="tab-clutch"></div>
</div>

<!-- Match detail overlay -->
<div id="match-detail">
  <div class="md-inner">
    <button class="md-back" onclick="closeMatchDetail()">← Назад</button>
    <div id="match-detail-content"></div>
  </div>
</div>

<script>
var tg=window.Telegram.WebApp;tg.ready();tg.expand();
var RING_CIRC=263.89;
var playerId=null;

// Performance ring color (monochrome)
function perfColor(score){if(score<30)return '#444';if(score<50)return '#666';if(score<70)return '#999';if(score<85)return '#ccc';return '#fff';}
function perfLabel(score){if(score<30)return ' играет ниже своего уровня';if(score<50)return ' слабо на свой уровень';if(score<70)return ' играет нормально';if(score<85)return ' играет хорошо';return ' играет выше своего уровня';}

function showError(t,txt){document.getElementById('loading').style.display='none';var e=document.getElementById('error');e.style.display='block';document.getElementById('error-title').textContent=t;document.getElementById('error-text').textContent=txt;}

function renderPerfRing(score){var offset=RING_CIRC*(1-score/100);var ring=document.getElementById('perf-ring-progress');ring.style.strokeDashoffset=offset;ring.style.stroke=perfColor(score);var pct=document.getElementById('perf-pct');pct.textContent=score+'%';pct.style.color=perfColor(score);var lbl=document.getElementById('perf-label');lbl.innerHTML='Оценка игры: <b>'+score+'/100</b> — игрок '+perfLabel(score);}

function renderMaps(maps){var c=document.getElementById('tab-maps');if(!maps||!maps.length){c.innerHTML='<p style="color:var(--hint);padding:20px;text-align:center">Нет данных</p>';return;}c.innerHTML=maps.map(function(m){var wr=parseInt(m.winrate)||0;var cls=wr>=55?'wr-good':(wr>=45?'wr-mid':'wr-bad');return '<div class="map-row fade-in"><div style="flex:1"><div class="map-name">'+m.name+'</div><div style="font-size:11px;color:var(--hint);margin-top:2px">'+m.matches+' матчей</div><div class="map-bar"><div class="map-bar-fill '+cls+'" style="width:'+wr+'%"></div></div></div><div class="map-stats"><span>WR <b>'+wr+'%</b></span><span>K/D <b>'+m.kd+'</b></span></div></div>';}).join('');}

function renderClutch(d){var c=document.getElementById('tab-clutch');var rows=[{label:'K/D рейт',val:d.kd},{label:'Винрейт',val:d.winrate+'%'},{label:'1v1 успешность',val:(d.v1_wr||'-')+'%'},{label:'1v2 успешность',val:(d.v2_wr||'-')+'%'},{label:'Энтри рейт',val:(d.entry_wr||'-')+'%'},{label:'Флешки',val:(d.flash_wr||'-')+'%'},{label:'Утилити',val:(d.util_wr||'-')+'%'},{label:'Снайпер',val:(d.sniper_wr||'-')+'%'},{label:'ADR',val:d.adr||'-'},{label:'Урон всего',val:d.dmg||'-'}];c.innerHTML='<div class="clutch-card"><h3>Детальная статистика</h3>'+rows.map(function(r){return '<div class="clutch-row fade-in"><span class="label">'+r.label+'</span><span class="value">'+r.val+'</span></div>';}).join('')+'</div>';}

function render(d){
  document.getElementById('loading').style.display='none';
  document.getElementById('app').style.display='block';
  playerId=d.player_id;
  document.getElementById('avatar').src=d.avatar||'';
  document.getElementById('nickname').textContent=d.nickname||'-';
  document.getElementById('country').textContent=d.country||'';
  document.getElementById('elo').textContent=d.elo||'-';
  document.getElementById('streak').textContent=d.streak?('Винстрик: '+d.streak):'';
  document.getElementById('matches').textContent=d.matches||'-';
  document.getElementById('winrate').textContent=d.winrate!==null?(d.winrate+'%'):'-';
  document.getElementById('kd').textContent=d.kd||'-';
  document.getElementById('hs').textContent=d.hs!==null?(d.hs+'%'):'-';
  document.getElementById('adr').textContent=d.adr||'-';
  document.getElementById('dmg').textContent=d.dmg||'-';
  // Rating 3.0 / Swing — из расширения (показываем только если есть)
  if(d.rating_3_0!=null&&d.rating_3_0!==undefined){
    document.getElementById('rating').textContent=d.rating_3_0;
    document.getElementById('card-rating').style.display='block';
  }
  if(d.swing!=null&&d.swing!==undefined){
    document.getElementById('swing').textContent=d.swing;
    document.getElementById('card-swing').style.display='block';
  }
  var r=document.getElementById('results');
  r.innerHTML='';
  (d.recent_results||[]).forEach(function(x){var dot=document.createElement('div');dot.className='result-dot '+(x==='1'?'win':'loss');dot.textContent=x==='1'?'W':'L';r.appendChild(dot);});
  renderPerfRing(d.perf_score||0);
  renderMaps(d.maps||[]);
  renderClutch(d);
}

// ===== Tab switching =====
document.querySelectorAll('.tab').forEach(function(tab){
  tab.addEventListener('click',function(){
    document.querySelectorAll('.tab').forEach(function(t){t.classList.remove('active');});
    document.querySelectorAll('.tab-content').forEach(function(c){c.classList.remove('active');});
    tab.classList.add('active');
    document.getElementById('tab-'+tab.dataset.tab).classList.add('active');
    if(tab.dataset.tab==='matches'&&!matchesLoaded)loadMatches();
  });
});

// ===== Matches list =====
var matchesLoaded=false;

async function loadMatches(){
  var c=document.getElementById('matches-list');
  c.innerHTML='<div class="match-loading">Загружаю матчи...</div>';
  try{
    var init=tg.initData||'';
    var resp=await fetch('/api/matches',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:init})});
    var data=await resp.json();
    if(!resp.ok){c.innerHTML='<div class="match-loading">'+(data.message||data.error||'Ошибка')+'</div>';return;}
    matchesLoaded=true;
    renderMatches(data.matches||[]);
  }catch(e){
    c.innerHTML='<div class="match-loading">Не удалось загрузить матчи.</div>';
  }
}

function renderMatches(matches){
  var c=document.getElementById('matches-list');
  if(!matches.length){c.innerHTML='<div class="match-loading">Нет сыгранных матчей.</div>';return;}
  c.innerHTML=matches.map(function(m){
    var dateStr=timeAgo(m.finished_at);
    return '<div class="match-card fade-in" onclick="openMatchDetail(\\''+m.match_id+'\\')">'+
      '<div class="mc-top">'+
        '<span class="match-badge '+(m.result?'win':'loss')+'">'+(m.result?'W':'L')+'</span>'+
        '<span class="mc-map">'+(m.map||'Unknown')+'</span>'+
        '<span class="mc-score">'+m.score+'</span>'+
      '</div>'+
      '<div class="mc-bottom"><span>'+dateStr+'</span><span>K/D: '+m.kd+'</span></div>'+
    '</div>';
  }).join('');
}

function timeAgo(ts){
  if(!ts)return '';
  var now=Math.floor(Date.now()/1000);
  var diff=now-ts;
  if(diff<60)return 'только что';
  if(diff<3600)return Math.floor(diff/60)+' мин назад';
  if(diff<86400)return Math.floor(diff/3600)+' ч назад';
  return Math.floor(diff/86400)+' дн назад';
}

// ===== Match detail =====
async function openMatchDetail(matchId){
  var overlay=document.getElementById('match-detail');
  var content=document.getElementById('match-detail-content');
  overlay.classList.add('active');
  content.innerHTML='<div class="match-loading">Загружаю детали матча...</div>';
  try{
    var init=tg.initData||'';
    var resp=await fetch('/api/match',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:init,match_id:matchId})});
    var data=await resp.json();
    if(!resp.ok){content.innerHTML='<div class="match-loading">'+(data.message||data.error||'Ошибка')+'</div>';return;}
    renderMatchDetail(data);
  }catch(e){
    content.innerHTML='<div class="match-loading">Не удалось загрузить детали.</div>';
  }
}

function closeMatchDetail(){
  document.getElementById('match-detail').classList.remove('active');
}

function renderMatchDetail(d){
  var content=document.getElementById('match-detail-content');
  var winClass=d.result?'win':'loss';
  var resultText=d.result?'ПОБЕДА':'ПОРАЖЕНИЕ';

  // Build team tables
  function buildTeam(team,teamName,isMyTeam){
    if(!team||!team.length)return '';
    var rows=team.map(function(p){
      var s=p.player_stats||{};
      var isYou=p.player_id===playerId?'you':'';
      return '<div class="team-row '+isYou+'">'+
        '<span class="tr-nick">'+p.nickname+'</span>'+
        '<span class="tr-num">'+(s.Kills||'0')+'</span>'+
        '<span class="tr-num">'+(s.Deaths||'0')+'</span>'+
        '<span class="tr-num">'+(s['K/D Ratio']||'0')+'</span>'+
        '<span class="tr-hs">'+(s['Headshots %']||'0')+'%</span>'+
      '</div>';
    }).join('');
    var head='<div class="team-head">'+
      '<span>Игрок</span><span class="th-num">K</span><span class="th-num">D</span><span class="th-num">K/D</span><span class="th-hs">HS</span>'+
    '</div>';
    return '<div class="team-section"><h3>'+(isMyTeam?'Твоя команда':'Противники')+'</h3><div class="team-table">'+head+rows+'</div></div>';
  }

  // My stats
  var ms=d.my_stats||{};
  var myStatsHtml='';
  if(ms.Kills){
    myStatsHtml='<div class="my-stats"><h3>Твоя статистика</h3><div class="my-stats-grid">'+
      '<div class="my-stat"><div class="label">Kills</div><div class="value">'+(ms.Kills||'0')+'</div></div>'+
      '<div class="my-stat"><div class="label">Deaths</div><div class="value">'+(ms.Deaths||'0')+'</div></div>'+
      '<div class="my-stat"><div class="label">K/D</div><div class="value">'+(ms['K/D Ratio']||'0')+'</div></div>'+
      '<div class="my-stat"><div class="label">HS%</div><div class="value">'+(ms['Headshots %']||'0')+'</div></div>'+
      '<div class="my-stat"><div class="label">MVP</div><div class="value">'+(ms.MVPs||'0')+'</div></div>'+
      '<div class="my-stat"><div class="label">Assists</div><div class="value">'+(ms.Assists||'0')+'</div></div>'+
      '<div class="my-stat"><div class="label">3K</div><div class="value">'+(ms['Triple Kills']||'0')+'</div></div>'+
      '<div class="my-stat"><div class="label">4K</div><div class="value">'+(ms['Quadro Kills']||'0')+'</div></div>'+
      '<div class="my-stat"><div class="label">5K</div><div class="value">'+(ms['Penta Kills']||'0')+'</div></div>'+
    '</div></div>';
  }

  content.innerHTML=
    '<div class="md-header">'+
      '<span class="md-map">'+d.map+'</span>'+
      '<span class="md-result '+winClass+'">'+resultText+'</span>'+
    '</div>'+
    '<div class="md-score">'+d.score+'</div>'+
    buildTeam(d.my_team,null,true)+
    buildTeam(d.enemy_team,null,false)+
    myStatsHtml;
}

// ===== Initial load =====
async function load(){
  try{
    var init=tg.initData||'';
    var resp=await fetch('/api/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:init})});
    var data=await resp.json();
    if(resp.status===404){showError('Ник не привязан',data.message||'Привяжи через /setnick.');return;}
    if(!resp.ok){showError('Ошибка',data.message||data.error||'Попробуй позже.');return;}
    render(data);
  }catch(e){
    showError('Ошибка сети','Не удалось загрузить.');
  }
}
load();
</script>
</body>
</html>`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, X-Auth-Secret',
        },
      });
    }

    if (url.pathname === '/' && request.method === 'GET') {
      return new Response(HTML, {
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      });
    }

    if (url.pathname === '/api/debug' && request.method === 'GET') {
      return jsonResp({
        bot_token_set: !!env.BOT_TOKEN,
        faceit_token_set: !!env.FACEIT_TOKEN,
        auth_secret_set: !!env.AUTH_SECRET,
        kv_bound: !!env.NICKS_KV,
      });
    }

    // ===== /api/profile (existing, unchanged) =====
    if (url.pathname === '/api/profile' && request.method === 'POST') {
      let initData = '';
      try {
        const body = await request.json();
        initData = body.init_data || '';
      } catch {
        return jsonResp({ error: 'bad_request' }, 400);
      }
      const userId = await validateInitData(initData, env.BOT_TOKEN);
      if (!userId) {
        return jsonResp({ error: 'invalid_init_data' }, 403);
      }
      const nickname = await env.NICKS_KV.get(String(userId));
      if (!nickname) {
        return jsonResp({ error: 'no_nickname', message: 'Привяжи ник через /setnick в боте.' }, 404);
      }
      const playerData = await getFaceitProfile(nickname, env.FACEIT_TOKEN);
      if (!playerData) {
        return jsonResp({ error: 'player_not_found' }, 404);
      }
      const playerId = playerData.player_id;
      const statsData = await getFaceitStats(playerId, env.FACEIT_TOKEN);
      const lifetime = (statsData && statsData.lifetime) || {};
      const games = (playerData.games && playerData.games.cs2) || {};
      var maps = [];
      if (statsData && statsData.segments) {
        var mapSegs = statsData.segments.filter(function(s) { return s.mode === '5v5' && s.type === 'Map'; });
        mapSegs.forEach(function(s) {
          var st = s.stats || {};
          var m = parseInt(st['Matches'] || '0') || 0;
          if (m > 0) maps.push({ name: s.label || '?', matches: m, winrate: st['Win Rate %'] || '0', kd: st['Average K/D Ratio'] || '0' });
        });
        maps.sort(function(a, b) { return b.matches - a.matches; });
        maps = maps.slice(0, 8);
      }
      var stats = {
        player_id: playerId,
        nickname: nickname,
        avatar: playerData.avatar,
        country: (playerData.country || '').toUpperCase(),
        elo: games.faceit_elo,
        level: games.skill_level,
        matches: lifetime.Matches,
        wins: lifetime.Wins,
        winrate: lifetime['Win Rate %'],
        kd: lifetime['Average K/D Ratio'],
        hs: lifetime['Average Headshots %'],
        adr: lifetime['ADR'],
        dmg: lifetime['Total Damage'],
        streak: lifetime['Current Win Streak'],
        longest_streak: lifetime['Longest Win Streak'],
        recent_results: lifetime['Recent Results'] || [],
        v1_wr: lifetime['1v1 Win Rate'],
        v2_wr: lifetime['1v2 Win Rate'],
        entry_wr: lifetime['Entry Success Rate'],
        flash_wr: lifetime['Flash Success Rate'],
        util_wr: lifetime['Utility Damage Success Rate'],
        sniper_wr: lifetime['Sniper Kill Rate'],
        maps: maps,
      };
      stats.perf_score = calcPerfScore(stats);

      // Расширенные данные из расширения (Rating 3.0, swing) — если есть link_token
      const linkToken = await env.NICKS_KV.get('link_token:' + String(userId));
      if (linkToken) {
        const scrapeRaw = await env.NICKS_KV.get('scrape:' + linkToken + ':advanced');
        if (scrapeRaw) {
          try {
            const scrape = JSON.parse(scrapeRaw);
            const payload = scrape.payload || {};
            stats.rating_3_0 = payload.rating_3_0 || null;
            stats.swing = payload.swing || null;
            stats.has_extension = true;
          } catch {}
        }
      }

      return jsonResp(stats);
    }

    // ===== NEW: /api/matches — list of recent matches =====
    if (url.pathname === '/api/matches' && request.method === 'POST') {
      let initData = '';
      let body;
      try {
        body = await request.json();
        initData = body.init_data || '';
      } catch {
        return jsonResp({ error: 'bad_request' }, 400);
      }
      const userId = await validateInitData(initData, env.BOT_TOKEN);
      if (!userId) {
        return jsonResp({ error: 'invalid_init_data' }, 403);
      }
      const nickname = await env.NICKS_KV.get(String(userId));
      if (!nickname) {
        return jsonResp({ error: 'no_nickname', message: 'Привяжи ник через /setnick в боте.' }, 404);
      }
      const playerData = await getFaceitProfile(nickname, env.FACEIT_TOKEN);
      if (!playerData) {
        return jsonResp({ error: 'player_not_found' }, 404);
      }
      const playerId = playerData.player_id;
      const historyData = await getMatchHistory(playerId, env.FACEIT_TOKEN, 20);
      if (!historyData || !historyData.items) {
        return jsonResp({ matches: [] });
      }

      // Fetch map name + K/D for each match in parallel (batched)
      const items = historyData.items;
      const matchInfos = items.map(function(item) {
        const matchId = item.match_id;
        const result = getMatchResultForPlayer(item, playerId);
        const scoreData = (item.results || {}).score || {};
        const s1 = scoreData.faction1 || 0;
        const s2 = scoreData.faction2 || 0;
        const finishedAt = item.finished_at || item.started_at || 0;
        return { match_id: matchId, result: result, score: s1 + ':' + s2, finished_at: finishedAt, _item: item };
      });

      // Batch-fetch match stats for map + K/D (limit concurrency to 5)
      const BATCH = 5;
      for (let i = 0; i < matchInfos.length; i += BATCH) {
        const batch = matchInfos.slice(i, i + BATCH);
        const statsResults = await Promise.all(batch.map(function(mi) {
          return getMatchStats(mi.match_id, env.FACEIT_TOKEN).catch(function() { return null; });
        }));
        batch.forEach(function(mi, idx) {
          const ms = statsResults[idx];
          if (ms && ms.rounds && ms.rounds[0]) {
            mi.map = ms.rounds[0].round_stats?.Map || 'Unknown';
            // Find player K/D
            const teams = ms.rounds[0].teams || [];
            for (const team of teams) {
              for (const p of (team.players || [])) {
                if (p.player_id === playerId) {
                  mi.kd = (p.player_stats || {})['K/D Ratio'] || '0';
                  break;
                }
              }
            }
          }
          mi.map = mi.map || 'Unknown';
          mi.kd = mi.kd || '-';
        });
      }

      // Strip _item before returning
      const cleanMatches = matchInfos.map(function(mi) {
        return { match_id: mi.match_id, result: mi.result, score: mi.score, finished_at: mi.finished_at, map: mi.map, kd: mi.kd };
      });

      return jsonResp({ matches: cleanMatches });
    }

    // ===== NEW: /api/match — full match detail =====
    if (url.pathname === '/api/match' && request.method === 'POST') {
      let initData = '';
      let matchId = '';
      try {
        const body = await request.json();
        initData = body.init_data || '';
        matchId = body.match_id || '';
      } catch {
        return jsonResp({ error: 'bad_request' }, 400);
      }
      if (!matchId) {
        return jsonResp({ error: 'no_match_id' }, 400);
      }
      const userId = await validateInitData(initData, env.BOT_TOKEN);
      if (!userId) {
        return jsonResp({ error: 'invalid_init_data' }, 403);
      }
      const nickname = await env.NICKS_KV.get(String(userId));
      if (!nickname) {
        return jsonResp({ error: 'no_nickname', message: 'Привяжи ник через /setnick.' }, 404);
      }

      // Get player profile to know player_id
      const playerData = await getFaceitProfile(nickname, env.FACEIT_TOKEN);
      if (!playerData) {
        return jsonResp({ error: 'player_not_found' }, 404);
      }
      const pid = playerData.player_id;

      // Get match stats
      const matchStats = await getMatchStats(matchId, env.FACEIT_TOKEN);
      if (!matchStats || !matchStats.rounds || !matchStats.rounds[0]) {
        return jsonResp({ error: 'match_not_found' }, 404);
      }

      const round = matchStats.rounds[0];
      const roundStats = round.round_stats || {};
      const teams = round.teams || [];

      var myTeam = null;
      var enemyTeam = null;
      var myResult = null;

      for (const team of teams) {
        const players = team.players || [];
        const isMyTeam = players.some(function(p) { return p.player_id === pid; });
        if (isMyTeam) {
          myTeam = players;
          // Determine result from individual player's stats (not team_stats)
          for (const p of players) {
            if (p.player_id === pid) {
              var playerResult = (p.player_stats || {}).Result;
              if (playerResult === '1') myResult = true;
              else if (playerResult === '0') myResult = false;
              break;
            }
          }
        } else {
          enemyTeam = players;
        }
      }

      // Extract my player stats
      var myStats = null;
      if (myTeam) {
        for (const p of myTeam) {
          if (p.player_id === pid) {
            myStats = p.player_stats || {};
            break;
          }
        }
      }

      // Sort teams by kills (descending)
      function sortByKills(arr) {
        if (!arr) return [];
        return arr.slice().sort(function(a, b) {
          var ka = parseInt((a.player_stats || {}).Kills || '0');
          var kb = parseInt((b.player_stats || {}).Kills || '0');
          return kb - ka;
        });
      }

      return jsonResp({
        map: roundStats.Map || 'Unknown',
        score: roundStats.Score || 'N/A',
        result: myResult,
        my_team: sortByKills(myTeam),
        enemy_team: sortByKills(enemyTeam),
        my_stats: myStats,
      });
    }

    // ===== /api/update-user (existing) =====
    if (url.pathname === '/api/update-user' && request.method === 'POST') {
      if (request.headers.get('X-Auth-Secret') !== env.AUTH_SECRET) {
        return jsonResp({ error: 'unauthorized' }, 403);
      }
      try {
        const body = await request.json();
        await env.NICKS_KV.put(String(body.user_id), String(body.nickname));
        if (body.link_token) {
          await env.NICKS_KV.put('link_token:' + String(body.user_id), String(body.link_token));
          // Обратный индекс для verify-link: link_token → {user_id, nickname, tg_nickname}
          await env.NICKS_KV.put('verify:' + String(body.link_token),
            JSON.stringify({
              user_id: body.user_id,
              nickname: body.nickname,
              tg_nickname: body.tg_nickname || body.nickname
            }));
        }
        return jsonResp({ ok: true });
      } catch {
        return jsonResp({ error: 'bad_request' }, 400);
      }
    }

    // ===== /api/bulk-update (existing) =====
    if (url.pathname === '/api/bulk-update' && request.method === 'POST') {
      if (request.headers.get('X-Auth-Secret') !== env.AUTH_SECRET) {
        return jsonResp({ error: 'unauthorized' }, 403);
      }
      try {
        const body = await request.json();
        const users = body.users || [];
        const promises = [];
        users.forEach(function(u) {
          promises.push(env.NICKS_KV.put(String(u.user_id), String(u.nickname)));
          if (u.link_token) {
            promises.push(env.NICKS_KV.put('link_token:' + String(u.user_id), String(u.link_token)));
            promises.push(env.NICKS_KV.put('verify:' + String(u.link_token),
              JSON.stringify({
                user_id: u.user_id,
                nickname: u.nickname,
                tg_nickname: u.tg_nickname || u.nickname
              })));
          }
        });
        await Promise.all(promises);
        return jsonResp({ ok: true, count: users.length });
      } catch {
        return jsonResp({ error: 'bad_request' }, 400);
      }
    }

    // ===== /api/match-event (NEW) — расширение шлёт идущий матч =====
    // Auth: link_token в теле (связывает с пользователем бота).
    // Сохраняем матч в KV pending_match:{link_token} (массив, дедуп по match_id).
    if (url.pathname === '/api/match-event' && request.method === 'POST') {
      let body;
      try {
        body = await request.json();
      } catch {
        return jsonResp({ error: 'bad_request' }, 400);
      }
      const linkToken = body && body.link_token;
      const match = body && body.match;
      if (!linkToken || !match || !match.match_id) {
        return jsonResp({ error: 'bad_request', message: 'link_token and match.match_id required' }, 400);
      }
      const key = 'pending_match:' + linkToken;
      let arr = [];
      try {
        const raw = await env.NICKS_KV.get(key);
        if (raw) arr = JSON.parse(raw) || [];
      } catch {}
      // Дедуп: если матч с этим match_id уже в очереди — не добавляем
      if (!arr.some(function(m) { return m.match_id === match.match_id; })) {
        arr.push(match);
        await env.NICKS_KV.put(key, JSON.stringify(arr));
      }
      return jsonResp({ ok: true, queued: arr.length });
    }

    // ===== /api/pending-matches (NEW) — бот забирает матчи для обработки =====
    // Auth: X-Auth-Secret. Query: ?link_token=... (получить) или ?link_token=...&match_id=... (удалить).
    if (url.pathname === '/api/pending-matches') {
      if (request.headers.get('X-Auth-Secret') !== env.AUTH_SECRET) {
        return jsonResp({ error: 'unauthorized' }, 403);
      }
      const linkToken = url.searchParams.get('link_token');
      if (!linkToken) {
        return jsonResp({ error: 'bad_request', message: 'link_token query required' }, 400);
      }
      const key = 'pending_match:' + linkToken;

      if (request.method === 'GET') {
        const raw = await env.NICKS_KV.get(key);
        const arr = raw ? (JSON.parse(raw) || []) : [];
        return jsonResp({ matches: arr });
      }

      if (request.method === 'DELETE') {
        const matchId = url.searchParams.get('match_id');
        let raw = await env.NICKS_KV.get(key);
        let arr = raw ? (JSON.parse(raw) || []) : [];
        if (matchId) {
          arr = arr.filter(function(m) { return m.match_id !== matchId; });
          await env.NICKS_KV.put(key, JSON.stringify(arr));
        } else {
          // без match_id — очищаем всю очередь для этого токена
          await env.NICKS_KV.delete(key);
          arr = [];
        }
        return jsonResp({ ok: true, remaining: arr.length });
      }

      return jsonResp({ error: 'method_not_allowed' }, 405);
    }

    // ===== /api/scrape-data (NEW) — расширенная статистика из расширения =====
    // Auth: link_token в теле (POST) или X-Auth-Secret (GET).
    // KV key: scrape:{link_token}:{type}, TTL 3600s (1 час).
    if (url.pathname === '/api/scrape-data') {
      const linkToken = url.searchParams.get('link_token');
      const type = url.searchParams.get('type') || 'advanced';
      if (!linkToken) {
        return jsonResp({ error: 'bad_request', message: 'link_token query required' }, 400);
      }
      const key = 'scrape:' + linkToken + ':' + type;

      if (request.method === 'POST') {
        let body;
        try { body = await request.json(); } catch { return jsonResp({ error: 'bad_request' }, 400); }
        const lt = body && body.link_token;
        const payload = body && body.payload;
        if (!lt || !payload) {
          return jsonResp({ error: 'bad_request', message: 'link_token and payload required' }, 400);
        }
        const k = 'scrape:' + lt + ':' + (body.type || 'advanced');
        // TTL 3600s — данные свежие, пока страница открыта; устареют — AI скажет открыть профиль.
        await env.NICKS_KV.put(k, JSON.stringify({ payload, timestamp: Math.floor(Date.now()/1000) }), { expirationTtl: 3600 });
        return jsonResp({ ok: true });
      }

      if (request.method === 'GET') {
        if (request.headers.get('X-Auth-Secret') !== env.AUTH_SECRET) {
          return jsonResp({ error: 'unauthorized' }, 403);
        }
        const raw = await env.NICKS_KV.get(key);
        if (!raw) return jsonResp({ error: 'no_data', message: 'Скрап-данные отсутствуют. Попросите пользователя открыть профиль на faceit.com.' }, 404);
        return jsonResp(JSON.parse(raw));
      }

      return jsonResp({ error: 'method_not_allowed' }, 405);
    }

    // ===== /api/verify-link (NEW) — расширение проверяет токен привязки =====
    // Расширение шлёт link_token → Worker находит user_id/nickname по
    // обратному индексу verify:{link_token}. Кладёт pending verify-уведомление
    // в KV verify_pending:{link_token} → бот поллит и шлёт «успешно привязано».
    if (url.pathname === '/api/verify-link' && request.method === 'POST') {
      let body;
      try { body = await request.json(); } catch { return jsonResp({ error: 'bad_request' }, 400); }
      const linkToken = body && body.link_token;
      if (!linkToken) {
        return jsonResp({ error: 'bad_request', message: 'link_token required' }, 400);
      }
      const raw = await env.NICKS_KV.get('verify:' + String(linkToken));
      if (!raw) {
        return jsonResp({ error: 'not_found', message: 'Токен не найден. Получи новый через /facelogin.' }, 404);
      }
      let info;
      try { info = JSON.parse(raw); } catch { info = {}; }
      // Pending-уведомление для бота
      await env.NICKS_KV.put('verify_pending:' + String(linkToken),
        JSON.stringify({ user_id: info.user_id, nickname: info.nickname, tg_nickname: info.tg_nickname, ts: Math.floor(Date.now()/1000) }),
        { expirationTtl: 600 });
      return jsonResp({ ok: true, nickname: info.nickname || '', tg_nickname: info.tg_nickname || '' });
    }

    // ===== /api/extension-profile (NEW) — профиль для расширения =====
    if (url.pathname === '/api/extension-profile' && request.method === 'GET') {
      const linkToken = url.searchParams.get('link_token');
      if (!linkToken) {
        return jsonResp({ error: 'bad_request', message: 'link_token required' }, 400);
      }
      const raw = await env.NICKS_KV.get('verify:' + String(linkToken));
      if (!raw) {
        return jsonResp({ error: 'not_found' }, 404);
      }
      let info;
      try { info = JSON.parse(raw); } catch { return jsonResp({ error: 'invalid_data' }, 500); }

      const nickname = info.nickname || '';
      if (!nickname) {
        return jsonResp({ error: 'no_nickname' }, 404);
      }

      // Получаем профиль с Faceit
      const playerData = await getFaceitProfile(nickname, env.FACEIT_TOKEN);
      if (!playerData) {
        return jsonResp({ error: 'player_not_found' }, 404);
      }

      return jsonResp({
        nickname: nickname,
        avatar: playerData.avatar || '',
        country: (playerData.country || '').toUpperCase(),
        tg_nickname: info.tg_nickname || ''
      });
    }

    // ===== /api/verify-pending (NEW) — бот забирает pending verify-уведомления =====
    if (url.pathname === '/api/verify-pending') {
      if (request.headers.get('X-Auth-Secret') !== env.AUTH_SECRET) {
        return jsonResp({ error: 'unauthorized' }, 403);
      }
      if (request.method === 'GET') {
        const linkToken = url.searchParams.get('link_token');
        if (!linkToken) return jsonResp({ error: 'bad_request' }, 400);
        const raw = await env.NICKS_KV.get('verify_pending:' + String(linkToken));
        return jsonResp(raw ? JSON.parse(raw) : { empty: true });
      }
      if (request.method === 'DELETE') {
        const linkToken = url.searchParams.get('link_token');
        if (linkToken) await env.NICKS_KV.delete('verify_pending:' + String(linkToken));
        return jsonResp({ ok: true });
      }
      return jsonResp({ error: 'method_not_allowed' }, 405);
    }

    // ===== /api/analyze-player (NEW) — анализ чужого игрока =====
    // Расширение шлёт {link_token, nickname} → Worker проверяет токен,
    // находит активный матч игрока, отправляет в бот для ИИ-анализа.
    if (url.pathname === '/api/analyze-player' && request.method === 'POST') {
      let body;
      try { body = await request.json(); } catch { return jsonResp({ error: 'bad_request' }, 400); }
      const linkToken = body && body.link_token;
      const targetNickname = body && body.nickname;

      if (!linkToken || !targetNickname) {
        return jsonResp({ error: 'bad_request', message: 'link_token и nickname обязательны' }, 400);
      }

      // Проверяем что link_token валидный (существует в БД)
      const verifyRaw = await env.NICKS_KV.get('verify:' + String(linkToken));
      if (!verifyRaw) {
        return jsonResp({ error: 'invalid_token', message: 'Токен не найден. Привяжи расширение через /facelogin' }, 403);
      }

      let verifyInfo;
      try { verifyInfo = JSON.parse(verifyRaw); } catch { verifyInfo = {}; }
      const userId = verifyInfo.user_id;
      if (!userId) {
        return jsonResp({ error: 'invalid_token' }, 403);
      }

      // Сохраняем запрос на анализ в KV → бот заберёт и обработает
      const requestId = 'analyze_request:' + linkToken + ':' + Date.now();
      await env.NICKS_KV.put(requestId, JSON.stringify({
        user_id: userId,
        target_nickname: targetNickname,
        faceit_session_token: body.faceit_session_token || null,
        ts: Math.floor(Date.now() / 1000)
      }), { expirationTtl: 600 }); // 10 минут TTL

      return jsonResp({ ok: true, message: 'Запрос отправлен в бот. Результат придёт в Telegram.' });
    }

    // ===== /api/kv-list (NEW) — список ключей с префиксом (для бота) =====
    if (url.pathname === '/api/kv-list' && request.method === 'GET') {
      if (request.headers.get('X-Auth-Secret') !== env.AUTH_SECRET) {
        return jsonResp({ error: 'unauthorized' }, 403);
      }
      const prefix = url.searchParams.get('prefix') || '';
      try {
        const list = await env.NICKS_KV.list({ prefix: prefix });
        return jsonResp({ keys: list.keys.map(k => k.name) });
      } catch (e) {
        return jsonResp({ error: 'list_failed', message: String(e) }, 500);
      }
    }

    // ===== /api/kv-get (NEW) — получить значение по ключу (для бота) =====
    if (url.pathname === '/api/kv-get' && request.method === 'GET') {
      if (request.headers.get('X-Auth-Secret') !== env.AUTH_SECRET) {
        return jsonResp({ error: 'unauthorized' }, 403);
      }
      const key = url.searchParams.get('key');
      if (!key) return jsonResp({ error: 'bad_request' }, 400);
      const value = await env.NICKS_KV.get(key);
      if (!value) return jsonResp({ error: 'not_found' }, 404);
      try {
        return jsonResp(JSON.parse(value));
      } catch {
        return jsonResp({ value: value });
      }
    }

    // ===== /api/kv-delete (NEW) — удалить ключ (для бота) =====
    if (url.pathname === '/api/kv-delete' && request.method === 'DELETE') {
      if (request.headers.get('X-Auth-Secret') !== env.AUTH_SECRET) {
        return jsonResp({ error: 'unauthorized' }, 403);
      }
      const key = url.searchParams.get('key');
      if (!key) return jsonResp({ error: 'bad_request' }, 400);
      await env.NICKS_KV.delete(key);
      return jsonResp({ ok: true });
    }

    return jsonResp({ error: 'not_found' }, 404);
  },
};