cmake_minimum_required(VERSION 3.10)
project(GraphEngine)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(graph_engine
        src/main.cpp
        src/GraphCore.cpp
        src/AlgoBFS.cpp
        src/AlgoPageRank.cpp
        src/AlgoLPA.cpp
        src/AlgoDijkstra.cpp
        src/AlgoDFS.cpp
)

target_include_directories(graph_engine PRIVATE include)
