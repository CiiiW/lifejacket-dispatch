// Expo's default Babel setup, plus one transform.
//
// maplibre-gl (the web map) ships static class blocks, which babel-preset-expo
// on SDK 52 does not handle, so bundling fails with "Static class blocks are
// not enabled". The plugin is already present as a @babel/preset-env
// dependency; this just switches it on.
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    plugins: ['@babel/plugin-transform-class-static-block'],
  };
};
