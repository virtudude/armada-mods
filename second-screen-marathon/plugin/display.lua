-- Replaces the status display around the view: the view takes the whole screen
-- and what the display showed is written out for the second screen.
Triggers = {}

local LINK = "@LINK@"
local written, frames, at = nil, 0, 0
local names = {}

-- the bridge that reads the file skips one it catches half written
local function put(name, text)
  local f = io.open(LINK .. "/" .. name, "w")
  if not f then return false end
  f:write(text); f:close()
  return true
end

local function quoted(s)
  return '"' .. tostring(s):gsub('[%c"\\]', " ") .. '"'
end

function Triggers.init()
  Triggers.resize()
end

function Triggers.resize()
  -- the game draws its world twice as wide as tall
  local w = math.min(Screen.width, 2 * Screen.height)
  for _, rect in ipairs({ Screen.world_rect, Screen.map_rect, Screen.term_rect }) do
    rect.width = w
    rect.height = w / 2
    rect.x = math.floor((Screen.width - w) / 2)
    rect.y = math.floor((Screen.height - w / 2) / 2)
  end
end

-- a weapon's rounds as the status display draws them: rows of bullets from two pictures, a full row and an
-- empty one, or a meter; each with its place on the display
local function trigger(t)
  if not t then return "null" end
  local b, e = t.bullet_display, t.energy_display
  if b then
    return string.format('{"rounds":%d,"full":%d,"across":%d,"picture":%d,"empty":%d,"x":%d,"y":%d,"h":%d,"rtl":%s}',
      math.max(0, t.rounds), b.across * b.down, b.across, b.texture_index, b.empty_texture_index, b.x, b.y, b.height, b.right_to_left and "true" or "false")
  elseif e then
    return string.format('{"rounds":%d,"full":%d,"x":%d,"y":%d,"w":%d,"h":%d}', math.max(0, t.rounds), e.maximum, e.x, e.y, e.width, e.height)
  end
  return "null"
end

-- the pictures the status display shows for a weapon, each with its place: a second one when two are carried
local function pictures(w, count)
  local list = {}
  local function add(shape)
    if shape then list[#list + 1] = string.format("[%d,%d,%d]", shape.texture_index, shape.x, shape.y) end
  end
  if w.multiple_unusable_shape then
    add(w.shape)
    add(count > 1 and w.multiple_shape or w.multiple_unusable_shape)
  else
    add(count > 1 and w.multiple_shape or w.shape)
  end
  return table.concat(list, ",")
end

function Triggers.draw()
  -- every frame comes through here: the second screen is told a few times a second
  frames = frames + 1
  if frames % 6 ~= 0 then return end
  local weapons, desired = {}, Player.weapons.desired
  for wt in WeaponTypes() do
    -- the fists are not an item; every other weapon is carried as one of the same name
    local w = Player.weapons[wt]
    local found, item = pcall(function() return Player.items[wt.mnemonic] end)
    if not found then item = nil end
    if w and (wt.mnemonic == "fist" or (item and item.count > 0)) then
      -- the game only gives the full name of the weapon in hand: keep each one once seen
      if w.name and w.name ~= "" then names[wt.mnemonic] = w.name end
      local count = item and item.count or 1
      weapons[#weapons + 1] = string.format('{"id":%s,"name":%s,"count":%d,"pictures":[%s],"primary":%s,"secondary":%s}',
        quoted(wt.mnemonic), quoted(names[wt.mnemonic] or wt.mnemonic), count, pictures(w, count), trigger(w.primary), trigger(w.secondary))
    end
  end
  local blips = {}
  if Player.motion_sensor.active then
    for i = 1, #Player.motion_sensor.blips do
      local b = Player.motion_sensor.blips[i - 1]
      blips[#blips + 1] = string.format('[%s,%d,%.3f,%d]', quoted(b.type.mnemonic), b.intensity, b.distance, b.direction)
    end
  end
  local text = string.format('{"energy":%d,"oxygen":%d,"desired":%s,"sensor":%s,"weapons":[%s],"blips":[%s]}',
    Player.energy, Player.oxygen, desired and quoted(desired.type.mnemonic) or "null",
    Player.motion_sensor.active and "true" or "false", table.concat(weapons, ","), table.concat(blips, ","))
  -- written again now and then unchanged: the bridge takes a file gone old for a game that has stopped
  if (text ~= written or frames - at >= 60) and put("state.json", text) then
    written, at = text, frames
  end
end
