"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const SVG_NS = "http://www.w3.org/2000/svg";
  const REFRESH_MS = 4000;

  const state = {
    token: sessionStorage.getItem("td.token"),
    user: JSON.parse(sessionStorage.getItem("td.user") || "null"),
    event: null,
    seats: [],
    hold: null,
    hadHold: false,
    // Server time minus local time. Timers use server time so a wrong laptop clock cannot mislead.
    offsetMs: 0,
    circles: new Map(),
    rows: [],
    focusId: null,
    paying: false,
    // Reused when a payment request gets no answer, so a retry cannot pay twice.
    payKey: null,
    expiryRefreshPending: false,
  };

  class ApiError extends Error {
    constructor(status, code, message) {
      super(message);
      this.status = status;
      this.code = code;
    }
  }

  async function api(method, path, body, extraHeaders = {}) {
    const headers = { ...extraHeaders };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let response;
    try {
      response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch {
      throw new ApiError(0, "network", "Ticket Drop could not be reached. Check your connection and try again.");
    }
    let data = null;
    if (response.status !== 204) {
      try { data = await response.json(); } catch { data = null; }
    }
    if (response.status === 401 && path !== "/api/login") {
      signOutLocally("Your session has ended. Sign in again.");
    }
    if (!response.ok) {
      const err = data && data.error;
      throw new ApiError(response.status, err ? err.code : "error",
        err ? err.message : `Something went wrong (error ${response.status}). Try again.`);
    }
    if (data && typeof data.server_now_ms === "number") state.offsetMs = data.server_now_ms - Date.now();
    return data;
  }

  const serverNow = () => Date.now() + state.offsetMs;

  // Seeded faults (see app/faults.py). The server lists them only when one is enabled.
  const faultOn = (name) => Boolean(state.event && state.event.faults && state.event.faults.includes(name));

  function money(cents) {
    return cents % 100 === 0 ? `RM ${cents / 100}` : `RM ${(cents / 100).toFixed(2)}`;
  }

  function seatName(seat) {
    return `Row ${seat.row}, seat ${seat.number}`;
  }

  function show(el, visible) {
    el.hidden = !visible;
  }

  function setNotice(el, text, ok = false) {
    el.textContent = text || "";
    el.classList.toggle("ok", ok);
    show(el, Boolean(text));
  }

  /* ---------- Routing ---------- */

  function route() {
    const signedIn = Boolean(state.token);
    show($("account"), signedIn);
    show($("signinView"), !signedIn);
    if (!signedIn) {
      show($("seatsView"), false);
      show($("ticketsView"), false);
      $("username").focus();
      return;
    }
    $("whoami").textContent = `Signed in as ${state.user.display_name}`;
    const onTickets = location.hash === "#tickets";
    show($("seatsView"), !onTickets);
    show($("ticketsView"), onTickets);
    $("navSeats").toggleAttribute("aria-current", !onTickets);
    $("navTickets").toggleAttribute("aria-current", onTickets);
    if (onTickets) {
      $("navTickets").setAttribute("aria-current", "page");
      loadTickets();
    } else {
      $("navSeats").setAttribute("aria-current", "page");
      loadSeatsView();
    }
  }

  /* ---------- Sign in and out ---------- */

  async function signIn(event) {
    event.preventDefault();
    const username = $("username").value.trim();
    const password = $("password").value;
    if (!username || !password) {
      setNotice($("signinError"), "Enter a username and a password.");
      return;
    }
    try {
      const data = await api("POST", "/api/login", { username, password });
      state.token = data.token;
      state.user = data.user;
      sessionStorage.setItem("td.token", data.token);
      sessionStorage.setItem("td.user", JSON.stringify(data.user));
      setNotice($("signinError"), "");
      $("password").value = "";
      location.hash = "#seats";
      route();
    } catch (err) {
      setNotice($("signinError"), err.message);
    }
  }

  function signOutLocally(message) {
    state.token = null;
    state.user = null;
    state.hold = null;
    state.hadHold = false;
    state.payKey = null;
    state.payKeyFor = null;
    sessionStorage.removeItem("td.token");
    sessionStorage.removeItem("td.user");
    route();
    if (message) setNotice($("signinError"), message);
  }

  async function signOut() {
    try { await api("POST", "/api/logout"); } catch { /* Signing out locally is enough. */ }
    signOutLocally();
  }

  /* ---------- Event and sale state ---------- */

  async function loadEvent() {
    state.event = await api("GET", "/api/event");
    const starts = new Date(state.event.starts_at);
    const day = new Intl.DateTimeFormat("en-GB", {
      weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "Asia/Kuala_Lumpur",
    }).format(starts);
    $("eventTitle").innerHTML = "";
    $("eventTitle").append(state.event.artist, document.createElement("br"), state.event.tour);
    $("eventMeta").textContent = `${day}, 8 pm, ${state.event.venue}`;
    for (const el of document.querySelectorAll("[data-price]")) {
      el.textContent = money(state.event.prices_cents[el.dataset.price]);
    }
  }

  function renderSaleState() {
    const el = $("saleState");
    if (!state.event) return;
    const opensAt = state.event.sale_opens_at_ms;
    const open = opensAt === null || serverNow() >= opensAt;
    el.classList.toggle("closed", !open);
    if (open) {
      el.innerHTML = `<strong>On sale now</strong>Up to ${state.event.max_seats} tickets per account`;
    } else {
      const left = Math.max(0, Math.ceil((opensAt - serverNow()) / 1000));
      el.innerHTML = `<strong>Sale opens in ${clockText(left)}</strong>Seats can be held once the sale opens`;
    }
  }

  function clockText(totalSeconds) {
    const m = Math.floor(totalSeconds / 60);
    const s = String(totalSeconds % 60).padStart(2, "0");
    return `${m}:${s}`;
  }

  /* ---------- Seat map ---------- */

  function buildMap(seats) {
    const map = $("map");
    map.innerHTML = "";
    state.circles.clear();
    const cx = 500, cy = 30, r0 = 150, dr = 19, spacing = 17.5, gap = 1.4;

    const stage = document.createElementNS(SVG_NS, "path");
    const sr = 112, sa = 0.8, ir = 40;
    const p = (r, a) => `${cx + r * Math.sin(a)} ${cy + r * Math.cos(a)}`;
    stage.setAttribute("d", `M ${p(sr, -sa)} A ${sr} ${sr} 0 0 0 ${p(sr, sa)} L ${p(ir, sa)} A ${ir} ${ir} 0 0 1 ${p(ir, -sa)} Z`);
    stage.setAttribute("class", "stage-shape");
    map.append(stage);
    const stageText = document.createElementNS(SVG_NS, "text");
    stageText.setAttribute("x", cx);
    stageText.setAttribute("y", cy + 70);
    stageText.setAttribute("text-anchor", "middle");
    stageText.setAttribute("class", "stage-label");
    stageText.textContent = "Stage";
    map.append(stageText);

    const byRow = new Map();
    for (const seat of seats) {
      if (!byRow.has(seat.row)) byRow.set(seat.row, []);
      byRow.get(seat.row).push(seat);
    }
    state.rows = [...byRow.keys()].sort();
    state.rows.forEach((row, i) => {
      const rowSeats = byRow.get(row).sort((a, b) => a.number - b.number);
      byRow.set(row, rowSeats);
      const r = r0 + i * dr;
      const slots = rowSeats.length + 2 * gap;
      const step = spacing / r;
      let slot = -(slots - 1) / 2;
      let prevBlock = rowSeats[0].block;
      const points = [];
      for (const seat of rowSeats) {
        if (seat.block !== prevBlock) { slot += gap; prevBlock = seat.block; }
        const a = slot * step;
        seat.x = cx + r * Math.sin(a);
        seat.y = cy + r * Math.cos(a);
        points.push(seat);
        slot += 1;
      }
      for (const [s, anchor, dx] of [[points[0], "end", -12], [points[points.length - 1], "start", 12]]) {
        const t = document.createElementNS(SVG_NS, "text");
        t.setAttribute("x", s.x + dx);
        t.setAttribute("y", s.y + 4);
        t.setAttribute("text-anchor", anchor);
        t.setAttribute("class", "row-label");
        t.setAttribute("aria-hidden", "true");
        t.textContent = row;
        map.append(t);
      }
      for (const seat of rowSeats) {
        const c = document.createElementNS(SVG_NS, "circle");
        c.setAttribute("cx", seat.x.toFixed(1));
        c.setAttribute("cy", seat.y.toFixed(1));
        c.setAttribute("r", 7);
        c.setAttribute("role", "button");
        c.setAttribute("tabindex", "-1");
        c.dataset.seat = seat.id;
        c.addEventListener("click", () => toggleSeat(seat.id));
        c.addEventListener("mouseenter", () => describeSeat(seat.id));
        c.addEventListener("focus", () => describeSeat(seat.id));
        c.addEventListener("keydown", onSeatKey);
        map.append(c);
        state.circles.set(seat.id, c);
      }
    });
    state.byRow = byRow;
    const box = map.getBBox();
    map.setAttribute("viewBox", `${box.x - 6} ${box.y - 6} ${box.width + 12} ${box.height + 12}`);
    const pan = document.querySelector(".map-scroll");
    pan.scrollLeft = (pan.scrollWidth - pan.clientWidth) / 2;
    setFocusSeat(state.focusId || seats.find((s) => s.state === "available")?.id || seats[0].id, false);
  }

  function seatById(id) {
    return state.seats.find((s) => s.id === id);
  }

  function renderSeats() {
    for (const seat of state.seats) {
      const c = state.circles.get(seat.id);
      if (!c) continue;
      c.setAttribute("class", `seat tier${seat.tier} ${seat.state === "available" ? "" : seat.state}`.trim()
        + (seat.id === state.focusId && document.activeElement === c ? " focused" : ""));
      c.dataset.state = seat.state;
      const status = seat.state === "mine" ? "held for you" : seat.state;
      c.setAttribute("aria-label", `${seatName(seat)}, category ${seat.tier}, ${money(seat.price_cents)}, ${status}`);
      c.setAttribute("aria-pressed", String(seat.state === "mine"));
    }
  }

  function describeSeat(id) {
    const seat = seatById(id);
    if (!seat) return;
    $("seatInfo").textContent = seat.state === "taken"
      ? `${seatName(seat)} is taken.`
      : `${seatName(seat)}, category ${seat.tier}, ${money(seat.price_cents)}${seat.state === "mine" ? ", held for you" : ""}`;
  }

  function setFocusSeat(id, moveFocus = true) {
    const previous = state.circles.get(state.focusId);
    if (previous) {
      previous.setAttribute("tabindex", "-1");
      previous.classList.remove("focused");
    }
    state.focusId = id;
    const c = state.circles.get(id);
    if (!c) return;
    c.setAttribute("tabindex", "0");
    if (moveFocus) {
      c.focus();
      c.classList.add("focused");
    }
  }

  function onSeatKey(event) {
    const seat = seatById(state.focusId);
    if (!seat) return;
    const rowSeats = state.byRow.get(seat.row);
    const index = rowSeats.findIndex((s) => s.id === seat.id);
    const rowIndex = state.rows.indexOf(seat.row);
    let target = null;
    switch (event.key) {
      case "ArrowLeft": target = rowSeats[Math.max(0, index - 1)]; break;
      case "ArrowRight": target = rowSeats[Math.min(rowSeats.length - 1, index + 1)]; break;
      case "ArrowUp":
      case "ArrowDown": {
        const next = state.rows[rowIndex + (event.key === "ArrowUp" ? -1 : 1)];
        if (next) {
          // Nearest seat by position, so moving up and down feels straight.
          target = state.byRow.get(next).reduce((best, s) =>
            Math.hypot(s.x - seat.x, s.y - seat.y) < Math.hypot(best.x - seat.x, best.y - seat.y) ? s : best);
        }
        break;
      }
      case "Enter":
      case " ":
        event.preventDefault();
        toggleSeat(seat.id);
        return;
      default:
        return;
    }
    event.preventDefault();
    if (target) setFocusSeat(target.id);
  }

  document.addEventListener("focusout", (event) => {
    if (event.target.classList && event.target.classList.contains("seat")) event.target.classList.remove("focused");
  });

  async function toggleSeat(id) {
    const seat = seatById(id);
    if (!seat || state.paying) return;
    setNotice($("mapError"), "");
    if (seat.state === "taken") {
      setNotice($("mapError"), `${seatName(seat)} is taken. Choose another seat.`);
      return;
    }
    const c = state.circles.get(id);
    c.classList.add("pending");
    let failed = false;
    try {
      const data = seat.state === "mine"
        ? await api("DELETE", `/api/hold/seats/${id}`)
        : await api("POST", "/api/hold/seats", { seat_id: id });
      applyHold(data.hold);
    } catch (err) {
      failed = true;
      if (err.status !== 401) setNotice($("mapError"), err.message);
    } finally {
      c.classList.remove("pending");
      if (!(failed && faultOn("map_stale_after_failed_seat_change"))) await refreshSeats();
      describeSeat(id);
    }
  }

  async function refreshSeats() {
    if (!state.token) return;
    try {
      const [seatData, holdData] = await Promise.all([api("GET", "/api/seats"), api("GET", "/api/hold")]);
      const firstLoad = state.seats.length === 0;
      state.seats = seatData.seats;
      if (firstLoad) buildMap(state.seats);
      renderSeats();
      applyHold(holdData.hold);
    } catch (err) {
      if (err.status !== 401) setNotice($("mapError"), err.message);
    }
  }

  /* ---------- Hold and payment ---------- */

  function applyHold(hold) {
    if (!hold && state.hadHold && !state.paying && state.lastHoldExpires && serverNow() >= state.lastHoldExpires) {
      setNotice($("notice"), "Your hold ended and the seats went back on sale.");
    }
    state.hold = hold;
    state.hadHold = Boolean(hold);
    state.lastHoldExpires = hold ? hold.expires_ms : state.lastHoldExpires;
    state.expiryRefreshPending = false;
    renderHold();
  }

  function renderHold() {
    const list = $("seatList");
    list.innerHTML = "";
    const hold = state.hold;
    const seats = hold ? hold.seats : [];
    if (!seats.length) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = "No seats held. Pick seats on the map.";
      list.append(li);
    }
    for (const seat of seats) {
      const li = document.createElement("li");
      const dot = document.createElement("span");
      dot.className = `dot tier${seat.tier}`;
      const name = document.createElement("span");
      name.textContent = seatName(seat);
      const small = document.createElement("small");
      small.textContent = `Category ${seat.tier}`;
      const release = document.createElement("button");
      release.type = "button";
      release.className = "link";
      release.textContent = "Release";
      release.setAttribute("aria-label", `Release ${seatName(seat)}`);
      release.addEventListener("click", () => toggleSeat(seat.id));
      small.append(" ", release);
      name.append(small);
      const price = document.createElement("span");
      price.textContent = money(seat.price_cents);
      li.append(dot, name, price);
      list.append(li);
    }
    const total = hold ? hold.total_cents : 0;
    $("total").textContent = money(total);
    show($("payForm"), seats.length > 0);
    show($("release"), seats.length > 0);
    $("pay").disabled = seats.length === 0 || state.paying;
    $("pay").textContent = state.paying ? "Paying" : seats.length ? `Pay ${money(total)}` : "Pay";
    $("timerNote").textContent = seats.length
      ? "Pay before the timer ends or these seats go back on sale."
      : `Seats are held for ${Math.round((state.event ? state.event.hold_seconds : 300) / 60)} minutes once you pick them.`;
    const stub = $("stub");
    stub.style.setProperty("--tear", `${$("stubTop").offsetHeight}px`);
    tick();
  }

  function tick() {
    renderSaleState();
    const timer = $("timer");
    const hold = state.hold;
    if (!hold || !hold.seats.length) {
      timer.textContent = clockText(state.event ? state.event.hold_seconds : 300);
      timer.className = "timer idle";
      return;
    }
    const left = Math.max(0, Math.ceil((hold.expires_ms - serverNow()) / 1000));
    timer.textContent = clockText(left);
    timer.className = left < 60 ? "timer low" : "timer";
    if (left === 0 && !state.paying && !state.expiryRefreshPending) {
      state.expiryRefreshPending = true;
      refreshSeats();
    }
  }

  function basketSignature() {
    return state.hold ? `${state.hold.id}:${state.hold.seats.map((s) => s.id).join(",")}` : "";
  }

  async function pay() {
    // Enter in the card field submits the form even while the button is disabled.
    if (state.paying) return;
    const card = $("card").value.trim();
    if (!card) {
      setNotice($("notice"), "Enter a card number. Use a test card listed below the field.");
      $("card").focus();
      return;
    }
    state.paying = true;
    setNotice($("notice"), "");
    renderHold();
    // A kept key is only reused for exactly the same hold and seats.
    if (state.payKeyFor !== basketSignature()) state.payKey = null;
    state.payKey = state.payKey || (crypto.randomUUID ? crypto.randomUUID() : `k${Date.now()}${Math.random().toString(16).slice(2)}`);
    state.payKeyFor = basketSignature();
    try {
      const data = await api("POST", "/api/checkout", { card_number: card }, { "Idempotency-Key": state.payKey });
      state.payKey = null;
      state.paying = false;
      state.hadHold = false;
      $("card").value = "";
      const n = data.tickets.length;
      setNotice($("ticketsNotice"), `Payment complete. ${n} ${n === 1 ? "ticket is" : "tickets are"} below.`, true);
      location.hash = "#tickets";
    } catch (err) {
      // No answer at all: keep the key so retrying cannot charge twice. Any answer: the next attempt is new.
      if (err.code !== "network") state.payKey = null;
      state.paying = false;
      if (err.status !== 401) setNotice($("notice"), err.message);
      await refreshSeats();
    }
  }

  async function releaseAll() {
    try {
      await api("DELETE", "/api/hold");
      setNotice($("notice"), "");
    } catch (err) {
      if (err.status !== 401) setNotice($("notice"), err.message);
    }
    await refreshSeats();
  }

  /* ---------- Views ---------- */

  async function loadSeatsView() {
    try {
      if (!state.event) await loadEvent();
    } catch (err) {
      setNotice($("mapError"), err.message);
      return;
    }
    await refreshSeats();
  }

  async function loadTickets() {
    const list = $("ticketList");
    try {
      const data = await api("GET", "/api/tickets");
      if (!state.event) await loadEvent();
      list.innerHTML = "";
      show($("ticketsEmpty"), data.tickets.length === 0);
      for (const t of data.tickets) {
        const li = document.createElement("li");
        li.className = `ticket tier${t.tier}`;
        const main = document.createElement("div");
        main.className = "main";
        const strong = document.createElement("strong");
        strong.textContent = seatName(t);
        const meta = document.createElement("span");
        meta.textContent = `${state.event.artist}, ${state.event.tour}`;
        const when = document.createElement("span");
        when.textContent = `${state.event.venue}, 13 March 2027, 8 pm`;
        main.append(strong, meta, document.createElement("br"), when);
        const side = document.createElement("div");
        side.className = "side";
        const tier = document.createElement("span");
        tier.className = "tier";
        tier.textContent = `Category ${t.tier}`;
        const price = document.createElement("span");
        price.textContent = money(t.price_cents);
        side.append(tier, price);
        li.append(main, side);
        list.append(li);
      }
    } catch (err) {
      if (err.status !== 401) setNotice($("ticketsNotice"), err.message);
    }
  }

  /* ---------- Start ---------- */

  $("signinForm").addEventListener("submit", signIn);
  $("signOut").addEventListener("click", signOut);
  $("pay").addEventListener("click", pay);
  $("payForm").addEventListener("submit", (e) => { e.preventDefault(); pay(); });
  $("release").addEventListener("click", releaseAll);
  window.addEventListener("hashchange", () => {
    if (location.hash !== "#tickets") setNotice($("ticketsNotice"), "");
    route();
  });
  setInterval(tick, 250);
  setInterval(() => {
    if (state.token && !$("seatsView").hidden && document.visibilityState === "visible" && !state.paying) refreshSeats();
  }, REFRESH_MS);
  route();
})();
