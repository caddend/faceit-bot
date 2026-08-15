const WORKER_URL = "https://polished-mouse-4c9d.mishashlikov216.workers.dev";
const STORAGE_KEY = "faceit_bot_link_token";
const VERIFIED_KEY = "faceit_bot_verified";
const PROFILE_KEY = "faceit_bot_profile";

function $(id) { return document.getElementById(id); }

// Загружаем сохранённые данные
chrome.storage.local.get([STORAGE_KEY, VERIFIED_KEY, PROFILE_KEY], (res) => {
  const token = res[STORAGE_KEY] || "";
  const verified = res[VERIFIED_KEY] || false;
  const profile = res[PROFILE_KEY] || null;

  $("token").value = token;

  if (verified && profile) {
    showProfile(profile);
    $("status").classList.add("show");
    $("status-text").innerHTML = '<span style="color:#3ddc84">✓ Активно</span> — расширение работает';
  } else if (token) {
    $("status").classList.add("show");
    $("status-text").innerHTML = '<span style="color:#ffa500">⚠ Не проверен</span> — нажми "Сохранить"';
  }
});

function showProfile(profile) {
  const profileDiv = $("profile");
  profileDiv.classList.add("show");

  $("avatar").src = profile.avatar || "";
  $("faceit-nick").textContent = profile.faceit_nickname || "—";
  $("tg-nick").textContent = "Telegram: " + (profile.tg_nickname || "—");
  $("faceit-status").textContent = "Faceit: привязан ✓";
  $("faceit-status").style.color = "#3ddc84";
}

$("save").addEventListener("click", async () => {
  const token = $("token").value.trim();
  if (!token) {
    $("error").textContent = "Введи токен из бота";
    $("error").style.display = "block";
    $("ok").style.display = "none";
    return;
  }

  $("ok").style.display = "none";
  $("error").style.display = "none";
  $("save").disabled = true;
  $("save").textContent = "Проверка...";

  try {
    const resp = await fetch(`${WORKER_URL}/api/verify-link`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ link_token: token }),
    });
    const data = await resp.json();

    if (resp.ok && data.ok) {
      // Получаем профиль с Faceit
      const faceitResp = await fetch(`${WORKER_URL}/api/extension-profile?link_token=${token}`);
      const faceitData = await faceitResp.json();

      const profile = {
        tg_nickname: data.tg_nickname || data.nickname || "—",
        faceit_nickname: faceitData.nickname || data.nickname || "—",
        avatar: faceitData.avatar || "",
        timestamp: Date.now()
      };

      await chrome.storage.local.set({
        [STORAGE_KEY]: token,
        [VERIFIED_KEY]: true,
        [PROFILE_KEY]: profile
      });

      showProfile(profile);
      $("ok").textContent = `✓ Привязано к ${profile.faceit_nickname}. Бот пришлёт подтверждение в Telegram.`;
      $("ok").style.display = "block";
      $("status").classList.add("show");
      $("status-text").innerHTML = '<span style="color:#3ddc84">✓ Активно</span> — расширение работает';

      setTimeout(() => window.close(), 2000);
    } else {
      $("error").textContent = `Ошибка: ${data.error || "токен не найден"}`;
      $("error").style.display = "block";
    }
  } catch (e) {
    $("error").textContent = `Ошибка сети: ${e.message}`;
    $("error").style.display = "block";
  }

  $("save").disabled = false;
  $("save").textContent = "Сохранить";
});

// === Анализ чужого игрока ===
$("analyze").addEventListener("click", async () => {
  const nickname = $("player-nick").value.trim();
  if (!nickname) {
    $("analyze-error").textContent = "Введи никнейм игрока";
    $("analyze-error").style.display = "block";
    $("analyze-ok").style.display = "none";
    return;
  }

  // Проверяем что есть link_token
  const stored = await chrome.storage.local.get(STORAGE_KEY);
  const token = stored[STORAGE_KEY];
  if (!token) {
    $("analyze-error").textContent = "Сначала привяжи токен выше";
    $("analyze-error").style.display = "block";
    $("analyze-ok").style.display = "none";
    return;
  }

  $("analyze-ok").style.display = "none";
  $("analyze-error").style.display = "none";
  $("analyze").disabled = true;
  $("analyze").textContent = "Анализ...";
  $("analyze-status").classList.add("show");
  $("analyze-result").innerHTML = '<span style="color:#ffa500">⏳ Ищу матч игрока...</span>';

  try {
    // Читаем session token из cookies Faceit
    const cookies = await chrome.cookies.getAll({ domain: ".faceit.com" });
    const sessionCookie = cookies.find(c => c.name === "t");
    const sessionToken = sessionCookie ? sessionCookie.value : null;

    const resp = await fetch(`${WORKER_URL}/api/analyze-player`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        link_token: token,
        nickname,
        faceit_session_token: sessionToken
      }),
    });
    const data = await resp.json();

    if (resp.ok && data.ok) {
      $("analyze-ok").textContent = "✓ Анализ отправлен в бота";
      $("analyze-ok").style.display = "block";
      $("analyze-result").innerHTML = `<span style="color:#3ddc84">✓ Результат отправлен в Telegram</span>`;
    } else {
      $("analyze-error").textContent = data.error || "Игрок не найден или нет активного матча";
      $("analyze-error").style.display = "block";
      $("analyze-result").innerHTML = `<span style="color:#ff6b6b">✗ ${data.error || "Ошибка"}</span>`;
    }
  } catch (e) {
    $("analyze-error").textContent = `Ошибка сети: ${e.message}`;
    $("analyze-error").style.display = "block";
    $("analyze-result").innerHTML = `<span style="color:#ff6b6b">✗ Ошибка сети</span>`;
  }

  $("analyze").disabled = false;
  $("analyze").textContent = "Анализировать матч";
});
