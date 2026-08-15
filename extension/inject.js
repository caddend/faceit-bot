// Inject-скрипт (main world). Перехватывает fetch/XHR к api.faceit.com:
//  - /match/v2/matches → идущий матч (составы команд)
//  - любые ответы со статистикой (Rating 3.0, swing, elo-история) → scrape-данные

(function () {
  const MATCH_RE = /api\.faceit\.com\/match\/v2\/matches/;
  // Паттерны ответов со статистикой, которых нет в публичном Data API v4.
  const STATS_RES = [
    /api\.faceit\.com\/stats\//,            // stats/v1/...
    /api\.faceit\.com\/match\/v2\/.*\/rating/, // rating матча
    /api\.faceit\.com\/players\/.*\/elo/,      // elo-история
  ];

  function normalizeMatch(raw) {
    if (!raw) return null;
    let item = null;
    if (Array.isArray(raw)) {
      item = raw[0];
    } else if (raw.payload && Array.isArray(raw.payload)) {
      item = raw.payload[0];
    } else if (raw.payload && typeof raw.payload === "object") {
      item = raw.payload;
    } else if (raw.id || raw.match_id) {
      item = raw;
    }
    if (!item) return null;
    const status = (item.status || "").toLowerCase();
    if (status === "finished" || status === "cancelled" || status === "aborted") return null;

    const matchId = item.id || item.match_id || item.matchId || "";
    if (!matchId) return null;

    const teamsRaw = item.teams || item.factions || {};
    const teams = {};
    let i = 0;
    const entries = (teamsRaw && typeof teamsRaw === "object") ? Object.entries(teamsRaw) : [];
    for (const [key, teamData] of entries) {
      i++;
      const factionKey = "faction" + i;
      const playersRaw = teamData.players || teamData.roster || [];
      const players = (playersRaw || []).map(function (p) {
        return {
          player_id: p.id || p.player_id || p.playerId || "",
          nickname: p.nickname || p.name || "?",
          skill_level: p.skill_level || p.skillLevel || p.game_skill_level || "?",
        };
      });
      teams[factionKey] = {
        nickname: teamData.nickname || ("team" + i),
        players: players,
      };
    }

    return {
      match_id: matchId,
      status: item.status || "ongoing",
      started_at: item.started_at || item.startedAt,
      teams: teams,
    };
  }

  function sendMatch(match) {
    if (!match) return;
    window.postMessage({ __faceit_bot: true, match }, "*");
  }

  // Извлекаем интересующие поля из произвольного ответа статистики.
  // Глубокий поиск по ключам — чтобы не зависеть от точной структуры.
  function extractStats(data) {
    if (!data) return null;
    const out = {};

    function walk(obj) {
      if (!obj || typeof obj !== "object") return;
      for (const [k, v] of Object.entries(obj)) {
        const kl = k.toLowerCase();
        if (kl.includes("rating") && (kl.includes("3") || kl.includes("faceit"))) {
          if (typeof v === "number" || (typeof v === "string" && v)) out.rating_3_0 = v;
        }
        if (kl === "swing" || (kl.includes("swing") && !kl.includes("ing"))) {
          if (typeof v === "number" || (typeof v === "string" && v)) out.swing = v;
        }
        // elo-история: массив точек {elo, ...} или {value, ts}
        if ((kl === "elo" || kl === "faceit_elo") && Array.isArray(v)) {
          out.elo_history = v.map(function (p) {
            return (p && (p.elo || p.value || p.Elo)) || null;
          }).filter(function (x) { return x !== null; });
        }
        if (v && typeof v === "object") walk(v);
      }
    }
    walk(data);

    if (!out.rating_3_0 && !out.swing && !out.elo_history) return null;
    out.timestamp = Date.now();
    return out;
  }

  function sendStats(payload) {
    if (!payload) return;
    window.postMessage({ __faceit_bot_stats: true, type: "advanced", payload }, "*");
  }

  function handleResponse(url, body) {
    if (!body) return;
    try {
      const data = typeof body === "string" ? JSON.parse(body) : body;
      if (MATCH_RE.test(url)) {
        sendMatch(normalizeMatch(data));
      }
      // Скрап статистики: если в ответе есть нужные поля
      for (const re of STATS_RES) {
        if (re.test(url)) {
          sendStats(extractStats(data));
          break;
        }
      }
    } catch (e) {}
  }

  function shouldIntercept(urlStr) {
    if (MATCH_RE.test(urlStr)) return true;
    for (const re of STATS_RES) { if (re.test(urlStr)) return true; }
    return false;
  }

  // --- fetch ---
  const origFetch = window.fetch;
  window.fetch = function () {
    const url = arguments[0];
    const urlStr = typeof url === "string" ? url : (url && url.url) || "";
    const p = origFetch.apply(this, arguments);
    if (shouldIntercept(urlStr)) {
      p.then((resp) => resp.clone().text().then((t) => handleResponse(urlStr, t))).catch(() => {});
    }
    return p;
  };

  // --- XHR ---
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__fb_url = url;
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    const self = this;
    const url = this.__fb_url || "";
    if (shouldIntercept(url)) {
      this.addEventListener("load", function () {
        try { handleResponse(url, self.responseText); } catch (e) {}
      });
    }
    return origSend.apply(this, arguments);
  };
})();
