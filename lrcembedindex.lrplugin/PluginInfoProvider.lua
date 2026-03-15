local LrView = import 'LrView'
local LrDialogs = import 'LrDialogs'
local LrHttp = import 'LrHttp'
local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'
local LrPrefs = import 'LrPrefs'

local json = require 'dkjson'

local function sectionsForTopOfDialog( f, propertyTable )
    local prefs = LrPrefs.prefsForPlugin()

    if not prefs.serverUrl then
        prefs.serverUrl = "http://localhost:8600"
    end
    if not prefs.ollamaUrl then
        prefs.ollamaUrl = "http://localhost:11434"
    end
    if not prefs.indexFolder then
        prefs.indexFolder = ""
    end

    propertyTable.serverUrl = prefs.serverUrl
    propertyTable.ollamaUrl = prefs.ollamaUrl
    propertyTable.indexFolder = prefs.indexFolder

    return {
        {
            title = "LrC Embed Index Settings",
            synopsis = "Configure server and index settings",

            f:row {
                f:static_text {
                    title = "Python Server URL:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:edit_field {
                    value = LrView.bind { key = 'serverUrl', object = propertyTable },
                    width_in_chars = 40,
                },
            },

            f:row {
                f:static_text {
                    title = "Ollama Endpoint:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:edit_field {
                    value = LrView.bind { key = 'ollamaUrl', object = propertyTable },
                    width_in_chars = 40,
                },
            },

            f:row {
                f:static_text {
                    title = "Index & Metadata Folder:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:edit_field {
                    value = LrView.bind { key = 'indexFolder', object = propertyTable },
                    width_in_chars = 30,
                },
                f:push_button {
                    title = "Browse...",
                    action = function( button )
                        local path = LrDialogs.runOpenPanel {
                            title = "Select Index Folder",
                            canChooseFiles = false,
                            canChooseDirectories = true,
                            allowsMultipleSelection = false,
                        }
                        if path then
                            propertyTable.indexFolder = path[1]
                        end
                    end,
                },
            },

            f:row {
                f:push_button {
                    title = "Save & Apply Settings",
                    action = function( button )
                        prefs.serverUrl = propertyTable.serverUrl
                        prefs.ollamaUrl = propertyTable.ollamaUrl
                        prefs.indexFolder = propertyTable.indexFolder

                        -- Send settings to Python server
                        local payload = json.encode({
                            index_folder = propertyTable.indexFolder,
                            ollama_url = propertyTable.ollamaUrl,
                        })
                        local headers = {
                            { field = 'Content-Type', value = 'application/json' },
                        }
                        local response, hdrs = LrHttp.post(
                            propertyTable.serverUrl .. "/settings",
                            payload,
                            headers,
                            "POST",
                            10
                        )
                        if response then
                            LrDialogs.message( "Settings Saved", "Settings have been sent to the server.", "info" )
                        else
                            LrDialogs.message( "Warning", "Settings saved locally but could not reach the server.", "warning" )
                        end
                    end,
                },
            },
        },
    }
end

return {
    sectionsForTopOfDialog = sectionsForTopOfDialog,
}
