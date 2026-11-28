-- WoW Planner : quêtes de donjon (fenêtre, bouton de la minimap, waypoints) et chasse au trésor.
--
-- Liste des quêtes : Data.lua (WowPlannerData.dungeons / .quests), préparé par le site à partir de l'API Blizzard et
-- des relevés de la guilde. Chasse au trésor : quand un PNJ propose une quête, l'addon note son donneur, la position
-- du joueur (le waypoint), le niveau de la quête et celui du joueur ; quand une quête rendue est suivie d'une nouvelle
-- chez le même PNJ, il note la suite. Le client envoie ces relevés au site (WowPlannerDB.hunt).

local ADDON, ns = ...
ADDON = ADDON or "WowPlanner"
ns = ns or {}

local COLOR = "|cff9d8cff"
local LOGO_PATH = "Interface\\AddOns\\WowPlanner\\logo"
local LINK_SECONDS = 120   -- suite : nouvelle quête chez le même PNJ, au plus 2 minutes après en avoir rendu une
local POPUP_SECONDS = 5    -- suite proposée d'office juste après le rendu (fenêtre de quête qui s'ouvre seule)
local ROW_HEIGHT = 15

local hunt, settings
local lastTurnIn, pendingTurnIn
local offered = {}  -- PNJ (GUID) -> quêtes qu'il proposait à la dernière visite

local function say(text)
  DEFAULT_CHAT_FRAME:AddMessage("|T" .. LOGO_PATH .. ":0|t " .. COLOR .. "WoW Planner|r : " .. text)
end

local function playerFaction()
  local f = UnitFactionGroup and UnitFactionGroup("player")
  return (f == "Alliance" and "alliance") or (f == "Horde" and "horde") or nil
end

-- ------------------------------------------------------------------ chasse au trésor (relevés)

-- PNJ (ou objet) qui propose la quête : { guid, id, name, src = "npc" | "object" | "item" }.
local function npcInfo()
  if not (UnitExists and UnitExists("npc")) then return nil end
  local guid = UnitGUID("npc")
  if guid and guid == UnitGUID("player") then return { guid = guid, src = "item" } end  -- objet du sac
  local kind, id
  if guid then
    local parts = { strsplit("-", guid) }
    kind, id = parts[1], tonumber(parts[6])
  end
  local src = (kind == "GameObject" and "object") or (kind == "Item" and "item") or "npc"
  return { guid = guid, id = id, name = UnitName("npc"), src = src }
end

-- Position du joueur (à côté du donneur) : carte du jeu, x et y de 0 à 1, nom de la zone. Rien dans une instance.
local function playerSpot()
  if not (C_Map and C_Map.GetBestMapForUnit and C_Map.GetPlayerMapPosition) then return nil end
  local map = C_Map.GetBestMapForUnit("player")
  if not map then return nil end
  local pos = C_Map.GetPlayerMapPosition(map, "player")
  if not pos then return nil end
  local x, y = pos:GetXY()
  if not x or not y or (x == 0 and y == 0) then return nil end
  local info = C_Map.GetMapInfo and C_Map.GetMapInfo(map)
  return map, floor(x * 10000 + 0.5) / 10000, floor(y * 10000 + 0.5) / 10000, info and info.name
end

local function record(qid, title, level, npc)
  if not hunt or not qid or qid <= 0 then return end
  local q = hunt.quests[qid]
  if not q then
    q = { by = UnitName("player"), at = time(), faction = playerFaction() }
    hunt.quests[qid] = q
  end
  if title and title ~= "" and not q.title then q.title = title end
  if level and level > 0 and not q.level then q.level = level end
  local plevel = UnitLevel("player")
  if plevel and plevel > 0 and (not q.plevel or plevel < q.plevel) then q.plevel = plevel end
  if npc and npc.src == "item" then
    q.kind = q.kind or "item"
  elseif npc then
    if npc.name and not q.npc then q.npc, q.npcId, q.kind = npc.name, npc.id, npc.src end
    if not q.map then
      local map, x, y, zone = playerSpot()
      if map then q.map, q.x, q.y, q.zone = map, x, y, zone end
    end
  end
end

-- La quête proposée suit-elle celle qu'on vient de rendre au même PNJ ?
local function linkFrom(npc, qid)
  local last = lastTurnIn
  if not (hunt and last and npc and npc.guid and last.npc == npc.guid and last.id ~= qid) then return end
  local age = GetTime() - last.t
  if age > LINK_SECONDS then return end
  local before = offered[npc.guid]
  -- Déjà proposée avant le rendu : pas une suite. Sans liste d'avant, seule la fenêtre ouverte d'office compte.
  if (before and not before[qid]) or (not before and age <= POPUP_SECONDS) then
    hunt.links[last.id .. ">" .. qid] = time()
  end
end

local function onGossip()
  if not (C_GossipInfo and C_GossipInfo.GetAvailableQuests) then return end
  local npc = npcInfo()
  local now = {}
  for _, info in ipairs(C_GossipInfo.GetAvailableQuests() or {}) do
    local qid = info.questID
    if qid then
      record(qid, info.title, info.questLevel, npc)
      linkFrom(npc, qid)
      now[qid] = true
    end
  end
  if npc and npc.guid then offered[npc.guid] = now end
end

local function onQuestDetail()
  local qid = GetQuestID and GetQuestID()
  if not qid or qid == 0 then return end
  local npc = npcInfo()
  record(qid, GetTitleText and GetTitleText(), nil, npc)
  linkFrom(npc, qid)
  if npc and npc.guid then
    offered[npc.guid] = offered[npc.guid] or {}
    offered[npc.guid][qid] = true
  end
end

-- ------------------------------------------------------------------ données (site + relevés pas encore envoyés)

local function siteQuest(qid)
  return WowPlannerData and WowPlannerData.quests and WowPlannerData.quests[qid]
end

-- Ce qu'on sait d'une quête : ce que le site a envoyé, complété par les relevés de ce compte.
local function questInfo(qid)
  local site, mine = siteQuest(qid) or {}, hunt and hunt.quests[qid] or {}
  return {
    id = qid, title = site.t or mine.title, level = site.lvl or mine.level, min = site.min or mine.plevel,
    npc = site.npc or mine.npc, zone = site.zone or mine.zone, map = site.map or mine.map,
    x = site.x or mine.x, y = site.y or mine.y, fac = site.fac, src = site.src or mine.kind,
  }
end

local function neighbours(qid, key)
  local list = {}
  local site = siteQuest(qid)
  for _, other in ipairs(site and site[key] or {}) do list[#list + 1] = other end
  if hunt then  -- suites relevées par ce compte, pas encore passées par le site
    for pair in pairs(hunt.links) do
      local prev, nxt = pair:match("^(%d+)>(%d+)$")
      prev, nxt = tonumber(prev), tonumber(nxt)
      if key == "prev" and nxt == qid then list[#list + 1] = prev end
      if key == "next" and prev == qid then list[#list + 1] = nxt end
    end
  end
  return list
end

-- Suite complète autour d'une quête, de la première étape à la dernière.
local function chain(qid)
  local order, seen = {}, {}
  local function back(id)
    if seen[id] then return end
    seen[id] = true
    for _, p in ipairs(neighbours(id, "prev")) do back(p) end
    order[#order + 1] = id
  end
  local function forward(id)
    for _, n in ipairs(neighbours(id, "next")) do
      if not seen[n] then
        seen[n] = true
        order[#order + 1] = n
        forward(n)
      end
    end
  end
  back(qid)
  forward(qid)
  return order
end

local function isDone(qid)
  if C_QuestLog and C_QuestLog.IsQuestFlaggedCompleted then return C_QuestLog.IsQuestFlaggedCompleted(qid) end
  if IsQuestFlaggedCompleted then return IsQuestFlaggedCompleted(qid) end
  return false
end

local function wrongFaction(q)
  local mine = playerFaction()
  return q.fac and mine and ((q.fac == "A") ~= (mine == "alliance"))
end

-- ------------------------------------------------------------------ waypoint

local function setWaypoint(q)
  local title = q.title or ("quête " .. q.id)
  if not (q.map and q.x and q.y) then
    say(title .. " : donneur pas encore repéré. À toi de le trouver !")
    return
  end
  local where = (q.zone and (q.zone .. " ") or "") .. format("%.1f, %.1f", q.x * 100, q.y * 100)
  local label = (q.npc or title) .. " (" .. title .. ")"
  if TomTom and TomTom.AddWaypoint then
    TomTom:AddWaypoint(q.map, q.x, q.y, { title = label, persistent = false })
    say("flèche TomTom vers " .. label .. " · " .. where)
  elseif C_Map and C_Map.SetUserWaypoint and UiMapPoint and UiMapPoint.CreateFromCoordinates
      and (not C_Map.CanSetUserWaypointOnMap or C_Map.CanSetUserWaypointOnMap(q.map)) then
    C_Map.SetUserWaypoint(UiMapPoint.CreateFromCoordinates(q.map, q.x, q.y))
    if C_SuperTrack and C_SuperTrack.SetSuperTrackedUserWaypoint then C_SuperTrack.SetSuperTrackedUserWaypoint(true) end
    say("épingle posée sur la carte : " .. label .. " · " .. where)
  else
    say(label .. " : " .. where)
  end
end

-- ------------------------------------------------------------------ fenêtre

local window, scroll, content, toggle, counter, header
local rows = {}

local function row(i)
  local r = rows[i]
  if r then return r end
  r = CreateFrame("Button", nil, content)
  r:SetHeight(ROW_HEIGHT)
  r.text = r:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  r.text:SetPoint("RIGHT", r, "RIGHT", -2, 0)
  r.text:SetJustifyH("LEFT")
  if r.text.SetWordWrap then r.text:SetWordWrap(false) end
  r:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
  r.bg = r:CreateTexture(nil, "BACKGROUND")  -- bandeau des titres de donjon
  r.bg:SetAllPoints(r)
  if r.bg.SetColorTexture then r.bg:SetColorTexture(1, 0.82, 0, 0.12) else r.bg:SetTexture(1, 0.82, 0, 0.12) end
  r:SetScript("OnClick", function(self) if self.onClick then self.onClick() end end)
  r:SetScript("OnEnter", function(self)
    if not self.tip then return end
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    for n, line in ipairs(self.tip) do
      if n == 1 then GameTooltip:SetText(line, 1, 0.82, 0) else GameTooltip:AddLine(line, 1, 1, 1, true) end
    end
    GameTooltip:Show()
  end)
  r:SetScript("OnLeave", function() GameTooltip:Hide() end)
  rows[i] = r
  return r
end

local function difficultyColor(level)
  if level and GetQuestDifficultyColor then
    local c = GetQuestDifficultyColor(level)
    if c then return format("|cff%02x%02x%02x", c.r * 255, c.g * 255, c.b * 255) end
  end
  return "|cffffd100"
end

local function refresh()
  if not window or not window:IsShown() then return end
  local level = UnitLevel("player") or 1
  local data = WowPlannerData and WowPlannerData.dungeons
  local n = 0
  local function add(indent, text, tip, onClick, band)
    n = n + 1
    local r = row(n)
    if band then r.bg:Show() else r.bg:Hide() end
    r:ClearAllPoints()
    r:SetPoint("TOPLEFT", content, "TOPLEFT", 0, -(n - 1) * ROW_HEIGHT)
    r:SetPoint("RIGHT", content, "RIGHT", 0, 0)
    r.text:ClearAllPoints()
    r.text:SetPoint("LEFT", r, "LEFT", 4 + indent, 0)
    r.text:SetPoint("RIGHT", r, "RIGHT", -2, 0)
    r.text:SetText(text)
    r.tip, r.onClick = tip, onClick
    r:Show()
  end

  if not data then
    -- Data.lua sans quêtes : écrit par un client trop ancien, ou pas encore retéléchargé.
    add(0, "|cffffd100Les quêtes de donjon arrivent avec le client WoW Planner 1.3 ou plus.|r", nil, nil, true)
    add(10, "1. Installe la dernière version du client (page Addon WoW du site).")
    add(10, "2. Laisse-le tourner : son journal dit « Prix … quêtes de donjon : … ».")
    add(10, "3. En jeu, tape /wp maj.")
  else
    local mine = playerFaction()
    local shown = 0
    for _, d in ipairs(data) do
      local inRange = level >= d.lo - 3 and level <= d.hi
      local otherSide = d.side and mine and ((d.side == "A") ~= (mine == "alliance"))
      if settings.showAll or (inRange and not otherSide) then
        shown = shown + 1
        local collapsed = settings.collapsed[d.n]
        local range = d.raid and "raid" or (d.lo .. "-" .. d.hi)
        local side = d.side and (" |cff888888(côté " .. (d.side == "A" and "Alliance" or "Horde") .. ")|r") or ""
        local count = #d.q > 0 and (" |cff888888· " .. #d.q .. " quête" .. (#d.q > 1 and "s" or "") .. "|r") or ""
        add(0, (collapsed and "|cffffd100+|r " or "|cffffd100-|r ") .. "|cffffd100" .. d.n .. "|r  |cffaaaaaa" .. range
          .. "|r" .. side .. count,
          { d.n, "Clique pour " .. (collapsed and "déplier" or "replier") .. "." },
          function() settings.collapsed[d.n] = not collapsed or nil; refresh() end, true)
        if not collapsed and #d.q == 0 then
          add(10, "|cff888888Quêtes pas encore chargées par le site (synchro des données).|r")
        elseif not collapsed then
          local listed = {}
          for _, qid in ipairs(d.q) do
            local steps = chain(qid)
            local fresh = false
            for _, st in ipairs(steps) do if not listed[st] then fresh = true end end
            if fresh and not wrongFaction(questInfo(qid)) then
              for i, st in ipairs(steps) do
                listed[st] = true
                local q = questInfo(st)
                local done = isDone(st)
                local mark = done and "|TInterface\\RaidFrame\\ReadyCheck-Ready:0|t " or "|TInterface\\GossipFrame\\AvailableQuestIcon:0|t "
                local stepText = #steps > 1 and format("|cffaaaaaa%d/%d|r ", i, #steps) or ""
                local finale = (#steps > 1 and i == #steps) and " |cffff8040(finale)|r" or ""
                local lvl = q.level and ("[" .. q.level .. "] ") or ""
                local title = done and ("|cff808080" .. lvl .. (q.title or ("Quête " .. st)) .. "|r")
                  or (difficultyColor(q.level) .. lvl .. (q.title or ("Quête " .. st)) .. "|r")
                local minText = q.min and ("  |cffaaaaaadès niv. " .. q.min .. "|r") or ""
                local giver
                if q.npc or q.x then
                  local where = q.x and format("%s %.0f, %.0f", q.zone or "", q.x * 100, q.y * 100) or (q.zone or "")
                  giver = "|cffcccccc" .. (q.npc or (q.src == "object" and "Objet" or "Donneur")) .. "|r |cff888888· " .. where .. "|r"
                elseif q.src == "item" then
                  giver = "|cffccccccCommence avec un objet|r"
                else
                  giver = "|cffff9933Donneur pas encore repéré : à toi de le trouver !|r"
                end
                local tip = { q.title or ("Quête " .. st) }
                if q.level then tip[#tip + 1] = "Niveau de la quête : " .. q.level end
                if q.min then tip[#tip + 1] = "Proposée dès le niveau " .. q.min .. " (plus bas niveau relevé)" end
                if q.npc then tip[#tip + 1] = "Donneur : " .. q.npc end
                if q.x then tip[#tip + 1] = "Clique pour un waypoint vers le donneur." end
                if done then tip[#tip + 1] = "|cff40ff40Déjà faite par ce perso.|r" end
                local click = function() setWaypoint(q) end
                add(10, mark .. stepText .. title .. finale .. minText, tip, click)
                add(30, giver, tip, click)
              end
            end
          end
        end
      end
    end
    if shown == 0 then
      add(0, "Aucun donjon de ton niveau.")
      add(0, "Clique sur « Afficher tous les donjons » en haut.")
    end
  end
  for i = n + 1, #rows do rows[i]:Hide() end
  content:SetHeight(math.max(n * ROW_HEIGHT, 1))

  local found = WowPlannerData and WowPlannerData.found
  local total = WowPlannerData and WowPlannerData.total
  counter:SetText(found and total and total > 0 and format("Chasse au trésor : %d/%d quêtes de donjon ont leur donneur repéré", found, total) or "")
  header:SetText(settings.showAll and "Tous les donjons" or ("Donjons de ton niveau (" .. level .. ")"))
  toggle:SetText(settings.showAll and "Seulement mon niveau" or "Afficher tous les donjons")
end

local function createWindow()
  window = CreateFrame("Frame", "WowPlannerQuestsFrame", UIParent, BackdropTemplateMixin and "BackdropTemplate" or nil)
  window:SetSize(470, 520)
  window:SetPoint("CENTER")
  window:SetFrameStrata("DIALOG")
  window:SetMovable(true)
  window:EnableMouse(true)
  window:RegisterForDrag("LeftButton")
  window:SetScript("OnDragStart", window.StartMoving)
  window:SetScript("OnDragStop", window.StopMovingOrSizing)
  if window.SetBackdrop then
    window:SetBackdrop({
      bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background", edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
      tile = true, tileSize = 32, edgeSize = 32, insets = { left = 11, right = 12, top = 12, bottom = 11 },
    })
  end
  if UISpecialFrames then tinsert(UISpecialFrames, "WowPlannerQuestsFrame") end  -- Échap ferme la fenêtre

  local close = CreateFrame("Button", nil, window, "UIPanelCloseButton")
  close:SetPoint("TOPRIGHT", window, "TOPRIGHT", -6, -6)
  local icon = window:CreateTexture(nil, "ARTWORK")
  icon:SetSize(22, 22)
  icon:SetPoint("TOPLEFT", window, "TOPLEFT", 18, -16)
  icon:SetTexture(LOGO_PATH)
  local title = window:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
  title:SetPoint("LEFT", icon, "RIGHT", 6, 0)
  title:SetText("Quêtes de donjon")

  header = window:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  header:SetPoint("TOPLEFT", window, "TOPLEFT", 20, -46)
  toggle = CreateFrame("Button", nil, window, "UIPanelButtonTemplate")
  toggle:SetSize(170, 22)
  toggle:SetPoint("TOPRIGHT", window, "TOPRIGHT", -20, -42)
  toggle:SetScript("OnClick", function() settings.showAll = not settings.showAll; refresh() end)
  counter = window:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  counter:SetPoint("BOTTOMLEFT", window, "BOTTOMLEFT", 20, 16)

  scroll = CreateFrame("ScrollFrame", "WowPlannerQuestsScroll", window, "UIPanelScrollFrameTemplate")
  scroll:SetPoint("TOPLEFT", window, "TOPLEFT", 16, -72)
  scroll:SetPoint("BOTTOMRIGHT", window, "BOTTOMRIGHT", -36, 34)
  content = CreateFrame("Frame", nil, scroll)
  content:SetSize(410, 1)
  scroll:SetScrollChild(content)
  window:SetScript("OnShow", refresh)
  window:Hide()
end

function ns.toggleQuests()
  if not window then createWindow() end
  if window:IsShown() then window:Hide() else window:Show(); refresh() end
end

-- ------------------------------------------------------------------ bouton de la minimap

local button

local function placeButton()
  local angle = math.rad(settings.minimapAngle or 215)
  local radius = (Minimap:GetWidth() or 140) / 2 + 10
  button:ClearAllPoints()
  button:SetPoint("CENTER", Minimap, "CENTER", math.cos(angle) * radius, math.sin(angle) * radius)
end

local function createButton()
  if button or not Minimap then return end
  button = CreateFrame("Button", "WowPlannerMinimapButton", Minimap)
  button:SetSize(31, 31)
  button:SetFrameStrata("MEDIUM")
  button:SetFrameLevel(8)
  button:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  button:RegisterForDrag("LeftButton")
  button:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")
  local back = button:CreateTexture(nil, "BACKGROUND")
  back:SetSize(20, 20)
  back:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
  back:SetPoint("TOPLEFT", button, "TOPLEFT", 7, -5)
  local icon = button:CreateTexture(nil, "ARTWORK")
  icon:SetSize(18, 18)
  icon:SetTexture(LOGO_PATH)
  icon:SetPoint("TOPLEFT", button, "TOPLEFT", 7, -6)
  local border = button:CreateTexture(nil, "OVERLAY")
  border:SetSize(53, 53)
  border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
  border:SetPoint("TOPLEFT", button, "TOPLEFT", 0, 0)

  button:SetScript("OnClick", function() ns.toggleQuests() end)
  button:SetScript("OnDragStart", function(self)
    self:SetScript("OnUpdate", function()
      local mx, my = Minimap:GetCenter()
      local cx, cy = GetCursorPosition()
      local scale = Minimap:GetEffectiveScale()
      settings.minimapAngle = math.deg(math.atan2(cy / scale - my, cx / scale - mx))
      placeButton()
    end)
  end)
  button:SetScript("OnDragStop", function(self) self:SetScript("OnUpdate", nil) end)
  button:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:SetText("WoW Planner", 0.62, 0.55, 1)
    GameTooltip:AddLine("Clic : quêtes de donjon", 1, 1, 1)
    GameTooltip:AddLine("Glisser : déplacer le bouton", 0.7, 0.7, 0.7)
    GameTooltip:Show()
  end)
  button:SetScript("OnLeave", function() GameTooltip:Hide() end)
  placeButton()
  if settings.hideButton then button:Hide() end
end

function ns.toggleButton()
  settings.hideButton = not settings.hideButton
  if button then
    if settings.hideButton then button:Hide() else button:Show() end
  end
  say(settings.hideButton and "bouton de la minimap masqué (/wp bouton pour le remettre)." or "bouton de la minimap affiché.")
end

-- ------------------------------------------------------------------ événements

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:SetScript("OnEvent", function(_, event, arg)
  if event == "ADDON_LOADED" then
    if arg ~= ADDON then return end
    WowPlannerDB = WowPlannerDB or {}
    WowPlannerDB.hunt = WowPlannerDB.hunt or {}
    hunt = WowPlannerDB.hunt
    hunt.quests = hunt.quests or {}
    hunt.links = hunt.links or {}
    WowPlannerDB.settings = WowPlannerDB.settings or { tooltip = true }
    settings = WowPlannerDB.settings
    settings.collapsed = settings.collapsed or {}
    for _, e in ipairs({ "PLAYER_LOGIN", "GOSSIP_SHOW", "QUEST_DETAIL", "QUEST_COMPLETE", "PLAYER_LEVEL_UP",
      "QUEST_ACCEPTED" }) do
      frame:RegisterEvent(e)
    end
    pcall(frame.RegisterEvent, frame, "QUEST_TURNED_IN")  -- absent de certains clients
  elseif event == "PLAYER_LOGIN" then
    createButton()
  elseif event == "GOSSIP_SHOW" then
    onGossip()
  elseif event == "QUEST_DETAIL" then
    onQuestDetail()
  elseif event == "QUEST_COMPLETE" then
    local npc = npcInfo()
    pendingTurnIn = { id = GetQuestID and GetQuestID(), npc = npc and npc.guid }
  elseif event == "QUEST_TURNED_IN" then
    local npc = pendingTurnIn and pendingTurnIn.id == arg and pendingTurnIn.npc
    if not npc then
      local info = npcInfo()
      npc = info and info.guid
    end
    lastTurnIn = { id = arg, npc = npc, t = GetTime() }
    refresh()
  elseif event == "PLAYER_LEVEL_UP" or event == "QUEST_ACCEPTED" then
    refresh()
  end
end)
