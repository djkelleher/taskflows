-- Log processor for plain text and JSON messages from journald
-- Handles both user services and Docker containers
-- Parses JSON messages from structlog and extracts Loki labels

local cjson = require("cjson.safe")

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

-- Try to parse JSON and extract fields for Loki labels
local function extract_json_fields(message)
    if not message or message:sub(1, 1) ~= "{" then
        return nil
    end

    local parsed, err = cjson.decode(message)
    if not parsed or type(parsed) ~= "table" then
        return nil
    end

    return parsed
end

function process_log(tag, timestamp, record)
    local message = record["MESSAGE"] or record["log_message"] or ""
    if not message or message == "" then
        return 0  -- Drop logs without MESSAGE
    end

    -- Extract service name based on source type
    local service_name = nil
    local log_source = nil

    -- User services (systemd)
    local unit = record["SYSTEMD_USER_UNIT"] or record["_SYSTEMD_USER_UNIT"]
    if unit and unit:match("^taskflows%-.*%.service$") then
        service_name = unit:gsub("%.service$", ""):gsub("^taskflows%-", "")
        log_source = "systemd"
    end

    -- Docker containers
    local syslog_id = record["SYSLOG_IDENTIFIER"] or record["_SYSLOG_IDENTIFIER"]
    if syslog_id and syslog_id:match("^docker%.") then
        local container_name = syslog_id:match("^docker%.(.+)$")
        if container_name then
            -- Strip taskflows- prefix and Docker's 12-char hex container ID suffix
            service_name = container_name:gsub("^taskflows%-", ""):gsub("%-[a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9]$", "")
            log_source = "docker"
        end
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

    -- Build clean record - try to extract JSON fields for Loki labels
    local clean_record = {
        MESSAGE = message,
        service_name = service_name,
        log_source = log_source
    }

    -- Try to parse JSON and extract label fields
    local json_data = extract_json_fields(message)
    if json_data then
        -- Extract key fields as Loki labels (low cardinality)
        if json_data.level_name then
            clean_record["level"] = json_data.level_name
        elseif json_data.level then
            clean_record["level"] = json_data.level
        end

        if json_data.logger then
            clean_record["logger"] = json_data.logger
        end

        if json_data.app then
            clean_record["app"] = json_data.app
        end

        if json_data.environment then
            clean_record["environment"] = json_data.environment
        end

        -- Extract event/message for easier querying
        if json_data.event then
            clean_record["event"] = json_data.event
        end
    end

    -- If new_ts is provided, use it; otherwise keep the original timestamp
    if new_ts then
        return 2, new_ts, clean_record
    else
        return 2, timestamp, clean_record
    end
end