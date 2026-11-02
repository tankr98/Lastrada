from lastrada.schemas.models import PathResult, Locate, Description


def analyze(requested=True):
    return PathResult(
        rights_type="publishing",
        locate=Locate(detection_status="not_verified" if requested else "not_requested"),
        describe=Description(
            limitations=[
                "Automatic composition/interpolation localization is not implemented.",
                "No master-audio match does not establish absence of compositional reuse.",
                "Expert-supplied melody, lyric and section observations are required.",
            ]
            if requested
            else []
        ),
    )
