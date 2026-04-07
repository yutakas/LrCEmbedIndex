local LrApplication = import 'LrApplication'
local LrDialogs = import 'LrDialogs'
local LrTasks = import 'LrTasks'
local LrHttp = import 'LrHttp'
local LrProgressScope = import 'LrProgressScope'
local LrPrefs = import 'LrPrefs'
local LrLogger = import 'LrLogger'

local json = require 'dkjson'
local utils = require 'LrCEmbedUtils'

local logger = LrLogger( 'LrCEmbedIndex' )
logger:enable( "logfile" )

local function generateIndex()
    LrTasks.startAsyncTask( function()
        local prefs = LrPrefs.prefsForPlugin()
        local serverUrl = prefs.serverUrl or "http://localhost:8600"

        local catalog = LrApplication.activeCatalog()
        local sources = catalog:getActiveSources()

        if not sources or #sources == 0 then
            LrDialogs.message( "No Folder Selected", "Please select a folder in the Library module.", "warning" )
            return
        end

        -- Collect photos from all active sources (folders/collections)
        local allPhotos = {}
        for _, source in ipairs( sources ) do
            if source.getPhotos then
                local photos = source:getPhotos()
                if photos then
                    for _, p in ipairs( photos ) do
                        allPhotos[#allPhotos + 1] = p
                    end
                end
            end
        end

        if #allPhotos == 0 then
            LrDialogs.message( "No Photos", "No photos found in the selected folder.", "warning" )
            return
        end

        local progress = LrProgressScope {
            title = "Generating Index (" .. #allPhotos .. " photos)",
        }

        local successCount = 0
        local errorCount = 0

        for i, photo in ipairs( allPhotos ) do
            if progress:isCanceled() then break end

            progress:setPortionComplete( i - 1, #allPhotos )
            progress:setCaption( "Processing photo " .. i .. " of " .. #allPhotos )

            local thumbnailPixels, thumbnailErr = utils.requestThumbnail( photo )

            if thumbnailPixels and not thumbnailErr then
                local imagePath = photo:getRawMetadata( "path" ) or ""

                local exifData = utils.collectExifData( photo )
                local exifEncoded = utils.encodeExifHeader( exifData )

                local contentHash = utils.computeContentHash( imagePath )

                local headers = {
                    { field = 'Content-Type', value = 'image/jpeg' },
                    { field = 'Content-Length', value = string.len( thumbnailPixels ) },
                    { field = 'X-Image-Path', value = imagePath },
                    { field = 'X-Exif-Data', value = exifEncoded },
                }
                if contentHash then
                    headers[#headers + 1] = { field = 'X-Content-Hash', value = contentHash }
                end

                local response, hdrs = LrHttp.post(
                    serverUrl .. "/index",
                    function() return thumbnailPixels end,
                    headers,
                    "POST",
                    1000,
                    string.len( thumbnailPixels )
                )

                if response then
                    local result = json.decode( response )
                    if result and result.status == "ok" then
                        successCount = successCount + 1
                    else
                        errorCount = errorCount + 1
                        logger:trace( "Index error for " .. imagePath .. ": " .. (response or "no response") )
                    end
                else
                    errorCount = errorCount + 1
                    logger:trace( "HTTP error for " .. imagePath )
                end
            else
                errorCount = errorCount + 1
                logger:trace( "Thumbnail error: " .. (thumbnailErr or "timeout") )
            end
        end

        progress:done()

        LrDialogs.message(
            "Index Generation Complete",
            "Indexed " .. successCount .. " photos successfully.\n" .. errorCount .. " errors.",
            "info"
        )
    end )
end

generateIndex()
