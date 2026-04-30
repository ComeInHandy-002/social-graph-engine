#include <catch2/catch_all.hpp>
#include "test_graph.h"

TEST_CASE("Betweenness Centrality", "[betweenness]") {
    auto g = create_test_graph();
    BetweennessCentralityAlgorithm algo;
    auto bc = algo.execute(g);
    REQUIRE(bc.size() == 6);
    REQUIRE(bc["B"] > bc["A"]);
    REQUIRE(bc["D"] > bc["F"]);
    REQUIRE(bc["A"] == 0.0);
    REQUIRE(bc["F"] == 0.0);
}
