cmake_minimum_required(VERSION 3.14)
project(GraphEngine)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 算法核心库（供主程序和测试共用）
set(ALGO_SOURCES
    src/GraphCore.cpp
    src/AlgoBFS.cpp
    src/AlgoPageRank.cpp
    src/AlgoLPA.cpp
    src/AlgoDijkstra.cpp
    src/AlgoDFS.cpp
    src/AlgoBetweennessCentrality.cpp
    src/AlgoConnectedComponents.cpp
    src/AlgoKCore.cpp
    src/AlgoClusteringCoeff.cpp
    src/AlgoGraphStats.cpp
)

add_library(graph_algo STATIC ${ALGO_SOURCES})
target_include_directories(graph_algo PUBLIC include)

# 主可执行文件
add_executable(graph_engine src/main.cpp)
target_link_libraries(graph_engine PRIVATE graph_algo)

# 测试 (Catch2)
include(FetchContent)
FetchContent_Declare(
    Catch2
    GIT_REPOSITORY https://github.com/catchorg/Catch2.git
    GIT_TAG v3.4.0
)
FetchContent_MakeAvailable(Catch2)

enable_testing()

add_executable(graph_tests
    tests/test_main.cpp
    tests/test_BFS.cpp
    tests/test_PageRank.cpp
    tests/test_LPA.cpp
    tests/test_Dijkstra.cpp
    tests/test_Betweenness.cpp
    tests/test_ConnectedComponents.cpp
    tests/test_KCore.cpp
    tests/test_ClusteringCoeff.cpp
    tests/test_GraphStats.cpp
)
target_link_libraries(graph_tests PRIVATE graph_algo Catch2::Catch2WithMain)
target_include_directories(graph_tests PRIVATE tests include)

include(CTest)
add_test(NAME GraphEngineTests COMMAND graph_tests)
