# Diagnostic-only wrapper around exact Qt6.11.2 Cocoa sources, using matching SDK.
# The ownership patch remains an unreleased Gerrit candidate.
cmake_minimum_required(VERSION 3.22)
project(QCocoaPatch VERSION 6.11.2 LANGUAGES C CXX OBJC OBJCXX)
set(QT_REPO_MODULE_VERSION 6.11.2)
set(QT_STANDALONE_PROJECT_NAME QCocoaPatch)
set(QT_PARENT_PROJECT_NAME QtBase)
set(QT_SKIP_AUTO_PLUGIN_INCLUSION ON)
set(QT_BUILD_INTERNALS_NO_FORCE_SET_INSTALL_PREFIX ON)
set(QT_BUILD_TESTS OFF)
set(QT_BUILD_EXAMPLES OFF)
find_package(Qt6 6.11.2 EXACT REQUIRED COMPONENTS BuildInternals)
qt_internal_project_setup()
find_package(Qt6 6.11.2 EXACT REQUIRED COMPONENTS Core Gui CorePrivate GuiPrivate)
set(QT_SBOM_LICENSE_DIRS "${QTBASE_SOURCE_DIR}/LICENSES")
qt_build_repo_begin()
if(NOT QT_FEATURE_accessibility)
    message(FATAL_ERROR "Matching SDK must retain accessibility")
endif()
add_subdirectory("${QTBASE_SOURCE_DIR}/src/plugins/platforms/cocoa" cocoa)
set_target_properties(QCocoaIntegrationPlugin PROPERTIES
    BUILD_WITH_INSTALL_RPATH TRUE
    INSTALL_RPATH "@loader_path/../../lib"
    INSTALL_RPATH_USE_LINK_PATH FALSE)
qt_build_repo_end()
