from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="comm",
    overlay_entries=["Lib/comm"],
    verification_steps=[
        inline_verification_step(
            "comm-smoke",
            """
from comm import BaseComm, create_comm, get_comm_manager


class RecordingComm(BaseComm):
    def __init__(self, *args, **kwargs):
        self.records = []
        super().__init__(*args, **kwargs)

    def publish_msg(self, msg_type, data=None, metadata=None, buffers=None, **keys):
        self.records.append((msg_type, data or {}, metadata or {}, list(buffers or []), keys))


manager = get_comm_manager()
manager.targets.clear()
manager.comms.clear()

default_comm = create_comm(target_name="default", comm_id="default-comm", data={"seed": 1})
assert manager.get_comm("default-comm") is default_comm
default_comm.close({"done": False})
assert manager.get_comm("default-comm") is None

opened = []
manager.register_target("staticpython-test", lambda comm, msg: opened.append((comm.comm_id, msg["content"]["data"])))

comm = RecordingComm(
    target_name="staticpython-test",
    comm_id="staticpython-comm",
    data={"hello": "world"},
)
assert manager.get_comm("staticpython-comm") is comm
manager.targets["staticpython-test"](comm, {"content": {"data": {"hello": "world"}}})

received = []
closed = []
comm.on_msg(lambda msg: received.append(msg["content"]["data"]))
comm.on_close(lambda msg: closed.append(msg["content"]["data"]))
comm.handle_msg({"content": {"data": {"answer": 42}}})
comm.handle_close({"content": {"data": {"done": True}}})

comm.send({"answer": 42})
comm.close({"done": True})

assert isinstance(comm, RecordingComm)
assert opened == [("staticpython-comm", {"hello": "world"})]
assert received == [{"answer": 42}]
assert closed == [{"done": True}]
assert [item[0] for item in comm.records] == ["comm_open", "comm_msg", "comm_close"]
assert comm.records[0][1]["hello"] == "world"
assert comm.records[1][1]["answer"] == 42
""",
        )
    ],
)
