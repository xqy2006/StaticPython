from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="pymongo",
    source_mapping={
        "pymongo": "Lib/pymongo",
        "bson": "Lib/bson",
        "gridfs": "Lib/gridfs",
    },
    python_packages=["pymongo", "bson", "gridfs"],
    verification_steps=[
        inline_verification_step(
            "pymongo-smoke",
            """
from bson import BSON, ObjectId
from pymongo import MongoClient
from pymongo.uri_parser import parse_uri

oid = ObjectId()
assert ObjectId(str(oid)) == oid
encoded = BSON.encode({"name": "staticpython", "value": 13})
assert BSON(encoded).decode()["value"] == 13
parsed = parse_uri("mongodb://localhost:27017/test")
assert parsed["database"] == "test"
client = MongoClient("mongodb://localhost:27017", connect=False)
assert client.get_database("test").name == "test"
client.close()
""",
        )
    ],
)
