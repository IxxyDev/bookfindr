const state = {
  publishers: [],
  publisherMap: {},
  books: [],
  limit: 20,
  offset: 0,
  loading: false,
  hasMore: true,
  controller: null,
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
  // "Load more" waits for the page in flight; a new query replaces it, so the latest one wins
  if (state.loading && !reset) return;
  if (state.controller) state.controller.abort();
  const controller = new AbortController();
  state.controller = controller;
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
    const res = await fetch("/books?" + params.toString(), { signal: controller.signal });
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
    // A full last page used to show "load more" that then loaded nothing
    const total = Number.parseInt(totalCount ?? "", 10);
    state.hasMore = Number.isNaN(total) ? data.length === state.limit : state.offset < total;
    loadMoreBtn.style.display = state.hasMore ? "inline-flex" : "none";
    statusEl.textContent = state.books.length ? `${state.books.length} книг` : "Ничего не найдено";

    if (totalEl && totalCount) {
      totalEl.textContent = `Показано ${state.books.length} из ${totalCount}`;
    } else if (totalEl) {
      totalEl.textContent = "";
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    console.error(err);
    statusEl.textContent = "Ошибка загрузки";
  } finally {
    if (state.controller === controller) {
      state.controller = null;
      state.loading = false;
    }
  }
}

// Builds an element; string children become text nodes, so source data is never parsed as HTML.
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([name, value]) => {
    if (value !== null && value !== undefined) node.setAttribute(name, value);
  });
  children.forEach((child) => {
    if (child !== null && child !== undefined) node.append(child);
  });
  return node;
}

// Only http(s) links and images: a source could hand us a javascript: URL.
function safeUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(value, window.location.href);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function highlightTerms(text, query) {
  const fragment = document.createDocumentFragment();
  const terms = (query || "").trim().split(/\s+/).filter(Boolean);
  if (!text || !terms.length) {
    fragment.append(text || "");
    return fragment;
  }
  const pattern = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  // A capturing group keeps the matches in split(): they land on odd indexes
  text.split(new RegExp(`(${pattern})`, "gi")).forEach((part, i) => {
    fragment.append(i % 2 === 1 ? el("mark", {}, part) : part);
  });
  return fragment;
}

function buildBadges(item) {
  return el(
    "div",
    { class: "badges" },
    el("span", { class: "badge" }, state.publisherMap[item.publisher_id] || String(item.publisher_id)),
    el("span", { class: "badge subtle" }, item.language || "—"),
    el("span", { class: "badge subtle" }, item.published_date || "—")
  );
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
    const titleText = item.title + (item.subtitle ? " — " + item.subtitle : "");
    const descText = item.description ? truncate(item.description, 260) : "Без описания";
    const coverUrl = safeUrl(item.cover_url);
    const detailBtn = el("button", { class: "ghost" }, "Подробнее");
    detailBtn.addEventListener("click", () => openDetail(item.id));
    const card = el(
      "article",
      { class: "book" },
      el(
        "div",
        { class: "cover" },
        coverUrl ? el("img", { src: coverUrl, alt: "" }) : el("div", { class: "placeholder" }, "No cover")
      ),
      el(
        "div",
        { class: "meta" },
        el("div", { class: "title-row" }, el("h3", {}, highlightTerms(titleText, queryVal)), detailBtn),
        el("div", { class: "authors muted" }, (item.authors || []).join(", ") || "—"),
        buildBadges(item),
        el("p", { class: "desc" }, highlightTerms(descText, queryVal)),
        el("div", { class: "links muted" }, ...buildLinks(item))
      )
    );
    booksEl.appendChild(card);
  });
}

function buildLinks(item) {
  const links = [];
  const infoUrl = safeUrl(item.info_url);
  if (infoUrl) {
    links.push(el("a", { href: infoUrl, target: "_blank", rel: "noopener noreferrer" }, "Источник"));
  }
  if (item.isbn_13) links.push(`ISBN13: ${item.isbn_13}`);
  if (item.isbn_10) links.push(`ISBN10: ${item.isbn_10}`);
  return links.flatMap((link, i) => (i ? [" · ", link] : [link]));
}

function truncate(text, limit) {
  if (!text) return "";
  return text.length > limit ? text.slice(0, limit) + "…" : text;
}

function infoCell(label, value) {
  return el("div", {}, el("strong", {}, label), el("br"), value);
}

async function openDetail(bookId) {
  modal.classList.add("open");
  modalContent.innerHTML = "<p class='muted'>Загружаем…</p>";
  try {
    const res = await fetch(`/books/${encodeURIComponent(bookId)}`);
    if (!res.ok) throw new Error("Failed to load book");
    const book = await res.json();
    const coverUrl = safeUrl(book.cover_url);
    const sources = (book.sources || []).map((s) =>
      el("li", {}, el("strong", {}, s.source), ` — ${s.source_key || "—"} (${s.fetched_at || ""})`)
    );
    modalContent.replaceChildren(
      el(
        "div",
        { class: "detail-head" },
        el(
          "div",
          {},
          coverUrl ? el("img", { class: "detail-cover", src: coverUrl, alt: "" }) : null,
          el("h2", {}, book.title + (book.subtitle ? " — " + book.subtitle : "")),
          el("p", { class: "muted" }, (book.authors || []).join(", ") || "—")
        ),
        buildBadges(book)
      ),
      el("p", {}, book.description || "Без описания"),
      el(
        "div",
        { class: "info-grid" },
        infoCell("ISBN13", book.isbn_13 || "—"),
        infoCell("ISBN10", book.isbn_10 || "—"),
        infoCell("Страниц", String(book.page_count || "—")),
        infoCell("Темы", (book.subjects || []).join(", ") || "—")
      ),
      el("div", { class: "sources" }, el("h4", {}, "Источники"), el("ul", {}, ...sources)),
      el("div", { class: "links muted" }, ...buildLinks(book))
    );
  } catch (err) {
    console.error(err);
    modalContent.innerHTML = "<p class='muted'>Не удалось загрузить книгу</p>";
  }
}

function closeModal() {
  modal.classList.remove("open");
}

async function waitForSyncToFinish() {
  // Poll /sync/status every 3s, up to ~15 minutes.
  for (let i = 0; i < 300; i++) {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    try {
      const res = await fetch("/sync/status");
      if (!res.ok) continue;
      const data = await res.json();
      if (!data.running) return true;
      statusEl.textContent = "Синхронизация выполняется…";
    } catch (err) {
      console.error(err);
    }
  }
  return false;
}

async function syncNow() {
  syncBtn.disabled = true;
  syncBtn.textContent = "Синхронизация…";
  try {
    const res = await fetch("/sync/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ publisher_id: publisherSelect.value || null }),
    });
    if (!res.ok && res.status !== 409) throw new Error("Sync start failed");
    statusEl.textContent = "Синхронизация запущена…";
    const finished = await waitForSyncToFinish();
    await fetchBooks(true);
    statusEl.textContent = finished ? "Синхронизация завершена" : "Синхронизация ещё идёт";
  } catch (err) {
    console.error(err);
    statusEl.textContent = "Ошибка синхронизации";
  } finally {
    syncBtn.disabled = false;
    syncBtn.textContent = "Обновить каталоги";
  }
}

document.addEventListener("DOMContentLoaded", init);
