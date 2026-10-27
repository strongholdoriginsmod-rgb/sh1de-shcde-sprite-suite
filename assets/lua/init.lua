-- Stronghold Europe DE - Baufreigaben
-- Ziel: Stronghold Crusader: Definitive Edition 2.7.x + SHCDE-SE 1.39.0
--
-- Schaltet die Jaegerhuette auf jeder Karte frei. Anlass ist die Arbeitermiliz
-- (docs/MILIZ_FORMATION_MAUERN.md): Jaeger und Holzfaeller sollen als schwache
-- Miliz taugen, und dafuer muss die Jaegerhuette ueberhaupt baubar sein.
--
-- Bewusst schlank. UniversalSiegeCore schaltet 70 Mapper auf einmal frei,
-- darunter MAPPER_OUTPOST_ARAB, MAPPER_OUTPOST_BEDOUIN und
-- MAPPER_BEDOUIN_STOCKADE - in einer europaeischen Umsetzung unerwuenscht.
-- Diese Datei fasst nur an, was hier gebraucht wird.
--
-- Gemessen am 16.08.2026:
--   * MAPPER_HUNTER = 78 (Enums.cs:802)
--   * Player_SetBuildingAvailable schreibt r_EMNullAvailable[mapper] und
--     erneuert danach das Bauleisten-HUD (GamePlayerManagerAPI.cs:1307)
--   * Die Freigabe gilt pro Karte, nicht global - deshalb wird sie bei jedem
--     Kartenstart neu gesetzt
--   * Zwei Lua-Mods mit denselben Einstiegsnamen laufen nachweislich
--     nebeneinander (USM-Core und USM-AI, je eigene Logzeilen im Lauf vom
--     16.08.). Jedes Plugin hat seine eigene Umgebung; diese Datei verdraengt
--     kein anderes Skript.
--
-- UNGEPRUEFT: Dieses Skript ist noch nicht im Spiel gelaufen. Der Nachweis ist
-- die Zeile "Baufreigabe Jaegerhuette" im BepInEx-Protokoll plus die sichtbare
-- Jaegerhuette im Baumenue einer Karte ohne Wild.

local VERSION = "0.1.0"
local PREFIX = "[Europa-Bau " .. VERSION .. "] "
local FREIZUSCHALTEN = { "MAPPER_HUNTER" }

local generation = 0
local timers = {}
local vorherVerfuegbar = {}
local gesetzt = {}

local function enum_member(containerName, memberName)
    local container = rawget(_G, containerName)
    if container == nil then return nil end
    local ok, value = pcall(function() return container[memberName] end)
    if ok then return value end
    return nil
end

local function log(message, levelName)
    local text = PREFIX .. tostring(message)
    local level = 2
    local levels = rawget(_G, "eLogEventLevel") or rawget(_G, "LogEventLevel")
    if levels ~= nil then
        local ok, value = pcall(function() return levels[levelName or "Information"] end)
        if ok and value ~= nil then level = value end
    end
    if rawget(_G, "Log") ~= nil then
        if pcall(function() Log(level, text) end) then return end
    end
    pcall(function() print(text) end)
end

local function cancel_timers()
    if rawget(_G, "Time_RemoveAction") ~= nil then
        for _, handle in ipairs(timers) do
            pcall(function() Time_RemoveAction(handle) end)
        end
    end
    timers = {}
end

local function schedule_once(milliseconds, callback, expectedGeneration)
    if rawget(_G, "Time_AddOneShot") == nil then return end
    local ok, handle = pcall(function()
        return Time_AddOneShot(milliseconds, function()
            if generation ~= expectedGeneration then return end
            pcall(callback)
        end)
    end)
    if ok and handle ~= nil then timers[#timers + 1] = handle end
end

local function anwenden(grund)
    if rawget(_G, "Player_SetBuildingAvailable") == nil then
        log("Player_SetBuildingAvailable fehlt; Baufreigaben bleiben aus.", "Error")
        return false
    end

    local gesetztZahl, aufgeloest = 0, 0
    for _, name in ipairs(FREIZUSCHALTEN) do
        local mapper = enum_member("eMappers", name)
        if mapper ~= nil then
            aufgeloest = aufgeloest + 1
            -- Den Ausgangswert einmal je Karte merken, damit mod_unload ihn
            -- zurueckgeben kann statt blind "verfuegbar" stehen zu lassen.
            if vorherVerfuegbar[name] == nil
                and rawget(_G, "Player_IsBuildingAvailable") ~= nil then
                local ok, war = pcall(function()
                    return Player_IsBuildingAvailable(mapper)
                end)
                if ok then vorherVerfuegbar[name] = war and true or false end
            end
            if pcall(function() Player_SetBuildingAvailable(mapper, true) end) then
                gesetzt[name] = mapper
                gesetztZahl = gesetztZahl + 1
            end
        end
    end
    log("Baufreigabe Jaegerhuette: " .. gesetztZahl .. "/" .. aufgeloest
        .. "; Grund=" .. tostring(grund))
    return gesetztZahl > 0
end

local function start(grund, isEditor)
    generation = generation + 1
    cancel_timers()
    vorherVerfuegbar = {}
    gesetzt = {}
    if isEditor then
        log("Karteneditor erkannt; keine Baufreigabe.")
        return
    end
    local aktuelle = generation
    anwenden(grund .. ":sofort")
    -- Missionen schreiben ihre Kartenregeln teils erst nach dem Start; ein
    -- einzelner begrenzter Nachlauf deckt das ab. Derselbe Wert wie in
    -- UniversalSiegeCore, wo er sich als ausreichend erwiesen hat.
    schedule_once(1200, function() anwenden(grund .. ":1200ms") end, aktuelle)
end

function mod_init()
    start("Neues Spiel", false)
end

function mod_load(isEditor)
    start("Spielstand geladen", isEditor and true or false)
end

function mod_unload()
    generation = generation + 1
    cancel_timers()
    if rawget(_G, "Player_SetBuildingAvailable") ~= nil then
        for name, mapper in pairs(gesetzt) do
            local vorher = vorherVerfuegbar[name]
            if vorher ~= nil then
                pcall(function() Player_SetBuildingAvailable(mapper, vorher) end)
            end
        end
    end
    vorherVerfuegbar = {}
    gesetzt = {}
    log("Baufreigaben beendet.")
end
