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
        {
            title = "Describe Selected Photo",
            file = "DescribePhoto.lua",
        },
        {
            title = "Show Index Stats",
            file = "ShowStats.lua",
        },
    },

    LrPluginInfoProvider = 'PluginInfoProvider.lua',

    VERSION = { major = 1, minor = 0, revision = 0 },
}
