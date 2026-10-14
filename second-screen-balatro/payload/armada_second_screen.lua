-- Armada second-screen provider for Balatro. Sends run state to the host's
-- HTML view and runs the few actions the view sends back.
local socket = require("socket")
local HELLO, STATE, INPUT, CMD = 1, 3, 16, 18
local sock, outbuf, inbuf, last, acc, retry = nil, "", "", "", 0, 0
local failures, dead, acc_total = 0, false, 0

local function u16(n) return string.char(n % 256, math.floor(n / 256) % 256) end
local function u32(n) return u16(n % 65536) .. u16(math.floor(n / 65536)) end
local function frame(t, body) return "A2SS" .. u16(t) .. u16(0) .. u32(#body) .. u32(0) .. body end

local function esc(s)
  return (tostring(s):gsub('[%c"\\]', function(c)
    if c == '"' then return '\\"' elseif c == "\\" then return "\\\\" else return string.format("\\u%04x", c:byte()) end
  end))
end
local function json(v)
  local t = type(v)
  if t == "table" then
    local parts = {}
    if #v > 0 or next(v) == nil then
      for i = 1, #v do parts[i] = json(v[i]) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    for k, x in pairs(v) do parts[#parts + 1] = '"' .. esc(k) .. '":' .. json(x) end
    return "{" .. table.concat(parts, ",") .. "}"
  elseif t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "0" end
    return tostring(v)
  elseif t == "boolean" then return tostring(v)
  elseif t == "nil" then return "null" end
  return '"' .. esc(v) .. '"'
end

local function name_of(card)
  local c = card.config and card.config.center
  local ok, n = pcall(function() return localize { type = "name_text", key = c.key, set = c.set } end)
  if ok and type(n) == "string" and n ~= "ERROR" then return n end
  return (card.ability and card.ability.name) or (c and c.name) or "?"
end

local function hex(c)
  if type(c) ~= "table" or type(c[1]) ~= "number" then return "" end
  return string.format("#%02x%02x%02x", c[1] * 255, c[2] * 255, c[3] * 255)
end

-- The game's own tooltip for a card, flattened to lines of coloured text runs.
-- Building it creates animated text objects, which are removed again here.
local function runs(nodes, out, bg)
  for _, n in ipairs(nodes) do
    local cfg = n.config or {}
    if cfg.object then
      local s = cfg.object.string
      if type(s) == "table" then s = s.string end
      out[#out + 1] = { t = tostring(s or ""), c = hex(cfg.object.colours and cfg.object.colours[1]), bg = bg }
    elseif cfg.text then out[#out + 1] = { t = tostring(cfg.text), c = hex(cfg.colour), bg = bg }
    elseif n.nodes then runs(n.nodes, out, hex(cfg.colour)) end
  end
  return out
end
local function sweep(v, depth)
  if type(v) ~= "table" or depth > 6 then return end
  if v.config and v.config.object and v.config.object.remove then pcall(v.config.object.remove, v.config.object) end
  for _, x in ipairs(v) do sweep(x, depth + 1) end
  if v.nodes then sweep(v.nodes, depth + 1) end
end
local function describe(card)
  local lines = {}
  local ok, ui = pcall(card.generate_UIBox_ability_table, card)
  if not ok or type(ui) ~= "table" then return lines end
  pcall(function()
    for _, line in ipairs(ui.main or {}) do lines[#lines + 1] = runs(line, {}) end
  end)
  -- whatever reading the lines left behind goes too
  pcall(sweep, ui.main, 0); pcall(sweep, ui.name, 0); pcall(sweep, ui.info, 0)
  return lines
end

local function cards(area, fn)
  local out = {}
  if area and area.cards then for _, c in ipairs(area.cards) do out[#out + 1] = fn(c) end end
  return out
end
local function held(c)
  -- a card the game has turned face down stays unknown here too
  if c.facing == "back" then return { hidden = true } end
  local center = c.config.center
  local a = c.ability or {}
  return { name = name_of(c), set = center.set, x = center.pos.x, y = center.pos.y,
           soul = center.soul_pos and { x = center.soul_pos.x, y = center.soul_pos.y } or nil,
           rarity = center.rarity or 0, sell = c.sell_cost or 0, edition = (c.edition and c.edition.type) or "",
           sticker = (a.eternal and "Eternal") or (a.perishable and "Perishable") or (a.rental and "Rental") or "",
           debuff = c.debuff and true or false, desc = describe(c) }
end
local SUITS = { Spades = 1, Hearts = 2, Clubs = 3, Diamonds = 4 }
local function playing(c)
  local center, base = c.config.center, c.base or {}
  return { suit = base.suit or "", value = base.value or "", id = base.id or 0,
           x = c.config.card.pos.x, y = c.config.card.pos.y, bx = center.pos.x, by = center.pos.y,
           enh = (center.set == "Enhanced" and center.name) or "", seal = c.seal or "",
           edition = (c.edition and c.edition.type) or "",
           -- a card drawn face down counts as still in the deck, as in the game's own deck view
           left = c.area == G.deck or (c.ability and c.ability.wheel_flipped) or false }
end
-- Every card of the run's deck in a fixed order, so nothing about the draw order leaves the game.
local function deck()
  local out = {}
  for _, c in ipairs(G.playing_cards or {}) do out[#out + 1] = playing(c) end
  table.sort(out, function(a, b)
    local sa, sb = SUITS[a.suit] or 9, SUITS[b.suit] or 9
    if sa ~= sb then return sa < sb end
    if a.id ~= b.id then return a.id > b.id end
    if a.enh ~= b.enh then return a.enh < b.enh end
    if a.seal ~= b.seal then return a.seal < b.seal end
    if a.edition ~= b.edition then return a.edition < b.edition end
    return a.left and not b.left
  end)
  return out
end

local function blinds(g)
  local out = {}
  local rr = g.round_resets
  for _, slot in ipairs({ "Small", "Big", "Boss" }) do
    local key = rr.blind_choices[slot]
    local b = key and G.P_BLINDS[key]
    if b then
      local e = { slot = slot, state = rr.blind_states[slot] or "", y = b.pos.y, dollars = b.dollars, boss = b.boss and true or false,
                  colour = hex(b.boss_colour), name = localize { type = "name_text", key = key, set = "Blind" },
                  chips = get_blind_amount(rr.blind_ante or rr.ante) * b.mult * g.starting_params.ante_scaling }
      if b.boss then
        local vars = b.name == "The Ox" and { localize(g.current_round.most_played_poker_hand, "poker_hands") } or b.vars
        local ok, text = pcall(localize, { type = "raw_descriptions", key = key, set = "Blind", vars = vars })
        e.text = ok and type(text) == "table" and table.concat(text, " ") or ""
      end
      local tag = rr.blind_tags and rr.blind_tags[slot]
      if tag and G.P_TAGS[tag] then
        e.tag = { name = localize { type = "name_text", key = tag, set = "Tag" }, x = G.P_TAGS[tag].pos.x, y = G.P_TAGS[tag].pos.y }
      end
      out[#out + 1] = e
    end
  end
  return out
end

local desc_at, desc_cache = 0, {}
local function snapshot()
  if not (G and G.GAME and G.STAGE == G.STAGES.RUN and G.jokers) then return { run = false } end
  local g = G.GAME
  -- nothing the game's own screen shows all the time (money, hands, the score) is repeated here
  local s = { run = true, can_sort = G.STATE == G.STATES.SELECTING_HAND,
              jokers_max = G.jokers.config.card_limit, cons_max = G.consumeables.config.card_limit }
  -- tooltips are rebuilt once a second; in between the last ones are reused
  local fresh = acc_total - desc_at >= 1
  if fresh then desc_at, desc_cache = acc_total, {} end
  local function item(c)
    local e = desc_cache[c]
    if not e then e = held(c); desc_cache[c] = e end
    return e
  end
  s.jokers = cards(G.jokers, item)
  s.consumables = cards(G.consumeables, item)
  s.deck = deck()
  s.blinds = blinds(g)
  s.vouchers = {}
  for key in pairs(g.used_vouchers or {}) do
    local v = G.P_CENTERS[key]
    if v then s.vouchers[#s.vouchers + 1] = { name = localize { type = "name_text", key = key, set = "Voucher" }, x = v.pos.x, y = v.pos.y, order = v.order or 0 } end
  end
  table.sort(s.vouchers, function(a, b) return a.order < b.order end)
  s.levels = {}
  for k, h in pairs(g.hands or {}) do
    if h.visible then s.levels[#s.levels + 1] = { name = localize(k, "poker_hands"), level = h.level, chips = h.chips, mult = h.mult, played = h.played, order = h.order } end
  end
  table.sort(s.levels, function(a, b) return a.order < b.order end)
  return s
end

local function handle(t, body)
  if t == CMD and os.getenv("ARMADA_MOD_DEV") then
    -- development aid: run a chunk in the game and reply
    local fn, err = loadstring(body)
    local ok, r = pcall(fn or error, err)
    outbuf = outbuf .. frame(STATE, json({ reply = tostring(r) }))
    return
  end
  if t ~= INPUT or not (G and G.hand and G.STATE == G.STATES.SELECTING_HAND) then return end
  if body:find('"sort_value"', 1, true) then G.FUNCS.sort_hand_value({})
  elseif body:find('"sort_suit"', 1, true) then G.FUNCS.sort_hand_suit({}) end
end

local function drop() if sock then sock:close() end sock, outbuf, inbuf, last = nil, "", "", "" end

local function pump()
  while #outbuf > 0 do
    local n, err, part = sock:send(outbuf)
    local sent = n or part or 0
    outbuf = outbuf:sub(sent + 1)
    if not n then if err ~= "timeout" then drop() end return end
  end
  local data, err, part = sock:receive(4096)
  data = data or part
  if data and #data > 0 then inbuf = inbuf .. data end
  if err == "closed" then drop() return end
  while #inbuf >= 16 do
    local b1, b2, b3, b4 = inbuf:byte(9, 12)
    local len = b1 + b2 * 256 + b3 * 65536 + b4 * 16777216
    -- nothing the view sends is large
    if inbuf:sub(1, 4) ~= "A2SS" or len > 65536 then drop() return end
    if #inbuf < 16 + len then break end
    local t = inbuf:byte(5) + inbuf:byte(6) * 256
    local body = inbuf:sub(17, 16 + len)
    inbuf = inbuf:sub(17 + len)
    pcall(handle, t, body)
  end
end

local function tick(dt)
  if dead then return end
  acc = acc + dt; acc_total = acc_total + dt
  if not sock then
    retry = retry - dt
    if retry > 0 then return end
    retry = 2
    local s = socket.tcp()
    s:settimeout(0.05)
    if s:connect("127.0.0.1", 47800) then
      s:settimeout(0); s:setoption("tcp-nodelay", true)
      sock = s
      outbuf = frame(HELLO, '{"game":"Balatro","appid":2379780,"provider":"balatro-run","view":"html","version":1}')
    else s:close() return end
  end
  if acc >= 0.25 then
    acc = 0
    local ok, s = pcall(function() return json(snapshot()) end)
    -- A provider that keeps failing (for example after a game update) lets go of the screen.
    if ok then failures = 0 else
      failures = failures + 1
      s = json({ run = false, visible = false, error = tostring(s) })
      if failures > 40 then dead = true drop() return end
    end
    if s ~= last and #outbuf < 1048576 then last = s; outbuf = outbuf .. frame(STATE, s) end
  end
  pump()
end

local update, broken = love.update, 0
love.update = function(dt)
  update(dt)
  if dead then return end
  if pcall(tick, dt) then broken = 0 else
    -- the same rule for a fault anywhere else in the provider
    broken = broken + 1
    if broken > 600 then dead = true pcall(drop) end
  end
end
