local LrApplication = import 'LrApplication'
local LrDialogs = import 'LrDialogs'
local LrTasks = import 'LrTasks'
local LrHttp = import 'LrHttp'
local LrProgressScope = import 'LrProgressScope'
local LrPrefs = import 'LrPrefs'
local LrLogger = import 'LrLogger'

local json = require 'dkjson'

local logger = LrLogger( 'LrCEmbedIndex' )
logger:enable( "logfile" )

local function batchDescribe()
    LrTasks.startAsyncTask( function()
        local prefs = LrPrefs.prefsForPlugin()
        local serverUrl = prefs.serverUrl or "http://localhost:8600"

        local catalog = LrApplication.activeCatalog()
        local sources = catalog:getActiveSources()

        if not sources or #sources == 0 then
            LrDialogs.message( "No Folder Selected",
                "Please select a folder in the Library module.", "warning" )
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
            LrDialogs.message( "No Photos",
                "No photos found in the selected folder.", "warning" )
            return
        end

        local progress = LrProgressScope {
            title = "Batch Describe (" .. #allPhotos .. " photos) — vision only, no embedding",
        }

        local successCount = 0
        local cachedCount = 0
        local errorCount = 0

        for i, photo in ipairs( allPhotos ) do
            if progress:isCanceled() then break end

            progress:setPortionComplete( i - 1, #allPhotos )
            progress:setCaption( "Describing photo " .. i .. " of " .. #allPhotos )

            -- Request JPEG thumbnail
            local thumbnailPixels = nil
            local thumbnailErr = nil
            local done = false

            local width = photo:getRawMetadata( "width" )
            local height = photo:getRawMetadata( "height" )
            if width and height then
                width = math.min( width / 2, 1024 )
                height = math.min( height / 2, 1024 )
            else
                width = 1024
                height = 1024
            end

            local request = photo:requestJpegThumbnail( width, height, function( pixels, errMsg )
                thumbnailPixels = pixels
                thumbnailErr = errMsg
                done = true
            end )

            -- Wait for thumbnail (up to 30 seconds)
            local waitCount = 0
            while not done and waitCount < 300 do
                LrTasks.sleep( 0.1 )
                waitCount = waitCount + 1
            end

            if thumbnailPixels and not thumbnailErr then
                local imagePath = photo:getRawMetadata( "path" ) or ""

                -- Collect EXIF / metadata
                local exifData = {}
                exifData.cameraMake = photo:getFormattedMetadata( "cameraMake" ) or ""
                exifData.cameraModel = photo:getFormattedMetadata( "cameraModel" ) or ""
                exifData.lens = photo:getFormattedMetadata( "lens" ) or ""
                exifData.focalLength = photo:getFormattedMetadata( "focalLength" ) or ""
                exifData.aperture = photo:getFormattedMetadata( "aperture" ) or ""
                exifData.shutterSpeed = photo:getFormattedMetadata( "shutterSpeed" ) or ""
                exifData.isoSpeedRating = photo:getFormattedMetadata( "isoSpeedRating" ) or ""
                exifData.exposureBias = photo:getFormattedMetadata( "exposureBias" ) or ""
                exifData.dateTimeOriginal = photo:getFormattedMetadata( "dateTimeOriginal" ) or ""
                exifData.gps = photo:getFormattedMetadata( "gps" ) or ""
                exifData.fileName = photo:getFormattedMetadata( "fileName" ) or ""
                exifData.fileType = photo:getFormattedMetadata( "fileType" ) or ""
                exifData.dimensions = photo:getFormattedMetadata( "dimensions" ) or ""
                exifData.title = photo:getFormattedMetadata( "title" ) or ""
                exifData.caption = photo:getFormattedMetadata( "caption" ) or ""
                exifData.keywords = photo:getFormattedMetadata( "keywordTags" ) or ""
                exifData.label = photo:getFormattedMetadata( "label" ) or ""
                exifData.rating = photo:getFormattedMetadata( "rating" ) or ""

                local exifJson = json.encode( exifData )

                -- Percent-encode JSON so special chars survive HTTP headers
                local exifEncoded = string.gsub( exifJson, "([^%w%-%.%_%~])", function( c )
                    return string.format( "%%%02X", string.byte( c ) )
                end )

                local headers = {
                    { field = 'Content-Type', value = 'image/jpeg' },
                    { field = 'Content-Length', value = string.len( thumbnailPixels ) },
                    { field = 'X-Image-Path', value = imagePath },
                    { field = 'X-Exif-Data', value = exifEncoded },
                }

                local response, hdrs = LrHttp.post(
                    serverUrl .. "/describe",
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
                        if result.cached then
                            cachedCount = cachedCount + 1
                        end
                    else
                        errorCount = errorCount + 1
                        logger:trace( "Describe error for " .. imagePath ..
                            ": " .. (response or "no response") )
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
            "Batch Describe Complete",
            "Described " .. successCount .. " photos (" .. cachedCount .. " already cached).\n"
                .. errorCount .. " errors.\n\n"
                .. "Tip: Descriptions are saved in metadata only (no embedding/ChromaDB).\n"
                .. "Run 'Generate Index' later to produce embeddings from the cached descriptions.",
            "info"
        )
    end )
end

batchDescribe()
