"use strict";

const $view = document.getElementById("view");
const $banner = document.getElementById("banner");
const $dialog = document.getElementById("issue-dialog");
const $dialogBody = document.getElementById("issue-dialog-body");

const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.json();
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const coverUrl = (code) => "/api/cover?v=3&code=" + encodeURIComponent(code);
const pubLink = (code) => "#/testata/" + encodeURIComponent(code);
const pct = (a, b) => (b ? Math.round((a / b) * 1000) / 10 : 0);

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2200);
}

function formatDate(d) {
  if (!d) return "";
  const months = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
  const [y, m, g] = d.split("-");
  if (!m) return y;
  return [g ? String(+g) : null, months[+m - 1], y].filter(Boolean).join(" ");
}

// ---------- Stato dell'importazione ----------
let statusTimer = null;
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    if (s.import.running) {
      $banner.hidden = false;
      $banner.className = "banner";
      $banner.textContent = `Sto aggiornando i dati da Inducks… ${s.import.step || ""}`;
      clearTimeout(statusTimer);
      statusTimer = setTimeout(async () => {
        await refreshStatus();
      }, 3000);
      window.__wasImporting = true;
    } else {
      if (window.__wasImporting) {
        window.__wasImporting = false;
        route();
      }
      if (!s.issues && !s.last_error) {
        clearTimeout(statusTimer);
        statusTimer = setTimeout(refreshStatus, 5000);
      }
      if (!s.issues && s.last_error) {
        $banner.hidden = false;
        $banner.className = "banner error";
        $banner.innerHTML = `Non sono riuscito a scaricare i dati da Inducks: ${esc(s.last_error)}. Vedi <a href="#/impostazioni">Impostazioni</a>.`;
      } else {
        $banner.hidden = true;
      }
    }
    return s;
  } catch (e) {
    return null;
  }
}

// ---------- Viste ----------
async function viewHome() {
  const [pubs, stats, status] = await Promise.all([api("/api/publications?followed=true"), api("/api/stats"), api("/api/status")]);
  if (!status.issues) {
    $view.innerHTML = `
      <h1>Benvenuto!</h1>
      <div class="balloon">Sto preparando l'archivio dei fumetti italiani da Inducks. La prima volta serve qualche minuto:
      questa pagina si aggiorna da sola quando ho finito.</div>`;
    return;
  }
  const tiles = pubs.map((p) => `
    <a class="pub-tile" href="${pubLink(p.code)}">
      <img loading="lazy" src="${p.sample_issue ? coverUrl(p.sample_issue) : "/api/cover?code="}" alt="">
      <div class="info">
        <div class="t">${esc(p.title)}</div>
        <div class="progress" title="${pct(p.read_count, p.issue_count)}%"><div style="width:${pct(p.read_count, p.issue_count)}%"></div></div>
        <div class="c">${p.read_count} letti su ${p.issue_count}</div>
      </div>
    </a>`).join("");
  const recent = stats.recent.length ? `
    <h2 style="margin-top:36px">Letti di recente</h2>
    <div class="grid">${stats.recent.map((i) => cardHtml(i, true)).join("")}</div>` : "";
  $view.innerHTML = `
    <h1>Le mie testate</h1>
    <div class="balloon">Hai letto <b>${stats.total_read}</b> fumetti. Tocca una copertina per segnarla come letta,
    in qualsiasi ordine. Aggiungi altre testate da <a href="#/testate">Tutte le testate</a>.</div>
    ${tiles ? `<div class="shelf">${tiles}</div>` : `<p class="empty">Non segui ancora nessuna testata. <a href="#/testate">Scegline qualcuna</a>.</p>`}
    ${recent}`;
  bindCards($view, stats.recent);
}

async function viewCatalog(q = "") {
  $view.innerHTML = `
    <h1>Tutte le testate</h1>
    <div class="toolbar">
      <input type="search" class="wide" id="pub-q" placeholder="Cerca: Almanacco, Classici, Paperinik…" value="${esc(q)}">
    </div>
    <div id="pub-results"></div>`;
  const $q = document.getElementById("pub-q");
  const $res = document.getElementById("pub-results");
  let timer;
  const load = async () => {
    const pubs = await api("/api/publications?q=" + encodeURIComponent($q.value.trim()));
    if (!pubs.length) {
      $res.innerHTML = `<p class="empty">Nessuna testata trovata.</p>`;
      return;
    }
    $res.innerHTML = `<div class="pub-list">${pubs.map((p) => `
      <div class="pub-row">
        <button class="star ${p.followed ? "on" : ""}" data-code="${esc(p.code)}" title="${p.followed ? "Smetti di seguire" : "Segui"}" aria-pressed="${p.followed}">&#9733;</button>
        <a href="${pubLink(p.code)}">${esc(p.title)}<small>${esc(p.code)} · ${p.issue_count} numeri${p.read_count ? ` · ${p.read_count} letti` : ""}</small></a>
      </div>`).join("")}</div>`;
  };
  $q.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(load, 250);
  });
  $res.addEventListener("click", async (e) => {
    const b = e.target.closest(".star");
    if (!b) return;
    const on = !b.classList.contains("on");
    await api("/api/follow", { method: "POST", body: { pubcode: b.dataset.code, follow: on } });
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", on);
    toast(on ? "Testata aggiunta alle tue" : "Testata rimossa dalle tue");
  });
  await load();
  $q.focus();
}

function cardHtml(i, showPub = false) {
  const label = showPub && i.pubtitle ? `<div class="sub">${esc(i.pubtitle)}</div>` : "";
  return `
    <div class="card ${i.read ? "read" : "unread"}" data-code="${esc(i.issuecode)}">
      <button class="cover" title="${i.read ? "Segna come da leggere" : "Segna come letto"}" aria-pressed="${i.read}">
        <img loading="lazy" src="${coverUrl(i.issuecode)}" alt="Copertina ${esc(i.number)}">
      </button>
      <span class="stamp">Letto!</span>
      <button class="more" title="Dettagli" aria-label="Dettagli">i</button>
      ${label}
      <div class="num">n. ${esc(i.number)}</div>
      <div class="sub">${esc(formatDate(i.date))}</div>
    </div>`;
}

// Collega click su copertine e dettagli. `items` è la lista degli oggetti numero.
function bindCards(root, items, onChange) {
  const byCode = new Map(items.map((i) => [i.issuecode, i]));
  root.addEventListener("click", async (e) => {
    const card = e.target.closest(".card");
    if (!card) return;
    const item = byCode.get(card.dataset.code);
    if (!item) return;
    if (e.target.closest(".more")) {
      openDetail(item, () => updateCard(card, item, onChange));
      return;
    }
    if (e.target.closest(".cover")) {
      await toggleRead(item);
      updateCard(card, item, onChange);
    }
  });
}

async function toggleRead(item, value = !item.read) {
  await api("/api/read", { method: "POST", body: { issuecodes: [item.issuecode], read: value } });
  item.read = value;
}

function updateCard(card, item, onChange) {
  card.classList.toggle("read", item.read);
  card.classList.toggle("unread", !item.read);
  const btn = card.querySelector(".cover");
  btn.setAttribute("aria-pressed", item.read);
  btn.title = item.read ? "Segna come da leggere" : "Segna come letto";
  onChange && onChange(item);
}

function openDetail(item, onToggle) {
  const render = () => {
    $dialogBody.innerHTML = `
      <div class="detail">
        <img src="${coverUrl(item.issuecode)}" alt="">
        <div class="info">
          <h2>${esc(item.pubtitle || "")} n. ${esc(item.number)}</h2>
          <dl>
            ${item.title ? `<dt>Titolo</dt><dd>${esc(item.title)}</dd>` : ""}
            ${item.date ? `<dt>Uscita</dt><dd>${esc(formatDate(item.date))}</dd>` : ""}
            <dt>Codice</dt><dd>${esc(item.issuecode)}</dd>
            <dt>Stato</dt><dd>${item.read ? "Letto ✔" : "Da leggere"}</dd>
          </dl>
          <div><button class="btn ${item.read ? "white" : "red"}" id="dlg-toggle">${item.read ? "Segna da leggere" : "Segna come letto"}</button></div>
          <div><a class="btn blue" href="${esc(item.inducks_url)}" target="_blank" rel="noopener">Indice storie su Inducks</a></div>
        </div>
      </div>`;
    document.getElementById("dlg-toggle").onclick = async () => {
      await toggleRead(item);
      onToggle && onToggle();
      render();
    };
  };
  render();
  $dialog.showModal();
}

async function viewPublication(code, focusNumber) {
  $view.innerHTML = `<p>Carico…</p>`;
  const pub = await api("/api/publication?code=" + encodeURIComponent(code));
  pub.issues.forEach((i) => (i.pubtitle = pub.title));
  let filter = "all";
  let readCount = pub.read_count;

  $view.innerHTML = `
    <div class="pub-head">
      <h1>${esc(pub.title)}</h1>
      <div class="meter">
        <div class="label" id="meter-label"></div>
        <div class="progress"><div id="meter-bar"></div></div>
      </div>
      <button class="btn ${pub.followed ? "white" : ""}" id="follow-btn"></button>
    </div>
    <div class="toolbar">
      <div class="segmented" role="group" aria-label="Filtro">
        <button data-f="all" class="on">Tutti</button><button data-f="read">Letti</button><button data-f="unread">Da leggere</button>
      </div>
      <form class="group" id="goto-form">
        <label for="goto-n">Vai al n.</label><input type="text" id="goto-n" inputmode="numeric" placeholder="1000">
        <button class="btn" type="submit">Vai</button>
      </form>
      <details class="group"><summary>Segna più numeri</summary>
      <form class="toolbar" id="range-form" style="margin:8px 0 0">
        <label>Dal n.</label><input type="number" id="r-from" min="0" required>
        <label>al</label><input type="number" id="r-to" min="0" required>
        <button class="btn red" type="submit" data-v="1">Letti</button>
        <button class="btn white" type="submit" data-v="0">Da leggere</button>
      </form></details>
      <a class="btn blue" href="${esc(pub.inducks_url)}" target="_blank" rel="noopener">Inducks</a>
    </div>
    <div class="grid" id="grid"></div>
    <div class="sentinel" id="sentinel"></div>`;

  const $grid = document.getElementById("grid");
  const $sentinel = document.getElementById("sentinel");
  const followBtn = document.getElementById("follow-btn");
  const setFollow = () => {
    followBtn.textContent = pub.followed ? "★ La segui" : "☆ Segui testata";
    followBtn.className = "btn " + (pub.followed ? "white" : "");
  };
  setFollow();
  followBtn.onclick = async () => {
    pub.followed = !pub.followed;
    await api("/api/follow", { method: "POST", body: { pubcode: code, follow: pub.followed } });
    setFollow();
  };

  const updateMeter = () => {
    document.getElementById("meter-label").textContent = `${readCount} letti su ${pub.issue_count} (${pct(readCount, pub.issue_count)}%)`;
    document.getElementById("meter-bar").style.width = pct(readCount, pub.issue_count) + "%";
  };
  updateMeter();

  // Disegna la griglia a blocchi: Topolino ha migliaia di numeri.
  const CHUNK = 120;
  let list = [];
  let shown = 0;
  const visible = () => pub.issues.filter((i) => filter === "all" || (filter === "read" ? i.read : !i.read));
  const renderMore = (upTo) => {
    const target = Math.min(list.length, Math.max(shown + CHUNK, upTo || 0));
    if (target <= shown) return;
    $grid.insertAdjacentHTML("beforeend", list.slice(shown, target).map((i) => cardHtml(i)).join(""));
    shown = target;
  };
  const reset = () => {
    list = visible();
    shown = 0;
    $grid.innerHTML = list.length ? "" : `<p class="empty">Nessun numero qui.</p>`;
    renderMore();
  };
  new IntersectionObserver((entries) => entries[0].isIntersecting && renderMore(), { rootMargin: "800px" }).observe($sentinel);

  bindCards($grid, pub.issues, (item) => {
    readCount = pub.issues.filter((i) => i.read).length;
    updateMeter();
  });

  $view.querySelector(".segmented").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    filter = b.dataset.f;
    $view.querySelectorAll(".segmented button").forEach((x) => x.classList.toggle("on", x === b));
    reset();
  });

  const goTo = (n) => {
    n = String(n).trim().toLowerCase();
    if (!n) return;
    if (filter !== "all") {
      filter = "all";
      $view.querySelectorAll(".segmented button").forEach((x) => x.classList.toggle("on", x.dataset.f === "all"));
      reset();
    }
    const idx = list.findIndex((i) => i.number.toLowerCase() === n);
    if (idx < 0) {
      toast(`Il n. ${n} non c'è in questa testata`);
      return;
    }
    renderMore(idx + 1);
    const card = $grid.querySelector(`.card[data-code="${CSS.escape(list[idx].issuecode)}"]`);
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.remove("flash");
    void card.offsetWidth;
    card.classList.add("flash");
  };
  document.getElementById("goto-form").addEventListener("submit", (e) => {
    e.preventDefault();
    goTo(document.getElementById("goto-n").value);
  });

  document.getElementById("range-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const read = e.submitter?.dataset.v !== "0";
    const start = +document.getElementById("r-from").value;
    const end = +document.getElementById("r-to").value;
    const lo = Math.min(start, end);
    const hi = Math.max(start, end);
    if (!confirm(`Segno ${read ? "come letti" : "come da leggere"} i numeri dal ${lo} al ${hi}?`)) return;
    const r = await api("/api/read-range", { method: "POST", body: { pubcode: code, start: lo, end: hi, read } });
    pub.issues.forEach((i) => {
      const n = parseInt(i.number, 10);
      if (!isNaN(n) && n >= lo && n <= hi) i.read = read;
    });
    readCount = pub.issues.filter((i) => i.read).length;
    updateMeter();
    reset();
    toast(`${r.count} numeri aggiornati`);
  });

  reset();
  if (focusNumber) goTo(focusNumber);
}

async function viewSearch(q) {
  $view.innerHTML = `<p>Cerco…</p>`;
  const items = await api("/api/search?q=" + encodeURIComponent(q));
  $view.innerHTML = `
    <h1>Risultati per “${esc(q)}”</h1>
    ${items.length ? `<div class="grid" id="grid">${items.map((i) => cardHtml(i, true)).join("")}</div>`
      : `<div class="balloon">Non ho trovato nessun numero. Prova con il numero da solo (es. <b>1000</b>) o con la testata e il numero (es. <b>almanacco 12</b>).</div>`}`;
  if (items.length) bindCards(document.getElementById("grid"), items);
}

async function viewSettings() {
  const s = await api("/api/status");
  $view.innerHTML = `
    <h1>Impostazioni</h1>
    <div class="settings">
      <section>
        <h2>Dati da Inducks</h2>
        <p>${s.publications} testate italiane, ${s.issues} numeri, ${s.reads} segnati come letti.</p>
        <p>Ultimo aggiornamento: <b>${s.last_import ? new Date(s.last_import).toLocaleString("it-IT") : "mai"}</b>
        ${s.last_import_stats ? `(${esc(s.last_import_stats)})` : ""}</p>
        ${s.last_error ? `<p style="color:var(--red)"><b>Ultimo errore:</b> ${esc(s.last_error)}<br>
          Se il download automatico non funziona, scarica a mano i file <code>inducks_publication.isv</code>,
          <code>inducks_issue.isv</code>, <code>inducks_entry.isv</code> e <code>inducks_entryurl.isv</code> da
          <a href="${esc(s.isv_url)}" target="_blank" rel="noopener">${esc(s.isv_url)}</a>, mettili nella cartella
          <code>data/isv</code> e premi “Rileggi i file”.</p>` : ""}
        <button class="btn red" id="upd" ${s.import.running ? "disabled" : ""}>Scarica di nuovo da Inducks</button>
        <button class="btn white" id="reimport" ${s.import.running ? "disabled" : ""}>Rileggi i file</button>
        <p><small>Le tue letture non vengono mai toccate dagli aggiornamenti.</small></p>
      </section>
      <section>
        <h2>Backup delle letture</h2>
        <p>Salva un file con tutti i numeri che hai letto, oppure ripristinalo.</p>
        <a class="btn blue" href="/api/backup">Scarica backup</a>
        <label class="btn white">Ripristina backup<input type="file" id="restore" accept="application/json" hidden></label>
      </section>
    </div>`;
  const start = async (force) => {
    await api("/api/update", { method: "POST", body: { force } });
    toast("Aggiornamento avviato");
    setTimeout(() => {
      refreshStatus();
      viewSettings();
    }, 500);
  };
  document.getElementById("upd").onclick = () => start(true);
  document.getElementById("reimport").onclick = () => start(false);
  document.getElementById("restore").onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      const r = await api("/api/restore", { method: "POST", body: { reads: data.reads || [], followed: data.followed || [] } });
      toast(`Ripristinati ${r.reads} letti`);
      viewSettings();
    } catch (err) {
      alert("File di backup non valido: " + err.message);
    }
  };
}

// ---------- Router ----------
async function route() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [name, ...rest] = hash.split("/");
  const arg = decodeURIComponent(rest.join("/"));
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === (name || "home")));
  if ($dialog.open) $dialog.close();
  window.scrollTo(0, 0);
  try {
    if (name === "testate") await viewCatalog();
    else if (name === "testata") {
      const [code, num] = arg.split("#n=");
      await viewPublication(code, num);
    } else if (name === "cerca") await viewSearch(arg);
    else if (name === "impostazioni") await viewSettings();
    else await viewHome();
  } catch (e) {
    $view.innerHTML = `<div class="balloon">Ops! Qualcosa è andato storto: ${esc(e.message)}</div>`;
  }
}

document.getElementById("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = document.getElementById("search-input").value.trim();
  if (q) location.hash = "#/cerca/" + encodeURIComponent(q);
});

window.addEventListener("hashchange", route);
refreshStatus().then(route);
