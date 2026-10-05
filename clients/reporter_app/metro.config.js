// Metro's default resolver only follows imports inside this app's own
// directory. `src/lib/api.ts` and `src/lib/theme.ts` re-export from
// `../../../shared/`, so Metro needs to watch the `clients/` workspace root.
const { getDefaultConfig } = require("expo/metro-config");
const path = require("path");

const projectRoot = __dirname;
const workspaceRoot = path.resolve(projectRoot, "..");

const config = getDefaultConfig(projectRoot);

config.watchFolders = [workspaceRoot];
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, "node_modules"),
  path.resolve(workspaceRoot, "node_modules"),
];

module.exports = config;
