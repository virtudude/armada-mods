"use strict";
// The page is only a view. The provider validates IDs, availability and confirmation.
const $ = (id) => document.getElementById(id);
const bridge = window.armada || { data: "", last: null, send() {} };
let state = {},
  page = "STAT",
  category = "Status",
  selection = null,
  signature = "",
  pendingUntil = 0;
let dismissedToken = null;
let confirmToken = null,
  confirmTimer = null,
  confirmReadyTimer = null,
  lastNotice = "";
const pages = {
  STAT: ["Status", "SPECIAL", "Perks"],
  INV: ["Weapons", "Apparel", "Aid", "Misc", "Junk", "Mods", "Ammo"],
  DATA: ["Quests", "Workshops", "Log"],
  MAP: ["World", "Local"],
  RADIO: [],
};
const filters = {
  Weapons: 2,
  Apparel: 4,
  Aid: 8,
  Misc: 512 | 128,
  Junk: 1024,
  Mods: 2048,
  Ammo: 4096,
};
const images = new Map();
const key = (item, index = 0) =>
  String(
    item?._id ??
      item?.formID ??
      item?.Clip ??
      item?.Name ??
      item?.text ??
      index,
  );
const arr = (v) => (Array.isArray(v) ? v : []);
const number = (v, digits = 0) =>
  Number.isFinite(Number(v))
    ? Number(v).toLocaleString(undefined, { maximumFractionDigits: digits })
    : "—";
const labels = {
  $ROF: "Fire rate",
  $rng: "Range",
  $acc: "Accuracy",
  $wt: "Weight",
  $val: "Value",
  $dmg: "Damage",
  $dr: "Resistance",
  $ammo: "Ammo",
  $speed: "Speed",
  $range: "Range",
  $accuracy: "Accuracy",
  $rate: "Fire rate",
  $APCost: "AP cost",
  WorkshopRatingPopulation: "People",
  PowerGenerated: "Power",
  Bed: "Beds",
};
function title(v) {
  return (
    labels[v] ||
    String(v ?? "")
      .replace(/^\$/, "")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
  );
}
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = String(text);
  return node;
}
function button(text, fn, cls = "") {
  const node = el("button", cls, text);
  node.type = "button";
  node.addEventListener("click", fn);
  return node;
}
function empty(text, sub = "") {
  const node = el("div", "empty");
  node.append(el("p", "", text));
  if (sub) node.append(el("p", "muted", sub));
  return node;
}
function reason() {
  const s = state.data?.Status || {};
  if (!state.connected) return state.message || "Connecting to Fallout 4…";
  if (!state.data?.PlayerInfo || s.IsDataUnavailable)
    return "Load a save to use the Pip-Boy";
  if (!state.data.Status) return "Pip-Boy controls unavailable";
  if (s.IsLoading) return "Loading…";
  if (s.IsPlayerDead) return "Player is dead";
  if (s.IsPipboyNotEquipped) return "Pip-Boy is not equipped";
  if (s.IsPlayerInDialogue) return "In dialogue";
  if (s.IsInVats || s.IsInVatsPlayback) return "V.A.T.S. active";
  if (s.IsPlayerPipboyLocked || s.IsPlayerMovementLocked || s.IsInAnimation)
    return "Pip-Boy controls unavailable";
  return "";
}
function send(command) {
  if (reason() || Date.now() < pendingUntil) return;
  pendingUntil = Date.now() + 450;
  bridge.send(command);
  $("notice").textContent = "Sent to game…";
}
function action(text, command, allowed = true) {
  const b = button(text, () => send(command), "primary");
  b.dataset.gameAction = "true";
  b.disabled = !!reason() || !allowed;
  if (!allowed) b.dataset.unavailable = "true";
  return b;
}
function facts(parent, rows) {
  const dl = el("dl", "facts");
  for (const [label, value] of rows) {
    dl.append(el("dt", "", title(label)), el("dd", "", value));
  }
  parent.append(dl);
}
function assetUrl(path) {
  if (!path) return null;
  if (/^file:\/\//.test(path)) return path;
  if (/(^|\/)\.\.(\/|$)/.test(path) || /^[a-z]+:/i.test(path)) return null;
  return bridge.data.replace(/\/$/, "") + "/" + path.replace(/^\//, "");
}
function picture(path) {
  const url = assetUrl(typeof path === "object" ? path?.path : path);
  if (!url) return null;
  if (!images.has(url)) {
    const img = new Image();
    img.onload = () => {
      if (page === "MAP") drawMap();
    };
    img.src = url;
    if (url.includes("local-map.png")) {
      for (const old of images.keys())
        if (old.includes("local-map.png")) images.delete(old);
      for (const old of tinted.keys())
        if (old.includes("local-map.png")) tinted.delete(old);
    }
    if (images.size >= 128) images.delete(images.keys().next().value);
    images.set(url, img);
  }
  return images.get(url);
}
function art(parent, path, intensity = 1) {
  const url = assetUrl(typeof path === "object" ? path?.path : path);
  if (!url) return;
  const canvas = el("canvas", "art"),
    img = new Image();
  canvas.setAttribute("aria-hidden", "true");
  img.onload = () => {
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const context = canvas.getContext("2d");
    const rgb = getComputedStyle(document.documentElement)
      .color.match(/[\d.]+/g)
      ?.slice(0, 3)
      .map(Number) || [20, 255, 23];
    const ink = `rgb(${rgb.map((v) => v * intensity).join(",")})`;
    context.drawImage(img, 0, 0, canvas.width, canvas.height);
    context.globalCompositeOperation = "multiply";
    context.fillStyle = ink;
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.globalCompositeOperation = "destination-in";
    context.drawImage(img, 0, 0, canvas.width, canvas.height);
  };
  img.onerror = () => canvas.remove();
  img.src = url;
  parent.append(canvas);
}
function nav() {
  const tabs = $("tabs");
  tabs.replaceChildren();
  for (const name of Object.keys(pages)) {
    const b = button(name, () => switchPage(name));
    b.classList.toggle("selected", page === name);
    b.setAttribute("aria-current", page === name ? "page" : "false");
    tabs.append(b);
  }
  const sub = $("subtabs");
  sub.replaceChildren();
  sub.hidden = !pages[page].length;
  for (const name of pages[page]) {
    const b = button(name, () => {
      category = name;
      selection = null;
      signature = "";
      cancelConfirm();
      render();
      if (page === "MAP" && category === "Local") send({ action: "localmap" });
    });
    b.classList.toggle("selected", category === name);
    sub.append(b);
  }
}
function switchPage(name) {
  if (page === name) return;
  page = name;
  category = pages[name][0] || "";
  selection = null;
  signature = "";
  cancelConfirm();
  render();
}
function render() {
  nav();
  updateChrome();
  const content = $("content");
  if (!state.data?.PlayerInfo) {
    $("quick-actions").replaceChildren();
    content.replaceChildren(
      empty(
        "Fallout 4",
        state.message || "Waiting for a save and the Pip-Boy connection.",
      ),
    );
    return;
  }
  if (page === "MAP") {
    $("quick-actions").replaceChildren();
    if (
      !content.querySelector("#map-canvas") ||
      content.dataset.mapMode !== category
    ) {
      buildMap();
      content.dataset.mapMode = category;
    }
    drawMap();
    return;
  }
  const data = state.data;
  let relevant;
  if (page === "STAT")
    relevant =
      category === "Status"
        ? [data.PlayerInfo, data.Stats]
        : data[category === "SPECIAL" ? "Special" : "Perks"];
  if (page === "INV") relevant = data.Inventory;
  if (page === "DATA")
    relevant =
      data[
        category === "Workshops"
          ? "Workshop"
          : category === "Log"
            ? "Log"
            : "Quests"
      ];
  if (page === "RADIO") relevant = data.Radio;
  const next = JSON.stringify([
    page,
    category,
    selection,
    relevant,
    state.assets,
  ]);
  if (next === signature) {
    for (const b of content.querySelectorAll("[data-game-action]"))
      b.disabled = !!reason() || b.dataset.unavailable === "true";
    return;
  }
  signature = next;
  const scroll = {
    list: content.querySelector(".list")?.scrollTop || 0,
    detail: content.querySelector(".detail")?.scrollTop || 0,
  };
  content.replaceChildren();
  if (page === "STAT") renderStats();
  else if (page === "INV") renderInventory();
  else if (page === "DATA") renderData();
  else renderRadio();
  if (page !== "STAT" || category !== "Status") {
    const quick = $("quick-actions");
    quick.replaceChildren();
    for (const row of content.querySelectorAll(".detail .actions")) {
      quick.append(...row.children);
      row.remove();
    }
  }
  if (content.querySelector(".list"))
    content.querySelector(".list").scrollTop = scroll.list;
  if (content.querySelector(".detail"))
    content.querySelector(".detail").scrollTop = scroll.detail;
}
function split(items, summary, detail, none) {
  const outer = el("div", "split"),
    list = el("div", "list"),
    panel = el("div", "detail");
  outer.append(list, panel);
  $("content").append(outer);
  if (!items.length) {
    outer.replaceChildren(empty(none));
    outer.style.display = "block";
    return;
  }
  let chosen = items.find((v, i) => key(v, i) === selection);
  if (!chosen) {
    chosen = items[0];
    selection = key(chosen);
  }
  items.forEach((item, index) => {
    const id = key(item, index),
      bits = summary(item),
      row = button("", () => {
        selection = id;
        signature = "";
        cancelConfirm();
        render();
      });
    row.classList.toggle("selected", id === selection);
    row.append(el("span", "", bits[0]));
    if (bits[1] != null) row.append(el("span", "badge", bits[1]));
    row.setAttribute("aria-pressed", String(id === selection));
    list.append(row);
  });
  detail(chosen, panel);
}
function renderStats() {
  const d = state.data;
  if (category === "SPECIAL") {
    split(
      arr(d.Special),
      (i) => [i.Name, number(i.Value)],
      (i, p) => {
        p.append(el("h2", "", i.Name));
        const names = [
          "strength",
          "perception",
          "endurance",
          "charisma",
          "intelligence",
          "agility",
          "luck",
        ];
        p.classList.add("special");
        const special = names[arr(d.Special).indexOf(i)];
        if (state.assets?.animations?.special?.[special])
          animatedArt(p, "special", special);
        else art(p, state.assets?.icons?.special?.[special]);
        p.append(el("p", "", i.Description));
        facts(p, [
          ["Value", number(i.Value)],
          ["Modifier", number(i.Modifier)],
        ]);
      },
      "SPECIAL data unavailable",
    );
    return;
  }
  if (category === "Perks") {
    split(
      arr(d.Perks).filter((p) => p.ListVisible && p.Rank > 0),
      (i) => [i.Name, `${i.Rank}/${i.MaxRank}`],
      (i, p) => {
        p.append(el("h2", "", i.Name));
        art(p, state.assets?.icons?.[i.Clip]);
        p.append(
          el(
            "p",
            "",
            arr(i.Perks)[Math.max(0, i.Rank - 1)]?.Description ||
              "No description available.",
          ),
        );
        facts(p, [["Rank", `${i.Rank} / ${i.MaxRank}`]]);
      },
      "No acquired perks",
    );
    return;
  }
  const player = d.PlayerInfo || {},
    stats = d.Stats || {};
  const wrap = el("div", "status-layout"),
    doll = el("div", "condition-doll");
  wrap.append(doll);
  $("content").append(wrap);
  if (state.assets?.animations?.status) animatedArt(doll, "status");
  else {
    art(doll, state.assets?.icons?.status?.healthy, 0.5);
  }
  for (const [label, cls, value] of [
    ["Head", "head", stats.HeadCondition],
    ["Left arm", "left-arm", stats.LArmCondition],
    ["Right arm", "right-arm", stats.RArmCondition],
    ["Left leg", "left-leg", stats.LLegCondition],
    ["Right leg", "right-leg", stats.RLegCondition],
    [
      "Health",
      "health",
      player.MaxHP > 0 ? (player.CurrHP / player.MaxHP) * 100 : 0,
    ],
  ]) {
    const bar = el("div", "limb limb-" + cls),
      fill = el("span");
    bar.setAttribute("role", "meter");
    bar.setAttribute("aria-label", label);
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
    bar.setAttribute("aria-valuenow", number(value));
    fill.style.width = Math.min(100, Math.max(0, Number(value) || 0)) + "%";
    bar.append(fill);
    doll.append(bar);
  }
  const ratings = el("div", "combat-ratings");
  for (const [values, kind] of [
    [player.TotalDamages, "weapon"],
    [player.TotalResists, "armor"],
  ]) {
    const group = el("div", "rating-group"),
      icon = el("div", "rating-type");
    const path = state.assets?.icons?.[kind];
    if (path) art(icon, path);
    else icon.append(el("span", "", kind === "weapon" ? "DMG" : "DR"));
    group.append(icon);
    for (const entry of arr(values).filter((v) => v.Value > 0)) {
      const item = el("div", "rating-value");
      const path =
        state.assets?.icons?.damage?.[
          Number(entry.type) + (kind === "weapon" ? 5 : -1)
        ];
      if (path) art(item, path);
      else
        item.append(
          el(
            "span",
            "fallback-symbol",
            ["", "⌖", "◉", "♨", "ϟ", "❄", "☢"][entry.type] || "◇",
          ),
        );
      item.append(el("span", "", number(Math.floor(entry.Value))));
      item.setAttribute(
        "aria-label",
        (kind === "weapon" ? "Damage " : "Resistance ") +
          entry.type +
          ": " +
          number(entry.Value),
      );
      group.append(item);
    }
    ratings.append(group);
  }
  wrap.append(ratings, el("div", "player-name", player.PlayerName || ""));
  const effects = arr(stats.ActiveEffects);
  if (effects.length) {
    const panel = el("div", "effects-indicator");
    for (const effect of effects)
      panel.append(
        el("p", "", effect.text || effect.Name || effect.Source || "Effect"),
      );
    wrap.append(panel);
  }
}

function meter(parent, value) {
  const bar = el("div", "meter"),
    fill = el("span");
  fill.style.width = Math.min(100, Math.max(0, Number(value) || 0)) + "%";
  bar.append(fill);
  parent.append(bar);
}
function inventoryItems() {
  return Object.entries(state.data?.Inventory || {})
    .filter(([k, v]) => /^\d+$/.test(k) && Array.isArray(v))
    .flatMap(([, v]) => v)
    .filter((i) => i && typeof i === "object" && "filterFlag" in i);
}
function renderInventory() {
  const items = inventoryItems()
    .filter((i) => i.filterFlag & filters[category])
    .sort((a, b) => String(a.text).localeCompare(String(b.text)));
  split(
    items,
    (i) => [
      i.text,
      `${i.equipState ? "◆ " : ""}${i.count > 1 ? "×" + i.count : ""}`,
    ],
    (i, p) => {
      p.append(el("h2", "", i.text));
      if (i.isLegendary) p.append(el("p", "muted", "Legendary"));
      const damage = [
        "",
        "Physical",
        "Poison",
        "Fire",
        "Energy",
        "Radiation",
        "Cryo",
      ];
      facts(
        p,
        arr(i.itemCardInfoList)
          .filter((v) => v.Value !== 0 || !v.damageType)
          .map((v) => [
            `${title(v.text)}${v.damageType && ["$dmg", "$dr"].includes(v.text) ? " · " + (damage[v.damageType] || v.damageType) : ""}`,
            typeof v.Value === "number"
              ? number(v.Value, v.precision || 0)
              : v.Value,
          ]),
      );
      if (i.description) p.append(el("p", "", i.description));
      const equip = !!(i.filterFlag & 6),
        usable = !!(i.filterFlag & (8 | 128 | 8192));
      if (equip || usable) {
        const row = el("div", "actions");
        row.append(
          action(
            equip
              ? i.equipState
                ? "Unequip"
                : "Equip"
              : i.filterFlag & 8192
                ? "Play"
                : "Use",
            { action: "use", id: i._id, version: state.data.Inventory.Version },
            Number.isInteger(i._id),
          ),
        );
        p.append(row);
      }
    },
    "No " + category.toLowerCase(),
  );
}
function renderData() {
  const d = state.data;
  if (category === "Quests") {
    split(
      arr(d.Quests),
      (i) => [i.text || i.Name, i.active ? "◆" : ""],
      (i, p) => {
        p.append(el("h2", "", i.text || i.Name));
        if (i.description) p.append(el("p", "", i.description));
        for (const objective of arr(i.objectives || i.Objectives)) {
          const row = el(
            "div",
            "objective" + (objective.completed ? " done" : ""),
          );
          row.append(
            el("span", "", objective.completed ? "✓" : "◇"),
            el("span", "", objective.text || objective.Name),
          );
          p.append(row);
        }
        const row = el("div", "actions");
        row.append(
          action(
            i.active ? "Stop tracking" : "Track quest",
            { action: "quest", id: i._id },
            Number.isInteger(i._id),
          ),
        );
        p.append(row);
      },
      "No quests",
    );
    return;
  }
  if (category === "Workshops") {
    split(
      arr(d.Workshop).filter((i) => i.owned),
      (i) => [i.text, i.rating < 0 ? "!" : ""],
      (i, p) => {
        p.append(el("h2", "", i.text));
        facts(
          p,
          arr(i.workshopData).map((v) => [v.text, number(v.Value)]),
        );
      },
      "No owned workshops",
    );
    return;
  }
  split(
    arr(d.Log),
    (i) => [title(i.text), ""],
    (i, p) => {
      p.append(el("h2", "", title(i.text)));
      facts(
        p,
        arr(i.statArray)
          .filter((v) => v.showIfZero || v.Value)
          .map((v) => [v.text, number(v.Value)]),
      );
    },
    "No statistics",
  );
}
function renderRadio() {
  split(
    arr(state.data.Radio),
    (i) => [i.text, i.active ? "ON" : i.inRange ? "" : "—"],
    (i, p) => {
      p.append(
        el("h2", "", i.text),
        el("p", "muted", i.inRange ? "Signal available" : "Out of range"),
      );
      if (i.frequency) facts(p, [["Frequency", number(i.frequency, 1)]]);
      const row = el("div", "actions"),
        b = action(
          i.active ? "Turn off" : "Tune in",
          { action: "radio", id: i._id },
          i.inRange !== false && Number.isInteger(i._id),
        );
      if (i.inRange === false) b.dataset.unavailable = "true";
      row.append(b);
      p.append(row);
    },
    "No radio stations",
  );
}
function updateChrome() {
  $("connection").textContent = reason();
  const p = state.data?.PlayerInfo;
  const vitals = $("vitals");
  vitals.replaceChildren();
  if (p && page === "STAT") {
    const hp = el(
      "div",
      "vital-hp",
      `HP ${Math.floor(p.CurrHP || 0)}/${Math.floor(p.MaxHP || 0)}`,
    );
    const level = el("div", "vital-level");
    level.append(el("span", "", `LEVEL ${number(p.XPLevel)}`));
    meter(level, Number(p.XPProgressPct) * 100);
    vitals.append(
      hp,
      level,
      el(
        "div",
        "vital-ap",
        `AP ${Math.floor(p.CurrAP || 0)}/${Math.floor(p.MaxAP || 0)}`,
      ),
    );
  }
  if (p && page === "INV") {
    const weight = el(
      "div",
      "vital-weight",
      `WT ${Math.floor(p.CurrWeight)}/${Math.floor(p.MaxWeight)}`,
    );
    const caps = el(
      "div",
      "vital-caps",
      `CAPS ${p.Caps >= 1000000 ? "1000000+" : number(p.Caps)}`,
    );
    const detail = el("div", "vital-inventory");
    if (category === "Aid") {
      detail.append(el("span", "", "HP"));
      meter(detail, p.MaxHP > 0 ? (p.CurrHP / p.MaxHP) * 100 : 0);
    }
    if (category === "Weapons" || category === "Apparel") {
      const values = category === "Weapons" ? p.TotalDamages : p.TotalResists;
      for (const v of arr(values).filter((v) => v.Value > 0)) {
        const icon =
          state.assets?.icons?.damage?.[
            Number(v.type) + (category === "Weapons" ? 5 : -1)
          ];
        if (icon) art(detail, icon);
        detail.append(el("span", "", number(Math.floor(v.Value))));
      }
    }
    vitals.append(weight, caps, detail);
  }
  if (p && (page === "DATA" || page === "MAP")) {
    const hour = Math.floor(p.TimeHour || 0),
      minute = Math.floor(((p.TimeHour || 0) - hour) * 60);
    vitals.append(
      el("div", "vital-date", `${p.DateMonth}.${p.DateDay}.2${p.DateYear}`),
      el(
        "div",
        "vital-clock",
        `${hour % 12 || 12}:${String(minute).padStart(2, "0")} ${hour < 12 ? "AM" : "PM"}`,
      ),
      el(
        "div",
        "vital-location",
        page === "MAP"
          ? state.data.Map?.CurrCell || state.data.Map?.CurrWorldspace || ""
          : "",
      ),
    );
  }
  $("context").textContent = "";
  const quick = $("quick-actions");
  if (page === "STAT" && category === "Status" && p) {
    quick.replaceChildren();
    const stats = state.data.Stats || {};
    quick.append(
      action(
        `STIMPAK (${stats.StimpakCount || 0})`,
        { action: "stimpak", version: state.data.Inventory?.Version },
        stats.StimpakCount > 0,
      ),
      action(
        `RADAWAY (${stats.RadawayCount || 0})`,
        { action: "radaway", version: state.data.Inventory?.Version },
        stats.RadawayCount > 0,
      ),
    );
    quick.append(
      button("PERKS", () => {
        category = "Perks";
        selection = null;
        signature = "";
        render();
      }),
    );
  }
  for (const b of quick.querySelectorAll("[data-game-action]"))
    b.disabled = !!reason() || b.dataset.unavailable === "true";
  const note =
    typeof state.notice === "string" ? state.notice : state.notice?.message;
  if (note && note !== lastNotice) {
    $("notice").textContent = note;
    lastNotice = note;
  } else if (Date.now() > pendingUntil + 2000) $("notice").textContent = "";
}

function cancelConfirm(notify = true) {
  const had = confirmToken;
  confirmToken = null;
  clearTimeout(confirmTimer);
  clearTimeout(confirmReadyTimer);
  $("confirmation").hidden = true;
  if (had) {
    dismissedToken = had;
    if (notify) bridge.send({ action: "cancel" });
  }
}
function confirmation() {
  const c = state.confirm;
  if (!c || reason()) {
    cancelConfirm(false);
    return;
  }
  if (c.token === confirmToken || c.token === dismissedToken) return;
  cancelConfirm(false);
  confirmToken = c.token;
  $("confirm-title").textContent = c.label || "Confirm action";
  $("confirm-description").textContent =
    "This changes the game. Tap Confirm to continue.";
  $("confirmation").hidden = false;
  $("confirm").disabled = true;
  const bar = $("confirmation").querySelector(".timeout");
  bar.style.animation = "none";
  void bar.offsetWidth;
  bar.style.animation = "";
  confirmReadyTimer = setTimeout(() => {
    $("confirm").disabled = false;
  }, 350);
  const remaining = Math.min(5000, Math.max(0, c.expires * 1000 - Date.now()));
  confirmTimer = setTimeout(() => cancelConfirm(), remaining);
}
$("cancel").onclick = () => cancelConfirm();
$("confirmation").onclick = (e) => {
  if (e.target === $("confirmation")) cancelConfirm();
};
$("confirm").onclick = () => {
  const token = confirmToken;
  if (!token || $("confirm").disabled) return;
  cancelConfirm(false);
  if (!reason()) {
    bridge.send({ action: "confirm", token });
    pendingUntil = Date.now() + 450;
    $("notice").textContent = "Sent to game…";
  }
};
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") cancelConfirm();
});
// Map coordinates are an affine plane; the three extents also cover rotated local maps.
let mapView = { zoom: 1, x: 0, y: 0 },
  mapIdentity = "",
  mapGeometry = null,
  mapSelected = null,
  mapMarkers = [],
  mapDrag = null;
const pointers = new Map();
const markerNames =
  "Cave City DiamondCity Encampment Factory Monument Metro MilitaryBase Landmark Office TownRuins UrbanRuins SancHills Settlement Sewer Vault Airfield BunkerHill Camper Car Church CountryClub CustomHouse DriveIn ElevatedHighway FaneuilHall Farm FillingStation Forested Goodneighbor Graveyard Hospital IndustrialDome IndustrialStacks Institute IrishPride Junkyard Observatory Pier PondLake Quarry RadioactiveArea RadioTower Salem School Shipwreck Submarine SwanPond SynthHead Town BoS Brownstone Bunker Castle Skyscraper Libertalia LowRise Minutemen PoliceStation Prydwen RailroadFaction Railroad Satellite Sentinel USSConstitution Door Quest QuestMarkerDoor Quest PlayerSet PlayerLoc PowerArmorLoc"
    .split(" ")
    .map((n) => (n.endsWith("MarkerDoor") ? n : n + "Marker"));
const tinted = new Map();
function markerImage(marker, ink) {
  const name =
    marker.kind === "location"
      ? localMode()
        ? "DoorMarker"
        : markerNames[marker.obj.type]
      : {
          quest: "QuestMarker",
          custom: "PlayerSetMarker",
          player: "PlayerLocMarker",
          armor: "PowerArmorLocMarker",
        }[marker.kind];
  const img = picture(state.assets?.markers?.[name]);
  if (!img?.complete || !img.naturalWidth) return null;
  const k = img.src + ink;
  if (!tinted.has(k)) {
    const c = document.createElement("canvas");
    c.width = c.height = 80;
    const ctx = c.getContext("2d");
    ctx.drawImage(img, 0, 0, 80, 80);
    ctx.globalCompositeOperation = "multiply";
    ctx.fillStyle = ink;
    ctx.fillRect(0, 0, 80, 80);
    ctx.globalCompositeOperation = "destination-in";
    ctx.drawImage(img, 0, 0, 80, 80);
    if (tinted.size >= 128) tinted.delete(tinted.keys().next().value);
    tinted.set(k, c);
  }
  return tinted.get(k);
}
function localMode() {
  return category === "Local";
}
function mapData() {
  return state.data?.Map?.[localMode() ? "Local" : "World"] || {};
}
function tintMap(img, ink) {
  const id = img.src + ink + "map";
  if (!tinted.has(id)) {
    const c = document.createElement("canvas");
    c.width = img.naturalWidth;
    c.height = img.naturalHeight;
    const ctx = c.getContext("2d");
    ctx.filter = "grayscale(1) brightness(1.8)";
    ctx.drawImage(img, 0, 0);
    ctx.filter = "none";
    ctx.globalCompositeOperation = "multiply";
    ctx.fillStyle = ink;
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.globalCompositeOperation = "destination-in";
    ctx.drawImage(img, 0, 0);
    if (tinted.size >= 128) tinted.delete(tinted.keys().next().value);
    tinted.set(id, c);
  }
  return tinted.get(id);
}
function mapExtents() {
  const raw = localMode()
    ? state.localMap?.extents || mapData().Extents
    : mapData().Extents;
  if (!raw) return null;
  const e = Array.isArray(raw)
    ? {
        NWX: raw[0],
        NWY: raw[1],
        NEX: raw[2],
        NEY: raw[3],
        SWX: raw[4],
        SWY: raw[5],
      }
    : raw;
  return ["NWX", "NWY", "NEX", "NEY", "SWX", "SWY"].every((k) =>
    Number.isFinite(e[k]),
  )
    ? e
    : null;
}
function worldToUV(x, y) {
  const e = mapExtents();
  if (!e) return null;
  const ax = e.NEX - e.NWX,
    ay = e.NEY - e.NWY,
    bx = e.SWX - e.NWX,
    by = e.SWY - e.NWY,
    det = ax * by - ay * bx;
  if (!Number.isFinite(det) || Math.abs(det) < 0.001) return null;
  return {
    u: ((x - e.NWX) * by - (y - e.NWY) * bx) / det,
    v: (ax * (y - e.NWY) - ay * (x - e.NWX)) / det,
  };
}
function screenToWorld(x, y) {
  const e = mapExtents(),
    g = mapGeometry;
  if (!e || !g) return null;
  const u = (x - g.x) / g.w,
    v = (y - g.y) / g.h;
  if (u < 0 || u > 1 || v < 0 || v > 1) return null;
  return {
    x: e.NWX + u * (e.NEX - e.NWX) + v * (e.SWX - e.NWX),
    y: e.NWY + u * (e.NEY - e.NWY) + v * (e.SWY - e.NWY),
  };
}
function mapAsset() {
  if (localMode()) return state.localMap?.url || state.localMap?.path;
  const maps = state.assets?.maps || {},
    world = (state.data?.Map?.CurrWorldspace || "").toLowerCase();
  if (/far harbor|farharbor|dlc03/.test(world)) return maps.farHarbor;
  if (/nuka|dlc04/.test(world)) return maps.nukaWorld;
  if (/commonwealth/.test(world)) return maps.commonwealth;
  return null;
}
function buildMap() {
  const outer = el("div", "map-wrap"),
    canvas = el("canvas");
  canvas.id = "map-canvas";
  canvas.setAttribute(
    "aria-label",
    "Map. Drag to pan, pinch or use buttons to zoom. Tap a location for details.",
  );
  const caption = el("div", "map-caption");
  caption.id = "map-caption";
  const controls = el("div", "map-tools");
  controls.append(
    button("+", () => zoomMap(1.5)),
    button("−", () => zoomMap(1 / 1.5)),
    button("◎", () => centerPlayer()),
    button("↺", () => {
      mapView = { zoom: 1, x: 0, y: 0 };
      drawMap();
    }),
  );
  controls.children[0].ariaLabel = "Zoom in";
  controls.children[1].ariaLabel = "Zoom out";
  controls.children[2].ariaLabel = "Center on player";
  controls.children[3].ariaLabel = "Reset map";
  if (localMode())
    controls.append(button("Refresh", () => send({ action: "localmap" })));
  const selected = el("div", "map-selection");
  selected.id = "map-selection";
  const hint = el(
    "div",
    "map-hint",
    "Drag to pan · Pinch to zoom · Tap to place a marker",
  );
  hint.id = "map-hint";
  outer.append(canvas, caption, controls, selected, hint);
  $("content").replaceChildren(outer);
  canvas.addEventListener("pointerdown", mapDown);
  canvas.addEventListener("pointermove", mapMove);
  canvas.addEventListener("pointerup", mapUp);
  canvas.addEventListener("pointercancel", () => {
    pointers.clear();
    mapDrag = null;
  });
  canvas.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const box = canvas.getBoundingClientRect();
      zoomMap(
        e.deltaY < 0 ? 1.15 : 1 / 1.15,
        e.clientX - box.left,
        e.clientY - box.top,
      );
    },
    { passive: false },
  );
}
function zoomMap(factor, cx, cy) {
  const canvas = $("map-canvas");
  if (!canvas) return;
  const w = canvas.clientWidth,
    h = canvas.clientHeight;
  cx ??= w / 2;
  cy ??= h / 2;
  const next = Math.max(1, Math.min(12, mapView.zoom * factor)),
    ratio = next / mapView.zoom;
  mapView.x = (mapView.x + w / 2 - cx) * ratio + cx - w / 2;
  mapView.y = (mapView.y + h / 2 - cy) * ratio + cy - h / 2;
  mapView.zoom = next;
  drawMap();
}
function centerPlayer() {
  const point = mapData().Player,
    uv = point && worldToUV(point.X, point.Y),
    canvas = $("map-canvas");
  if (!uv || !canvas) return;
  const size = Math.min(canvas.clientWidth, canvas.clientHeight) * mapView.zoom;
  mapView.x = (0.5 - uv.u) * size;
  mapView.y = (0.5 - uv.v) * size;
  drawMap();
}
function drawMap() {
  const canvas = $("map-canvas");
  if (!canvas) return;
  const identity =
    category +
    ":" +
    (localMode() ? state.data?.Map?.CurrCell : state.data?.Map?.CurrWorldspace);
  if (identity !== mapIdentity) {
    mapIdentity = identity;
    mapView = { zoom: 1, x: 0, y: 0 };
    mapSelected = null;
  }
  const width = canvas.clientWidth,
    height = canvas.clientHeight;
  if (!width || !height) return;
  const scale = window.devicePixelRatio || 1;
  if (
    canvas.width !== Math.round(width * scale) ||
    canvas.height !== Math.round(height * scale)
  ) {
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const ink =
    getComputedStyle(document.documentElement)
      .getPropertyValue("--ink")
      .trim() || "#65ff78";
  const size = Math.min(width, height) * mapView.zoom;
  const x = (width - size) / 2 + mapView.x,
    y = (height - size) / 2 + mapView.y;
  mapGeometry = { x, y, w: size, h: size };
  const img = picture(mapAsset());
  ctx.fillStyle = "#0a190e";
  ctx.fillRect(x, y, size, size);
  if (img?.complete && img.naturalWidth) {
    ctx.save();
    ctx.drawImage(tintMap(img, ink), x, y, size, size);
    ctx.restore();
  } else {
    ctx.strokeStyle = "#17331e";
    ctx.lineWidth = 1;
    for (let n = 0; n <= 10; n++) {
      ctx.beginPath();
      ctx.moveTo(x + (n * size) / 10, y);
      ctx.lineTo(x + (n * size) / 10, y + size);
      ctx.moveTo(x, y + (n * size) / 10);
      ctx.lineTo(x + size, y + (n * size) / 10);
      ctx.stroke();
    }
  }
  const m = mapData();
  mapMarkers = [];
  for (const loc of arr(localMode() ? m.Doors : m.Locations)) {
    if (loc.Visible)
      mapMarkers.push({
        obj: loc,
        kind: "location",
        label: loc.Name || "Location",
      });
  }
  for (const q of arr(m.Quests)) {
    if (q.Visible !== false)
      mapMarkers.push({
        obj: q,
        kind: "quest",
        label: q.Name || q.text || "Quest objective",
      });
  }
  if (m.Custom?.Visible)
    mapMarkers.push({ obj: m.Custom, kind: "custom", label: "Custom marker" });
  if (m.PowerArmor?.Visible)
    mapMarkers.push({ obj: m.PowerArmor, kind: "armor", label: "Power armor" });
  if (m.Player)
    mapMarkers.push({ obj: m.Player, kind: "player", label: "You" });
  const r = Math.max(8, height * 0.022);
  for (const marker of mapMarkers) {
    const p = worldToUV(marker.obj.X, marker.obj.Y);
    if (!p) continue;
    marker.x = x + p.u * size;
    marker.y = y + p.v * size;
    if (
      marker.x < -r ||
      marker.x > width + r ||
      marker.y < -r ||
      marker.y > height + r
    )
      continue;
    ctx.save();
    ctx.translate(marker.x, marker.y);
    ctx.strokeStyle = ink;
    ctx.fillStyle = ink;
    ctx.lineWidth = 2;
    ctx.shadowColor = "#000";
    ctx.shadowBlur = 3;
    const chosen =
      mapSelected?.id === key(marker.obj) && mapSelected?.kind === marker.kind;
    if (chosen) {
      ctx.beginPath();
      ctx.arc(0, 0, r * 1.8, 0, 2 * Math.PI);
      ctx.stroke();
    }
    const sprite = markerImage(marker, ink);
    if (sprite) {
      if (marker.kind === "player")
        ctx.rotate((Number(marker.obj.Rotation || 0) * Math.PI) / 180);
      ctx.globalAlpha = marker.obj.Discovered === false ? 0.5 : 1;
      ctx.drawImage(sprite, -r, -r, r * 2, r * 2);
    } else if (marker.kind === "player") {
      ctx.rotate((Number(marker.obj.Rotation || 0) * Math.PI) / 180);
      ctx.beginPath();
      ctx.moveTo(0, -r);
      ctx.lineTo(r * 0.75, r);
      ctx.lineTo(0, r * 0.55);
      ctx.lineTo(-r * 0.75, r);
      ctx.closePath();
      ctx.fill();
    } else if (marker.kind === "quest" || marker.kind === "custom") {
      ctx.beginPath();
      ctx.moveTo(0, -r);
      ctx.lineTo(r, 0);
      ctx.lineTo(0, r);
      ctx.lineTo(-r, 0);
      ctx.closePath();
      if (marker.kind === "quest") ctx.fill();
      else ctx.stroke();
    } else {
      ctx.globalAlpha = marker.obj.Discovered === false ? 0.5 : 1;
      ctx.strokeRect(-r * 0.65, -r * 0.65, r * 1.3, r * 1.3);
      if (marker.kind === "armor") {
        ctx.beginPath();
        ctx.moveTo(-r, 0);
        ctx.lineTo(r, 0);
        ctx.stroke();
      }
    }
    ctx.restore();
  }
  $("map-caption").textContent =
    img?.complete && img.naturalWidth
      ? localMode()
        ? "LOCAL MAP"
        : state.data?.Map?.CurrWorldspace || "WORLD MAP"
      : localMode()
        ? "Request a local map snapshot"
        : "Map image unavailable · Live markers";
  updateMapSelection();
}
function updateMapSelection() {
  const panel = $("map-selection");
  if (!panel) return;
  panel.replaceChildren();
  $("map-hint").hidden = !!mapSelected;
  if (!mapSelected) return;
  if (mapSelected.kind === "point") {
    panel.append(
      el("span", "", "Place custom marker here?"),
      action("Place", {
        action: "marker",
        x: mapSelected.x,
        y: mapSelected.y,
        local: localMode(),
      }),
    );
  } else {
    const marker = mapMarkers.find(
      (m) => key(m.obj) === mapSelected.id && m.kind === mapSelected.kind,
    );
    if (!marker) {
      mapSelected = null;
      return;
    }
    panel.append(el("span", "", marker.label));
    if (marker.kind === "custom")
      panel.append(action("Remove", { action: "clear-marker" }));
    if (marker.kind === "location" && marker.obj.Discovered && !localMode())
      panel.append(
        action(
          "Travel",
          { action: "travel", id: marker.obj._id },
          Number.isInteger(marker.obj._id),
        ),
      );
  }
  panel.append(
    button("×", () => {
      mapSelected = null;
      drawMap();
    }),
  );
}
function point(e) {
  const b = $("map-canvas").getBoundingClientRect();
  return { x: e.clientX - b.left, y: e.clientY - b.top };
}
function mapDown(e) {
  e.preventDefault();
  cancelConfirm();
  const p = point(e);
  pointers.set(e.pointerId, p);
  e.target.setPointerCapture(e.pointerId);
  mapDrag = { start: p, last: p, moved: false };
  if (pointers.size === 2) {
    const [a, b] = [...pointers.values()];
    mapDrag = {
      distance: Math.hypot(a.x - b.x, a.y - b.y),
      center: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
      moved: true,
    };
  }
}
function mapMove(e) {
  if (!pointers.has(e.pointerId) || !mapDrag) return;
  e.preventDefault();
  const p = point(e);
  pointers.set(e.pointerId, p);
  if (pointers.size >= 2) {
    const [a, b] = [...pointers.values()],
      distance = Math.hypot(a.x - b.x, a.y - b.y),
      center = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    if (mapDrag.distance) {
      mapView.x += center.x - mapDrag.center.x;
      mapView.y += center.y - mapDrag.center.y;
      zoomMap(distance / mapDrag.distance, center.x, center.y);
    }
    mapDrag = { distance, center, moved: true };
    return;
  }
  if (!mapDrag.last) {
    mapDrag = { start: p, last: p, moved: true };
    return;
  }
  if (Math.hypot(p.x - mapDrag.start.x, p.y - mapDrag.start.y) > 8)
    mapDrag.moved = true;
  if (mapDrag.moved) {
    mapView.x += p.x - mapDrag.last.x;
    mapView.y += p.y - mapDrag.last.y;
    drawMap();
  }
  mapDrag.last = p;
}
function mapUp(e) {
  if (!pointers.has(e.pointerId)) return;
  const p = point(e),
    tap = mapDrag && !mapDrag.moved && pointers.size === 1;
  pointers.delete(e.pointerId);
  if (tap) {
    const near = mapMarkers
      .filter((m) => Number.isFinite(m.x))
      .map((m) => ({ m, d: Math.hypot(m.x - p.x, m.y - p.y) }))
      .sort((a, b) => a.d - b.d)[0];
    if (near && near.d < 28)
      mapSelected = { kind: near.m.kind, id: key(near.m.obj) };
    else {
      const world = screenToWorld(p.x, p.y);
      mapSelected = world ? { kind: "point", ...world } : null;
    }
    drawMap();
  }
  mapDrag = pointers.size ? { moved: true } : null;
}
for (const type of ["gesturestart", "gesturechange", "gestureend"])
  document.addEventListener(type, (e) => e.preventDefault(), {
    passive: false,
  });
document.addEventListener("dragstart", (e) => e.preventDefault());
window.addEventListener("resize", () => {
  if (page === "MAP") drawMap();
});
bridge.onState = (next) => {
  state = next || {};
  const color = state.data?.Status?.EffectColor;
  if (
    Array.isArray(color) &&
    color.length >= 3 &&
    color.slice(0, 3).every(Number.isFinite)
  ) {
    const rgb = color
      .slice(0, 3)
      .map((v) => Math.round(Math.max(0, Math.min(1, v)) * 255));
    document.documentElement.style.setProperty(
      "--ink",
      `rgb(${rgb.join(",")})`,
    );
  }
  loadFonts();
  window.PipboyCRT?.update(state);
  for (const [key, css] of [
    ["dust", "--glass-image"],
    ["scanlines", "--scanline-image"],
  ]) {
    const url = assetUrl(state.assets?.effects?.[key]?.path);
    if (url) document.documentElement.style.setProperty(css, `url("${url}")`);
  }
  render();
  confirmation();
};
setInterval(() => {
  updateChrome();
}, 1000);
const loadedFonts = new Set();
function loadFonts() {
  for (const [key, weight] of [
    ["main", "400"],
    ["bold", "700"],
  ]) {
    const path = state.assets?.fonts?.[key]?.path;
    if (!path || loadedFonts.has(path)) continue;
    loadedFonts.add(path);
    const face = new FontFace("PipBoy", `url("${assetUrl(path)}")`, { weight });
    face
      .load()
      .then((font) => document.fonts.add(font))
      .catch(() => loadedFonts.delete(path));
  }
}
function animatedArt(parent, kind, name = "") {
  const canvas = el("canvas", "art animated");
  canvas.dataset.animation = kind;
  canvas.dataset.animationName = name;
  canvas.setAttribute("aria-hidden", "true");
  parent.append(canvas);
}
let animationTick = 0;
function animate(now) {
  requestAnimationFrame(animate);
  if (now - animationTick < 1000 / 30) return;
  animationTick = now;
  renderAnimations(now);
}
function renderAnimations(now) {
  for (const canvas of document.querySelectorAll("canvas[data-animation]")) {
    const status = canvas.dataset.animation === "status";
    const entry = status
      ? state.assets?.animations?.status?.bodies?.[
          String(state.data?.Stats?.BodyFlags || 0)
        ]
      : state.assets?.animations?.special?.[canvas.dataset.animationName];
    if (!entry?.frames?.length) continue;
    const index =
      Math.floor((now / 1000) * (entry.fps || 30)) % entry.frames.length;
    const body = picture(entry.frames[index]);
    const heads = state.assets?.animations?.status?.heads;
    const headIndex = Math.max(
      0,
      Math.min(
        (heads?.frames?.length || 1) - 1,
        state.data?.Stats?.HeadFlags || 0,
      ),
    );
    const head = status && heads ? picture(heads.frames[headIndex]) : null;
    const transform = status ? entry.headTransforms?.[index] : null;
    if (
      !body?.complete ||
      !body.naturalWidth ||
      (status && head && !head.complete)
    )
      continue;
    const rect = canvas.getBoundingClientRect();
    const width = Math.round(rect.width * (devicePixelRatio || 1)),
      height = Math.round(rect.height * (devicePixelRatio || 1));
    const baseInk = getComputedStyle(document.documentElement).color;
    const channels = baseInk
      .match(/[\d.]+/g)
      ?.slice(0, 3)
      .map(Number) || [20, 255, 23];
    const ink = status
      ? `rgb(${channels.map((v) => v * 0.5).join(",")})`
      : baseInk;
    const stamp =
      entry.frames[index] +
      headIndex +
      JSON.stringify(transform) +
      ink +
      width +
      height;
    if (canvas.dataset.frame === stamp) continue;
    canvas.dataset.frame = stamp;
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d"),
      box = entry.viewBox;
    const scale = status
      ? width / 799.8
      : Math.min(width / box[2], height / box[3]);
    ctx.save();
    if (status) {
      ctx.scale(scale, scale);
      ctx.translate(386.85, 193.7);
      ctx.scale(1.2 / 20, 1.2 / 20);
    } else {
      ctx.translate(
        (width - box[2] * scale) / 2,
        (height - box[3] * scale) / 2,
      );
      ctx.scale(scale, scale);
      ctx.translate(-box[0], -box[1]);
    }
    ctx.drawImage(body, box[0], box[1], box[2], box[3]);
    if (status && head?.complete && head.naturalWidth && transform) {
      ctx.transform(...transform);
      ctx.drawImage(head, ...heads.viewBox);
    }
    ctx.restore();
    const mask =
      canvas._mask || (canvas._mask = document.createElement("canvas"));
    mask.width = width;
    mask.height = height;
    mask.getContext("2d").drawImage(canvas, 0, 0);
    ctx.globalCompositeOperation = "multiply";
    ctx.fillStyle = ink;
    ctx.fillRect(0, 0, width, height);
    ctx.globalCompositeOperation = "destination-in";
    ctx.drawImage(mask, 0, 0);
    ctx.globalCompositeOperation = "source-over";
  }
}
requestAnimationFrame(animate);
if (bridge.last) bridge.onState(bridge.last);
else render();
