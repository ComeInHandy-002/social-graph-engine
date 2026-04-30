#include <catch2/catch_all.hpp>
#include "test_graph.h"
#include <cmath>

TEST_CASE("PageRank 计算全网权重", "[pagerank]") {
    auto g = create_test_graph();
    PageRankAlgorithm algo(100, 0.85);
    auto pr = algo.execute(g);
    REQUIRE(pr.size() == 6);

    double sum = 0;
    for (const auto& p : pr) sum += p.second;
    REQUIRE(std::abs(sum - 1.0) < 0.01);

    REQUIRE(pr["B"] > pr["A"]);
    REQUIRE(pr["D"] > pr["F"]);
}
