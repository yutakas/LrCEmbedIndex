local LrApplication = import 'LrApplication'
local LrDialogs = import 'LrDialogs'
local LrTasks = import 'LrTasks'
local LrHttp = import 'LrHttp'
local LrView = import 'LrView'
local LrBinding = import 'LrBinding'
local LrFunctionContext = import 'LrFunctionContext'
local LrPrefs = import 'LrPrefs'
local LrLogger = import 'LrLogger'
local LrPathUtils = import 'LrPathUtils'

local json = require 'dkjson'

local logger = LrLogger( 'LrCEmbedIndex' )
logger:enable( "logfile" )

local COLLECTION_NAME = "LrCEmbedIndex Search Results"


-- Build folder path -> LrFolder lookup (recursive)
local function indexFolders( folders, lookup )
    for _, folder in ipairs( folders ) do
        lookup[folder:getPath()] = folder
        indexFolders( folder:getChildren(), lookup )
    end
end


-- Find photos by their full paths, searching only in the relevant folders.
-- Much faster than iterating all catalog photos for large catalogs.
local function findPhotosByPaths( catalog, targetPaths )
    -- Group target paths by parent folder
    local folderToFiles = {}
    for _, filePath in ipairs( targetPaths ) do
        local folderPath = LrPathUtils.parent( filePath )
        if folderPath then
            if not folderToFiles[folderPath] then
                folderToFiles[folderPath] = {}
            end
            folderToFiles[folderPath][filePath] = true
        end
    end

    -- Build folder lookup from catalog (recursive)
    local folderLookup = {}
    indexFolders( catalog:getFolders(), folderLookup )

    -- Search only within the specific folders that contain results
    local found = {}
    for folderPath, fileSet in pairs( folderToFiles ) do
        local folder = folderLookup[folderPath]
        if folder then
            local photos = folder:getPhotos()
            for _, photo in ipairs( photos ) do
                local p = photo:getRawMetadata( "path" )
                if p and fileSet[p] then
                    found[p] = photo
                end
            end
        end
    end
    return found
end


-- Find or create our search results collection
local function getOrCreateCollection( catalog )
    local collections = catalog:getChildCollections()
    for _, col in ipairs( collections ) do
        if col:getName() == COLLECTION_NAME then
            return col
        end
    end
    -- Create it
    local col
    catalog:withWriteAccessDo( "Create search results collection", function()
        col = catalog:createCollection( COLLECTION_NAME, nil, true )
    end )
    return col
end


local function searchPhoto()
    LrFunctionContext.callWithContext( "searchPhoto", function( context )
        local f = LrView.osFactory()
        local prefs = LrPrefs.prefsForPlugin()
        local props = LrBinding.makePropertyTable( context )
        props.searchText = ""
        props.maxResults = prefs.searchMaxResults or 10
        props.relevance = prefs.searchRelevance or 50

        local result = LrDialogs.presentModalDialog {
            title = "Search Photo by Description",
            contents = f:column {
                spacing = f:control_spacing(),
                f:row {
                    f:static_text {
                        title = "Search:",
                        alignment = 'right',
                        width = 80,
                    },
                    f:edit_field {
                        value = LrView.bind { key = 'searchText', object = props },
                        width_in_chars = 50,
                        height_in_lines = 3,
                    },
                },
                f:row {
                    f:static_text {
                        title = "Max results:",
                        alignment = 'right',
                        width = 80,
                    },
                    f:edit_field {
                        value = LrView.bind { key = 'maxResults', object = props },
                        width_in_chars = 5,
                        min = 1,
                        max = 100,
                        precision = 0,
                    },
                },
                f:row {
                    f:static_text {
                        title = "Relevance:",
                        alignment = 'right',
                        width = 80,
                    },
                    f:slider {
                        value = LrView.bind { key = 'relevance', object = props },
                        min = 0,
                        max = 100,
                        integral = true,
                        width = 200,
                    },
                    f:static_text {
                        title = LrView.bind { key = 'relevance', object = props },
                        width = 30,
                    },
                },
                f:row {
                    f:spacer { width = 80 },
                    f:static_text {
                        title = "0 = show everything, 100 = only very close matches",
                        font = "<system/small>",
                    },
                },
            },
            actionVerb = "Search",
        }

        if result == "ok" and props.searchText and props.searchText ~= "" then
            -- Remember the user's choices for next time
            prefs.searchMaxResults = props.maxResults
            prefs.searchRelevance = props.relevance

            LrTasks.startAsyncTask( function()
                local serverUrl = prefs.serverUrl or "http://localhost:8600"

                local payload = json.encode({
                    query = props.searchText,
                    max_results = tonumber( props.maxResults ) or 10,
                    relevance = tonumber( props.relevance ) or 50,
                })
                local headers = {
                    { field = 'Content-Type', value = 'application/json' },
                }

                local response, hdrs = LrHttp.post(
                    serverUrl .. "/search",
                    payload,
                    headers,
                    "POST",
                    1000
                )

                if not response then
                    LrDialogs.message( "Error", "Could not connect to the server at " .. serverUrl, "critical" )
                    return
                end

                local data = json.decode( response )
                if not data or not data.results or #data.results == 0 then
                    LrDialogs.message( "Search", "No matching photos found.", "warning" )
                    return
                end

                local catalog = LrApplication.activeCatalog()

                -- Collect result paths
                local targetPaths = {}
                for _, item in ipairs( data.results ) do
                    if item.path and item.path ~= "" then
                        table.insert( targetPaths, item.path )
                    end
                end

                -- Find photos by searching only in relevant folders (fast)
                local lookup = findPhotosByPaths( catalog, targetPaths )

                -- Match results to catalog photos (preserve server order)
                local foundPhotos = {}
                local notFound = {}
                for _, item in ipairs( data.results ) do
                    local path = item.path or ""
                    local photo = lookup[path]
                    if photo then
                        table.insert( foundPhotos, photo )
                    else
                        table.insert( notFound, path )
                    end
                end

                if #foundPhotos == 0 then
                    LrDialogs.message( "Search",
                        "Server returned " .. #data.results .. " results but none were found in the current catalog.",
                        "warning" )
                    return
                end

                -- Put results into a collection and navigate there
                local collection = getOrCreateCollection( catalog )
                if collection then
                    catalog:withWriteAccessDo( "Populate search results", function()
                        -- Clear previous results
                        local existing = collection:getPhotos()
                        if #existing > 0 then
                            collection:removePhotos( existing )
                        end
                        -- Add new results
                        collection:addPhotos( foundPhotos )
                    end )

                    -- Switch to Library and set the collection as the active source
                    catalog:setActiveSources { collection }

                    -- Select the first photo
                    if #foundPhotos > 0 then
                        catalog:setSelectedPhotos( foundPhotos[1], foundPhotos )
                    end
                end

                local msg = "Found " .. #foundPhotos .. " photos in catalog (sorted by relevance)"
                if #notFound > 0 then
                    msg = msg .. "\n" .. #notFound .. " result(s) not found in catalog"
                end
                msg = msg .. "\n\nTip: Set Sort to \"Custom Order\" in the toolbar to see results ranked by score."
                logger:info( "Found " .. #foundPhotos .. " photos, " .. #notFound .. " not in catalog" )
                LrDialogs.message( "Search Results", msg, "info" )
            end )
        end
    end )
end

LrTasks.startAsyncTask( function()
    searchPhoto()
end )
