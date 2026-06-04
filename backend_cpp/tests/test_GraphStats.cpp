#include <catch2/catch_all.hpp>
#include "test_graph.h"

TEST_CASE("Graph Statistics", "[stats]") {
    auto g = create_test_graph();
    GraphStatsAlgorithm algo;
    std::string json = algo.execute(g);
    REQUIRE(json.find("\"nodes\":6") != std::string::npos);
    REQUIRE(json.find("\"edges\":6") != std::string::npos);
    REQUIRE(json.find("\"density\"") != std::string::npos);
    REQUIRE(json.find("\"components\"") != std::string::npos);
}
