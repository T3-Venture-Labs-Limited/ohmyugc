"""Caption engine vendored from popcaps (https://github.com/T3-Venture-Labs-Limited/popcaps, MIT).

Turns word timings into animated captions: grouping, layout, presets and an ASS compiler that
ffmpeg's libass filter burns into video. Only the pieces ads need are included (no
transcription, face detection or emoji overlays).

A transcript is a list of words, each a dict::

    {"text": "Hello", "start": 0.12, "end": 0.48, "emph": None, "emoji": None, "br": False}
"""
