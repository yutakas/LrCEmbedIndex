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

        local response = LrHttp.post(
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

        -- Open the photo detail page in the browser
        local detailUrl = serverUrl .. "/photo?path=" .. utils.percentEncode( imagePath )
        LrHttp.openUrlInBrowser( detailUrl )
    end )
end

describePhoto()
