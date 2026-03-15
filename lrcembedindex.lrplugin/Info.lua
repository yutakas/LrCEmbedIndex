return {
    LrSdkVersion = 3.0,
    LrToolkitIdentifier = 'yutakas.plugin.lrcembedindex',
    LrPluginName = "LrC Embed Index",

    LrLibraryMenuItems = {
        {
            title = "Generate Index",
            file = "GenerateIndex.lua",
        },
        {
            title = "Search Photo",
            file = "SearchPhoto.lua",
        },
    },

    LrPluginInfoProvider = 'PluginInfoProvider.lua',

    VERSION = { major = 1, minor = 0, revision = 0 },
}
