-- Log processor for plain text messages from journald
-- Handles both user services and Docker containers

-- State for timestamp tie-breaking
local last_ts_us_by_service = {}
local last_offset_by_service = {}

function process_log(tag, timestamp, record)
    local message = record["MESSAGE"] or record["log_message"] or ""
    if not message then
        return 0  -- Drop logs without MESSAGE
    end
    
    -- Extract service name based on source type
    local service_name = nil
    
    -- User services (systemd)
    local unit = record["SYSTEMD_USER_UNIT"] or record["_SYSTEMD_USER_UNIT"]
    if unit and unit:match("^taskflows%-.*%.service$") then
        service_name = unit:gsub("%.service$", ""):gsub("^taskflows%-", "")
        record["log_source"] = "systemd"
    end
    
    -- Docker containers
    local syslog_id = record["SYSLOG_IDENTIFIER"] or record["_SYSLOG_IDENTIFIER"]
    if syslog_id and syslog_id:match("^docker%.") then
        local container_name = syslog_id:match("^docker%.(.+)$")
        if container_name then
            service_name = container_name:gsub("^taskflows%-", ""):gsub("%-[a-f0-9]+$", "")
            record["log_source"] = "docker"
        end
    end
    
    -- Skip if we couldn't extract a service name
    if not service_name then
        return 0  -- Drop non-service logs
    end
    
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
            local svc = record["service_name"] or "__unknown__"
            local last_us = last_ts_us_by_service[svc]
            if last_us == us then
                local off = (last_offset_by_service[svc] or 0) + 1
                -- bump nsec minimally (1ns per duplicate); cap to keep under 1s boundary
                if nsec + off >= 1000000000 then
                    -- roll over: increment sec if ever needed (extremely unlikely)
                    sec = sec + 1
                    nsec = (nsec + off) - 1000000000
                else
                    nsec = nsec + off
                end
                last_offset_by_service[svc] = off
            else
                last_offset_by_service[svc] = 0
                last_ts_us_by_service[svc] = us
            end
            new_ts = { sec = sec, nsec = nsec }
        end
    end
    
    -- Build clean record with the plain text message
    local clean_record = {
        MESSAGE = message,  -- Keep the plain text message as-is
        service_name = service_name,
        log_source = record["log_source"]
    }
    
    -- If new_ts is provided, use it; otherwise keep the original timestamp
    if new_ts then
        return 2, new_ts, clean_record
    else
        return 2, timestamp, clean_record
    end
end