local LrApplication = import 'LrApplication'
local LrDialogs = import 'LrDialogs'
local LrTasks = import 'LrTasks'
local LrHttp = import 'LrHttp'
local LrPrefs = import 'LrPrefs'
local LrLogger = import 'LrLogger'

local json = require 'dkjson'

local logger = LrLogger( 'LrCEmbedIndex' )
logger:enable( "logfile" )

local function describePhoto()
    LrTasks.startAsyncTask( function()
        local catalog = LrApplication.activeCatalog()
        local selectedPhotos = catalog:getTargetPhotos()

        if not selectedPhotos or #selectedPhotos == 0 then
            LrDialogs.message( "No Photo Selected",
                "Please select a single photo in the Library module.", "warning" )
            return
        end

        if #selectedPhotos > 1 then
            LrDialogs.message( "Multiple Photos Selected",
                "Please select only one photo to describe.", "warning" )
            return
        end

        local photo = selectedPhotos[1]
        local imagePath = photo:getRawMetadata( "path" ) or ""
        local fileName = photo:getFormattedMetadata( "fileName" ) or "photo"

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

        photo:requestJpegThumbnail( width, height, function( pixels, errMsg )
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

        if not thumbnailPixels or thumbnailErr then
            LrDialogs.message( "Error",
                "Could not generate thumbnail: " .. ( thumbnailErr or "timeout" ), "critical" )
            return
        end

        -- Collect EXIF
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
        local exifEncoded = string.gsub( exifJson, "([^%w%-%.%_%~])", function( c )
            return string.format( "%%%02X", string.byte( c ) )
        end )

        local prefs = LrPrefs.prefsForPlugin()
        local serverUrl = prefs.serverUrl or "http://localhost:8600"

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
            300,
            string.len( thumbnailPixels )
        )

        if not response then
            LrDialogs.message( "Error",
                "Could not connect to the server at " .. serverUrl, "critical" )
            return
        end

        local data = json.decode( response )
        if not data or data.status ~= "ok" then
            LrDialogs.message( "Error",
                "Server error: " .. ( data and data.message or "unknown" ), "critical" )
            return
        end

        local desc = data.description or "(no description)"
        local model = data.vision_model or "unknown"
        local elapsed = data.elapsed or 0
        local cached = data.cached or false
        local cachedAt = data.cached_at or ""

        local header = "Model: " .. model .. "  (" .. string.format( "%.1f", elapsed ) .. "s)"
        if cached then
            header = header .. "\n[Cached from " .. cachedAt .. "]"
        end

        LrDialogs.message( "Photo Description — " .. fileName,
            header .. "\n\n" .. desc,
            "info" )
    end )
end

describePhoto()
