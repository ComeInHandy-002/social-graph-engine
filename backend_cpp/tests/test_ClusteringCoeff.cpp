#include <catch2/catch_all.hpp>
#include "test_graph.h"

TEST_CASE("Clustering Coefficient", "[clustering]") {
    auto g = create_test_graph();
    ClusteringCoefficientAlgorithm algo;
    auto cc = algo.execute(g);
    REQUIRE(cc.size() == 6);
    REQUIRE(cc["A"] == 0.0);
    REQUIRE(cc["F"] == 0.0);
    REQUIRE(cc["B"] > 0.0);
    for (const auto& p : cc) {
        REQUIRE(p.second >= 0.0);
        REQUIRE(p.second <= 1.0);
    }
}
