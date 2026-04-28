from libs import inline_verification_step, replace_text_once, simple_library, source_path, transform_source_text


def _bytes_chunks_literal(data: bytes, *, chunk_size: int = 8192) -> str:
    chunks = [data[index : index + chunk_size] for index in range(0, len(data), chunk_size)]
    if not chunks:
        return "b''"
    lines = ["("]
    lines.extend(f"    {chunk!r}" for chunk in chunks)
    lines.append(")")
    return "\n".join(lines)


def patch_chardet_sources(context) -> None:
    models_bin = source_path(context, "Lib/chardet/models/models.bin").read_bytes()
    idf_bin = source_path(context, "Lib/chardet/models/idf.bin").read_bytes()
    confusion_bin = source_path(context, "Lib/chardet/models/confusion.bin").read_bytes()

    def patch_models(text: str) -> str:
        constants = (
            "_STATICPYTHON_MODELS_BIN = "
            + _bytes_chunks_literal(models_bin)
            + "\n\n_STATICPYTHON_IDF_BIN = "
            + _bytes_chunks_literal(idf_bin)
            + "\n\n"
        )
        text = replace_text_once(
            text,
            '_V2_MAGIC = b"CMD2"\n\n',
            '_V2_MAGIC = b"CMD2"\n\n' + constants,
            label="chardet embedded model resources",
        )
        text = replace_text_once(
            text,
            (
                '    ref = importlib.resources.files("chardet.models").joinpath("models.bin")\n'
                "    data = ref.read_bytes()\n"
            ),
            "    data = _STATICPYTHON_MODELS_BIN\n",
            label="chardet models.bin loader",
        )
        return replace_text_once(
            text,
            (
                '    ref = importlib.resources.files("chardet.models").joinpath("idf.bin")\n'
                "    data = ref.read_bytes()\n"
            ),
            "    data = _STATICPYTHON_IDF_BIN\n",
            label="chardet idf.bin loader",
        )

    def patch_confusion(text: str) -> str:
        text = replace_text_once(
            text,
            "DistinguishingMaps = dict[\n",
            (
                "_STATICPYTHON_CONFUSION_BIN = "
                + _bytes_chunks_literal(confusion_bin)
                + "\n\nDistinguishingMaps = dict[\n"
            ),
            label="chardet embedded confusion resource",
        )
        return replace_text_once(
            text,
            (
                '    ref = importlib.resources.files("chardet.models").joinpath("confusion.bin")\n'
                "    raw = ref.read_bytes()\n"
            ),
            "    raw = _STATICPYTHON_CONFUSION_BIN\n",
            label="chardet confusion.bin loader",
        )

    transform_source_text(context, "Lib/chardet/models/__init__.py", patch_models)
    transform_source_text(context, "Lib/chardet/pipeline/confusion.py", patch_confusion)


LIBRARY_INTEGRATION = simple_library(
    name="chardet",
    overlay_entries=["Lib/chardet"],
    post_patch_hooks=[patch_chardet_sources],
    verification_steps=[
        inline_verification_step(
            "chardet-smoke",
            """
import chardet
from chardet.models import BigramProfile, get_enc_index, get_idf_weights, load_models
from chardet.pipeline.confusion import load_confusion_data
from chardet.universaldetector import UniversalDetector

payload = b"caf\\xe9"
result = chardet.detect(payload)
assert result["encoding"].lower() in {"iso-8859-1", "windows-1255", "windows-1252"}

detector = UniversalDetector()
detector.feed(payload)
detector.close()
assert detector.result["encoding"]

models = load_models()
enc_index = get_enc_index()
idf = get_idf_weights()
confusion = load_confusion_data()
profile = BigramProfile(payload)
assert models
assert enc_index
assert len(idf) == 65536
assert confusion
assert profile.nonzero
""",
        )
    ],
)
