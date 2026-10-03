-- APC_Feedback.lua  -  grandMA3 plugin for MPC Mapper
--
-- Polls the executors the MPC Mapper app is interested in and pushes their
-- state to the app over OSC (SendOSC keyword), so the APC mini mk2 LEDs can
-- show what is running on the console.
--
-- Messages (the OSC line prefix is prepended by MA3, the app accepts any):
--   /apc/exec  ,iiifiii  page exec active(0/1) fader(0-100) r g b   (-1 = no colour)
--   /apc/page  ,i        current executor page
--   /apc/hello ,s        plugin version (heartbeat)
--
-- The app writes the executor list into the user variable APC_WATCH, e.g.
--   "0.201 0.202 2.101"   (page 0 = whatever page is currently selected)
-- If APC_WATCH is empty, FALLBACK_EXECS on the current page are reported.
--
-- Run the plugin once to start it, run it again to stop it.

local OSC_LINE        = 2      -- In & Out > OSC line that points at the app (Enable Output, Send + Send Command = Yes)
local INTERVAL        = 0.05   -- seconds between polls
local FULL_REFRESH    = 3.0    -- resend everything every N seconds (UDP may drop packets)
local VERSION         = "1.0"
local FALLBACK_EXECS  = {101,102,103,104,105,106,107,108,
                         201,202,203,204,205,206,207,208}

local function now()
    local ok, t = pcall(Time)          -- MA3: station uptime in seconds (float)
    if ok and tonumber(t) then return tonumber(t) end
    return os.time()
end

local function sendOSC(addr_and_args)
    Cmd(string.format('SendOSC %d "%s"', OSC_LINE, addr_and_args))
end

local function currentPageNo()
    local ok, pg = pcall(CurrentExecPage)
    if ok and pg then
        local okn, no = pcall(function() return pg.no end)
        local n = (okn and tonumber(no)) or tonumber(tostring(pg):match("Page (%d+)"))
        if n then return n end
    end
    return 1
end

-- executor handle for (page, exec); page == current uses GetExecutor (fast path)
local function findExecutor(pageNo, execNo, curPage)
    if pageNo == curPage then
        local ok, ex = pcall(GetExecutor, execNo)
        if ok and ex then return ex end
    end
    local ok, ex = pcall(function()
        -- Pages[n] would index by position, not by page number (pools can have gaps)
        local pages = DataPool().Pages
        if not pages then return nil end
        local pg
        for _, p in ipairs(pages:Children()) do
            if tonumber(p.no) == pageNo then pg = p break end
        end
        if not pg then return nil end
        for _, child in ipairs(pg:Children()) do
            if tonumber(child.no) == execNo then return child end
        end
        return nil
    end)
    if ok then return ex end
    return nil
end

local function num(v)
    return tonumber(v) or 0
end

local function appearanceRGB(ex, obj)
    for _, h in ipairs({obj, ex}) do
        if h then
            local ok, ap = pcall(function() return h.Appearance end)
            if ok and ap then
                local okc, r, g, b, a = pcall(function()
                    return ap.BackR, ap.BackG, ap.BackB, ap.BackAlpha
                end)
                if okc and r then
                    if a ~= nil and num(a) == 0 then return -1, -1, -1 end
                    return math.floor(num(r)), math.floor(num(g)), math.floor(num(b))
                end
            end
        end
    end
    return -1, -1, -1
end

local function execState(ex)
    if not ex then return 0, 0, -1, -1, -1 end
    local obj = ex.Object
    local active = 0
    if obj then
        local ok, res = pcall(function() return obj:HasActivePlayback() end)
        if ok and res then active = 1 end
    end
    local fader = 0
    local ok, f = pcall(function() return ex:GetFader({}) end)
    if ok and f then
        fader = num(f)
    elseif obj then
        local ok2, f2 = pcall(function() return obj:GetFader({token = "FaderMaster"}) end)
        if ok2 and f2 then fader = num(f2) end
    end
    local r, g, b = appearanceRGB(ex, obj)
    return active, fader, r, g, b
end

local function watchList(curPage)
    local list = {}
    local raw = ""
    local ok, v = pcall(function() return GetVar(UserVars(), "APC_WATCH") end)
    if ok and v then raw = tostring(v) end
    for p, e in string.gmatch(raw, "(%d+)%.(%d+)") do
        local pn = tonumber(p)
        if pn == 0 then pn = curPage end
        list[#list + 1] = {pn, tonumber(e)}
    end
    if #list == 0 then
        for _, e in ipairs(FALLBACK_EXECS) do list[#list + 1] = {curPage, e} end
    end
    return list
end

local function main(display_handle, argument)
    if _G.APC_FEEDBACK_RUNNING then
        _G.APC_FEEDBACK_RUNNING = false
        Printf("APC_Feedback: stopping")
        return
    end
    _G.APC_FEEDBACK_RUNNING = true
    Printf("APC_Feedback " .. VERSION .. ": running, OSC line " .. OSC_LINE ..
           " (run the plugin again to stop)")

    local last = {}          -- key "p.e" -> state string
    local lastPage = -1
    local lastFull = 0
    local lastHello = 0

    while _G.APC_FEEDBACK_RUNNING do
        local t = now()
        local full = (t - lastFull) >= FULL_REFRESH
        if full then
            lastFull = t
            last = {}
        end
        if (t - lastHello) >= 1.0 then
            lastHello = t
            sendOSC("/apc/hello,s," .. VERSION)
        end

        local curPage = currentPageNo()
        if curPage ~= lastPage or full then
            lastPage = curPage
            sendOSC(string.format("/apc/page,i,%d", curPage))
        end

        for _, pe in ipairs(watchList(curPage)) do
            local p, e = pe[1], pe[2]
            local active, fader, r, g, b = execState(findExecutor(p, e, curPage))
            local key = p .. "." .. e
            local state = string.format("%d,%d,%d,%.1f,%d,%d,%d", p, e, active, fader, r, g, b)
            if last[key] ~= state then
                last[key] = state
                sendOSC("/apc/exec,iiifiii," .. state)
            end
        end

        coroutine.yield(INTERVAL)
    end
    Printf("APC_Feedback: stopped")
end

return main
