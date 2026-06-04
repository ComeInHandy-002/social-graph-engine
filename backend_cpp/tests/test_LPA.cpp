#include <catch2/catch_all.hpp>
#include "test_graph.h"

TEST_CASE("LPA 社区发现", "[lpa]") {
    SocialGraph g;
    g.add_edge("A", "B"); g.add_edge("B", "C"); g.add_edge("A", "C");
    g.add_edge("D", "E"); g.add_edge("E", "F"); g.add_edge("D", "F");

    LPAAlgorithm algo;
    auto comms = algo.execute(g);
    REQUIRE(comms.size() == 6);
    REQUIRE(comms["A"] == comms["B"]);
    REQUIRE(comms["D"] == comms["E"]);
    REQUIRE(comms["A"] != comms["D"]);
}
