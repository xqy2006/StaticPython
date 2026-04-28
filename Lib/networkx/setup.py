from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='networkx',
    overlay_entries=['Lib/networkx'],
    verification_steps=[
        inline_verification_step(
            "networkx-smoke",
            """
import networkx as nx

graph = nx.Graph()
graph.add_weighted_edges_from([("a", "b", 2), ("b", "c", 3), ("a", "c", 10)])
assert nx.shortest_path(graph, "a", "c", weight="weight") == ["a", "b", "c"]
assert nx.shortest_path_length(graph, "a", "c", weight="weight") == 5
assert nx.is_connected(graph)
""",
        )
    ],
)
