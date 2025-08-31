-- Log processor with UTF-8 escape sequence decoder
-- Handles both user services and Docker containers

-- State for timestamp tie-breaking
local last_ts_us_by_service = {}
local last_offset_by_service = {}

-- Decode UTF-8 escape sequences like \u4f60 or \uD83D\uDE80
function decode_utf8_escapes(str)
    if not str then return str end
    
    -- Decode \uXXXX sequences
    str = str:gsub("\\u(%x%x%x%x)", function(hex)
        local code = tonumber(hex, 16)
        if code then
            -- Handle UTF-16 surrogate pairs for emoji
            if code >= 0xD800 and code <= 0xDBFF then
                -- High surrogate, look for low surrogate
                local low = str:match("\\u(%x%x%x%x)", str:find("\\u" .. hex) + 6)
                if low then
                    local low_code = tonumber(low, 16)
                    if low_code and low_code >= 0xDC00 and low_code <= 0xDFFF then
                        -- Valid surrogate pair
                        code = 0x10000 + (code - 0xD800) * 0x400 + (low_code - 0xDC00)
                        -- Remove the low surrogate from further processing
                        str = str:gsub("\\u" .. low, "", 1)
                    end
                end
            end
            
            -- Convert code point to UTF-8
            if code < 0x80 then
                return string.char(code)
            elseif code < 0x800 then
                return string.char(
                    0xC0 + math.floor(code / 0x40),
                    0x80 + (code % 0x40)
                )
            elseif code < 0x10000 then
                return string.char(
                    0xE0 + math.floor(code / 0x1000),
                    0x80 + math.floor((code % 0x1000) / 0x40),
                    0x80 + (code % 0x40)
                )
            elseif code < 0x110000 then
                return string.char(
                    0xF0 + math.floor(code / 0x40000),
                    0x80 + math.floor((code % 0x40000) / 0x1000),
                    0x80 + math.floor((code % 0x1000) / 0x40),
                    0x80 + (code % 0x40)
                )
            end
        end
        return "\\u" .. hex  -- Return original if decode fails
    end)
    
    return str
end

function process_log(tag, timestamp, record)
    local message = record["MESSAGE"] or record["log_message"] or ""
    if not message then
        return 0  -- Drop logs without MESSAGE
    end
    
    -- Decode any UTF-8 escape sequences in the message
    message = decode_utf8_escapes(message)
    
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
            local svc = service_name or "__unknown__"
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
    
    -- Build clean record with the decoded message
    local clean_record = {
        MESSAGE = message,  -- Decoded UTF-8 message
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