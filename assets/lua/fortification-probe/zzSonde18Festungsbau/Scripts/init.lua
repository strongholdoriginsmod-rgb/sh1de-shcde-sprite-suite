-- Sonde 18 - Festungsbau
--
-- Diese Sonde beobachtet genau den nativen Bauweg fuer die Mapper 25-27, 35,
-- 46, 110, 140-147 und 181-186. Sie baut nichts, schaltet nichts frei und
-- schreibt weder Spielzustand noch Save-Daten. Mapper 35 und 181-186 sind nur
-- Referenzwerte.

local TAG = "SONDE18"
local SUBS_KEY = "__zzsonde18_festungsbau_subs"
local GENERATION_KEY = "__zzsonde18_festungsbau_generation"
local SCHEMA = "fortification_probe_v1"

local LIMITS = {
    api = 80,
    lifecycle = 40,
    placement = 240,
    build = 120,
    tile = 720,
    building = 160,
    resource = 280,
    damage = 280,
    movement = 200,
    gate = 180,
    repair = 160,
    bulldoze = 120,
    pairing = 80,
}

local SNAPSHOT_TILE_LIMIT = 512
local WATCHED_TILE_LIMIT = 4096
local MOVEMENT_TRACK_LIMIT = 2048

local MAPPER_SPECS = {
    { id = 25,  name = "MAPPER_WALL",         role = "stone_wall" },
    { id = 26,  name = "MAPPER_CRENAL",       role = "native_battlements" },
    { id = 27,  name = "MAPPER_STAIR",        role = "stair_route_native_vs_wooden_variant", family = "stair", expected_struct = "STRUCT_STAIRS" },
    { id = 35,  name = "MAPPER_CRENAL2",      role = "reference_only", reference = true },
    { id = 46,  name = "MAPPER_WOODWALL",     role = "wood_wall" },
    { id = 110, name = "MAPPER_TOWER1",       role = "watchtower_slot_native_vs_wooden_platform", expected_struct = "STRUCT_TOWER1" },
    { id = 140, name = "MAPPER_GATE_WOOD1A",  role = "wood_gate_a" },
    { id = 141, name = "MAPPER_GATE_WOOD1B",  role = "wood_gate_b" },
    { id = 142, name = "MAPPER_GATE_WOOD1C",  role = "wood_gate_c" },
    { id = 143, name = "MAPPER_GATE_WOOD1D",  role = "wood_gate_d" },
    { id = 144, name = "MAPPER_GATE_STONE1A", role = "stone_gate_small_a" },
    { id = 145, name = "MAPPER_GATE_STONE1B", role = "stone_gate_small_b" },
    { id = 146, name = "MAPPER_GATE_STONE2A", role = "stone_gate_large_a" },
    { id = 147, name = "MAPPER_GATE_STONE2B", role = "stone_gate_large_b" },
    { id = 181, name = "MAPPER_STAIR1",       role = "stair_family_reference_1", family = "stair", reference = true },
    { id = 182, name = "MAPPER_STAIR2",       role = "stair_family_reference_2", family = "stair", reference = true },
    { id = 183, name = "MAPPER_STAIR3",       role = "stair_family_reference_3", family = "stair", reference = true },
    { id = 184, name = "MAPPER_STAIR4",       role = "stair_family_reference_4", family = "stair", reference = true },
    { id = 185, name = "MAPPER_STAIR5",       role = "stair_family_reference_5", family = "stair", reference = true },
    { id = 186, name = "MAPPER_STAIR6",       role = "stair_family_reference_6", family = "stair", reference = true },
}

local ALL_MAPPER_COUNT = #MAPPER_SPECS
local PRIMARY_MAPPER_COUNT = 0
for _, spec in ipairs(MAPPER_SPECS) do
    if not spec.reference then PRIMARY_MAPPER_COUNT = PRIMARY_MAPPER_COUNT + 1 end
end

local phase_pre = nil
local phase_post = nil
local state = nil

local function next_generation()
    local value = rawget(_G, GENERATION_KEY)
    if type(value) ~= "number" then value = 0 end
    value = value + 1
    rawset(_G, GENERATION_KEY, value)
    return value
end

local function current_generation()
    local value = rawget(_G, GENERATION_KEY)
    if type(value) ~= "number" then return 0 end
    return value
end

local function clean(value)
    local text = tostring(value == nil and "na" or value)
    text = text:gsub("[\r\n|]", "_")
    return text
end

local function log_line(text, level_name)
    local payload = tostring(text == nil and "na" or text):gsub("[\r\n]", "_")
    local line = "[" .. TAG .. "] " .. payload
    local level = 2
    local levels = rawget(_G, "eLogEventLevel")
    if levels ~= nil then
        local ok, value = pcall(function() return levels[level_name or "Information"] end)
        if ok and value ~= nil then level = value end
    end
    local logger = rawget(_G, "Log")
    if logger ~= nil and pcall(function() logger(level, line) end) then return end
    local printer = rawget(_G, "print")
    if printer ~= nil then pcall(function() printer(line) end) end
end

local function counter(kind)
    local item = state.logs[kind]
    if item == nil then
        item = { observed = 0, emitted = 0, duplicate = 0, suppressed = 0, keys = {} }
        state.logs[kind] = item
    end
    return item
end

local function emit(kind, key, payload, level_name)
    local item = counter(kind)
    item.observed = item.observed + 1
    if key ~= nil and item.keys[key] then
        item.duplicate = item.duplicate + 1
        return
    end
    local cap = LIMITS[kind] or 100
    if item.emitted >= cap then
        item.suppressed = item.suppressed + 1
        if item.suppressed == 1 then
            log_line("LOG_LIMIT|kind=" .. clean(kind) .. "|cap=" .. cap, "Warning")
        end
        return
    end
    -- Keep the deduplication ledger bounded as well as the emitted log. Event
    -- kinds whose key contains a sequence number would otherwise retain one
    -- table entry forever for every suppressed event.
    if key ~= nil then item.keys[key] = true end
    item.emitted = item.emitted + 1
    log_line(payload, level_name)
end

local function note_api(name, reason)
    emit("api", name .. ":" .. reason,
        "API_COVERAGE|name=" .. clean(name) .. "|status=" .. clean(reason),
        reason == "ok" and "Information" or "Warning")
end

local function api(name, ...)
    local fn = rawget(_G, name)
    if fn == nil then
        note_api(name, "missing")
        return nil, false
    end
    local args = table.pack(...)
    local ok, value = pcall(function()
        return fn(table.unpack(args, 1, args.n))
    end)
    if not ok then
        emit("api", name .. ":error",
            "API_COVERAGE|name=" .. clean(name) .. "|status=call_error|detail=" .. clean(value),
            "Warning")
        return nil, false
    end
    return value, true
end

local function enum_member(container_name, member_name)
    local container = rawget(_G, container_name)
    if container == nil then
        note_api(container_name, "missing")
        return nil
    end
    local ok, value = pcall(function() return container[member_name] end)
    if not ok or value == nil then
        note_api(container_name .. "." .. member_name, "missing")
        return nil
    end
    return value
end

-- Registrierte Enums sind userdata. Darum wird nie tonumber(enum) benutzt;
-- Vergleich laeuft ueber die geboxte Enum-Identitaet oder deren Text.
local function enum_equal(left, right)
    if left == nil or right == nil then return false end
    return left == right or tostring(left) == tostring(right)
end

local function enum_name(value)
    local text = tostring(value == nil and "na" or value)
    return clean((text:gsub(":%s*%-?%d+%s*$", "")))
end

local function phase_name(value)
    if enum_equal(value, phase_pre) then return "Pre" end
    if enum_equal(value, phase_post) then return "Post" end
    return enum_name(value)
end

local function mapper_for(value)
    for _, spec in ipairs(MAPPER_SPECS) do
        if enum_equal(value, spec.value) then return spec end
    end
    return nil
end

local function blank_stats()
    return {
        build_pre = 0,
        build_post = 0,
        placement_pre = 0,
        placement_post = 0,
        local_build_pre = 0,
        local_build_post = 0,
        changed_tiles = 0,
        local_changed_tiles = 0,
        no_diff = 0,
        local_no_diff = 0,
        incomplete_diff = 0,
        local_incomplete_diff = 0,
        resource_pre_events = 0,
        resource_post_events = 0,
        resource_pre_amount = 0,
        resource_post_amount = 0,
        damage_pre = 0,
        damage_post = 0,
        movement_hits = 0,
        gate_queries = 0,
        repair_events = 0,
        bulldoze_events = 0,
    }
end

local function reset_state(entry, is_editor)
    state = {
        entry = entry,
        editor = is_editor and true or false,
        scope = is_editor and "editor" or "unknown",
        active = false,
        activated = false,
        local_player = -1,
        logs = {},
        stats = {},
        pending = { wall = {}, structure = {}, damage = {} },
        active_operations = {},
        watched_tiles = {},
        watched_coords = {},
        watched_buildings = {},
        watched_tile_count = 0,
        watch_limit_reached = false,
        movement_last = {},
        movement_tracked_count = 0,
        movement_track_limit_reached = false,
        operation_sequence = 0,
        placement_sequence = 0,
        resource_sequence = 0,
        damage_sequence = 0,
        movement_sequence = 0,
        gate_sequence = 0,
        repair_sequence = 0,
        bulldoze_sequence = 0,
    }
    for _, spec in ipairs(MAPPER_SPECS) do state.stats[spec.id] = blank_stats() end
end

local function subscriptions()
    local list = rawget(_G, SUBS_KEY)
    if type(list) ~= "table" then
        list = {}
        rawset(_G, SUBS_KEY, list)
    end
    return list
end

local function unsubscribe_all()
    local list = subscriptions()
    local unresolved = {}
    local total = #list
    for index = #list, 1, -1 do
        local record = list[index]
        local sub = record
        if type(record) == "table" and record.subscription ~= nil then
            if record.lease ~= nil then record.lease.active = false end
            sub = record.subscription
        end
        local ok, result = pcall(function() return sub:Unsubscribe() end)
        if not ok or result == false then table.insert(unresolved, 1, record) end
    end
    rawset(_G, SUBS_KEY, unresolved)
    emit("lifecycle", "unsubscribe:" .. total .. ":" .. #unresolved,
        "SUBSCRIPTIONS|action=unsubscribe|total=" .. total .. "|unresolved=" .. #unresolved,
        #unresolved == 0 and "Information" or "Error")
    return #unresolved == 0, total, #unresolved
end

local function safe_handler(name, handler, lease)
    return function(event_args)
        if not lease.active then return end
        local ok, err = pcall(handler, event_args)
        if not ok then
            emit("api", "handler:" .. name .. ":" .. clean(err),
                "HANDLER_ERROR|name=" .. clean(name) .. "|detail=" .. clean(err), "Error")
        end
    end
end

local function subscribe(name, handler, required)
    local hooks = rawget(_G, "Hooks")
    if hooks == nil then
        note_api("Hooks", "missing")
        return false
    end
    local lease = { active = true }
    local ok, sub = pcall(function()
        local hook = hooks:GetHook(name)
        if hook == nil then return nil end
        return hook:Subscribe(safe_handler(name, handler, lease))
    end)
    if not ok or sub == nil then
        emit("api", "hook:" .. name,
            "HOOK_COVERAGE|name=" .. clean(name) .. "|status=missing|required=" .. tostring(required),
            required and "Error" or "Warning")
        return false
    end
    table.insert(subscriptions(), { subscription = sub, lease = lease })
    emit("api", "hook:" .. name,
        "HOOK_COVERAGE|name=" .. clean(name) .. "|status=subscribed|required=" .. tostring(required))
    return true
end

local function coord_key(x, y)
    return tostring(x) .. "," .. tostring(y)
end

local function tile_value(name, tile_id)
    local value, ok = api(name, tile_id)
    if not ok then return "na", false end
    return value, true
end

local function read_tile(x, y)
    local inside, inside_ok = api("Tile_IsInsideMapBounds", x, y)
    if not inside_ok then return nil, false end
    if inside ~= true then return nil, true end
    local tile_id, id_ok = api("Tile_GetId", x, y)
    if not id_ok or tonumber(tile_id) == nil then return nil, false end
    tile_id = tonumber(tile_id)
    local flags, flags_ok = tile_value("Tile_GetPropertyFlag", tile_id)
    local height, height_ok = tile_value("Tile_GetHeight", tile_id)
    local tile_state, state_ok = tile_value("Tile_GetState", tile_id)
    local default_height, default_height_ok = tile_value("Tile_GetDefaultHeight", tile_id)
    local owner, owner_ok = tile_value("Tile_GetOwnerId", tile_id)
    local building, building_ok = tile_value("Tile_GetBuildingId", tile_id)
    local tile_type, type_ok = tile_value("Tile_GetType", tile_id)
    local walkable, walkable_ok = tile_value("Tile_IsWalkableAndUnoccupied", tile_id)
    local complete = flags_ok and height_ok and state_ok and default_height_ok
        and owner_ok and building_ok and type_ok and walkable_ok
    return {
        id = tile_id,
        x = x,
        y = y,
        flags = enum_name(flags),
        height = height,
        state = tile_state,
        default_height = default_height,
        owner = owner,
        building = building,
        tile_type = enum_name(tile_type),
        walkable = walkable,
    }, complete
end

local function tile_text(tile)
    if tile == nil then return "missing" end
    return table.concat({
        "id=" .. clean(tile.id),
        "flags=" .. clean(tile.flags),
        "height=" .. clean(tile.height),
        "state=" .. clean(tile.state),
        "default_height=" .. clean(tile.default_height),
        "owner=" .. clean(tile.owner),
        "building=" .. clean(tile.building),
        "type=" .. clean(tile.tile_type),
        "walkable=" .. clean(tile.walkable),
    }, ";")
end

local function snapshot(x_begin, y_begin, x_end, y_end, padding)
    local min_x = math.min(x_begin, x_end) - padding
    local max_x = math.max(x_begin, x_end) + padding
    local min_y = math.min(y_begin, y_end) - padding
    local max_y = math.max(y_begin, y_end) + padding
    local requested = (max_x - min_x + 1) * (max_y - min_y + 1)
    if requested > SNAPSHOT_TILE_LIMIT then
        emit("pairing", "snapshot_limit:" .. min_x .. ":" .. min_y .. ":" .. max_x .. ":" .. max_y,
            "SNAPSHOT_SKIPPED|reason=tile_limit|requested=" .. requested
                .. "|limit=" .. SNAPSHOT_TILE_LIMIT, "Warning")
        return { tiles = {}, count = 0, complete = false, requested = requested }
    end
    local result = { tiles = {}, count = 0, complete = true, requested = requested }
    for y = min_y, max_y do
        for x = min_x, max_x do
            local tile, tile_complete = read_tile(x, y)
            if not tile_complete then result.complete = false end
            if tile ~= nil then
                result.tiles[coord_key(x, y)] = tile
                result.count = result.count + 1
            end
        end
    end
    return result
end

local function collection_count(collection)
    if collection == nil then return -1 end
    local ok_length, length = pcall(function() return collection.Length end)
    if ok_length and tonumber(length) ~= nil then return tonumber(length) end
    local ok_count, count = pcall(function() return collection.Count end)
    if ok_count and tonumber(count) ~= nil then return tonumber(count) end
    local ok_hash, hash = pcall(function() return #collection end)
    if ok_hash and tonumber(hash) ~= nil then return tonumber(hash) end
    return -1
end

local function read_building(building_id)
    building_id = tonumber(building_id)
    if building_id == nil or building_id <= 0 then return nil end
    local valid = api("Building_IsValid", building_id)
    if valid ~= true then return nil end
    local occupied = api("Building_GetOccupiedTileIds", building_id)
    return {
        id = building_id,
        type = enum_name(api("Building_GetType", building_id)),
        owner = api("Building_GetOwner", building_id),
        health = api("Building_GetCurrentHealth", building_id),
        max_health = api("Building_GetMaxHealth", building_id),
        begin_tile = api("Building_GetBeginTileId", building_id),
        grid_size = api("Building_GetBuildingOccupyTileGridSize", building_id),
        occupied = collection_count(occupied),
    }
end

local function register_building(op, building_id)
    building_id = tonumber(building_id)
    if building_id == nil or building_id <= 0 then return end
    state.watched_buildings[building_id] = op.spec
    local building = read_building(building_id)
    if building == nil then return end
    emit("building", op.sequence .. ":" .. building_id,
        "BUILDING_STATE|op=" .. op.sequence
            .. "|mapper=" .. op.spec.id
            .. "|mapper_name=" .. op.spec.name
            .. "|building_id=" .. building.id
            .. "|building_type=" .. clean(building.type)
            .. "|owner=" .. clean(building.owner)
            .. "|health=" .. clean(building.health)
            .. "|max_health=" .. clean(building.max_health)
            .. "|begin_tile=" .. clean(building.begin_tile)
            .. "|grid_size=" .. clean(building.grid_size)
            .. "|occupied_tiles=" .. clean(building.occupied))
end

local function remember_changed_tile(op, tile)
    if tile == nil then return end
    if state.watched_tiles[tile.id] == nil then
        if state.watched_tile_count >= WATCHED_TILE_LIMIT then
            if not state.watch_limit_reached then
                state.watch_limit_reached = true
                emit("pairing", "watch_limit",
                    "WATCH_LIMIT|kind=changed_tiles|cap=" .. WATCHED_TILE_LIMIT,
                    "Warning")
            end
            return
        end
        state.watched_tile_count = state.watched_tile_count + 1
    end
    state.watched_tiles[tile.id] = op.spec
    state.watched_coords[coord_key(tile.x, tile.y)] = op.spec
    register_building(op, tile.building)
end

local function compare_snapshots(op, after)
    local stats = state.stats[op.spec.id]
    if op.before == nil or after == nil or not op.before.complete or not after.complete then
        stats.incomplete_diff = stats.incomplete_diff + 1
        if op.local_action then
            stats.local_incomplete_diff = stats.local_incomplete_diff + 1
        end
        emit("pairing", "diff_incomplete:" .. op.sequence,
            "TILE_DIFF_SUMMARY|op=" .. op.sequence .. "|mapper=" .. op.spec.id
                .. "|status=incomplete|changed=unknown", "Warning")
        return -1
    end
    local keys = {}
    for key in pairs(op.before.tiles) do keys[key] = true end
    for key in pairs(after.tiles) do keys[key] = true end
    local ordered = {}
    for key in pairs(keys) do table.insert(ordered, key) end
    table.sort(ordered)
    local changed = 0
    for _, key in ipairs(ordered) do
        local before_tile = op.before.tiles[key]
        local after_tile = after.tiles[key]
        if tile_text(before_tile) ~= tile_text(after_tile) then
            changed = changed + 1
            remember_changed_tile(op, after_tile)
            emit("tile", op.sequence .. ":" .. key,
                "TILE_DIFF|op=" .. op.sequence
                    .. "|mapper=" .. op.spec.id
                    .. "|mapper_name=" .. op.spec.name
                    .. "|coord=" .. clean(key)
                    .. "|before=" .. tile_text(before_tile)
                    .. "|after=" .. tile_text(after_tile))
        end
    end
    stats.changed_tiles = stats.changed_tiles + changed
    if op.local_action then stats.local_changed_tiles = stats.local_changed_tiles + changed end
    if changed == 0 then
        stats.no_diff = stats.no_diff + 1
        if op.local_action then stats.local_no_diff = stats.local_no_diff + 1 end
    end
    emit("pairing", "diff:" .. op.sequence,
        "TILE_DIFF_SUMMARY|op=" .. op.sequence .. "|mapper=" .. op.spec.id
            .. "|status=complete|changed=" .. changed
            .. "|scanned_before=" .. op.before.count
            .. "|scanned_after=" .. after.count)
    return changed
end

local function push_operation(kind, event_args, spec, x_begin, y_begin, x_end, y_end, padding)
    state.operation_sequence = state.operation_sequence + 1
    local op = {
        sequence = state.operation_sequence,
        kind = kind,
        spec = spec,
        player = event_args.PlayerId,
        local_action = tonumber(event_args.PlayerId) == state.local_player,
        x_begin = x_begin,
        y_begin = y_begin,
        x_end = x_end,
        y_end = y_end,
        before = snapshot(x_begin, y_begin, x_end, y_end, padding),
        padding = padding,
    }
    table.insert(state.pending[kind], op)
    table.insert(state.active_operations, op)
    return op
end

local function remove_active(op)
    for index = #state.active_operations, 1, -1 do
        if state.active_operations[index] == op then
            table.remove(state.active_operations, index)
            return
        end
    end
end

local function current_operation()
    return state.active_operations[#state.active_operations]
end

local function pop_operation(kind)
    local list = state.pending[kind]
    local op = list[#list]
    if op ~= nil then table.remove(list, #list) end
    return op
end

local function record_unpaired_post(spec, event_args)
    local stats = state.stats[spec.id]
    stats.build_post = stats.build_post + 1
    stats.incomplete_diff = stats.incomplete_diff + 1
    if tonumber(event_args.PlayerId) == state.local_player then
        stats.local_build_post = stats.local_build_post + 1
        stats.local_incomplete_diff = stats.local_incomplete_diff + 1
    end
end

local function on_placement_validation(event_args)
    if not state.active then return end
    local spec = mapper_for(event_args.Mappers)
    if spec == nil then return end
    local phase = phase_name(event_args.Phase)
    local stats = state.stats[spec.id]
    if phase == "Pre" then stats.placement_pre = stats.placement_pre + 1 end
    if phase == "Post" then stats.placement_post = stats.placement_post + 1 end
    state.placement_sequence = state.placement_sequence + 1
    local key = table.concat({
        spec.id,
        phase,
        clean(event_args.PlayerId),
        clean(event_args.TileX),
        clean(event_args.TileY),
        clean(event_args.Unknown1),
        clean(event_args.Unknown2),
    }, ":")
    -- The hook exposes inputs but no native allowed/result value. In
    -- particular, CustomValidationRules and ForceBlockPlacementState are
    -- override controls, not a readable native placement result.
    emit("placement", key,
        "PLACEMENT_VALIDATION|seq=" .. state.placement_sequence
            .. "|phase=" .. clean(phase)
            .. "|player=" .. clean(event_args.PlayerId)
            .. "|local=" .. tostring(tonumber(event_args.PlayerId) == state.local_player)
            .. "|mapper=" .. spec.id
            .. "|mapper_name=" .. spec.name
            .. "|family=" .. clean(spec.family)
            .. "|coord=" .. clean(event_args.TileX) .. "," .. clean(event_args.TileY)
            .. "|unknown1=" .. clean(event_args.Unknown1)
            .. "|unknown2=" .. clean(event_args.Unknown2)
            .. "|custom_rules=" .. clean(event_args.CustomValidationRules)
            .. "|force_block_override=" .. clean(event_args.ForceBlockPlacementState)
            .. "|skip=" .. tostring(event_args.SkipOriginalFunction == true)
            .. "|native_result=not_exposed")
end

local function on_build_wall(event_args)
    if not state.active then return end
    local spec = mapper_for(event_args.WallType)
    if spec == nil then return end
    local phase = phase_name(event_args.Phase)
    if phase == "Pre" then
        local op = push_operation("wall", event_args, spec,
            event_args.TileXBegin, event_args.TileYBegin,
            event_args.TileXEnd, event_args.TileYEnd, 2)
        local stats = state.stats[spec.id]
        stats.build_pre = stats.build_pre + 1
        if op.local_action then stats.local_build_pre = stats.local_build_pre + 1 end
        emit("build", op.sequence .. ":Pre",
            "BUILD|op=" .. op.sequence .. "|kind=wall|phase=Pre|player=" .. clean(event_args.PlayerId)
                .. "|local=" .. tostring(op.local_action)
                .. "|mapper=" .. spec.id .. "|mapper_name=" .. spec.name
                .. "|role=" .. spec.role
                .. "|family=" .. clean(spec.family)
                .. "|expected_struct=" .. clean(spec.expected_struct)
                .. "|begin=" .. clean(event_args.TileXBegin) .. "," .. clean(event_args.TileYBegin)
                .. "|end=" .. clean(event_args.TileXEnd) .. "," .. clean(event_args.TileYEnd)
                .. "|build_max=" .. clean(event_args.BuildWallsMaximum)
                .. "|skip=" .. tostring(event_args.SkipOriginalFunction == true)
                .. "|scan_tiles=" .. op.before.count)
        return
    end
    if phase ~= "Post" then return end
    local op = pop_operation("wall")
    if op == nil then
        record_unpaired_post(spec, event_args)
        emit("pairing", "wall_post_missing:" .. state.operation_sequence,
            "PAIRING|kind=wall|phase=Post|status=missing_pre|mapper=" .. spec.id, "Warning")
        return
    end
    remove_active(op)
    local stats = state.stats[op.spec.id]
    stats.build_post = stats.build_post + 1
    if op.local_action then stats.local_build_post = stats.local_build_post + 1 end
    local after = snapshot(op.x_begin, op.y_begin, op.x_end, op.y_end, op.padding)
    local changed = compare_snapshots(op, after)
    emit("build", op.sequence .. ":Post",
        "BUILD|op=" .. op.sequence .. "|kind=wall|phase=Post|player=" .. clean(event_args.PlayerId)
            .. "|local=" .. tostring(op.local_action)
            .. "|mapper=" .. op.spec.id .. "|mapper_name=" .. op.spec.name
            .. "|expected_struct=" .. clean(op.spec.expected_struct)
            .. "|changed_tiles=" .. clean(changed))
end

local function on_build_structure(event_args)
    if not state.active then return end
    local spec = mapper_for(event_args.Mappers)
    if spec == nil then return end
    local phase = phase_name(event_args.Phase)
    if phase == "Pre" then
        local op = push_operation("structure", event_args, spec,
            event_args.TileX, event_args.TileY, event_args.TileX, event_args.TileY, 6)
        local stats = state.stats[spec.id]
        stats.build_pre = stats.build_pre + 1
        if op.local_action then stats.local_build_pre = stats.local_build_pre + 1 end
        emit("build", op.sequence .. ":Pre",
            "BUILD|op=" .. op.sequence .. "|kind=structure|phase=Pre|player=" .. clean(event_args.PlayerId)
                .. "|local=" .. tostring(op.local_action)
                .. "|mapper=" .. spec.id .. "|mapper_name=" .. spec.name
                .. "|role=" .. spec.role
                .. "|family=" .. clean(spec.family)
                .. "|expected_struct=" .. clean(spec.expected_struct)
                .. "|coord=" .. clean(event_args.TileX) .. "," .. clean(event_args.TileY)
                .. "|scale=" .. clean(event_args.BuildingScaleUnknown)
                .. "|unknown1=" .. clean(event_args.Unknown1)
                .. "|free=" .. clean(event_args.IsFree)
                .. "|skip=" .. tostring(event_args.SkipOriginalFunction == true)
                .. "|scan_tiles=" .. op.before.count)
        return
    end
    if phase ~= "Post" then return end
    local op = pop_operation("structure")
    if op == nil then
        record_unpaired_post(spec, event_args)
        emit("pairing", "structure_post_missing:" .. state.operation_sequence,
            "PAIRING|kind=structure|phase=Post|status=missing_pre|mapper=" .. spec.id, "Warning")
        return
    end
    remove_active(op)
    local stats = state.stats[op.spec.id]
    stats.build_post = stats.build_post + 1
    if op.local_action then stats.local_build_post = stats.local_build_post + 1 end
    local after = snapshot(op.x_begin, op.y_begin, op.x_end, op.y_end, op.padding)
    local changed = compare_snapshots(op, after)
    emit("build", op.sequence .. ":Post",
        "BUILD|op=" .. op.sequence .. "|kind=structure|phase=Post|player=" .. clean(event_args.PlayerId)
            .. "|local=" .. tostring(op.local_action)
            .. "|mapper=" .. op.spec.id .. "|mapper_name=" .. op.spec.name
            .. "|expected_struct=" .. clean(op.spec.expected_struct)
            .. "|changed_tiles=" .. clean(changed))
end

local function on_subtract_resource(event_args)
    if not state.active then return end
    local op = current_operation()
    local phase = phase_name(event_args.Phase)
    state.resource_sequence = state.resource_sequence + 1
    local amount = tonumber(event_args.Amount) or 0
    if op ~= nil then
        local stats = state.stats[op.spec.id]
        if phase == "Pre" then
            stats.resource_pre_events = stats.resource_pre_events + 1
            stats.resource_pre_amount = stats.resource_pre_amount + amount
        elseif phase == "Post" then
            stats.resource_post_events = stats.resource_post_events + 1
            stats.resource_post_amount = stats.resource_post_amount + amount
        end
    end
    local stock = api("Player_GetGoodAmount", event_args.PlayerId, event_args.Good)
    emit("resource", tostring(state.resource_sequence),
        "RESOURCE_SUBTRACT|seq=" .. state.resource_sequence
            .. "|op=" .. (op and tostring(op.sequence) or "none")
            .. "|phase=" .. clean(phase)
            .. "|player=" .. clean(event_args.PlayerId)
            .. "|mapper=" .. (op and tostring(op.spec.id) or "unattributed")
            .. "|good=" .. enum_name(event_args.Good)
            .. "|amount=" .. clean(event_args.Amount)
            .. "|dont_subtract=" .. clean(event_args.DontSubtract)
            .. "|skip=" .. tostring(event_args.SkipOriginalFunction == true)
            .. "|stock_at_event=" .. clean(stock))
end

local function attributed_spec(tile_id, x, y)
    local by_id = state.watched_tiles[tonumber(tile_id)]
    if by_id ~= nil then return by_id end
    return state.watched_coords[coord_key(x, y)]
end

local function on_damage(event_args)
    if not state.active then return end
    local phase = phase_name(event_args.Phase)
    state.damage_sequence = state.damage_sequence + 1
    local spec = attributed_spec(event_args.TileId, event_args.TileX, event_args.TileY)
    local before_or_after = read_tile(event_args.TileX, event_args.TileY)
    if spec ~= nil then
        local stats = state.stats[spec.id]
        if phase == "Pre" then stats.damage_pre = stats.damage_pre + 1 end
        if phase == "Post" then stats.damage_post = stats.damage_post + 1 end
    end
    -- The pinned 1.44 damage detour ignores SkipOriginalFunction and always
    -- calls the native function followed by Post. Keep pairing independent of
    -- a value another subscriber may have written into that inherited field.
    if phase == "Pre" then
        table.insert(state.pending.damage, before_or_after)
    elseif phase == "Post" and #state.pending.damage > 0 then
        table.remove(state.pending.damage, #state.pending.damage)
    end
    emit("damage", tostring(state.damage_sequence),
        "DAMAGE|seq=" .. state.damage_sequence
            .. "|phase=" .. clean(phase)
            .. "|tile=" .. clean(event_args.TileId)
            .. "|coord=" .. clean(event_args.TileX) .. "," .. clean(event_args.TileY)
            .. "|mapper=" .. (spec and tostring(spec.id) or "unattributed")
            .. "|damage=" .. clean(event_args.Damage)
            .. "|player_source=" .. clean(event_args.PlayerIdSource)
            .. "|unknown1=" .. clean(event_args.Unknown1)
            .. "|unknown3=" .. clean(event_args.Unknown3)
            .. "|unknown4=" .. clean(event_args.Unknown4)
            .. "|skip=" .. tostring(event_args.SkipOriginalFunction == true)
            .. "|damage_kind=not_exposed"
            .. "|tile_state=" .. tile_text(before_or_after))
end

local function on_unit_movement(event_args)
    if not state.active or next(state.watched_coords) == nil then return end
    if phase_name(event_args.Phase) ~= "Pre" then return end
    local unit_id = tonumber(event_args.UnitId)
    if unit_id == nil then return end
    local local_position = api("Unit_GetLocalPosition", unit_id)
    if local_position == nil then
        note_api("Unit_GetLocalPosition", "nil_result")
        return
    end
    local ok_x, x = pcall(function() return tonumber(local_position.X) end)
    local ok_y, y = pcall(function() return tonumber(local_position.Y) end)
    if not ok_x or not ok_y or x == nil or y == nil then
        note_api("Unit_GetLocalPosition.XY", "member_unreadable")
        return
    end

    local previous = state.movement_last[unit_id]
    if previous == nil then
        if state.movement_tracked_count >= MOVEMENT_TRACK_LIMIT then
            if not state.movement_track_limit_reached then
                state.movement_track_limit_reached = true
                emit("pairing", "movement_track_limit",
                    "WATCH_LIMIT|kind=movement_units|cap=" .. MOVEMENT_TRACK_LIMIT,
                    "Warning")
            end
            return
        end
        state.movement_tracked_count = state.movement_tracked_count + 1
        state.movement_last[unit_id] = { x = x, y = y, z = nil }
        return
    end
    local tile_changed = previous.x ~= x or previous.y ~= y
    local spec = state.watched_coords[coord_key(x, y)]
    if spec == nil then
        state.movement_last[unit_id] = { x = x, y = y, z = nil }
        return
    end

    -- Unity-side lookup is the more expensive per-frame read. Only perform it
    -- while the real unit is currently on a changed target tile.
    local unity_position = api("Unit_GetUnityPosition", unit_id)
    local unity_x, unity_y, unity_z = nil, nil, nil
    local unity_status = "unavailable"
    if unity_position ~= nil then
        local ok_unity_x, value_x = pcall(function() return tonumber(unity_position.X) end)
        local ok_unity_y, value_y = pcall(function() return tonumber(unity_position.Y) end)
        local ok_unity_z, value_z = pcall(function() return tonumber(unity_position.Z) end)
        if ok_unity_x and value_x ~= nil then unity_x = value_x
        else note_api("Unit_GetUnityPosition.X", "member_unreadable") end
        if ok_unity_y and value_y ~= nil then unity_y = value_y
        else note_api("Unit_GetUnityPosition.Y", "member_unreadable") end
        if ok_unity_z and value_z ~= nil then unity_z = value_z
        else note_api("Unit_GetUnityPosition.Z", "member_unreadable") end
        if unity_x ~= nil and unity_y ~= nil and unity_z ~= nil then
            if unity_x == 0 and unity_y == 0 and unity_z == 0 then
                unity_status = "zero_or_unavailable"
                note_api("Unit_GetUnityPosition", "zero_or_unavailable")
            else
                unity_status = "ok"
            end
        else
            unity_status = "member_unreadable"
        end
    else
        note_api("Unit_GetUnityPosition", "nil_result")
    end

    local comparable_z = unity_status == "ok" and unity_z or nil
    local remembered_z = comparable_z
    if remembered_z == nil then remembered_z = previous.z end
    state.movement_last[unit_id] = { x = x, y = y, z = remembered_z }
    local z_changed = previous.z ~= nil and comparable_z ~= nil and previous.z ~= comparable_z
    if not tile_changed and not z_changed then return end
    local unique = table.concat({
        unit_id,
        coord_key(x, y),
        clean(unity_z),
        spec.id,
    }, ":")
    state.movement_sequence = state.movement_sequence + 1
    state.stats[spec.id].movement_hits = state.stats[spec.id].movement_hits + 1
    emit("movement", unique,
        "MOVEMENT_HIT|seq=" .. state.movement_sequence
            .. "|unit=" .. unit_id
            .. "|owner=" .. clean(api("Unit_GetOwner", unit_id))
            .. "|unit_type=" .. enum_name(api("Unit_GetType", unit_id))
            .. "|local_coord=" .. x .. "," .. y
            .. "|unity_coord=" .. clean(unity_x) .. "," .. clean(unity_y)
                .. "," .. clean(unity_z)
            .. "|unity_status=" .. unity_status
            .. "|tile_changed=" .. tostring(tile_changed)
            .. "|z_changed=" .. tostring(z_changed)
            .. "|mapper=" .. spec.id
            .. "|mapper_name=" .. spec.name)
end

local function on_gate_query(event_args)
    if not state.active then return end
    state.gate_sequence = state.gate_sequence + 1
    local spec = state.watched_buildings[tonumber(event_args.BuildingId)]
    if spec ~= nil then state.stats[spec.id].gate_queries = state.stats[spec.id].gate_queries + 1 end
    local decision = event_args.ShouldClose == nil and "native" or clean(event_args.ShouldClose)
    local key = clean(event_args.BuildingId) .. ":" .. clean(event_args.UnitId) .. ":" .. decision
    emit("gate", key,
        "GATE_QUERY|seq=" .. state.gate_sequence
            .. "|phase=" .. phase_name(event_args.Phase)
            .. "|building=" .. clean(event_args.BuildingId)
            .. "|unit=" .. clean(event_args.UnitId)
            .. "|mapper=" .. (spec and tostring(spec.id) or "unattributed")
            .. "|should_close=" .. decision)
end

local function repair_spec(building_id)
    return state.watched_buildings[tonumber(building_id)]
end

local function on_building_repair(event_args)
    if not state.active then return end
    state.repair_sequence = state.repair_sequence + 1
    local spec = repair_spec(event_args.BuildingId)
    if spec ~= nil then state.stats[spec.id].repair_events = state.stats[spec.id].repair_events + 1 end
    emit("repair", "repair:" .. state.repair_sequence,
        "REPAIR|seq=" .. state.repair_sequence
            .. "|phase=" .. phase_name(event_args.Phase)
            .. "|player=" .. clean(event_args.PlayerId)
            .. "|building=" .. clean(event_args.BuildingId)
            .. "|global_id=" .. clean(event_args.BuildingGlobalId)
            .. "|mapper=" .. (spec and tostring(spec.id) or "unattributed")
            .. "|wood=" .. clean(event_args.WoodCost)
            .. "|stone=" .. clean(event_args.StoneCost)
            .. "|skip=" .. tostring(event_args.SkipOriginalFunction == true))
end

local function on_repair_cost(event_args, resource)
    if not state.active then return end
    state.repair_sequence = state.repair_sequence + 1
    local spec = repair_spec(event_args.BuildingId)
    if spec ~= nil then state.stats[spec.id].repair_events = state.stats[spec.id].repair_events + 1 end
    emit("repair", resource .. ":" .. state.repair_sequence,
        "REPAIR_COST|seq=" .. state.repair_sequence
            .. "|resource=" .. resource
            .. "|phase=" .. phase_name(event_args.Phase)
            .. "|building=" .. clean(event_args.BuildingId)
            .. "|mapper=" .. (spec and tostring(spec.id) or "unattributed")
            .. "|cost=" .. clean(event_args.RepairCost)
            .. "|skip=" .. tostring(event_args.SkipOriginalFunction == true))
end

local function on_wall_bulldoze(event_args)
    if not state.active then return end
    state.bulldoze_sequence = state.bulldoze_sequence + 1
    local tile = api("Tile_GetTileVectorFromId", event_args.TileId)
    local spec = state.watched_tiles[tonumber(event_args.TileId)]
    if spec ~= nil then state.stats[spec.id].bulldoze_events = state.stats[spec.id].bulldoze_events + 1 end
    emit("bulldoze", "wall:" .. state.bulldoze_sequence,
        "BULLDOZE|seq=" .. state.bulldoze_sequence
            .. "|kind=wall|phase=" .. phase_name(event_args.Phase)
            .. "|player=" .. clean(event_args.PlayerId)
            .. "|tile=" .. clean(event_args.TileId)
            .. "|tile_vector=" .. clean(tile)
            .. "|mapper=" .. (spec and tostring(spec.id) or "unattributed")
            .. "|skip=" .. tostring(event_args.SkipOriginalFunction == true))
end

local function on_building_bulldoze(event_args)
    if not state.active then return end
    state.bulldoze_sequence = state.bulldoze_sequence + 1
    local spec = state.watched_buildings[tonumber(event_args.BuildingId)]
    if spec ~= nil then state.stats[spec.id].bulldoze_events = state.stats[spec.id].bulldoze_events + 1 end
    emit("bulldoze", "building:" .. state.bulldoze_sequence,
        "BULLDOZE|seq=" .. state.bulldoze_sequence
            .. "|kind=building|phase=" .. phase_name(event_args.Phase)
            .. "|building=" .. clean(event_args.BuildingId)
            .. "|mapper=" .. (spec and tostring(spec.id) or "unattributed")
            .. "|skip=" .. tostring(event_args.SkipOriginalFunction == true))
end

local function bind_enums()
    phase_pre = enum_member("eEventHookPhase", "Pre")
    phase_post = enum_member("eEventHookPhase", "Post")
    local ok = phase_pre ~= nil and phase_post ~= nil
    for _, spec in ipairs(MAPPER_SPECS) do
        spec.value = enum_member("eMappers", spec.name)
        if spec.value == nil then ok = false end
    end
    return ok
end

local function activate()
    if not bind_enums() then
        state.active = false
        emit("lifecycle", "enum_failure",
            "CONTRACT|active=false|fail_closed=true|reason=enum_missing", "Error")
        return false
    end
    -- api() returns (value, success). Passing that call directly to tonumber
    -- would turn success into tonumber's optional base argument and abort every
    -- activation under Lua 5.4.
    local local_player_value, local_player_ok = api("Player_GetLocalId")
    local local_player = local_player_ok and tonumber(local_player_value) or nil
    if local_player == nil or local_player < 1 then
        state.active = false
        emit("lifecycle", "local_player_failure",
            "CONTRACT|active=false|fail_closed=true|reason=local_player_unavailable", "Error")
        return false
    end
    state.local_player = local_player
    local required_wall = subscribe("OnBuildWall", on_build_wall, true)
    local required_structure = subscribe("OnBuildStructure", on_build_structure, true)
    local placement = subscribe("OnPlacementValidation", on_placement_validation, true)
    local resource = subscribe("OnPlayerSubtractResource", on_subtract_resource, true)
    local damage = subscribe("OnBuildingTileTakeDamage", on_damage, true)
    subscribe("OnUnitMovement", on_unit_movement, false)
    subscribe("OnGatehouseQuery", on_gate_query, false)
    subscribe("OnBuildingRepair", on_building_repair, false)
    subscribe("OnBuildingCalculateStoneRepairCost",
        function(event_args) on_repair_cost(event_args, "stone") end, false)
    subscribe("OnBuildingCalculateWoodRepairCost",
        function(event_args) on_repair_cost(event_args, "wood") end, false)
    subscribe("OnWallBulldoze", on_wall_bulldoze, false)
    subscribe("OnBuildingBulldoze", on_building_bulldoze, false)
    state.active = required_wall and required_structure and placement and resource and damage
    state.activated = state.active
    emit("lifecycle", "activate:" .. tostring(state.active),
        "CONTRACT|active=" .. tostring(state.active)
            .. "|scope=" .. state.scope
            .. "|fail_closed=true"
            .. "|read_only=true"
            .. "|local_player=" .. state.local_player
            .. "|schema=" .. SCHEMA,
        state.active and "Information" or "Error")
    if not state.active then unsubscribe_all() end
    return state.active
end

local function begin(entry, is_editor)
    local my_generation = next_generation()
    reset_state(entry, is_editor)
    local clean_subs = unsubscribe_all()
    local map_name = api("Player_GetCurrentMapName")
    emit("lifecycle", "start:" .. entry,
        "LIFECYCLE|event=start|entry=" .. entry
            .. "|editor=" .. tostring(is_editor)
            .. "|map=" .. clean(map_name)
            .. "|shcdese_required=1.44.0")
    if not clean_subs then
        emit("lifecycle", "old_subscriptions",
            "CONTRACT|active=false|fail_closed=true|reason=old_subscriptions", "Error")
        return
    end
    if is_editor then
        state.scope = "editor"
        activate()
        return
    end
    local network_check = rawget(_G, "Net_IsNetworkedEnvironmentAsync")
    if network_check == nil then
        note_api("Net_IsNetworkedEnvironmentAsync", "missing")
        emit("lifecycle", "network_api_missing",
            "CONTRACT|active=false|scope=unknown|fail_closed=true|reason=network_api_missing",
            "Error")
        return
    end
    local ok, err = pcall(function()
        network_check(function(is_networked)
            local callback_ok, callback_err = pcall(function()
                if current_generation() ~= my_generation then return end
                if is_networked ~= false then
                    state.scope = is_networked == true and "multiplayer" or "unknown"
                    state.active = false
                    emit("lifecycle", "network_suppressed:" .. state.scope,
                        "CONTRACT|active=false|scope=" .. state.scope
                            .. "|fail_closed=true|reason=networked_or_unknown")
                    return
                end
                state.scope = "singleplayer"
                activate()
            end)
            if not callback_ok then
                emit("api", "network_callback:" .. clean(callback_err),
                    "HANDLER_ERROR|name=network_scope_callback|detail=" .. clean(callback_err), "Error")
            end
        end)
    end)
    if not ok then
        emit("api", "network_call:" .. clean(err),
            "CONTRACT|active=false|scope=unknown|fail_closed=true|reason=network_check_error"
                .. "|detail=" .. clean(err), "Error")
    end
end

local function summary()
    local local_pre_all = 0
    local local_pre_primary = 0
    local observed_primary = 0
    local observed_all = 0
    local observed_primary_any_player = 0
    local observed_all_any_player = 0
    local changed_primary = 0
    local changed_primary_any_player = 0
    local negative_primary = 0
    local inconclusive_primary = 0
    local wood_gate_orientations = 0
    local wood_gate_changed = 0
    for _, spec in ipairs(MAPPER_SPECS) do
        local stats = state.stats[spec.id]
        if stats.local_build_pre > 0 then
            local_pre_all = local_pre_all + 1
            if not spec.reference then local_pre_primary = local_pre_primary + 1 end
        end
        if stats.local_build_post > 0 then
            observed_all = observed_all + 1
            if not spec.reference then observed_primary = observed_primary + 1 end
            if spec.id >= 140 and spec.id <= 143 then
                wood_gate_orientations = wood_gate_orientations + 1
            end
        end
        if stats.build_post > 0 then
            observed_all_any_player = observed_all_any_player + 1
            if not spec.reference then
                observed_primary_any_player = observed_primary_any_player + 1
            end
        end
        if not spec.reference and stats.local_changed_tiles > 0 then
            changed_primary = changed_primary + 1
        end
        if not spec.reference and stats.changed_tiles > 0 then
            changed_primary_any_player = changed_primary_any_player + 1
        end
        if not spec.reference and stats.local_build_post > 0
                and stats.local_changed_tiles == 0 then
            if stats.local_no_diff > 0 and stats.local_incomplete_diff == 0 then
                negative_primary = negative_primary + 1
            else
                inconclusive_primary = inconclusive_primary + 1
            end
        end
        if spec.id >= 140 and spec.id <= 143 and stats.local_changed_tiles > 0 then
            wood_gate_changed = wood_gate_changed + 1
        end
        log_line("MAPPER_SUMMARY|schema=" .. SCHEMA
            .. "|mapper=" .. spec.id
            .. "|mapper_name=" .. spec.name
            .. "|role=" .. spec.role
            .. "|family=" .. clean(spec.family)
            .. "|expected_struct=" .. clean(spec.expected_struct)
            .. "|reference=" .. tostring(spec.reference == true)
            .. "|placement_pre=" .. stats.placement_pre
            .. "|placement_post=" .. stats.placement_post
            .. "|build_pre=" .. stats.build_pre
            .. "|build_post=" .. stats.build_post
            .. "|local_build_pre=" .. stats.local_build_pre
            .. "|local_build_post=" .. stats.local_build_post
            .. "|changed_tiles=" .. stats.changed_tiles
            .. "|local_changed_tiles=" .. stats.local_changed_tiles
            .. "|no_diff=" .. stats.no_diff
            .. "|local_no_diff=" .. stats.local_no_diff
            .. "|incomplete_diff=" .. stats.incomplete_diff
            .. "|local_incomplete_diff=" .. stats.local_incomplete_diff
            .. "|resource_pre_events=" .. stats.resource_pre_events
            .. "|resource_post_events=" .. stats.resource_post_events
            .. "|resource_pre_amount=" .. stats.resource_pre_amount
            .. "|resource_post_amount=" .. stats.resource_post_amount
            .. "|damage_pre=" .. stats.damage_pre
            .. "|damage_post=" .. stats.damage_post
            .. "|movement_hits=" .. stats.movement_hits
            .. "|gate_queries=" .. stats.gate_queries
            .. "|repair_events=" .. stats.repair_events
            .. "|bulldoze_events=" .. stats.bulldoze_events)
    end
    for kind, item in pairs(state.logs) do
        log_line("LOG_SUMMARY|kind=" .. clean(kind)
            .. "|observed=" .. item.observed
            .. "|emitted=" .. item.emitted
            .. "|duplicates=" .. item.duplicate
            .. "|suppressed=" .. item.suppressed)
    end
    log_line("SESSION_SUMMARY|schema=" .. SCHEMA
        .. "|entry=" .. state.entry
        .. "|scope=" .. state.scope
        .. "|editor=" .. tostring(state.editor)
        .. "|activated=" .. tostring(state.activated)
        .. "|active_at_end=" .. tostring(state.active)
        .. "|local_pre_primary=" .. local_pre_primary .. "/" .. PRIMARY_MAPPER_COUNT
        .. "|local_pre_all=" .. local_pre_all .. "/" .. ALL_MAPPER_COUNT
        .. "|observed_primary=" .. observed_primary .. "/" .. PRIMARY_MAPPER_COUNT
        .. "|observed_all=" .. observed_all .. "/" .. ALL_MAPPER_COUNT
        .. "|observed_primary_any_player=" .. observed_primary_any_player .. "/" .. PRIMARY_MAPPER_COUNT
        .. "|observed_all_any_player=" .. observed_all_any_player .. "/" .. ALL_MAPPER_COUNT
        .. "|changed_primary=" .. changed_primary .. "/" .. PRIMARY_MAPPER_COUNT
        .. "|changed_primary_any_player=" .. changed_primary_any_player .. "/" .. PRIMARY_MAPPER_COUNT
        .. "|negative_primary=" .. negative_primary .. "/" .. PRIMARY_MAPPER_COUNT
        .. "|inconclusive_primary=" .. inconclusive_primary .. "/" .. PRIMARY_MAPPER_COUNT
        .. "|wood_gate_orientations=" .. wood_gate_orientations .. "/4"
        .. "|wood_gate_changed=" .. wood_gate_changed .. "/4"
        .. "|watched_tiles=" .. state.watched_tile_count .. "/" .. WATCHED_TILE_LIMIT
        .. "|watch_limit_reached=" .. tostring(state.watch_limit_reached)
        .. "|movement_units=" .. state.movement_tracked_count .. "/" .. MOVEMENT_TRACK_LIMIT
        .. "|movement_track_limit_reached=" .. tostring(state.movement_track_limit_reached)
        .. "|operations=" .. state.operation_sequence)
    local status = "inactive"
    local reason = "probe_not_activated"
    if state.activated and local_pre_all == 0 and observed_all == 0 then
        status = "nothing_observed"
        reason = "no_local_mapper_build_observed"
    elseif state.activated and observed_all == 0 then
        status = "observed_inconclusive"
        reason = "local_pre_observed_without_post"
    elseif changed_primary == 0 and inconclusive_primary > 0 then
        status = "observed_inconclusive"
        reason = "local_build_observed_with_incomplete_tile_snapshot"
    elseif changed_primary == 0 and negative_primary > 0 then
        status = "observed_negative"
        reason = "local_build_observed_without_tile_change"
    elseif observed_primary == PRIMARY_MAPPER_COUNT and changed_primary == PRIMARY_MAPPER_COUNT then
        status = "placement_coverage_complete"
        reason = "variant_context_render_path_damage_kind_and_save_persistence_require_manual_review"
    else
        status = "partial"
        reason = "local_mapper_or_tile_diff_coverage_incomplete"
    end
    log_line("URTEIL|status=" .. status
        .. "|placement_confirmed="
        .. tostring(observed_primary == PRIMARY_MAPPER_COUNT and changed_primary == PRIMARY_MAPPER_COUNT)
        .. "|mechanics_confirmed=false"
        .. "|variant_context=not_exposed"
        .. "|stair_comparison=manual_protocol_required"
        .. "|watchtower_slot_comparison=manual_protocol_required"
        .. "|wood_gate_release=false"
        .. "|reason=" .. reason)
end

function mod_init()
    local ok, err = pcall(begin, "new_game", false)
    if not ok then log_line("LIFECYCLE_ERROR|entry=mod_init|detail=" .. clean(err), "Error") end
end

function mod_load(is_editor)
    local ok, err = pcall(begin, is_editor and "editor_load" or "save_load", is_editor and true or false)
    if not ok then log_line("LIFECYCLE_ERROR|entry=mod_load|detail=" .. clean(err), "Error") end
end

function mod_unload()
    local ok, err = pcall(function()
        next_generation()
        if state == nil then reset_state("unknown", false) end
        state.active = false
        local clean_subs, total, unresolved = unsubscribe_all()
        emit("lifecycle", "unload",
            "LIFECYCLE|event=unload|subscriptions=" .. total
                .. "|unresolved=" .. unresolved
                .. "|cleanup=" .. (clean_subs and "complete" or "incomplete"),
            clean_subs and "Information" or "Error")
        summary()
    end)
    if not ok then log_line("LIFECYCLE_ERROR|entry=mod_unload|detail=" .. clean(err), "Error") end
end
