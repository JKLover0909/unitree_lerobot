cmake_minimum_required(VERSION 3.16)
project(g1_state_recorder LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Threads REQUIRED)

add_executable(g1_lowstate_recorder g1_lowstate_recorder.cpp)

find_package(unitree_sdk2 QUIET)
if(unitree_sdk2_FOUND)
  message(STATUS "Found unitree_sdk2 by CMake package config")
  target_link_libraries(g1_lowstate_recorder PRIVATE unitree_sdk2 Threads::Threads)
else()
  message(STATUS "unitree_sdk2 package config not found; falling back to manual header/library lookup")
  set(UNITREE_SDK2_ROOT "" CACHE PATH "Path to unitree_sdk2 source/install root")

  set(_unitree_include_hints
    ${UNITREE_SDK2_ROOT}/include
    ${UNITREE_SDK2_ROOT}
    /usr/local/include
    /usr/include
  )
  set(_unitree_lib_hints
    ${UNITREE_SDK2_ROOT}/lib
    ${UNITREE_SDK2_ROOT}/lib/aarch64
    ${UNITREE_SDK2_ROOT}/lib/x86_64
    /usr/local/lib
    /usr/lib
    /usr/lib/aarch64-linux-gnu
    /usr/lib/x86_64-linux-gnu
  )

  find_path(
    UNITREE_SDK2_INCLUDE_DIR
    NAMES unitree/robot/channel/channel_subscriber.hpp
    HINTS ${_unitree_include_hints}
  )
  find_library(
    UNITREE_SDK2_LIBRARY
    NAMES unitree_sdk2 libunitree_sdk2.a
    HINTS ${_unitree_lib_hints}
  )

  if(NOT UNITREE_SDK2_INCLUDE_DIR OR NOT UNITREE_SDK2_LIBRARY)
    message(FATAL_ERROR
      "Could not find unitree_sdk2 manually.\n"
      "Pass -DUNITREE_SDK2_ROOT=/path/to/unitree_sdk2 or install SDK to /usr/local.\n"
      "Missing include: ${UNITREE_SDK2_INCLUDE_DIR}\n"
      "Missing library: ${UNITREE_SDK2_LIBRARY}"
    )
  endif()

  message(STATUS "UNITREE_SDK2_INCLUDE_DIR=${UNITREE_SDK2_INCLUDE_DIR}")
  message(STATUS "UNITREE_SDK2_LIBRARY=${UNITREE_SDK2_LIBRARY}")
  target_include_directories(g1_lowstate_recorder PRIVATE ${UNITREE_SDK2_INCLUDE_DIR})
  target_link_libraries(g1_lowstate_recorder PRIVATE ${UNITREE_SDK2_LIBRARY} Threads::Threads)
endif()

target_compile_options(g1_lowstate_recorder PRIVATE -O2 -Wall -Wextra)
