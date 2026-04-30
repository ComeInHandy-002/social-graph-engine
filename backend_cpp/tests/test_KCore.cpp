#include <catch2/catch_all.hpp>
#include "test_graph.h"

TEST_CASE("K-Core Decomposition", "[kcore]") {
    auto g = create_test_graph();
    KCoreAlgorithm algo;
    auto kc = algo.execute(g);
    REQUIRE(kc.size() == 6);
    REQUIRE(kc["A"] == 1.0);
    REQUIRE(kc["F"] == 1.0);
    REQUIRE(kc["B"] >= 2.0);
    REQUIRE(kc["C"] >= 2.0);
}
