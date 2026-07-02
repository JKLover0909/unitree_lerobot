cmake_minimum_required(VERSION 3.10)
project(g1_d435i_camera_tools LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(realsense2 REQUIRED)
find_package(OpenCV REQUIRED)
find_package(Threads REQUIRED)

add_executable(g1_d435i_mjpeg_server g1_d435i_mjpeg_server.cpp)
target_link_libraries(
  g1_d435i_mjpeg_server
  PRIVATE
    ${realsense2_LIBRARY}
    ${OpenCV_LIBS}
    Threads::Threads
)
target_compile_options(g1_d435i_mjpeg_server PRIVATE -O2 -Wall -Wextra)
