/* 임대주택 평면 보드. 주소의 ?b=<보드 이름> 으로 data/boards/<보드 이름>.json 을 읽어 그린다.
   평면도는 data/plans.json 에 받아 둔 사본이 있으면 그것을, 없으면 원본 주소를 그대로 쓴다. */
(async () => {
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const won = (n) => (n == null ? "-" : Math.round(n).toLocaleString("ko-KR"));
  const man = (n) => {
    if (n == null) return "-";
    const m = Math.round(n / 10000);
    if (m < 10000) return m.toLocaleString("ko-KR") + "만";
    return (Math.floor(m / 10000) + "억 " + (m % 10000 ? (m % 10000).toLocaleString("ko-KR") + "만" : "")).trim();
  };
  const py = (a) => (a / 3.3058).toFixed(1);
  const isImg = (u) => /\.(jpe?g|png|gif|webp|bmp|tiff?)$/i.test((u || "").split(/[?#]/)[0]);
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
  const short = (name) => String(name).split(/\s*\(/)[0];

  const SORT = {
    unit: [["dep", "임대보증금 낮은순"], ["rent", "월 임대료 낮은순"], ["real", "실질임대료 낮은순"], ["area", "전용면적 넓은순"]],
    complex: [["dep", "임대보증금 낮은순"], ["rent", "월 임대료 낮은순"], ["area", "주거전용 넓은순"], ["vac", "공가 많은순"]],
    building: [["vac", "공가 많은순"], ["dep", "임대보증금 낮은순"], ["rent", "월 임대료 낮은순"], ["area", "전용면적 넓은순"]],
    type: [["vac", "공가 많은순"], ["dep", "임대보증금 낮은순"], ["rent", "월 임대료 낮은순"], ["area", "전용면적 넓은순"]],
  };
  const DESC = new Set(["area", "vac"]);

  const slug = (new URLSearchParams(location.search).get("b") || "").replace(/[^a-z0-9-]/gi, "");
  const get = (path) => fetch(path, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);

  /* 보드 이름이 없으면 보드 목록을 보여 준다 */
  if (!slug) {
    const idx = await get("../data/boards/index.json");
    const rows = (idx && idx.boards) || [];
    const KIND = { notice: "모집공고", spec: "조건 모음", manual: "직접 정리" };
    $("sub").textContent = "SH 임대주택의 면적·보증금·월임대료와 평면도를 보드별로 비교합니다.";
    ["tabs", "stats"].forEach((id) => ($(id).hidden = true));
    document.querySelector(".bar").hidden = true;
    $("grid").classList.add("list");
    $("grid").innerHTML = rows.length ? rows.map((b) => `<a class="card row" href="?b=${esc(b.slug)}"><div class="body">
      <div class="chips"><span class="chip ${b.closed ? "warn" : ""}">${esc(KIND[b.kind] || b.kind)}${b.closed ? " · 마감" : ""}</span><span class="chip">${esc(b.count)}건</span></div>
      <div class="nm">${esc(b.title)}</div><div class="meta">${esc(b.notice_date ? "공고일 " + b.notice_date : b.updated ? b.updated + " 기준" : "")}</div></div></a>`).join("")
      : '<p class="empty">아직 보드가 없습니다.</p>';
    return;
  }
  const [board, manifest] = await Promise.all([get(`../data/boards/${slug}.json`), get("../data/plans.json")]);
  if (!board) {
    $("grid").innerHTML = '<p class="empty">보드를 찾지 못했습니다. 주소를 확인해 주세요.</p>';
    return;
  }
  const plans = (manifest && manifest.plans) || {};

  document.title = `${board.title} | 소현리치랩`;
  $("title").textContent = board.title;
  $("sub").textContent = board.sub || "";
  $("note").textContent = board.note || "";
  if (board.source) { $("source").textContent = board.source.name; $("source").href = safeUrl(board.source.url); }
  const stamp = board.updated || (manifest && manifest.updated);
  $("updated").textContent = stamp ? `${stamp} 기준` : "";
  if (board.notice && safeUrl(board.notice.url)) {
    $("sub").insertAdjacentHTML("afterend", `<p class="sub"><a href="${esc(board.notice.url)}" target="_blank" rel="noopener">SH 공고 원문 보기 ↗</a></p>`);
  }

  let tab = board.tabs[0];
  $("tabs").innerHTML = board.tabs.map((t) => `<button class="tab" role="tab" data-id="${esc(t.id)}">${esc(t.label)} ${t.items.length}</button>`).join("");
  $("tabs").hidden = board.tabs.length < 2;

  /* 평면도 칸: 받아 둔 사본 → 원본 이미지 → 링크 순으로 쓴다 */
  function planBox(d) {
    const all = [d.plan_url, ...(d.plan_urls || [])].map(safeUrl).filter(Boolean);
    const url = all[0];
    if (!url) return '<div class="plan none"><span>평면도 없음</span></div>';
    if (!isImg(url)) return `<div class="plan none"><span>평면도 이미지 없음<br><a href="${esc(url)}" target="_blank" rel="noopener">관련 링크 열기 ↗</a></span></div>`;
    const local = plans[url];
    const srcOf = (u) => (plans[u] ? "../" + plans[u].file : u);
    const src = srcOf(url);
    const size = local ? ` width="${local.w}" height="${local.h}"` : "";
    const imgs = all.filter(isImg);
    const label = d.type ? `${d.name} ${d.type}형` : d.name;
    return `<button type="button" class="plan" data-srcs="${esc(JSON.stringify(imgs.map(srcOf)))}" data-origin="${esc(url)}" data-name="${esc(label)}">
      <img src="${esc(src)}"${size} alt="${esc(label)} 평면도" loading="lazy" referrerpolicy="no-referrer"><span class="zoom">크게 보기${imgs.length > 1 ? " · " + imgs.length + "장" : ""}</span></button>`;
  }

  function card(d) {
    const cell = (k, v) => `<div><dt>${k}</dt><dd>${v}</dd></div>`;
    const area = d.area ? `${esc(d.area)}㎡ <small>(${py(d.area)}평)</small>` : "-";
    if (tab.kind === "unit") {
      const floor = Math.floor(d.ho / 100);
      return `<article class="card">${planBox(d)}<div class="body">
        <div class="top"><div><div class="nm">${esc(d.name)}</div><div class="meta">${esc(d.gu)} · 단지코드 ${esc(d.code)}</div></div><span class="no">연번 ${esc(d.no)}</span></div>
        <div class="chips"><span class="chip">${esc(d.room)}</span><span class="chip ${d.elev === "미설치" ? "warn" : "ok"}">승강기 ${esc(d.elev)}</span><span class="chip">${esc(d.ho)}호 · ${floor}층</span></div>
        <dl>${cell("전용면적", area)}${cell("실질임대료(이자반영)", won(d.real))}${cell("임대보증금", won(d.dep))}${cell("월 임대료", won(d.rent))}${cell("전세보증금(전환)", won(d.jdep))}${cell("전세 전환 시 임대료", won(d.jrent))}</dl>
        <div class="addr">${esc(d.addr)}</div></div></article>`;
    }
    if (tab.kind === "building") {
      const range = (r, f) => (!r ? "-" : r[0] === r[1] ? f(r[0]) : `${f(r[0])} ~ ${f(r[1])}`);
      return `<article class="card">${planBox(d)}<div class="body">
        <div class="top"><div><div class="nm">${esc(d.name)}</div><div class="meta">${esc(d.gu)} · ${esc(d.supply)}</div></div><span class="no">${esc(d.units)}호</span></div>
        <div class="chips"><span class="chip ${d.vac ? "ok" : "warn"}">공가 ${esc(d.vac ?? 0)} · 예비 ${esc(d.wait ?? 0)}</span>${d.elevator ? `<span class="chip ${d.elevator === "설치" ? "ok" : "warn"}">승강기 ${esc(d.elevator)}</span>` : ""}${d.floors ? `<span class="chip">${esc(d.floors)}층</span>` : ""}${d.built ? `<span class="chip">준공 ${esc(String(d.built).slice(0, 4))}</span>` : ""}</div>
        <dl>${cell("전용면적", range(d.area_range, (v) => v + "㎡"))}${cell("기준월", esc(d.as_of || "-"))}${cell("임대보증금", range(d.dep_range, man))}${cell("월 임대료", range(d.rent_range, won))}</dl>
        <div class="addr">${esc(d.addr)}</div></div></article>`;
    }
    if (tab.kind === "type") {
      const model = safeUrl(d.model_url);
      return `<article class="card">${planBox(d)}<div class="body">
        <div class="top"><div><div class="nm">${esc(d.name)}</div><div class="meta">${esc(d.gu)} · ${esc(d.supply)}</div></div><span class="no">${esc(d.type)}형</span></div>
        <div class="chips"><span class="chip">방 ${esc(d.rooms ?? "-")}</span><span class="chip">${esc(d.households ?? "-")}세대</span><span class="chip ${d.vac ? "ok" : "warn"}">공가 ${esc(d.vac ?? 0)} · 예비 ${esc(d.wait ?? 0)}</span></div>
        <dl>${cell("전용면적", area)}${cell("기준월", esc(d.as_of || "-"))}${cell("임대보증금", d.dep ? won(d.dep) : "-")}${cell("월 임대료", d.rent ? won(d.rent) : "-")}</dl>
        <div class="addr">${esc(d.addr)}${model ? ` · <a href="${esc(model)}" target="_blank" rel="noopener">사이버 모델하우스 ↗</a>` : ""}</div></div></article>`;
    }
    return `<article class="card">${planBox(d)}<div class="body">
      <div class="top"><div><div class="nm">${esc(d.name)}</div><div class="meta">${esc(d.gu)}</div></div><span class="no">연번 ${esc(d.no)}</span></div>
      <div class="chips"><span class="chip">구조 ${esc(d.room)}</span><span class="chip">모집 ${esc(d.total)}세대</span><span class="chip ${d.vac ? "ok" : "warn"}">공가 ${esc(d.vac)} · 예비 ${esc(d.wait)}</span></div>
      <dl>${cell("주거전용", area)}${cell("합계(공가+예비)", esc(d.total) + "세대")}${cell("임대보증금", won(d.dep))}${cell("월 임대료", won(d.rent))}${cell("임대보증금(+)", won(d.dep2))}${cell("월임대료(-)", won(d.rent2))}</dl>
      </div></article>`;
  }

  function stats(list) {
    const min = (k) => list.reduce((a, b) => (b[k] < a[k] ? b : a));
    const a = min("dep"), b = min("rent");
    const s = [[list.length + "건", tab.kind === "type" ? "표시 중인 주택형" : tab.kind === "building" ? "표시 중인 건물" : "표시 중인 단지/호"], [man(a.dep), "최저 보증금 · " + short(a.name)], [won(b.rent), "최저 월 임대료 · " + short(b.name)]];
    if (tab.kind === "unit") s.push([list.filter((d) => d.elev === "전체동 설치").length + " / " + list.length, "승강기 설치 호수"]);
    else s.push([list.reduce((t, d) => t + (d.vac || 0), 0) + " / " + list.reduce((t, d) => t + (d.wait || 0), 0), "공가 / 예비 합계(세대)"]);
    $("stats").innerHTML = s.map(([v, t]) => `<div class="stat"><b>${esc(v)}</b><span>${esc(t)}</span></div>`).join("");
  }

  function render() {
    const gu = $("f-gu").value, el = $("f-el").value, k = $("f-sort").value;
    const list = tab.items.filter((d) => (!gu || d.gu === gu) && (tab.kind !== "unit" || !el || d.elev === el));
    list.sort((x, y) => (DESC.has(k) ? y[k] - x[k] : x[k] - y[k]));
    $("count").textContent = list.length + "건 표시";
    if (!list.length) {
      $("grid").innerHTML = '<p class="empty">조건에 맞는 단지가 없습니다. 필터를 바꿔 보세요.</p>';
      $("stats").innerHTML = "";
      return;
    }
    stats(list);
    $("grid").innerHTML = list.map(card).join("");
  }

  function setup() {
    const gus = [...new Set(tab.items.map((d) => d.gu))];
    $("f-gu").innerHTML = '<option value="">전체</option>' + gus.map((g) => `<option>${esc(g)}</option>`).join("");
    $("f-sort").innerHTML = (SORT[tab.kind] || SORT.complex).map(([k, l]) => `<option value="${k}">${l}</option>`).join("");
    $("l-el").hidden = tab.kind !== "unit";
    $("f-el").value = "";
    $("tabs").querySelectorAll(".tab").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.id === tab.id)));
    render();
  }

  $("tabs").addEventListener("click", (e) => {
    const b = e.target.closest(".tab");
    if (!b) return;
    tab = board.tabs.find((t) => t.id === b.dataset.id) || tab;
    setup();
  });
  ["f-gu", "f-el", "f-sort"].forEach((id) => $(id).addEventListener("change", render));

  /* 크게 보기 */
  const viewer = $("viewer");
  $("grid").addEventListener("click", (e) => {
    const p = e.target.closest("button.plan");
    if (!p) return;
    $("v-title").textContent = p.dataset.name + " 평면도";
    const srcs = JSON.parse(p.dataset.srcs || "[]");
    $("v-body").innerHTML = srcs.map((u) => `<img src="${esc(u)}" alt="${esc(p.dataset.name)} 평면도" referrerpolicy="no-referrer">`).join("");
    $("v-src").href = p.dataset.origin;
    viewer.showModal();
  });
  $("v-close").addEventListener("click", () => viewer.close());
  viewer.addEventListener("click", (e) => { if (e.target === viewer) viewer.close(); });

  /* 이미지를 불러오지 못하면 링크로 바꾼다 */
  $("grid").addEventListener("error", (e) => {
    const img = e.target;
    const p = img.closest && img.closest("button.plan");
    if (!p) return;
    const box = document.createElement("div");
    box.className = "plan none";
    box.innerHTML = `<span>평면도를 불러오지 못했습니다<br><a href="${esc(p.dataset.origin)}" target="_blank" rel="noopener">원본에서 보기 ↗</a></span>`;
    p.replaceWith(box);
  }, true);

  setup();
})();
