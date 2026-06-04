#ifndef TEST_GRAPH_H
#define TEST_GRAPH_H
#include "../include/Graph.h"

// 6 节点标准测试图：
//   A -- B -- C -- D -- E -- F
//        |_________|
// 关键属性：节点 B-C-D 形成三角形，A 和 F 是叶子节点
inline SocialGraph create_test_graph() {
    SocialGraph g;
    g.add_edge("A", "B");
    g.add_edge("B", "C");
    g.add_edge("B", "D");
    g.add_edge("C", "D");
    g.add_edge("D", "E");
    g.add_edge("E", "F");
    return g;
}
#endif
