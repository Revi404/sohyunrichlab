(() => {
  const $ = (s) => document.querySelector(s);
  const esc = (s = "") => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ICONS = {
    blog: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8M8 12h5"/></svg>',
    mail: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
    insta: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor"/></svg>',
    youtube: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="4"/><path d="m10 9 5 3-5 3z" fill="currentColor"/></svg>',
    link: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/></svg>',
  };

  // 청약 일정 종류(티스토리 스킨 '다가오는 7일'과 같은 이름·배지 글자)
  const TYPES = [
    { key: "sp", label: "특별공급", short: "특" },
    { key: "r1", label: "1순위", short: "1" },
    { key: "r2", label: "2순위", short: "2" },
    { key: "rcpt", label: "무순위·재공급", short: "무" },
    { key: "winner", label: "당첨 발표", short: "발" },
  ];
  const RECEIPT = ["sp", "r1", "r2", "rcpt"];
  const WD = ["일", "월", "화", "수", "목", "금", "토"];
  const parse = (s) => { const p = s.split("-"); return new Date(+p[0], +p[1] - 1, +p[2]); };
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const addDays = (s, n) => { const d = parse(s); d.setDate(d.getDate() + n); return iso(d); };
  const md = (s) => { const d = parse(s); return `${d.getMonth() + 1}.${d.getDate()}`; };
  const dayDiff = (a, b) => Math.round((parse(b) - parse(a)) / 864e5);
  // 한국 날짜 기준 오늘(?today=2026-10-22 로 바꿔 볼 수 있음)
  const todayIso = () => {
    const q = /[?&]today=(\d{4}-\d{2}-\d{2})/.exec(location.search);
    return q ? q[1] : new Date(Date.now() + 9 * 36e5).toISOString().slice(0, 10);
  };
  const kindLabel = (n) => (n.kind === "remndr" ? n.type : n.house && n.house !== "APT" ? n.house : n.type === "국민" ? "공공분양" : "민영");

  const track = (name) => { try { window.goatcounter?.count({ path: "click/" + name, title: name, event: true }); } catch (_) {} };
  document.addEventListener("click", (e) => { const a = e.target.closest("a[data-track]"); if (a) track(a.dataset.track); });

  const load = (u, bust = true) => fetch(bust ? u + "?v=" + Date.now() : u, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);

  const renderChips = (el, names, counts, cur, on) => {
    el.innerHTML = names.map((n) => `<button class="chip" aria-pressed="${n === cur}" data-v="${esc(n)}">${esc(n)}${counts ? `<span class="n">${counts[n] ?? 0}</span>` : ""}</button>`).join("");
    el.onclick = (e) => { const b = e.target.closest(".chip"); if (b) on(b.dataset.v); };
  };

  load("config.json").then((cfg) => {
    if (!cfg) return;
    const P = cfg.profile;

    // 프로필
    $("#avatar").src = P.image;
    $("#name").textContent = P.name;
    $("#bio").textContent = P.bio || "";
    if (cfg.notice?.show && cfg.notice.text) {
      const n = $("#notice"); n.hidden = false; n.textContent = cfg.notice.text;
      if (cfg.notice.url) { n.href = cfg.notice.url; n.target = "_blank"; n.rel = "noopener"; n.dataset.track = "notice"; }
    }

    // 바로가기
    const linkHtml = (l) => `
      <a class="link${l.highlight ? " hl" : ""}${l.color ? " " + esc(l.color) : ""}" href="${esc(l.url)}" ${l.url.startsWith("mailto:") ? "" : 'target="_blank" rel="noopener"'} data-track="${esc(l.id)}">
        <span class="ic">${ICONS[l.icon] || ICONS.link}</span>
        <span class="tx"><span class="t">${esc(l.title)}</span>${l.sub ? `<span class="s">${esc(l.sub)}</span>` : ""}</span>
        <span class="go" aria-hidden="true">→</span>
      </a>`;
    // type "pair": 다른 채널 묶음 — 제목·설명 아래 버튼 2개를 가로로
    const pairHtml = (g) => `
      <div class="pair${g.color ? " " + esc(g.color) : ""}">
        <p class="pair-head">${g.title ? `<span class="t">${esc(g.title)}</span>` : ""}${g.sub ? `<span class="s">${esc(g.sub)}</span>` : ""}</p>
        <div class="pair-row">${g.items.map((l) => `
          <a class="pair-btn" href="${esc(l.url)}" target="_blank" rel="noopener" data-track="${esc(l.id)}">
            <span class="ic">${ICONS[l.icon] || ICONS.link}</span>
            <span class="tx"><span class="t">${esc(l.title)}</span>${l.sub ? `<span class="s">${esc(l.sub)}</span>` : ""}</span>
          </a>`).join("")}
        </div>
      </div>`;
    $("#links").innerHTML = cfg.links.filter((l) => !l.hidden).map((l) => (l.type === "pair" ? pairHtml(l) : linkHtml(l))).join("");

    $("#disclosure").textContent = cfg.disclosure || "";
    $("#week-more").href = cfg.week.calendarUrl;
    $("#blog-more").href = cfg.blog.url;

    // 탭
    const tabs = [["#tab-week", "#panel-week"], ["#tab-blog", "#panel-blog"]];
    const show = (i) => tabs.forEach(([t, p], k) => { $(t).setAttribute("aria-selected", k === i); $(p).hidden = k !== i; });
    tabs.forEach(([t], i) => $(t).addEventListener("click", () => show(i)));

    // ---------- 이번 주 청약단지: 오늘부터 7일 안의 청약 접수·당첨 발표 ----------
    const t0 = todayIso(), t6 = addDays(t0, (cfg.week.days || 7) - 1);
    $("#weeks").innerHTML = `<li class="empty">일정을 불러오는 중…</li>`;
    const calendar = load(cfg.week.dataUrl).then((d) => (d && d.notices ? d : load("data/calendar.json")));
    calendar.then((cal) => {
      if (!cal) { $("#weeks").innerHTML = `<li class="empty">일정을 불러오지 못했어요. 블로그 청약 캘린더에서 확인해 주세요.</li>`; return; }
      const rows = [];
      cal.notices.forEach((n) => {
        const evs = TYPES.map((t) => {
          const v = n[t.key]; if (!v) return null;
          const r = typeof v === "string" ? [v, v] : v;
          return r[0] <= t6 && r[1] >= t0 ? { ...t, start: r[0], end: r[1] } : null;
        }).filter(Boolean);
        if (!evs.length) return;
        const rc = evs.filter((e) => RECEIPT.includes(e.key));
        const first = (rc.length ? rc : evs).map((e) => (e.start < t0 ? t0 : e.start)).sort()[0];
        let status;
        if (rc.length) {
          const open = rc.some((e) => e.start <= t0 && t0 <= e.end);
          const d = dayDiff(t0, rc.map((e) => e.start).sort()[0]);
          status = open ? ["open", "접수 중"] : ["soon", `접수 D-${d}`];
        } else {
          const d = dayDiff(t0, n.winner);
          status = ["wait", d ? `발표 D-${d}` : "오늘 발표"];
        }
        rows.push({ n, evs, first, status, receipt: rc.length > 0 });
      });
      rows.sort((a, b) => (a.first < b.first ? -1 : a.first > b.first ? 1 : (b.n.units || 0) - (a.n.units || 0)));

      const GROUPS = {
        "청약 접수": (r) => r.receipt,
        "일반 분양": (r) => r.receipt && r.n.kind !== "remndr",
        "무순위·줍줍": (r) => r.receipt && r.n.kind === "remndr",
        "당첨 발표": (r) => r.evs.some((e) => e.key === "winner"),
      };
      const names = Object.keys(GROUPS);
      const counts = Object.fromEntries(names.map((k) => [k, rows.filter(GROUPS[k]).length]));
      let wf = names[0];
      const max = cfg.week.max || 30;
      const renderWeek = () => {
        const list = rows.filter(GROUPS[wf]);
        // 당첨 발표 칩: 발표일 기준으로 다시 정렬하고 발표 일정만 보여 준다
        const winnerView = (r) => { const d = dayDiff(t0, r.n.winner); return { ...r, evs: r.evs.filter((e) => e.key === "winner"), first: r.n.winner, status: ["wait", d ? `발표 D-${d}` : "오늘 발표"] }; };
        const shown = wf === "당첨 발표" ? list.map(winnerView).sort((a, b) => (a.first < b.first ? -1 : a.first > b.first ? 1 : 0)) : list;
        $("#weeks").innerHTML = shown.length ? shown.slice(0, max).map((r, k) => {
          const n = r.n, f = parse(r.first);
          return `
          <li class="wk"><a href="${esc(n.post || cfg.blog.url + "/")}" target="_blank" rel="noopener" data-track="week-${k}">
            <span class="day${r.first === t0 ? " today" : ""}"><b>${f.getMonth() + 1}.${f.getDate()}</b><span>${r.first === t0 ? "오늘" : WD[f.getDay()]}</span></span>
            <span class="tx">
              <span class="tags"><span class="st ${r.status[0]}">${esc(r.status[1])}</span><span class="kd">${esc(kindLabel(n))}</span>${n.post ? '<span class="kd post">요약 글</span>' : ""}</span>
              <span class="t" title="${esc(n.name)}">${esc(n.name)}</span>
              <span class="m">${esc(n.region || "")}${n.units ? ` · ${Number(n.units).toLocaleString("ko-KR")}세대` : ""}</span>
              <span class="ev">${r.evs.map((e) => `<span class="e e-${e.key}"><i>${e.short}</i>${e.start === e.end ? md(e.start) : `${md(e.start)}~${md(e.end)}`}</span>`).join("")}</span>
            </span>
          </a></li>`;
        }).join("") + (shown.length > max ? `<li class="empty">외 ${shown.length - max}건은 청약 캘린더에서 볼 수 있어요</li>` : "")
          : `<li class="empty">이번 주에는 ${esc(wf)} 일정이 없어요</li>`;
      };
      const weekChips = () => renderChips($("#week-filters"), names, counts, wf, (v) => { wf = v; weekChips(); renderWeek(); });
      weekChips(); renderWeek();
      if (cal.updated) $("#updated").dataset.cal = cal.updated;
      stamp();
    });

    // ---------- 분석 리포트: 티스토리 카테고리별 최신 글 ----------
    load("data/feed.json").then((feed) => {
      feed = feed || { posts: {}, all: [] };
      const label = (c) => (cfg.blog.labels || {})[c] || c;
      const cats = (feed.categories || Object.keys(feed.posts)).filter((c) => (feed.posts[c] || []).length);
      const byUrl = {};
      cats.forEach((c) => feed.posts[c].forEach((p) => { byUrl[p.url] = byUrl[p.url] || p; }));
      const all = (feed.all || []).map((u) => byUrl[u]).filter(Boolean);
      let bf = "전체";
      const renderPosts = () => {
        const list = bf === "전체" ? all : feed.posts[cats.find((c) => label(c) === bf)] || [];
        $("#posts").innerHTML = list.length ? list.map((p, k) => `
          <li class="post"><a href="${esc(p.url)}" target="_blank" rel="noopener" data-track="post-${k}">
            <span class="th">${p.thumb ? `<img src="${esc(p.thumb)}" alt="" loading="lazy">` : ""}</span>
            <span class="tx"><span class="cat">${esc(label(p.category))}</span><span class="t">${esc(p.title)}</span><span class="d">${esc(p.date)}</span></span>
          </a></li>`).join("") : `<li class="empty">아직 글이 없어요</li>`;
      };
      const blogChips = () => renderChips($("#blog-filters"), ["전체", ...cats.map(label)], null, bf, (v) => { bf = v; blogChips(); renderPosts(); });
      blogChips(); renderPosts();
      if (feed.updated) $("#updated").dataset.feed = feed.updated;
      stamp();
    });

    const stamp = () => {
      const u = $("#updated").dataset;
      $("#updated").textContent = [u.cal && `청약 일정 ${u.cal}`, u.feed && `글 목록 ${u.feed}`].filter(Boolean).join(" · ") + " 업데이트";
    };

    if (cfg.goatcounter) {
      const s = document.createElement("script");
      s.async = true; s.src = "https://gc.zgo.at/count.js"; s.dataset.goatcounter = `https://${cfg.goatcounter}.goatcounter.com/count`;
      document.body.appendChild(s);
    }
  });
})();
