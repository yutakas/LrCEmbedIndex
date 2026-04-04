local LrHttp = import 'LrHttp'
local LrPrefs = import 'LrPrefs'
local LrTasks = import 'LrTasks'

LrTasks.startAsyncTask( function()
    local prefs = LrPrefs.prefsForPlugin()
    local serverUrl = prefs.serverUrl or "http://localhost:8600"
    LrHttp.openUrlInBrowser( serverUrl )
end )
