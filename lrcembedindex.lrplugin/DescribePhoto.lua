local LrApplication = import 'LrApplication'
local LrDialogs = import 'LrDialogs'
local LrTasks = import 'LrTasks'
local LrHttp = import 'LrHttp'
local LrPrefs = import 'LrPrefs'
local LrLogger = import 'LrLogger'

local json = require 'dkjson'
local utils = require 'LrCEmbedUtils'

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

        local thumbnailPixels, thumbnailErr = utils.requestThumbnail( photo )

        if not thumbnailPixels or thumbnailErr then
            LrDialogs.message( "Error",
                "Could not generate thumbnail: " .. ( thumbnailErr or "timeout" ), "critical" )
            return
        end

        local exifData = utils.collectExifData( photo )
        local exifEncoded = utils.encodeExifHeader( exifData )

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
            1000,
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

        local descriptions = data.descriptions or {}
        local elapsed = data.elapsed or 0
        local cached = data.cached or false

        if #descriptions == 0 then
            LrDialogs.message( "Photo Description — " .. fileName,
                "(no description available)", "info" )
            return
        end

        -- Build display text with all available descriptions
        local parts = {}
        if cached then
            table.insert( parts, string.format( "%d cached model(s), %.1fs\n", #descriptions, elapsed ) )
        else
            table.insert( parts, string.format( "New description generated, %.1fs\n", elapsed ) )
        end

        for i, entry in ipairs( descriptions ) do
            local model = entry.vision_model or "unknown"
            local processedAt = entry.processed_at or ""
            local desc = entry.vision_description or "(no description)"

            if i > 1 then
                table.insert( parts, "\n————————————————————————————————\n\n" )
            end
            table.insert( parts, "Model: " .. model )
            if processedAt ~= "" then
                table.insert( parts, "  (" .. processedAt .. ")" )
            end
            table.insert( parts, "\n\n" .. desc .. "\n" )
        end

        LrDialogs.message( "Photo Description — " .. fileName,
            table.concat( parts ),
            "info" )
    end )
end

describePhoto()
