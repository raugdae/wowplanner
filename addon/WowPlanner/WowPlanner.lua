-- WoW Planner : prix de l'hôtel des ventes dans les infobulles (Data.lua, écrit par le client WoW Planner) et
-- relevé de l'inventaire, des métiers et des recettes (WowPlannerDB, enregistré par le jeu à la déconnexion ou au
-- /reload, puis envoyé au site par le client).

local ADDON = "WowPlanner"
-- Sacs portés : le sac à dos (0), les sacs équipés, et l'emplacement « composants » des clients qui en ont un.
local NUM_BAGS = NUM_TOTAL_EQUIPPED_BAG_SLOTS or ((NUM_BAG_SLOTS or 4) + (NUM_REAGENTBAG_SLOTS or 0))
local NUM_BANK_BAGS = NUM_BANKBAGSLOTS or 6
local BANK = BANK_CONTAINER or -1
local COLOR = "|cff9d8cff"
local VERSION = "1.0.3"
local AH_CUT = 0.05  -- commission de l'hôtel des ventes sur une vente (comme la calculatrice du site)
local LOGO = "|TInterface\\AddOns\\WowPlanner\\logo:0|t"  -- logo à la taille du texte

local db, me, bankOpen

-- ------------------------------------------------------------------ outils

local function say(text)
  DEFAULT_CHAT_FRAME:AddMessage(LOGO .. " " .. COLOR .. "WoW Planner|r : " .. text)
end

local function itemId(link)
  return link and tonumber(link:match("item:(%d+)"))
end

local function money(copper)
  if GetCoinTextureString then return GetCoinTextureString(copper) end
  local g, s, c = floor(copper / 10000), floor(copper / 100) % 100, copper % 100
  return (g > 0 and g .. "po " or "") .. ((g > 0 or s > 0) and s .. "pa " or "") .. c .. "pc"
end

local function slots(bag)
  if C_Container and C_Container.GetContainerNumSlots then return C_Container.GetContainerNumSlots(bag) end
  return GetContainerNumSlots(bag)
end

-- (id de l'objet, quantité) dans un emplacement de sac, nil si vide.
local function slotItem(bag, slot)
  if C_Container and C_Container.GetContainerItemInfo then
    local info = C_Container.GetContainerItemInfo(bag, slot)
    if info then return info.itemID or itemId(info.hyperlink), info.stackCount or 1 end
    return nil
  end
  local _, count, _, _, _, _, link, _, _, id = GetContainerItemInfo(bag, slot)
  if count then return id or itemId(link), count end
end

local function scanBags(list)
  local found = {}
  for _, bag in ipairs(list) do
    for slot = 1, slots(bag) or 0 do
      local id, count = slotItem(bag, slot)
      if id then found[id] = (found[id] or 0) + count end
    end
  end
  return found
end

-- ------------------------------------------------------------------ relevés

local function carriedBags()
  local bags = {}
  for bag = 0, NUM_BAGS do bags[#bags + 1] = bag end
  return bags
end

local function bankBags()
  local bags = { BANK }
  for bag = NUM_BAGS + 1, NUM_BAGS + NUM_BANK_BAGS do bags[#bags + 1] = bag end
  return bags
end

local function scanInventory()
  me.bags = scanBags(carriedBags())
  me.money = GetMoney()
  me.level = UnitLevel("player")
  me.updated = time()
end

local function scanBank()
  me.bank = scanBags(bankBags())
  me.bankAt = time()
end

local function scanSkills()
  local skills = {}
  for i = 1, GetNumSkillLines() do
    local name, header, _, rank = GetSkillLineInfo(i)
    if name and not header then skills[name] = rank end
  end
  me.professions = skills
end

-- Recettes d'une fenêtre de métier, ajoutées à celles déjà vues (un titre replié ou un filtre en cache une partie,
-- et une recette apprise ne s'oublie pas).
local function addRecipes(profession, count, info, link)
  if not profession or profession == "" or profession == "UNKNOWN" then return end
  me.recipes = me.recipes or {}
  local known = me.recipes[profession] or {}
  me.recipes[profession] = known
  for i = 1, count do
    local name, kind = info(i)
    if name and kind ~= "header" then
      local l = link(i)
      known[name] = { item = itemId(l), spell = l and tonumber(l:match("enchant:(%d+)")), name = name }
    end
  end
end

local function scanTradeSkill()
  local profession = GetTradeSkillLine()
  addRecipes(profession, GetNumTradeSkills(), GetTradeSkillInfo, GetTradeSkillItemLink)
end

local function scanCraft()  -- Enchantement (et le dressage des familiers du chasseur, sans niveau : ignoré)
  if not GetCraftDisplaySkillLine then return end
  local profession, rank = GetCraftDisplaySkillLine()
  if not rank or rank == 0 then return end
  addRecipes(profession, GetNumCrafts(), function(i)
    local name, _, kind = GetCraftInfo(i)
    return name, kind
  end, GetCraftItemLink)
end

-- ------------------------------------------------------------------ infobulles

local function priceLines(tooltip, id, count)
  if not db.settings.tooltip or not WowPlannerData or not WowPlannerData.items then return end
  local p = WowPlannerData.items[id]
  if not p then return end
  local low, sold = p[1], p[3]  -- p[2], le prix médian, n'est plus affiché
  local n = (count and count > 1) and count or 1
  tooltip:AddDoubleLine(LOGO .. " " .. COLOR .. "HdV, plus bas (l'unité)|r", money(low), 1, 1, 1, 1, 1, 1)
  if n > 1 then
    tooltip:AddDoubleLine(COLOR .. "HdV, les " .. n .. "|r", money(low * n), 1, 1, 1, 1, 1, 1)
  end
  -- Le jeu affiche le prix marchand de toute la pile : on donne celui d'un exemplaire, puis ce que rapporte l'HdV
  -- au plus bas actuel (moins la commission de 5 %) par rapport au marchand.
  local sell = select(11, GetItemInfo(id))  -- 0 : le marchand n'en veut pas ; nil : objet pas encore en cache
  if sell and sell > 0 then
    tooltip:AddDoubleLine(COLOR .. "Marchand (l'unité)|r", money(sell), 1, 1, 1, 1, 1, 1)
    local diff = floor(low * n * (1 - AH_CUT)) - sell * n
    local label = n > 1 and ("les " .. n) or "l'unité"
    if diff >= 0 then
      tooltip:AddDoubleLine(COLOR .. "Bénéfice à l'HdV (" .. label .. ")|r", "+" .. money(diff), 1, 1, 1, 0.3, 1, 0.3)
    else
      tooltip:AddDoubleLine(COLOR .. "Perte à l'HdV (" .. label .. ")|r", "-" .. money(-diff), 1, 1, 1, 1, 0.35, 0.35)
    end
  end
  if sold and sold > 0 then
    tooltip:AddDoubleLine(COLOR .. "Ventes estimées|r", "~" .. sold .. " / jour", 1, 1, 1, 1, 1, 1)
  end
  local age = time() - (WowPlannerData.ts or 0)
  if age > 6 * 3600 then
    tooltip:AddLine("Prix du " .. date("%d/%m à %Hh", WowPlannerData.ts) .. " (lance le client, puis /wp maj)",
      0.6, 0.6, 0.6)
  end
end

-- Quantité de la pile survolée, lue sur le bouton du sac ou de la banque (sans toucher aux fonctions du jeu).
local function stackCount(tooltip)
  local owner = tooltip.GetOwner and tooltip:GetOwner()
  local name = owner and owner.GetName and owner:GetName()
  if not name or not owner.GetID then return nil end
  local bag
  if name:match("^ContainerFrame%d+Item%d+$") then
    bag = owner:GetParent():GetID()
  elseif name:match("^BankFrameItem%d+$") then
    bag = BANK
  else
    return nil
  end
  local _, count = slotItem(bag, owner:GetID())
  return count
end

local function onItem(tooltip)
  local _, link = tooltip:GetItem()
  local id = itemId(link)
  if id then priceLines(tooltip, id, stackCount(tooltip)) end
end

local function hookTooltips()
  if TooltipDataProcessor and Enum and Enum.TooltipDataType then
    TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(tooltip)
      if tooltip == GameTooltip or tooltip == ItemRefTooltip then onItem(tooltip) end
    end)
  else
    GameTooltip:HookScript("OnTooltipSetItem", onItem)
    ItemRefTooltip:HookScript("OnTooltipSetItem", onItem)
  end
end

-- ------------------------------------------------------------------ commandes

SLASH_WOWPLANNER1 = "/wp"
SLASH_WOWPLANNER2 = "/wowplanner"
SlashCmdList.WOWPLANNER = function(text)
  local command = strlower(strtrim(text or ""))
  if command == "maj" or command == "reload" then
    ReloadUI()
  elseif command == "sacs" then
    -- Diagnostic : ce que l'addon lit dans chaque conteneur (y compris un cran au-delà des sacs portés).
    say("sacs portés : conteneurs 0 à " .. NUM_BAGS .. " (NUM_BAG_SLOTS=" .. tostring(NUM_BAG_SLOTS)
      .. ", NUM_REAGENTBAG_SLOTS=" .. tostring(NUM_REAGENTBAG_SLOTS) .. ").")
    for bag = 0, NUM_BAGS + 1 do
      local n, objects = slots(bag) or 0, 0
      for slot = 1, n do
        if slotItem(bag, slot) then objects = objects + 1 end
      end
      say("conteneur " .. bag .. " : " .. n .. " emplacements, " .. objects .. " occupés"
        .. (bag > NUM_BAGS and " (pas lu : au-delà des sacs portés)" or ""))
    end
    scanInventory()
    local kinds = 0
    for _ in pairs(me.bags) do kinds = kinds + 1 end
    say(kinds .. " objets différents notés dans tes sacs (envoyés au prochain /reload).")
  elseif command == "info" then
    say("version " .. VERSION .. ", par Raugdae, gratuit et libre (licence MIT, sans aucune garantie : voir "
      .. "LICENSE.txt dans le dossier de l'addon).")
    say("Logo créé par ideapub (ideapub.ch). Développé avec l'aide de l'IA Claude Code (Anthropic).")
    say("Site : wow.raug-info.ch · code : github.com/raugdae/wowplanner")
  elseif command == "off" or command == "on" then
    db.settings.tooltip = command == "on"
    say(db.settings.tooltip and "prix affichés dans les infobulles." or "prix masqués dans les infobulles.")
  else
    if WowPlannerData and WowPlannerData.ts then
      local n = 0
      for _ in pairs(WowPlannerData.items or {}) do n = n + 1 end
      say(n .. " objets, prix du " .. date("%d/%m à %H:%M", WowPlannerData.ts) .. ".")
    else
      say("pas encore de prix : lance le client WoW Planner, puis /wp maj.")
    end
    say("/wp maj : recharger l'interface pour prendre les derniers prix · /wp off, /wp on : prix dans les infobulles · /wp sacs : ce que l'addon voit dans tes sacs · /wp info : à propos.")
    say("Banque " .. (me.bankAt and ("vue le " .. date("%d/%m à %H:%M", me.bankAt)) or "jamais ouverte : ouvre-la une fois") .. ".")
  end
end

-- ------------------------------------------------------------------ événements

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:SetScript("OnEvent", function(_, event, arg)
  if event == "ADDON_LOADED" then
    if arg ~= ADDON then return end
    WowPlannerDB = WowPlannerDB or {}
    db = WowPlannerDB
    db.version = 1
    db.settings = db.settings or { tooltip = true }
    db.chars = db.chars or {}
    local key = UnitName("player") .. " - " .. GetRealmName()
    db.chars[key] = db.chars[key] or {}
    me = db.chars[key]
    me.name, me.realm = UnitName("player"), GetRealmName()
    me.class = select(2, UnitClass("player"))
    hookTooltips()
    for _, e in ipairs({ "PLAYER_LOGIN", "PLAYER_LOGOUT", "BAG_UPDATE", "PLAYER_MONEY", "SKILL_LINES_CHANGED",
      "BANKFRAME_OPENED", "BANKFRAME_CLOSED", "PLAYERBANKSLOTS_CHANGED", "TRADE_SKILL_SHOW", "TRADE_SKILL_UPDATE",
      "CRAFT_SHOW", "CRAFT_UPDATE" }) do
      frame:RegisterEvent(e)
    end
  elseif event == "PLAYER_LOGIN" then
    scanInventory()
    scanSkills()
  elseif event == "PLAYER_LOGOUT" then
    scanInventory()  -- enregistré par le jeu juste après
  elseif event == "BAG_UPDATE" or event == "PLAYERBANKSLOTS_CHANGED" then
    if bankOpen then scanBank() end
  elseif event == "PLAYER_MONEY" then
    me.money = GetMoney()
  elseif event == "SKILL_LINES_CHANGED" then
    scanSkills()
  elseif event == "BANKFRAME_OPENED" then
    bankOpen = true
    scanBank()
  elseif event == "BANKFRAME_CLOSED" then
    bankOpen = false
  elseif event == "TRADE_SKILL_SHOW" or event == "TRADE_SKILL_UPDATE" then
    scanTradeSkill()
  elseif event == "CRAFT_SHOW" or event == "CRAFT_UPDATE" then
    scanCraft()
  end
end)
