cmake_minimum_required(VERSION 3.14)
project(GraphEngine)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ═══════════════════════════════════════════════════════════════════
# 选项: 功能开关 (默认全部关闭, 保持零依赖 CLI 构建不受影响)
# ═══════════════════════════════════════════════════════════════════
option(ENABLE_SERVER  "构建微服务模式 (TCP + gRPC 支持)" ON)
option(ENABLE_GRPC    "启用 gRPC 支持 (需要 grpc + protobuf)" OFF)
option(ENABLE_REDIS   "启用 Redis 缓存直写 (需要 redis++)" OFF)
option(ENABLE_MYSQL   "启用 MySQL 指标写入 (需要 mysql-connector-cpp)" OFF)

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

# ═══════════════════════════════════════════════════════════════════
# CLI 可执行文件 (原有, 向后兼容)
# ═══════════════════════════════════════════════════════════════════
add_executable(graph_engine src/main.cpp)
target_link_libraries(graph_engine PRIVATE graph_algo)

# ═══════════════════════════════════════════════════════════════════
# 微服务可执行文件 (新)
# ═══════════════════════════════════════════════════════════════════
if(ENABLE_SERVER)
    set(SERVER_SOURCES
        server/main.cpp
    )

    add_executable(graph_server ${SERVER_SOURCES})
    target_include_directories(graph_server PRIVATE include server)
    target_link_libraries(graph_server PRIVATE graph_algo)

    # ── 平台特定: 微服务需要 socket 库 ──────────────────────────
    if(WIN32)
        target_link_libraries(graph_server PRIVATE ws2_32)
        # 设置 Windows 子系统为控制台 (避免启动时弹窗)
        set_target_properties(graph_server PROPERTIES WIN32_EXECUTABLE OFF)
    endif()

    # ── 编译定义: 控制条件编译 ──────────────────────────────────
    if(ENABLE_REDIS)
        find_package(redis++ QUIET)
        if(redis++_FOUND)
            target_compile_definitions(graph_server PRIVATE REDIS_ENABLED)
            target_link_libraries(graph_server PRIVATE redis++ hiredis)
            message(STATUS "Redis 支持: 已启用")
        else()
            message(WARNING "Redis++ 未找到, Redis 缓存功能将不可用")
        endif()
    endif()

    if(ENABLE_MYSQL)
        find_package(mysql-connector-cpp QUIET)
        if(mysql-connector-cpp_FOUND)
            find_package(MySQL QUIET)
        endif()
        if(mysql-connector-cpp_FOUND OR MySQL_FOUND)
            target_compile_definitions(graph_server PRIVATE MYSQL_ENABLED)
            if(mysql-connector-cpp_FOUND)
                target_link_libraries(graph_server PRIVATE mysqlcppconn)
            else()
                target_link_libraries(graph_server PRIVATE MySQL::MySQL)
            endif()
            message(STATUS "MySQL 支持: 已启用")
        else()
            message(WARNING "MySQL Connector/C++ 未找到, MySQL 功能将不可用")
        endif()
    endif()

    # ── gRPC 支持 ──────────────────────────────────────────────
    if(ENABLE_GRPC)
        find_package(gRPC CONFIG QUIET)
        find_package(Protobuf REQUIRED)

        if(gRPC_FOUND AND Protobuf_FOUND)
            # 编译 proto 文件
            set(PROTO_DIR "${CMAKE_SOURCE_DIR}/proto")
            set(PROTO_FILE "${PROTO_DIR}/socialgraph.proto")

            get_target_property(protobuf_INCLUDE_DIR protobuf::libprotobuf INTERFACE_INCLUDE_DIRECTORIES)
            if(NOT protobuf_INCLUDE_DIR)
                set(protobuf_INCLUDE_DIR "${Protobuf_INCLUDE_DIRS}")
            endif()

            # 生成 proto 源文件
            protobuf_generate_cpp(PROTO_SRCS PROTO_HDRS ${PROTO_FILE})
            grpc_generate_cpp(GRPC_SRCS GRPC_HDRS ${PROTO_FILE})

            set(GRPC_SERVER_SOURCES
                server/grpc_server.cpp
                ${PROTO_SRCS}
                ${GRPC_SRCS}
            )

            target_sources(graph_server PRIVATE ${GRPC_SERVER_SOURCES})
            target_include_directories(graph_server PRIVATE
                ${CMAKE_CURRENT_BINARY_DIR}
                ${protobuf_INCLUDE_DIR}
            )
            target_compile_definitions(graph_server PRIVATE GRPC_ENABLED)
            target_link_libraries(graph_server PRIVATE grpc++ grpc++_reflection protobuf::libprotobuf)

            message(STATUS "gRPC 支持: 已启用")
        else()
            message(WARNING "gRPC/Protobuf 未找到, gRPC 功能将不可用")
        endif()
    endif()

    message(STATUS "微服务构建已启用 (graph_server)")
endif()

# ═══════════════════════════════════════════════════════════════════
# 测试 (Catch2)
# ═══════════════════════════════════════════════════════════════════
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
