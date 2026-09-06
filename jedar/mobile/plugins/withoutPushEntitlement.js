// Jedar only uses LOCAL notifications. expo-notifications' config plugin adds the
// `aps-environment` (remote push) entitlement unconditionally, which fails code
// signing on free/personal Apple developer teams. This plugin runs after it and
// removes that entitlement so `expo run:ios --device` works with any Apple ID.
// NOTE: Expo runs later-registered mods first, so this plugin must be listed
// BEFORE expo-notifications in app.json to run after it.
const { withEntitlementsPlist } = require("expo/config-plugins");

module.exports = function withoutPushEntitlement(config) {
  return withEntitlementsPlist(config, (cfg) => {
    delete cfg.modResults["aps-environment"];
    return cfg;
  });
};
