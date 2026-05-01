from libs import inline_verification_step, replace_text_once, simple_library, transform_source_text


def patch_jupyter_client_sources(context):
    def patch_provisioning_factory(text: str) -> str:
        text = replace_text_once(
            text,
            '            return EntryPoint(\n                "local-provisioner", "jupyter_client.provisioning", "LocalProvisioner"\n            )\n',
            '            return EntryPoint(\n                "local-provisioner",\n                "jupyter_client.provisioning:LocalProvisioner",\n                KernelProvisionerFactory.GROUP_NAME,\n            )\n',
            label="jupyter_client local provisioner fallback",
        )
        return replace_text_once(
            text,
            '            self.log.warning(\n                f"Kernel Provisioning: The \'local-provisioner\' is not found.  This is likely "\n                f"due to the presence of multiple jupyter_client distributions and a previous "\n                f"distribution is being used as the source for entrypoints - which does not "\n                f"include \'local-provisioner\'.  That distribution should be removed such that "\n                f"only the version-appropriate distribution remains (version >= 7).  Until "\n                f"then, a \'local-provisioner\' entrypoint will be automatically constructed "\n                f"and used.\\nThe candidate distribution locations are: {distros}"\n            )\n',
            '            if distros:\n                self.log.warning(\n                    f"Kernel Provisioning: The \'local-provisioner\' is not found.  This is likely "\n                    f"due to the presence of multiple jupyter_client distributions and a previous "\n                    f"distribution is being used as the source for entrypoints - which does not "\n                    f"include \'local-provisioner\'.  That distribution should be removed such that "\n                    f"only the version-appropriate distribution remains (version >= 7).  Until "\n                    f"then, a \'local-provisioner\' entrypoint will be automatically constructed "\n                    f"and used.\\nThe candidate distribution locations are: {distros}"\n                )\n            else:\n                self.log.info(\n                    "Kernel Provisioning: Constructing \'local-provisioner\' directly because "\n                    "entry-point metadata is unavailable in this frozen runtime."\n                )\n',
            label="jupyter_client frozen local provisioner log level",
        )

    transform_source_text(
        context,
        "Lib/jupyter_client/provisioning/factory.py",
        patch_provisioning_factory,
    )


LIBRARY_INTEGRATION = simple_library(
    name="jupyter_client",
    project_name="jupyter-client",
    overlay_entries=["Lib/jupyter_client"],
    post_patch_hooks=[patch_jupyter_client_sources],
    verification_steps=[
        inline_verification_step(
            "jupyter-client-smoke",
            """
import json
import os
import sys
import tempfile
from pathlib import Path

from jupyter_client.connect import find_connection_file, write_connection_file
from jupyter_client.kernelspec import KernelSpec, KernelSpecManager
from jupyter_client.manager import KernelManager
from jupyter_client.provisioning.factory import KernelProvisionerFactory
from jupyter_client.session import Session

session = Session(key=b"staticpython-secret")
message = session.msg("execute_request", content={"code": "answer = 40 + 2"})
idents, frames = session.feed_identities(session.serialize(message))
assert idents == []
restored = session.deserialize(frames)
assert restored["header"]["msg_type"] == "execute_request"
assert restored["content"]["code"] == "answer = 40 + 2"

with tempfile.TemporaryDirectory() as temp_dir:
    connection_path = Path(temp_dir) / "kernel-staticpython.json"
    written_path, connection_info = write_connection_file(
        fname=str(connection_path),
        ip="127.0.0.1",
        key=b"secret",
        transport="tcp",
    )
    assert Path(written_path) == connection_path
    assert connection_info["ip"] == "127.0.0.1"
    assert connection_info["transport"] == "tcp"
    found_connection_file = Path(find_connection_file(connection_path.name, path=[temp_dir]))
    assert found_connection_file.name == connection_path.name
    assert found_connection_file.resolve() == connection_path.resolve()

    kernels_dir = Path(temp_dir) / "kernels"
    spec_dir = kernels_dir / "python3"
    spec_dir.mkdir(parents=True)
    spec = KernelSpec(
        argv=["python", "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        display_name="StaticPython",
        language="python",
        resource_dir=str(spec_dir),
    )
    (spec_dir / "kernel.json").write_text(json.dumps(spec.to_dict(), indent=2), encoding="utf-8")

    kernel_spec_manager = KernelSpecManager(
        kernel_dirs=[str(kernels_dir)],
        ensure_native_kernel=False,
    )
    loaded_spec = kernel_spec_manager.get_kernel_spec("python3")
    assert loaded_spec.display_name == "StaticPython"
    factory = KernelProvisionerFactory()
    entry_point = factory._get_provisioner("local-provisioner")
    assert entry_point.name == "local-provisioner"
    assert entry_point.value == "jupyter_client.provisioning:LocalProvisioner"
    assert entry_point.group == KernelProvisionerFactory.GROUP_NAME

    manager = KernelManager(
        kernel_name="python3",
        kernel_spec_manager=kernel_spec_manager,
    )
    manager.connection_file = str(connection_path)
    formatted = manager.format_kernel_cmd(["--HistoryManager.enabled=False"])
    assert formatted[0] == sys.executable
    assert formatted[1:4] == ["-m", "ipykernel_launcher", "-f"]
    assert formatted[4] == str(connection_path.resolve())
    assert formatted[-1] == "--HistoryManager.enabled=False"
""",
        )
    ],
)
