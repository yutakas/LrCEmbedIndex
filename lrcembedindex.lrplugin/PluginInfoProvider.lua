local LrView = import 'LrView'
local LrDialogs = import 'LrDialogs'
local LrHttp = import 'LrHttp'
local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'
local LrPrefs = import 'LrPrefs'
local LrBinding = import 'LrBinding'

local json = require 'dkjson'

local function sectionsForTopOfDialog( f, propertyTable )
    local prefs = LrPrefs.prefsForPlugin()

    -- Defaults
    if not prefs.serverUrl then prefs.serverUrl = "http://localhost:8600" end
    if not prefs.indexFolder then prefs.indexFolder = "" end

    -- Vision settings
    if not prefs.visionMode then prefs.visionMode = "ollama" end
    if not prefs.ollamaVisionEndpoint then prefs.ollamaVisionEndpoint = "http://localhost:11434" end
    if not prefs.ollamaVisionModel then prefs.ollamaVisionModel = "qwen3.5" end
    if not prefs.openaiVisionApiKey then prefs.openaiVisionApiKey = "" end
    if not prefs.openaiVisionModel then prefs.openaiVisionModel = "gpt-4o" end

    -- Embedding settings
    if not prefs.embedMode then prefs.embedMode = "ollama" end
    if not prefs.ollamaEmbedEndpoint then prefs.ollamaEmbedEndpoint = "http://localhost:11434" end
    if not prefs.ollamaEmbedModel then prefs.ollamaEmbedModel = "nomic-embed-text" end
    if not prefs.openaiEmbedApiKey then prefs.openaiEmbedApiKey = "" end
    if not prefs.openaiEmbedModel then prefs.openaiEmbedModel = "text-embedding-3-small" end

    -- Search settings
    if not prefs.searchMaxResults then prefs.searchMaxResults = 10 end
    if not prefs.searchRelevance then prefs.searchRelevance = 50 end

    -- Bind to property table
    propertyTable.serverUrl = prefs.serverUrl
    propertyTable.indexFolder = prefs.indexFolder
    propertyTable.searchMaxResults = prefs.searchMaxResults
    propertyTable.searchRelevance = prefs.searchRelevance

    propertyTable.visionMode = prefs.visionMode
    propertyTable.ollamaVisionEndpoint = prefs.ollamaVisionEndpoint
    propertyTable.ollamaVisionModel = prefs.ollamaVisionModel
    propertyTable.openaiVisionApiKey = prefs.openaiVisionApiKey
    propertyTable.openaiVisionModel = prefs.openaiVisionModel

    propertyTable.embedMode = prefs.embedMode
    propertyTable.ollamaEmbedEndpoint = prefs.ollamaEmbedEndpoint
    propertyTable.ollamaEmbedModel = prefs.ollamaEmbedModel
    propertyTable.openaiEmbedApiKey = prefs.openaiEmbedApiKey
    propertyTable.openaiEmbedModel = prefs.openaiEmbedModel

    -- Visibility helpers
    propertyTable:addObserver( 'visionMode', function( props, key, value )
        props.visionIsOllama = ( value == "ollama" )
        props.visionIsOpenai = ( value == "openai" )
    end )
    propertyTable.visionIsOllama = ( propertyTable.visionMode == "ollama" )
    propertyTable.visionIsOpenai = ( propertyTable.visionMode == "openai" )

    propertyTable:addObserver( 'embedMode', function( props, key, value )
        props.embedIsOllama = ( value == "ollama" )
        props.embedIsOpenai = ( value == "openai" )
    end )
    propertyTable.embedIsOllama = ( propertyTable.embedMode == "ollama" )
    propertyTable.embedIsOpenai = ( propertyTable.embedMode == "openai" )

    return {
        {
            title = "LrC Embed Index — General",
            synopsis = "Server and index folder settings",

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
                f:static_text {
                    title = "Search Max Results:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:edit_field {
                    value = LrView.bind { key = 'searchMaxResults', object = propertyTable },
                    width_in_chars = 5,
                    min = 1,
                    max = 100,
                    precision = 0,
                },
                f:static_text {
                    title = "(max candidates from vector DB, before relevance filtering)",
                },
            },

            f:row {
                f:static_text {
                    title = "Relevance Threshold:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:slider {
                    value = LrView.bind { key = 'searchRelevance', object = propertyTable },
                    min = 0,
                    max = 100,
                    integral = true,
                    width = 200,
                },
                f:edit_field {
                    value = LrView.bind { key = 'searchRelevance', object = propertyTable },
                    width_in_chars = 4,
                    min = 0,
                    max = 100,
                    precision = 0,
                },
                f:static_text {
                    title = "(0 = show all, 100 = only very close matches)",
                },
            },
        },

        -- Vision Model Settings
        {
            title = "LrC Embed Index — Vision Model",
            synopsis = "Configure vision model (Ollama or OpenAI)",

            f:row {
                f:static_text {
                    title = "Vision Mode:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:popup_menu {
                    value = LrView.bind { key = 'visionMode', object = propertyTable },
                    items = {
                        { title = "Ollama", value = "ollama" },
                        { title = "OpenAI API", value = "openai" },
                    },
                    width = 150,
                },
            },

            -- Ollama vision fields
            f:row {
                visible = LrView.bind { key = 'visionIsOllama', object = propertyTable },
                f:static_text {
                    title = "Ollama Endpoint:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:edit_field {
                    value = LrView.bind { key = 'ollamaVisionEndpoint', object = propertyTable },
                    width_in_chars = 40,
                },
            },

            f:row {
                visible = LrView.bind { key = 'visionIsOllama', object = propertyTable },
                f:static_text {
                    title = "Vision Model Name:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:edit_field {
                    value = LrView.bind { key = 'ollamaVisionModel', object = propertyTable },
                    width_in_chars = 30,
                },
            },

            -- OpenAI vision fields
            f:row {
                visible = LrView.bind { key = 'visionIsOpenai', object = propertyTable },
                f:static_text {
                    title = "OpenAI API Key:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:password_field {
                    value = LrView.bind { key = 'openaiVisionApiKey', object = propertyTable },
                    width_in_chars = 40,
                },
            },

            f:row {
                visible = LrView.bind { key = 'visionIsOpenai', object = propertyTable },
                f:static_text {
                    title = "Vision Model Name:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:edit_field {
                    value = LrView.bind { key = 'openaiVisionModel', object = propertyTable },
                    width_in_chars = 30,
                },
            },
        },

        -- Embedding Model Settings
        {
            title = "LrC Embed Index — Embedding Model",
            synopsis = "Configure embedding model (Ollama or OpenAI)",

            f:row {
                f:static_text {
                    title = "Embedding Mode:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:popup_menu {
                    value = LrView.bind { key = 'embedMode', object = propertyTable },
                    items = {
                        { title = "Ollama", value = "ollama" },
                        { title = "OpenAI API", value = "openai" },
                    },
                    width = 150,
                },
            },

            -- Ollama embedding fields
            f:row {
                visible = LrView.bind { key = 'embedIsOllama', object = propertyTable },
                f:static_text {
                    title = "Ollama Endpoint:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:edit_field {
                    value = LrView.bind { key = 'ollamaEmbedEndpoint', object = propertyTable },
                    width_in_chars = 40,
                },
            },

            f:row {
                visible = LrView.bind { key = 'embedIsOllama', object = propertyTable },
                f:static_text {
                    title = "Embed Model Name:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:edit_field {
                    value = LrView.bind { key = 'ollamaEmbedModel', object = propertyTable },
                    width_in_chars = 30,
                },
            },

            -- OpenAI embedding fields
            f:row {
                visible = LrView.bind { key = 'embedIsOpenai', object = propertyTable },
                f:static_text {
                    title = "OpenAI API Key:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:password_field {
                    value = LrView.bind { key = 'openaiEmbedApiKey', object = propertyTable },
                    width_in_chars = 40,
                },
            },

            f:row {
                visible = LrView.bind { key = 'embedIsOpenai', object = propertyTable },
                f:static_text {
                    title = "Embed Model Name:",
                    alignment = 'right',
                    width = LrView.share 'label_width',
                },
                f:edit_field {
                    value = LrView.bind { key = 'openaiEmbedModel', object = propertyTable },
                    width_in_chars = 30,
                },
            },
        },

        -- Save button
        {
            title = "LrC Embed Index — Apply",

            f:row {
                f:push_button {
                    title = "Save & Apply Settings",
                    action = function( button )
                        -- Persist to prefs
                        prefs.serverUrl = propertyTable.serverUrl
                        prefs.indexFolder = propertyTable.indexFolder
                        prefs.searchMaxResults = propertyTable.searchMaxResults
                        prefs.searchRelevance = propertyTable.searchRelevance

                        prefs.visionMode = propertyTable.visionMode
                        prefs.ollamaVisionEndpoint = propertyTable.ollamaVisionEndpoint
                        prefs.ollamaVisionModel = propertyTable.ollamaVisionModel
                        prefs.openaiVisionApiKey = propertyTable.openaiVisionApiKey
                        prefs.openaiVisionModel = propertyTable.openaiVisionModel

                        prefs.embedMode = propertyTable.embedMode
                        prefs.ollamaEmbedEndpoint = propertyTable.ollamaEmbedEndpoint
                        prefs.ollamaEmbedModel = propertyTable.ollamaEmbedModel
                        prefs.openaiEmbedApiKey = propertyTable.openaiEmbedApiKey
                        prefs.openaiEmbedModel = propertyTable.openaiEmbedModel

                        -- Send all settings to the Python server
                        local payload = json.encode({
                            index_folder = propertyTable.indexFolder,

                            vision_mode = propertyTable.visionMode,
                            ollama_vision_endpoint = propertyTable.ollamaVisionEndpoint,
                            ollama_vision_model = propertyTable.ollamaVisionModel,
                            openai_vision_api_key = propertyTable.openaiVisionApiKey,
                            openai_vision_model = propertyTable.openaiVisionModel,

                            embed_mode = propertyTable.embedMode,
                            ollama_embed_endpoint = propertyTable.ollamaEmbedEndpoint,
                            ollama_embed_model = propertyTable.ollamaEmbedModel,
                            openai_embed_api_key = propertyTable.openaiEmbedApiKey,
                            openai_embed_model = propertyTable.openaiEmbedModel,

                            search_max_results = propertyTable.searchMaxResults,
                            search_relevance = propertyTable.searchRelevance,
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
