cmake_minimum_required(VERSION 3.16)
project(unitree_lerobot_cpp_replay LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(unitree_sdk2 REQUIRED)

add_executable(g1_wbt_body_replay g1_wbt_body_replay.cpp)
target_link_libraries(g1_wbt_body_replay PRIVATE unitree_sdk2)
target_compile_options(g1_wbt_body_replay PRIVATE -Wall -Wextra -Wpedantic)
