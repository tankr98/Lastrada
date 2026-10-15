"""Optional real pretrained CPU inference on generated audio, not an accuracy benchmark."""

import json
from pathlib import Path
from time import perf_counter
from lastrada.audio.synthetic import demo_pair
from lastrada.recognition.sampleid_adapter import SampleIDAdapter


def main():
    original, _, _ = demo_pair()
    adapter = SampleIDAdapter(
        Path("checkpoints/sampleid-best.ckpt"), "cache/sampleid-smoke", batch_size=1
    )
    start = perf_counter()
    embeddings = adapter.embed(original)
    assert embeddings.values.shape == (1, 2048)
    matches = adapter.match(original, original, threshold=0.9)
    assert len(matches) == 1
    assert matches[0].similarity > 0.99
    print(
        json.dumps(
            {
                "model": "Sony SampleID",
                "device": "cpu",
                "synthetic_input": True,
                "embedding_shape": list(embeddings.values.shape),
                "self_match_cosine": matches[0].similarity,
                "seconds": perf_counter() - start,
                "checkpoint_sha256": adapter.model_hash,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
