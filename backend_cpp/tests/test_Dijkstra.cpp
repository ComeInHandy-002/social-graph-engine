#include <catch2/catch_all.hpp>
#include "test_graph.h"

TEST_CASE("Dijkstra 带权最短路径", "[dijkstra]") {
    auto g = create_test_graph();
    DijkstraAlgorithm algo;
    auto path = algo.execute(g, "A", "F");
    REQUIRE(path.size() >= 5);
    REQUIRE(path[0] == "A");
    REQUIRE(path.back() == "F");

    auto emptyPath = algo.execute(g, "X", "Y");
    REQUIRE(emptyPath.empty());
}
