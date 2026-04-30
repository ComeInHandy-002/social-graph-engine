#include <catch2/catch_all.hpp>
#include "test_graph.h"

TEST_CASE("BFS 寻找最短路径", "[bfs]") {
    auto g = create_test_graph();
    BFSAlgorithm algo;

    SECTION("A 到 F 的最短路径为 4 跳") {
        auto path = algo.execute(g, "A", "F");
        REQUIRE(path.size() == 5);
        REQUIRE(path[0] == "A");
        REQUIRE(path[4] == "F");
    }

    SECTION("A 到 C 的最短路径为 2 跳") {
        auto path = algo.execute(g, "A", "C");
        REQUIRE(path.size() == 3);
    }

    SECTION("不存在的节点") {
        auto path = algo.execute(g, "A", "Z");
        REQUIRE(path.empty());
    }
}
