local LrTasks = import 'LrTasks'

local json = require 'dkjson'

local LrCEmbedUtils = {}


function LrCEmbedUtils.collectExifData( photo )
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
    return exifData
end


function LrCEmbedUtils.requestThumbnail( photo, maxSize )
    maxSize = maxSize or 1024

    local thumbnailPixels = nil
    local thumbnailErr = nil
    local done = false

    local width = photo:getRawMetadata( "width" )
    local height = photo:getRawMetadata( "height" )
    if width and height then
        width = math.min( width / 2, maxSize )
        height = math.min( height / 2, maxSize )
    else
        width = maxSize
        height = maxSize
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

    return thumbnailPixels, thumbnailErr
end


function LrCEmbedUtils.percentEncode( str )
    return string.gsub( str, "([^%w%-%.%_%~])", function( c )
        return string.format( "%%%02X", string.byte( c ) )
    end )
end


function LrCEmbedUtils.encodeExifHeader( exifData )
    local exifJson = json.encode( exifData )
    return LrCEmbedUtils.percentEncode( exifJson )
end


return LrCEmbedUtils
