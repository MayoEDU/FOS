// FOS uses the shared, unmodified updater with its own release repository.
// Keep the app, binary and asset names compatible with existing Steam Frame installs.
#pragma once

#include "update_check.h"

#include <string>

namespace fos {

inline constexpr const char* kRepository = "MayoEDU/FOS";
inline constexpr const char* kReleasePage = "https://github.com/MayoEDU/FOS/releases/latest";

// The upstream installer's generic menu can reinstall frameeyeosc. Only named companion apps are offered.
inline bool canInstallCompanion(const std::string& key) {
    return !key.empty() && key != "eye" && key != "frameeyeosc";
}

inline frame_updater::UpdaterConfig updaterConfig(const std::string& script, const std::string& version) {
    frame_updater::UpdaterConfig config;
    config.script = script;
    config.app = "frameeyeosc";
    config.repo = kRepository;
    config.currentVersion = version;
    config.assetPattern = "frameeyeosc-{version}-steamframe-aarch64.tar.gz";
    config.defaultInstallArgs = {"--with-panel"};
    return config;
}

}  // namespace fos
