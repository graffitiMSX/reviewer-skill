"""Turn a cgr offline index (index.bin) into plain JSON on stdout.

Run by codemap.py with the Python interpreter that cgr itself is installed
under, because that is where the protobuf schema lives. It only reads.
"""
import json
import sys

from codec import schema_pb2 as pb

KINDS = {"module": "module", "function": "function", "method": "method", "class_node": "class"}
RELS = {"IMPORTS", "CALLS", "DEFINES", "DEFINES_METHOD", "INHERITS", "IMPLEMENTS"}

index = pb.GraphCodeIndex()
with open(sys.argv[1], "rb") as fh:
    index.ParseFromString(fh.read())

nodes = []
for node in index.nodes:
    kind = KINDS.get(node.WhichOneof("payload"))
    if not kind:
        continue
    body = getattr(node, node.WhichOneof("payload"))
    nodes.append({
        "kind": kind,
        "qn": body.qualified_name,
        "name": body.name,
        "path": getattr(body, "path", ""),
        "start": getattr(body, "start_line", 0),
        "end": getattr(body, "end_line", 0),
    })

rels = []
for rel in index.relationships:
    name = pb.Relationship.RelationshipType.Name(rel.type)
    if name in RELS:
        rels.append([name, rel.source_id, rel.target_id, rel.target_label])

json.dump({"nodes": nodes, "rels": rels}, sys.stdout)
