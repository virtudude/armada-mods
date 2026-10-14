// Armada second-screen provider for CrossCode. Sends structured game state to
// the host's HTML view and executes actions the view sends back.
(function () {
  if (window !== window.top || window.__armadaSecondScreen) return;
  window.__armadaSecondScreen = true;
  var net = (window.require || (window.nw && nw.require))("net");
  var HELLO = 1, STATE = 3, INPUT = 16, CMD = 18;
  var sock = null, last = "", inbuf = Buffer.alloc(0), used = null, dead = false;

  function send(type, obj) {
    // a host that has stopped reading is not sent more
    if (!sock || sock.writableLength > 1 << 20) return false;
    var body = Buffer.from(typeof obj === "string" ? obj : JSON.stringify(obj), "utf8");
    var hd = Buffer.alloc(16);
    hd.write("A2SS", 0, "ascii"); hd.writeUInt16LE(type, 4); hd.writeUInt32LE(body.length, 8);
    try { sock.write(Buffer.concat([hd, body])); } catch (e) { return false; }
    return true;
  }

  function connect() {
    var s = net.connect(47800, "127.0.0.1");
    s.on("connect", function () {
      sock = s; last = ""; inbuf = Buffer.alloc(0); assets = {}; pending = null;
      send(HELLO, { game: "CrossCode", appid: 368340, provider: "crosscode-status", view: "html", version: 1 });
    });
    s.on("data", function (d) {
      inbuf = Buffer.concat([inbuf, d]);
      while (inbuf.length >= 16) {
        var len = inbuf.readUInt32LE(8);
        if (inbuf.length < 16 + len) break;
        var type = inbuf.readUInt16LE(4), text = inbuf.slice(16, 16 + len).toString("utf8");
        inbuf = inbuf.slice(16 + len);
        try { handle(type, text); } catch (e) { send(STATE, { reply: "error: " + e }); }
      }
    });
    var retry = function () { if (sock === s || !sock) { sock = null; if (!dead) setTimeout(connect, 1500); } s.removeAllListeners(); s.on("error", function () {}); };
    s.on("error", retry); s.on("close", retry);
  }

  function handle(type, text) {
    if (type === CMD && process.env.ARMADA_MOD_DEV) {
      // development aid: evaluate an expression in the game and reply
      var r; try { r = (0, eval)(text); } catch (e) { r = "error: " + e; }
      try { r = typeof r === "string" ? r : JSON.stringify(r); } catch (e) { r = String(r); }
      send(STATE, { reply: String(r).slice(0, 20000) });
    } else if (type === INPUT) {
      var m = JSON.parse(text);
      if (m.action === "useItem") {
        var ok = canUse(m.id);
        if (ok) ig.game.playerEntity.useItem(m.id);
        used = { id: m.id, ok: ok, n: (used ? used.n : 0) + 1 };
      } else if (m.action === "element" && canSwitch(m.mode)) {
        sc.model.player.setElementMode(m.mode);
      } else if (m.action === "assets") {
        // a view that has just loaded has none of the art yet
        assets = {}; last = "";
      }
    }
  }

  function inGame() {
    return !!(window.sc && sc.model && sc.model.isGame && sc.model.isGame() && ig.game && ig.game.playerEntity);
  }
  function canSwitch(mode) {
    var p = sc.model.player;
    // what the game asks before it switches on a button, and what its own function leaves to the caller
    return inGame() && !sc.model.isCutscene() && [0, 1, 2, 3, 4].indexOf(mode) >= 0 && !!p.hasElement(mode) && !!p.getCore(sc.PLAYER_CORE.ELEMENT_CHANGE) &&
      !p.hasOverload && !ig.game.playerEntity.isElementChangeBlocked();
  }
  function canUse(id) {
    var p = sc.model.player;
    return inGame() && p.getItemAmount(id) > 0 && sc.inventory.isConsumable(id) && !(p.itemBlockTimer > 0) && !sc.model.isCutscene();
  }
  function text(l) {
    if (l && typeof l.value === "string") return l.value;
    try { return ig.LangLabel.getText(l) || String(l); } catch (e) { return ""; }
  }
  function clean(s) {
    return String(s || "").replace(/\\v\[([^\]]+)\]/g, function (m, path) { try { return String(ig.vars.get(path)); } catch (e) { return ""; } })
      .replace(/\\[cCsSiIvV]\[[^\]]*\]/g, "").replace(/\\\./g, "");
  }

  // Art the view draws with is cut from the running game's own images and sent once per link.
  var assets = {}, pending = null;
  function asset(key, draw) {
    // a picture the game has not loaded yet is tried again a few times
    var tries = assets[key] || 0;
    if (tries === true || tries >= 5) return key;
    try { var url = draw(); if (url) { pending = pending || {}; pending[key] = url; } assets[key] = true; } catch (e) { assets[key] = tries + 1; }
    return key;
  }
  function icon(name) {
    return asset("i:" + name, function () {
      var f = sc.fontsystem.font, m = f.mapping[name];
      if (!m) return "";
      var set = f.iconSets[m[0]], i = m[1], e = ig.system.scale, w = (set.widthMap[i] + 1) * e, h = set.charHeight * e;
      var c = document.createElement("canvas"); c.width = w; c.height = h;
      c.getContext("2d").drawImage(set.data, set.indicesX[i] * e, set.indicesY[i] * e, w, h, 0, 0, w, h);
      return c.toDataURL();
    });
  }
  var lea = null;
  function face(expr) {
    return asset("f:" + expr, function () {
      lea = lea || new sc.Character("main.lea");
      var f = lea.data.face, names = (f.expressions[expr] || f.expressions.DEFAULT).faces[0], e = ig.system.scale;
      var c = document.createElement("canvas"); c.width = f.width * e; c.height = f.height * e;
      var g = c.getContext("2d"), x = 0, y = 0;
      for (var k = 0; k < names.length; k++) {
        var part = f.parts[k][names[k]];
        if (part.img) throw "needs a second image";
        g.drawImage(lea.faceImage.data, part.srcX * e, part.srcY * e, part.width * e, part.height * e, (x + part.destX) * e, (y + part.destY) * e, part.width * e, part.height * e);
        x += part.subX || 0; y += part.subY || 0;
      }
      return c.toDataURL();
    });
  }
  function itemIcon(it) { return icon((it.icon || "item-default") + sc.inventory.getRaritySuffix(it.rarity || 0)); }

  function snapshot() {
    if (!(window.sc && sc.model && sc.model.player && sc.model.player.params)) return { ready: false };
    if (sc.model.isTitle()) return { ready: false, title: true };
    var p = sc.model.player, pr = p.params, out = { ready: true, inGame: inGame() };
    var hp = Math.round(pr.currentHp), maxHp = pr.getStat("hp");
    var combat = false; try { combat = out.inGame && sc.combat.isInCombat(ig.game.playerEntity); } catch (e) {}
    out.player = {
      name: p.name || "Lea", level: p.level, exp: p.exp, expMax: sc.EXP_PER_LEVEL, credit: p.credit,
      hp: hp, maxHp: maxHp, sp: pr.currentSp, maxSp: pr.maxSp,
      attack: pr.getStat("attack"), defense: pr.getStat("defense"), focus: pr.getStat("focus"),
      element: p.currentElementMode, itemBlocked: p.itemBlockTimer > 0, combat: combat,
      canSwitch: !!p.getCore(sc.PLAYER_CORE.ELEMENT_CHANGE), elements: [], res: [],
      face: face(hp < maxHp * 0.3 ? "EXHAUSTED" : combat ? "DETERMINED" : "DEFAULT")
    };
    ["neutral", "heat", "cold", "shock", "wave"].forEach(function (n, i) {
      out.player.elements.push({ has: !!p.hasElement(i), icon: icon("element-" + n) });
      if (i) out.player.res.push(Math.round((1 - pr.getStat("elemFactor")[i - 1]) * 100));
    });
    ["hp", "attack", "defense", "focus"].forEach(function (n) { icon("stat-" + n); });
    out.buffs = [];
    for (var b = 0; b < pr.buffs.length; b++) {
      var bf = pr.buffs[b], icons = [];
      String(bf.iconString || "").replace(/\\i\[([^\]]+)\]/g, function (m, n) { icons.push(icon(n)); });
      out.buffs.push({ icons: icons, left: bf.getTimeFactor ? bf.getTimeFactor() : 1 });
    }
    try { out.area = clean(sc.map.getCurrentAreaName().toString()); } catch (e) { out.area = ""; }
    try { out.map = clean(sc.map.getCurrentMapName ? String(sc.map.getCurrentMapName()) : ""); } catch (e) { out.map = ""; }
    try {
      var path = sc.map.currentArea.path, total = sc.map.getChestCount(path);
      if (total) out.chests = [Math.min(sc.stats.getMap("chests", path) || 0, total), total];
    } catch (e) {}
    out.time = Math.floor(sc.stats.getMap("player", "playtime") || 0);
    out.equip = [];
    var slots = { head: "Head", rightArm: "Right arm", leftArm: "Left arm", torso: "Torso", feet: "Feet" };
    for (var k in slots) {
      var id = p.equip[k], eq = id >= 0 ? sc.inventory.getItem(id) : null;
      out.equip.push({ slot: slots[k], name: eq ? clean(text(eq.name)) : "", level: eq ? eq.level || 0 : 0,
                       icon: eq ? itemIcon(eq) : "", params: eq && eq.params || {} });
    }
    out.items = [];
    for (var i = 0; i < p.items.length; i++) {
      if (!p.items[i] || !sc.inventory.isConsumable(i)) continue;
      var it = sc.inventory.getItem(i);
      out.items.push({ id: i, name: clean(text(it.name)), count: p.items[i], desc: clean(text(it.description)), icon: itemIcon(it) });
    }
    out.used = used;
    out.party = [];
    try {
      (sc.party.currentParty || []).forEach(function (n) {
        var m = sc.party.getPartyMemberModel(n);
        if (m) out.party.push({ name: n, level: m.level, hp: Math.round(m.params.currentHp), maxHp: m.params.getStat("hp") });
      });
    } catch (e) {}
    out.quests = [];
    try {
      var qs = sc.quests.activeQuests || [];
      for (var q = 0; q < qs.length && out.quests.length < 6; q++) {
        var st = qs[q].quest, task = st && st.tasks[qs[q].currentTask];
        if (!st || !task) continue;
        var subs = [];
        task.subTasks.forEach(function (s, n) {
          var state = (qs[q].done[qs[q].currentTask] || [])[n], sub = { text: s.text || s.short ? clean(text(s.text || s.short)) : "", done: false };
          try { sub.done = !!s.isFulfilled(state); } catch (e) {}
          try { if (s.amount > 1) { sub.max = s.amount; sub.cur = Math.min(s.getCurrentValue(state) || 0, s.amount); } } catch (e) {}
          subs.push(sub);
        });
        out.quests.push({ name: clean(text(st.name)), desc: clean(text(st.description)), level: st.level, task: clean(text(task.task)),
                          step: qs[q].currentTask + 1, steps: st.tasks.length, subs: subs, fav: sc.quests.focusQuest === q });
      }
    } catch (e) {}
    return out;
  }

  // A provider that keeps failing (for example after a game update) lets go of the screen.
  var failures = 0, timer = setInterval(function () {
    if (!sock) return;
    var s;
    try { s = JSON.stringify(snapshot()); failures = 0; }
    catch (e) {
      s = JSON.stringify({ ready: false, visible: false });
      if (++failures > 50) { clearInterval(timer); dead = true; try { sock.destroy(); } catch (e2) {} return; }
    }
    if (pending && send(STATE, { assets: pending })) pending = null;
    if (s !== last && send(STATE, s)) last = s;
  }, 200);
  connect();
})();
