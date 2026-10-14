-- Draws the weapon the second screen asks for.
Triggers = {}

local LINK = "@LINK@"
local seen = nil

local function request()
  local f = io.open(LINK .. "/input.json", "r")
  if not f then return nil end
  local text = f:read("*a")
  f:close()
  return text:match('"weapon":%s*"([^"]+)"'), text:match('"n":%s*(%d+)')
end

function Triggers.init()
  -- what was asked for before this level started is not acted on
  local _, n = request()
  seen = n
end

function Triggers.idle()
  if Game.ticks % 5 ~= 0 then return end
  local weapon, n = request()
  if not weapon or n == seen then return end
  seen = n
  for p in Players() do
    if p.local_ and p.weapons[weapon] then p.weapons[weapon]:select() end
  end
end
