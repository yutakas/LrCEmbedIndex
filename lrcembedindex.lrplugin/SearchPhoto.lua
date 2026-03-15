local LrApplication = import 'LrApplication'
local LrDialogs = import 'LrDialogs'
local LrTasks = import 'LrTasks'
local LrHttp = import 'LrHttp'
local LrView = import 'LrView'
local LrBinding = import 'LrBinding'
local LrFunctionContext = import 'LrFunctionContext'
local LrPrefs = import 'LrPrefs'
local LrLogger = import 'LrLogger'

local json = require 'dkjson'

local logger = LrLogger( 'LrCEmbedIndex' )
logger:enable( "logfile" )

local function searchPhoto()
    LrFunctionContext.callWithContext( "searchPhoto", function( context )
        local f = LrView.osFactory()
        local props = LrBinding.makePropertyTable( context )
        props.searchText = ""

        local result = LrDialogs.presentModalDialog {
            title = "Search Photo by Description",
            contents = f:column {
                spacing = f:control_spacing(),
                f:row {
                    f:static_text {
                        title = "Search:",
                        alignment = 'right',
                        width = 60,
                    },
                    f:edit_field {
                        value = LrView.bind { key = 'searchText', object = props },
                        width_in_chars = 50,
                        height_in_lines = 3,
                    },
                },
            },
            actionVerb = "Search",
        }

        if result == "ok" and props.searchText and props.searchText ~= "" then
            LrTasks.startAsyncTask( function()
                local prefs = LrPrefs.prefsForPlugin()
                local serverUrl = prefs.serverUrl or "http://localhost:8600"

                local payload = json.encode({
                    query = props.searchText,
                })
                local headers = {
                    { field = 'Content-Type', value = 'application/json' },
                }

                local response, hdrs = LrHttp.post(
                    serverUrl .. "/search",
                    payload,
                    headers,
                    "POST",
                    60
                )

                if response then
                    local data = json.decode( response )
                    if data and data.results then
                        local catalog = LrApplication.activeCatalog()
                        local resultText = "Found " .. #data.results .. " matching photos:\n\n"
                        for idx, item in ipairs( data.results ) do
                            local path = item.path or "unknown"
                            local distance = item.distance or 0
                            local description = item.description or ""
                            resultText = resultText .. idx .. ". " .. path .. "\n"
                            if description ~= "" then
                                resultText = resultText .. "   " .. description .. "\n"
                            end
                            resultText = resultText .. "\n"
                        end
                        LrDialogs.message( "Search Results", resultText, "info" )
                    else
                        LrDialogs.message( "Search", "No results found or server error.", "warning" )
                    end
                else
                    LrDialogs.message( "Error", "Could not connect to the server at " .. serverUrl, "critical" )
                end
            end )
        end
    end )
end

LrTasks.startAsyncTask( function()
    searchPhoto()
end )
