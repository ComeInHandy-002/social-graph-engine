#include <catch2/catch_all.hpp>
#include "test_graph.h"

TEST_CASE("Connected Components", "[components]") {
    auto g = create_test_graph();
    ConnectedComponentsAlgorithm algo;
    auto comps = algo.execute(g);
    REQUIRE(algo.get_component_count() == 1);
    REQUIRE(comps.size() == 6);

    SocialGraph g2;
    g2.add_edge("A", "B");
    g2.add_edge("C", "D");
    ConnectedComponentsAlgorithm algo2;
    algo2.execute(g2);
    REQUIRE(algo2.get_component_count() == 2);
}
