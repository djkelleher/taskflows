-- Log processor for systemd user services (journald) and Docker containers (fluentd forward)
-- Systemd services: collected via journald input
-- Docker containers: collected via fluentd forward protocol (TCP 24224)
-- Parses JSON messages from structlog and extracts Loki labels

-- Decode JSON-escaped unicode sequences (e.g., \u001b -> ESC for ANSI colors)
local function decode_unicode_escapes(str)
    if not str then return str end
    return str:gsub("\\u(%x%x%x%x)", function(hex)
        return string.char(tonumber(hex, 16))
    end)
end

-- State for timestamp tie-breaking (with LRU-style cleanup)
local last_ts_us_by_service = {}
local last_offset_by_service = {}
local service_access_order = {}  -- Track access order for cleanup
local MAX_TRACKED_SERVICES = 100  -- Limit to prevent unbounded memory growth

-- Clean up oldest service entries when limit is exceeded
local function cleanup_old_services()
    while #service_access_order > MAX_TRACKED_SERVICES do
        local oldest = table.remove(service_access_order, 1)
        last_ts_us_by_service[oldest] = nil
        last_offset_by_service[oldest] = nil
    end
end

-- Update service access order (move to end = most recently used)
local function touch_service(svc)
    -- Remove from current position if present
    for i, s in ipairs(service_access_order) do
        if s == svc then
            table.remove(service_access_order, i)
            break
        end
    end
    -- Add to end (most recent)
    table.insert(service_access_order, svc)
    -- Cleanup if needed
    cleanup_old_services()
end

-- Extract a string value from JSON using pattern matching
-- Handles: "key": "value" or "key":"value"
local function extract_json_string(json, key)
    -- Pattern for "key": "value" (handles escaped quotes in value)
    local pattern = '"' .. key .. '"%s*:%s*"([^"]*)"'
    return json:match(pattern)
end

-- Try to extract fields from JSON message using pattern matching
-- This avoids the need for cjson library which isn't bundled in Fluent Bit 4.x
local function extract_json_fields(message)
    if not message or message:sub(1, 1) ~= "{" then
        return nil
    end

    -- Build a table with extracted fields
    local parsed = {}
    local found_any = false

    local level_name = extract_json_string(message, "level_name")
    if level_name then parsed.level_name = level_name; found_any = true end

    local level = extract_json_string(message, "level")
    if level then parsed.level = level; found_any = true end

    local logger = extract_json_string(message, "logger")
    if logger then parsed.logger = logger; found_any = true end

    local app = extract_json_string(message, "app")
    if app then parsed.app = app; found_any = true end

    local environment = extract_json_string(message, "environment")
    if environment then parsed.environment = environment; found_any = true end

    local event = extract_json_string(message, "event")
    if event then parsed.event = event; found_any = true end

    if found_any then
        return parsed
    end
    return nil
end

function process_log(tag, timestamp, record)
    -- Handle both journald format (MESSAGE) and fluentd forward format (log)
    local message = record["MESSAGE"] or record["log_message"] or record["log"] or ""
    if not message or message == "" then
        return 0  -- Drop logs without message
    end

    -- Extract service name based on source type
    local service_name = nil
    local log_source = nil

    -- User services (systemd) - journald format
    local unit = record["SYSTEMD_USER_UNIT"] or record["_SYSTEMD_USER_UNIT"]
    if unit and unit:match("^taskflows%-.*%.service$") then
        service_name = unit:gsub("%.service$", ""):gsub("^taskflows%-", "")
        log_source = "systemd"
    end

    -- Docker containers - fluentd forward format (from fluentd logging driver)
    -- The fluentd driver sends container_name field
    local container_name = record["container_name"]
    if container_name then
        -- Strip leading slash if present (Docker adds it)
        container_name = container_name:gsub("^/", "")
        -- Strip taskflows- prefix and Docker's 12-char hex container ID suffix
        service_name = container_name:gsub("^taskflows%-", ""):gsub("%-[a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9]$", "")
        log_source = "docker"
    end

    -- Skip if we couldn't extract a service name
    if not service_name then
        return 0  -- Drop non-service logs
    end

    -- Update service access tracking for LRU cleanup
    touch_service(service_name)

    -- Build precise sec/nsec timestamp from journald microseconds to preserve strict ordering
    local new_ts = nil
    local realtime_ts = record["SOURCE_REALTIME_TIMESTAMP"] or record["REALTIME_TIMESTAMP"]
    if realtime_ts then
        local us = tonumber(realtime_ts)
        if us ~= nil then
            local sec = math.floor(us / 1000000)
            local rem_us = us - (sec * 1000000)
            local nsec = rem_us * 1000

            -- Apply per-service tie-breaker for identical microsecond timestamps
            local last_us = last_ts_us_by_service[service_name]
            if last_us and last_us == us then
                local off = (last_offset_by_service[service_name] or 0) + 1
                -- bump nsec minimally (1ns per duplicate); cap to keep under 1s boundary
                if nsec + off >= 1000000000 then
                    -- roll over: increment sec if ever needed (extremely unlikely)
                    sec = sec + 1
                    nsec = (nsec + off) - 1000000000
                else
                    nsec = nsec + off
                end
                last_offset_by_service[service_name] = off
            else
                last_offset_by_service[service_name] = 0
                last_ts_us_by_service[service_name] = us
            end
            new_ts = { sec = sec, nsec = nsec }
        end
    end

    -- Try to parse JSON and extract label fields
    local json_data = extract_json_fields(message)

    -- For JSON logs, use event field as the message (cleaner output)
    -- For non-JSON logs, decode any escaped ANSI sequences
    local final_message = message
    if json_data and json_data.event then
        final_message = json_data.event
    else
        -- Non-JSON log - decode unicode escapes for ANSI colors
        final_message = decode_unicode_escapes(message)
    end

    -- Build clean record with simplified labels
    local clean_record = {
        MESSAGE = final_message,
        service_name = service_name
    }

    -- Extract label fields from JSON (low cardinality only)
    if json_data then
        if json_data.level_name then
            clean_record["level"] = json_data.level_name
        elseif json_data.level then
            clean_record["level"] = json_data.level
        end

        if json_data.environment then
            clean_record["environment"] = json_data.environment
        end
    end

    -- If new_ts is provided, use it; otherwise keep the original timestamp
    if new_ts then
        return 2, new_ts, clean_record
    else
        return 2, timestamp, clean_record
    end
end