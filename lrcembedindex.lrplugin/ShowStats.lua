local LrDialogs = import 'LrDialogs'
local LrTasks = import 'LrTasks'
local LrHttp = import 'LrHttp'
local LrPrefs = import 'LrPrefs'
local LrLogger = import 'LrLogger'

local json = require 'dkjson'

local logger = LrLogger( 'LrCEmbedIndex' )
logger:enable( "logfile" )

local function showStats()
    LrTasks.startAsyncTask( function()
        local prefs = LrPrefs.prefsForPlugin()
        local serverUrl = prefs.serverUrl or "http://localhost:8600"

        local response, hdrs = LrHttp.get( serverUrl .. "/stats", nil, 30 )

        if not response then
            LrDialogs.message( "Error", "Could not connect to the server at " .. serverUrl, "critical" )
            return
        end

        local data = json.decode( response )
        if not data or data.status ~= "ok" then
            LrDialogs.message( "Error", "Server returned an error: " .. ( data and data.message or "unknown" ), "critical" )
            return
        end

        -- Build a readable stats string
        local lines = {}

        -- Config
        table.insert( lines, "=== Current Configuration ===" )
        local cfg = data.config or {}
        table.insert( lines, "Index folder: " .. ( cfg.index_folder or "(not set)" ) )
        table.insert( lines, "Vision mode: " .. ( cfg.vision_mode or "?" ) )
        if cfg.vision_mode == "ollama" then
            table.insert( lines, "  Endpoint: " .. ( cfg.ollama_vision_endpoint or "?" ) )
            table.insert( lines, "  Model: " .. ( cfg.ollama_vision_model or "?" ) )
        elseif cfg.vision_mode == "claude" then
            table.insert( lines, "  Model: " .. ( cfg.claude_vision_model or "?" ) .. " (Claude)" )
        else
            table.insert( lines, "  Model: " .. ( cfg.openai_vision_model or "?" ) .. " (OpenAI)" )
        end
        table.insert( lines, "Embed mode: " .. ( cfg.embed_mode or "?" ) )
        if cfg.embed_mode == "ollama" then
            table.insert( lines, "  Endpoint: " .. ( cfg.ollama_embed_endpoint or "?" ) )
            table.insert( lines, "  Model: " .. ( cfg.ollama_embed_model or "?" ) )
        elseif cfg.embed_mode == "voyage" then
            table.insert( lines, "  Model: " .. ( cfg.voyage_embed_model or "?" ) .. " (Voyage AI)" )
        else
            table.insert( lines, "  Model: " .. ( cfg.openai_embed_model or "?" ) .. " (OpenAI)" )
        end
        table.insert( lines, "Search max results: " .. ( cfg.search_max_results or "?" ) )
        table.insert( lines, "Relevance threshold: " .. ( cfg.search_relevance or "?" ) )
        table.insert( lines, "" )

        -- Metadata
        table.insert( lines, "=== Metadata ===" )
        local meta = data.metadata or {}
        table.insert( lines, "Total metadata files: " .. ( meta.total_files or 0 ) )

        local vm = meta.vision_models or {}
        if next( vm ) then
            table.insert( lines, "Vision models used:" )
            for model, count in pairs( vm ) do
                table.insert( lines, "  " .. model .. ": " .. count .. " photos" )
            end
        end

        local em = meta.embed_models or {}
        if next( em ) then
            table.insert( lines, "Embedding model pairs:" )
            for pair, count in pairs( em ) do
                table.insert( lines, "  " .. pair .. ": " .. count .. " photos" )
            end
        end

        if meta.oldest_entry then
            table.insert( lines, "Oldest entry: " .. meta.oldest_entry )
        end
        if meta.newest_entry then
            table.insert( lines, "Newest entry: " .. meta.newest_entry )
        end
        table.insert( lines, "" )

        -- ChromaDB
        table.insert( lines, "=== ChromaDB Vector Store ===" )
        local chroma = data.chromadb or {}
        table.insert( lines, "Current model: " .. ( chroma.current_model or "?" ) )
        table.insert( lines, "Current store count: " .. ( chroma.current_count or 0 ) )

        local stores = chroma.all_stores or {}
        if #stores > 0 then
            table.insert( lines, "All stores:" )
            for _, store in ipairs( stores ) do
                local countStr = store.count >= 0 and tostring( store.count ) or "error"
                table.insert( lines, "  " .. store.model_dir .. ": " .. countStr .. " vectors" )
            end
        end

        local text = table.concat( lines, "\n" )
        LrDialogs.message( "LrC Embed Index — Statistics", text, "info" )
    end )
end

showStats()
