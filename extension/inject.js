// Inject-скрипт (main world, страница). Перехватывает fetch/XHR к api.faceit.com,
// ловит ответ /match/v2/matches (идущий матч) и шлёт его content script'у.

(function () {
  const MATCH_RE = /api\.faceit\.com\/match\/v2\/matches/;

  function normalizeMatch(raw) {
    if (!raw) return null;
    // Ответ может быть массивом (payload: [...]) или одним объектом
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

    // Не интересуют завершённые/отменённые
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

  function handleResponse(url, body) {
    if (!MATCH_RE.test(url)) return;
    try {
      const data = typeof body === "string" ? JSON.parse(body) : body;
      const match = normalizeMatch(data);
      sendMatch(match);
    } catch (e) {}
  }

  // --- fetch ---
  const origFetch = window.fetch;
  window.fetch = function () {
    const url = arguments[0];
    const urlStr = typeof url === "string" ? url : (url && url.url) || "";
    const p = origFetch.apply(this, arguments);
    if (MATCH_RE.test(urlStr)) {
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
    if (MATCH_RE.test(url)) {
      this.addEventListener("load", function () {
        try {
          handleResponse(url, self.responseText);
        } catch (e) {}
      });
    }
    return origSend.apply(this, arguments);
  };
})();
