const state = {
  publishers: [],
  publisherMap: {},
  books: [],
  limit: 20,
  offset: 0,
  loading: false,
  hasMore: true,
};

const booksEl = document.getElementById("books");
const publisherSelect = document.getElementById("publisher");
const syncBtn = document.getElementById("syncBtn");
const loadMoreBtn = document.getElementById("loadMore");
const statusEl = document.getElementById("status");
const modal = document.getElementById("detailModal");
const modalContent = document.getElementById("modalBody");
const modalClose = document.getElementById("modalClose");

function debounce(fn, ms) {
  let timer;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), ms);
  };
}

function initTheme() {
  const saved = localStorage.getItem("theme");
  if (saved) {
    document.documentElement.dataset.theme = saved;
  } else {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = prefersDark ? "dark" : "light";
  }
  updateThemeToggle();
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme;
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("theme", next);
  updateThemeToggle();
}

function updateThemeToggle() {
  const btn = document.getElementById("themeToggle");
  if (!btn) return;
  const isDark = document.documentElement.dataset.theme === "dark";
  btn.textContent = isDark ? "\u2600\uFE0F Light" : "\uD83C\uDF19 Dark";
}

async function init() {
  initTheme();
  await loadPublishers();
  await fetchBooks(true);
  bindEvents();
}

function bindEvents() {
  document.getElementById("applyFilters").addEventListener("click", () => fetchBooks(true));
  document.getElementById("clearFilters").addEventListener("click", clearFilters);
  syncBtn.addEventListener("click", syncNow);
  loadMoreBtn.addEventListener("click", () => fetchBooks(false));
  modalClose.addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });

  const themeBtn = document.getElementById("themeToggle");
  if (themeBtn) themeBtn.addEventListener("click", toggleTheme);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  const filterInputs = document.querySelectorAll(".filters input, .filters select");
  filterInputs.forEach((input) => {
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") fetchBooks(true);
    });
  });

  const queryInput = document.getElementById("query");
  if (queryInput) {
    queryInput.addEventListener("input", debounce(() => fetchBooks(true), 350));
  }
}

function clearFilters() {
  ["language", "subject", "query", "date_from", "date_to"].forEach((id) => {
    document.getElementById(id).value = "";
  });
  publisherSelect.value = "";
  fetchBooks(true);
}

async function loadPublishers() {
  const res = await fetch("/publishers");
  const pubs = await res.json();
  state.publishers = pubs;
  state.publisherMap = Object.fromEntries(pubs.map((p) => [p.id, p.name]));
  publisherSelect.innerHTML = '<option value="">Все издательства</option>';
  pubs.forEach((pub) => {
    const opt = document.createElement("option");
    opt.value = pub.id;
    opt.textContent = pub.name;
    publisherSelect.appendChild(opt);
  });
}

function buildParams() {
  const params = new URLSearchParams();
  if (publisherSelect.value) params.append("publisher_id", publisherSelect.value);
  const fields = ["language", "subject", "query", "date_from", "date_to"];
  fields.forEach((field) => {
    const el = document.getElementById(field);
    if (el?.value) {
      const key = field === "query" ? "q" : field;
      params.append(key, el.value);
    }
  });
  params.append("limit", state.limit.toString());
  params.append("offset", state.offset.toString());
  return params;
}

function showSkeletons(count) {
  let html = "";
  for (let i = 0; i < count; i++) {
    html += `
      <div class="skeleton-card">
        <div class="skeleton skeleton-cover"></div>
        <div>
          <div class="skeleton skeleton-line"></div>
          <div class="skeleton skeleton-line"></div>
          <div class="skeleton skeleton-line"></div>
          <div class="skeleton skeleton-line"></div>
        </div>
      </div>`;
  }
  booksEl.innerHTML = html;
}

async function fetchBooks(reset = false) {
  if (state.loading) return;
  state.loading = true;
  statusEl.textContent = "Загружаем…";
  if (reset) {
    state.offset = 0;
    state.books = [];
    showSkeletons(4);
    state.hasMore = true;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  try {
    const params = buildParams();
    const res = await fetch("/books?" + params.toString());
    if (!res.ok) throw new Error("Failed to load");
    const data = await res.json();

    const totalCount = res.headers.get("X-Total-Count");
    const totalEl = document.getElementById("totalCount");

    if (reset) {
      state.books = data;
    } else {
      state.books = [...state.books, ...data];
    }
    renderBooks(state.books);
    state.offset += data.length;
    state.hasMore = data.length === state.limit;
    loadMoreBtn.style.display = state.hasMore ? "inline-flex" : "none";
    statusEl.textContent = state.books.length ? `${state.books.length} книг` : "Ничего не найдено";

    if (totalEl && totalCount) {
      totalEl.textContent = `Показано ${state.books.length} из ${totalCount}`;
    } else if (totalEl) {
      totalEl.textContent = "";
    }
  } catch (err) {
    console.error(err);
    statusEl.textContent = "Ошибка загрузки";
  } finally {
    state.loading = false;
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function highlightTerms(text, query) {
  if (!query || !text) return escapeHtml(text || "");
  const escaped = escapeHtml(text);
  const terms = query.trim().split(/\s+/).filter(Boolean);
  if (!terms.length) return escaped;
  const pattern = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  const regex = new RegExp(`(${pattern})`, "gi");
  return escaped.replace(regex, "<mark>$&</mark>");
}

function renderBooks(list) {
  booksEl.innerHTML = "";
  if (!list.length) {
    booksEl.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">&#128218;</div>
        <h3>Ничего не найдено</h3>
        <p>Попробуйте изменить фильтры или поисковой запрос</p>
      </div>`;
    return;
  }
  const queryVal = document.getElementById("query")?.value || "";
  list.forEach((item) => {
    const card = document.createElement("article");
    card.className = "book";
    const titleText = item.title + (item.subtitle ? " — " + item.subtitle : "");
    const descText = item.description ? truncate(item.description, 260) : "Без описания";
    card.innerHTML = `
      <div class="cover">${item.cover_url ? `<img src="${escapeHtml(item.cover_url)}" alt="">` : '<div class="placeholder">No cover</div>'}</div>
      <div class="meta">
        <div class="title-row">
          <h3>${highlightTerms(titleText, queryVal)}</h3>
          <button class="ghost" data-id="${item.id}">Подробнее</button>
        </div>
        <div class="authors muted">${escapeHtml((item.authors || []).join(", ") || "—")}</div>
        <div class="badges">
          <span class="badge">${escapeHtml(state.publisherMap[item.publisher_id] || String(item.publisher_id))}</span>
          <span class="badge subtle">${escapeHtml(item.language || "—")}</span>
          <span class="badge subtle">${escapeHtml(item.published_date || "—")}</span>
        </div>
        <p class="desc">${highlightTerms(descText, queryVal)}</p>
        <div class="links muted">${buildLinks(item)}</div>
      </div>
    `;
    card.querySelector("button[data-id]").addEventListener("click", () => openDetail(item.id));
    booksEl.appendChild(card);
  });
}

function buildLinks(item) {
  const links = [];
  if (item.info_url) links.push(`<a href="${escapeHtml(item.info_url)}" target="_blank">Источник</a>`);
  if (item.isbn_13) links.push(`ISBN13: ${escapeHtml(item.isbn_13)}`);
  if (item.isbn_10) links.push(`ISBN10: ${escapeHtml(item.isbn_10)}`);
  return links.join(" · ");
}

function truncate(text, limit) {
  if (!text) return "";
  return text.length > limit ? text.slice(0, limit) + "…" : text;
}

async function openDetail(bookId) {
  modal.classList.add("open");
  modalContent.innerHTML = "<p class='muted'>Загружаем…</p>";
  try {
    const res = await fetch(`/books/${bookId}`);
    if (!res.ok) throw new Error("Failed to load book");
    const book = await res.json();
    const coverHtml = book.cover_url
      ? `<img class="detail-cover" src="${escapeHtml(book.cover_url)}" alt="">`
      : "";
    modalContent.innerHTML = `
      <div class="detail-head">
        <div>
          ${coverHtml}
          <h2>${escapeHtml(book.title)}${book.subtitle ? " — " + escapeHtml(book.subtitle) : ""}</h2>
          <p class="muted">${escapeHtml((book.authors || []).join(", ") || "—")}</p>
        </div>
        <div class="badges">
          <span class="badge">${escapeHtml(state.publisherMap[book.publisher_id] || String(book.publisher_id))}</span>
          <span class="badge subtle">${escapeHtml(book.language || "—")}</span>
          <span class="badge subtle">${escapeHtml(book.published_date || "—")}</span>
        </div>
      </div>
      <p>${escapeHtml(book.description || "Без описания")}</p>
      <div class="info-grid">
        <div><strong>ISBN13</strong><br>${escapeHtml(book.isbn_13 || "—")}</div>
        <div><strong>ISBN10</strong><br>${escapeHtml(book.isbn_10 || "—")}</div>
        <div><strong>Страниц</strong><br>${book.page_count || "—"}</div>
        <div><strong>Темы</strong><br>${escapeHtml((book.subjects || []).join(", ") || "—")}</div>
      </div>
      <div class="sources">
        <h4>Источники</h4>
        <ul>
          ${(book.sources || [])
            .map(
              (s) =>
                `<li><strong>${escapeHtml(s.source)}</strong> — ${escapeHtml(s.source_key || "—")} (${
                  escapeHtml(s.fetched_at || "")
                })</li>`
            )
            .join("")}
        </ul>
      </div>
      <div class="links muted">${buildLinks(book)}</div>
    `;
  } catch (err) {
    console.error(err);
    modalContent.innerHTML = "<p class='muted'>Не удалось загрузить книгу</p>";
  }
}

function closeModal() {
  modal.classList.remove("open");
}

async function syncNow() {
  syncBtn.disabled = true;
  syncBtn.textContent = "Синхронизация…";
  try {
    await fetch("/sync/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ publisher_id: publisherSelect.value || null }),
    });
    fetchBooks(true);
    statusEl.textContent = "Синхронизация завершена";
  } catch (err) {
    console.error(err);
    statusEl.textContent = "Ошибка синхронизации";
  } finally {
    syncBtn.disabled = false;
    syncBtn.textContent = "Обновить каталоги";
  }
}

document.addEventListener("DOMContentLoaded", init);
