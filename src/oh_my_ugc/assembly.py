"""Stitch chosen clips into finished ads: voice, music, captions, text and the end card (design D12, D13)."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from oh_my_ugc import clips, costs, db, media, projects, render_local, store, storyboard, texts, voice
from oh_my_ugc.captions import ass as caption_ass
from oh_my_ugc.captions import layout as caption_layout
from oh_my_ugc.captions import presets as caption_presets
from oh_my_ugc.captions import words as cwords
from oh_my_ugc.errors import OmuError

FPS = 30
LUFS = -14.0
Progress = Callable[[float, str], None] | None


# ── timeline plan ────────────────────────────────────────────────────────────


def _audio_duration(shot: dict[str, Any]) -> float:
    path = store.maybe_path(shot.get("audio"))
    return media.probe(path).duration if path else 0.0


def _take_len(take: dict[str, Any]) -> float:
    return (take["trim_end"] or take["duration"] or 0.0) - (take["trim_start"] or 0.0)


def build_units(project: dict[str, Any], variant: dict[str, Any] | None = None) -> list[list[dict[str, Any]]]:
    units = storyboard.units(project["id"])
    if variant:
        hook = storyboard.ensure_variant_shot(variant["id"])
        units = [[hook], *units[1:]]
    return units


def plan(project_id: str, variant_id: str | None = None) -> dict[str, Any]:
    """The timeline: each unit's clip, length, start time and where every shot's words fall."""
    from oh_my_ugc import scripts

    project = projects.get(project_id)
    variant = scripts.get_variant(variant_id) if variant_id else None
    units = build_units(project, variant)
    crossfade = float(project["crossfade"] or 0)
    segments, cursor = [], 0.0
    for unit in units:
        lead = unit[0]
        if lead["text_card"]:
            length = lead["duration"]
            segments.append({"kind": "card", "shots": unit, "start": cursor, "length": length, "take": None})
        else:
            take = clips.chosen_take(lead)
            if not take:
                raise OmuError(
                    f"Shot {lead['position'] + 1} has no clip yet. Render it on the Clips stage first."
                )
            mode = clips.effective_mode(project, unit)
            spoken = clips.unit_line_shots(unit)
            clip_len = _take_len(take)
            offsets, shot_lens, t = [], [], 0.0
            for s in unit:
                audio_len = _audio_duration(s) if (s["line"].strip() and mode == "voiceover") else 0.0
                length_s = (
                    max(s["duration"], audio_len + voice.LEAD + voice.TAIL) if audio_len else s["duration"]
                )
                offsets.append(t)
                shot_lens.append(length_s)
                t += length_s
            if spoken and mode in ("native", "avatar") and lead["type"] != "real_product":
                length = clip_len
            elif lead["type"] == "real_product":
                length = max(clip_len, 0.5)
            else:
                length = t
            segments.append(
                {
                    "kind": "clip",
                    "shots": unit,
                    "take": take,
                    "start": cursor,
                    "length": length,
                    "mode": mode,
                    "offsets": offsets,
                    "shot_lens": shot_lens,
                }
            )
        cursor += segments[-1]["length"] - crossfade
    card = project.get("end_card") or {}
    end = None
    if card.get("on") and project.get("product_id"):
        seconds = float(card.get("seconds") or 3.0)
        end = {"start": cursor, "length": seconds}  # overlaps the last shot by the crossfade
        cursor += seconds
    else:
        cursor += crossfade
    return {
        "project": project,
        "variant": variant,
        "segments": segments,
        "end_card": end,
        "duration": cursor,
        "crossfade": crossfade,
    }


# ── words for captions ───────────────────────────────────────────────────────


def _transcribe(path: Path) -> list[dict[str, Any]] | None:
    """Word times from a clip's own audio with faster-whisper, when it is installed."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    from oh_my_ugc import config

    try:
        model = WhisperModel(
            "base", device="cpu", compute_type="int8", download_root=str(config.home() / "models")
        )
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "a.wav"
            media.run_ffmpeg(
                ["-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)]
            )
            segments, _ = model.transcribe(str(wav), word_timestamps=True, vad_filter=False)
            return [
                {"text": w.word.strip(), "start": w.start, "end": w.end}
                for seg in segments
                for w in (seg.words or [])
            ]
    except Exception:
        return None


def native_words(take: dict[str, Any], text: str) -> list[dict[str, Any]]:
    """Word times for a native-dialogue clip, always spelled like the script."""
    key = f"words:{take['media']}:{text}"
    hit = costs.cache_get(key)
    if hit:
        return hit["meta"]["words"]
    path = store.path(take["media"])
    heard = _transcribe(path)
    words = cwords.retime(cwords.clean(heard), text) if heard else voice.align_even(text, path)
    costs.cache_put(key, [], {"words": words}, 0.0)
    return words


def caption_words(p: dict[str, Any]) -> list[dict[str, Any]]:
    """Every spoken word of the ad on the final timeline, spelled as in the script."""
    out: list[dict[str, Any]] = []
    for seg in p["segments"]:
        if seg["kind"] != "clip":
            continue
        unit, take, mode = seg["shots"], seg["take"], seg["mode"]
        spoken = clips.unit_line_shots(unit)
        if not spoken:
            continue
        if mode == "voiceover" or unit[0]["type"] == "real_product":
            for shot, offset in zip(unit, seg["offsets"], strict=False):
                if shot["line"].strip() and shot["words"]:
                    out += [
                        {
                            **w,
                            "start": seg["start"] + offset + voice.LEAD + w["start"],
                            "end": seg["start"] + offset + voice.LEAD + w["end"],
                        }
                        for w in shot["words"]
                    ]
        elif mode == "avatar":
            for shot in unit:
                out += [
                    {**w, "start": seg["start"] + w["start"], "end": seg["start"] + w["end"]}
                    for w in shot["words"]
                ]
        else:  # native dialogue: the clip's own audio
            text = " ".join(s["line"].strip() for s in spoken)
            shift = take["trim_start"] or 0.0
            out += [
                {
                    **w,
                    "start": seg["start"] + max(0.0, w["start"] - shift),
                    "end": seg["start"] + max(0.0, w["end"] - shift),
                }
                for w in native_words(take, text)
            ]
    return cwords.fix_overlaps(cwords.clean(out))


def caption_preset(project: dict[str, Any]):
    return caption_presets.get_builtin(project["caption_style"]) or caption_presets.get_builtin("punch")


def compile_ass(
    p: dict[str, Any], words: list[dict[str, Any]], width: int, height: int, *, with_captions: bool = True
) -> tuple[str, list[Any]]:
    """One ASS script for the whole ad: captions plus on-screen text, text cards and the end card."""
    project = p["project"]
    compiled = None
    if with_captions and project["caption_on"] and words:
        compiled = caption_ass.compile_captions(
            words, caption_preset(project), width, height, font_dirs=(texts.fonts_dir(),)
        )
    items: list[texts.Item] = []
    for seg in p["segments"]:
        if seg["kind"] == "card":
            shot = seg["shots"][0]
            items.append(
                texts.Item(
                    shot["onscreen"],
                    seg["start"],
                    seg["start"] + seg["length"],
                    y=0.5,
                    size=0.07,
                    animate=True,
                )
            )
            continue
        for shot, offset, length in zip(
            seg["shots"], seg.get("offsets", [0]), seg.get("shot_lens", [seg["length"]]), strict=False
        ):
            if shot["onscreen"].strip():
                start = seg["start"] + offset + 0.1
                items.append(
                    texts.Item(
                        shot["onscreen"],
                        start,
                        min(seg["start"] + seg["length"], seg["start"] + offset + length) - 0.05,
                        y=0.16,
                        size=0.052,
                    )
                )
    items += end_card_items(p, width, height)
    styles, events = texts.build(items, width, height)
    return texts.merge(compiled.ass if compiled else None, styles, events, width, height), items


def end_card_items(p: dict[str, Any], width: int, height: int) -> list[texts.Item]:
    end = p["end_card"]
    if not end:
        return []
    project = p["project"]
    product = db.one("SELECT * FROM products WHERE id = ?", (project["product_id"],))
    card = project.get("end_card") or {}
    brand_color = card.get("button_color") or "#FFE14D"
    start, stop = end["start"] + 0.2, end["start"] + end["length"]
    items = [texts.Item(product["name"], start, stop, y=0.17, size=0.058)]
    if card.get("offer"):
        items.append(texts.Item(card["offer"], start + 0.25, stop, y=0.74, size=0.042, color="#FFFFFF"))
    if card.get("cta"):
        items.append(
            texts.Item(card["cta"], start + 0.4, stop, y=0.84, size=0.05, color="#111111", box=brand_color)
        )
    return items


# ── ffmpeg ───────────────────────────────────────────────────────────────────


def _ffmpeg(args: list[str]) -> None:
    media.run_ffmpeg(args)


def _segment(project: dict[str, Any], seg: dict[str, Any], out: Path, size: tuple[int, int]) -> None:
    w, h = size
    length = seg["length"]
    if seg["kind"] == "card":
        card = project.get("end_card") or {}
        color = (card.get("color") or render_local.BRAND_DEFAULT).lstrip("#")
        _ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x{color}:s={w}x{h}:r={FPS}:d={length:.3f}",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-t",
                f"{length:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-shortest",
                str(out),
            ]
        )
        return
    take = seg["take"]
    clip = store.path(take["media"])
    start, eff = take["trim_start"] or 0.0, _take_len(take)
    pad = max(0.0, length - eff) + 0.1
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={FPS},"
        f"tpad=stop_mode=clone:stop_duration={pad:.3f},trim=duration={length:.3f},setpts=PTS-STARTPTS,format=yuv420p"
    )
    inputs = ["-ss", f"{start:.3f}", "-t", f"{eff:.3f}", "-i", str(clip)]
    graph = f"[0:v]{vf}[v]"
    mode, unit = seg["mode"], seg["shots"]
    spoken = clips.unit_line_shots(unit)
    has_clip_audio = bool(take["has_audio"]) and (
        mode in ("native", "avatar") and spoken and unit[0]["type"] != "real_product"
    )
    if has_clip_audio:
        graph += f";[0:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={length:.3f},asetpts=PTS-STARTPTS[a]"
    elif mode == "voiceover" and spoken:
        n = 1
        labels = []
        inputs += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        labels.append("[1:a]")
        for shot, offset in zip(unit, seg["offsets"], strict=False):
            path = store.maybe_path(shot.get("audio")) if shot["line"].strip() else None
            if not path:
                continue
            n += 1
            inputs += ["-i", str(path)]
            delay = round((offset + voice.LEAD) * 1000)
            graph += f";[{n}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={delay}|{delay}[s{n}]"
            labels.append(f"[s{n}]")
        graph += f";{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,atrim=duration={length:.3f},asetpts=PTS-STARTPTS[a]"
    else:
        inputs += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        graph += ";[1:a]anull[a]"
    _ffmpeg(
        [
            *inputs,
            "-filter_complex",
            graph,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            f"{length:.3f}",
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(out),
        ]
    )


def _join(files: list[Path], lengths: list[float], crossfade: float, out: Path, tmp: Path) -> None:
    if len(files) == 1:
        out.write_bytes(files[0].read_bytes())
        return
    if crossfade <= 0:
        listing = tmp / "list.txt"
        listing.write_text("".join(f"file '{f}'\n" for f in files))
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)])
        return
    args: list[str] = []
    for f in files:
        args += ["-i", str(f)]
    vg, ag, offset = [], [], 0.0
    prev_v, prev_a = "[0:v]", "[0:a]"
    for i in range(1, len(files)):
        offset += lengths[i - 1] - crossfade
        vg.append(f"{prev_v}[{i}:v]xfade=transition=fade:duration={crossfade}:offset={offset:.3f}[xv{i}]")
        ag.append(f"{prev_a}[{i}:a]acrossfade=d={crossfade}[xa{i}]")
        prev_v, prev_a = f"[xv{i}]", f"[xa{i}]"
    _ffmpeg(
        [
            *args,
            "-filter_complex",
            ";".join(vg + ag),
            "-map",
            prev_v,
            "-map",
            prev_a,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            str(out),
        ]
    )


def _measure_loudness(audio: Path) -> dict[str, str]:
    proc = subprocess.run(
        [
            media.ffmpeg_bin(),
            "-hide_banner",
            "-nostdin",
            "-i",
            str(audio),
            "-af",
            f"loudnorm=I={LUFS}:TP=-1:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    return json.loads(match.group(0)) if match else {}


def mix_audio(video: Path, music: Path | None, music_volume: float, out: Path, duration: float) -> None:
    """Voice bus plus music ducked under speech (sidechain), as WAV."""
    if music:
        graph = (
            f"[1:a]aloop=loop=-1:size=2147483647,atrim=duration={duration:.3f},volume={music_volume:.3f}[m];"
            "[0:a]asplit=2[vo][sc];[m][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck];"
            "[vo][duck]amix=inputs=2:normalize=0:duration=first[mix]"
        )
        _ffmpeg(
            [
                "-i",
                str(video),
                "-stream_loop",
                "-1",
                "-i",
                str(music),
                "-filter_complex",
                graph,
                "-map",
                "[mix]",
                "-t",
                f"{duration:.3f}",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(out),
            ]
        )
    else:
        _ffmpeg(["-i", str(video), "-vn", "-ar", "48000", "-ac", "2", str(out)])


def render(
    project_id: str,
    variant_id: str | None = None,
    *,
    captions: bool | None = None,
    progress: Progress = None,
    out_name: str | None = None,
) -> dict[str, Any]:
    """Assemble one finished ad. Returns {media, path, duration, srt?}."""
    p = plan(project_id, variant_id)
    project = p["project"]
    size = projects.output_size(project)
    width, height = size
    note = progress or (lambda f, s: None)
    with tempfile.TemporaryDirectory(dir=str(store.config.cache_dir())) as tmp_name:
        tmp = Path(tmp_name)
        files, lengths = [], []
        total = len(p["segments"]) + (1 if p["end_card"] else 0)
        for i, seg in enumerate(p["segments"]):
            note(i / (total + 3), f"Preparing shot {i + 1} of {total}")
            f = tmp / f"seg{i}.mp4"
            _segment(project, seg, f, size)
            files.append(f)
            lengths.append(seg["length"])
        if p["end_card"]:
            note(len(p["segments"]) / (total + 3), "Making the end card")
            product = render_local.require_product(project)
            card = project.get("end_card") or {}
            end_id = render_local.render_real_product(
                project,
                {
                    "duration": p["end_card"]["length"],
                    "motion": "push_in",
                    "background": card.get("background", "blur"),
                    "position": 10**6,
                    "variant_id": None,
                    "id": "",
                },
                product,
                p["end_card"]["length"],
                logo=store.maybe_path(_brand_logo(project)),
            )
            end_file = tmp / "endcard.mp4"
            _ffmpeg(
                [
                    "-i",
                    str(store.path(end_id)),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    str(FPS),
                    "-c:a",
                    "aac",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    str(end_file),
                ]
            )
            files.append(end_file)
            lengths.append(p["end_card"]["length"])
        crossfade = p["crossfade"] if len(files) > 1 else 0.0
        note((total + 0.5) / (total + 3), "Joining the shots")
        joined = tmp / "joined.mp4"
        _join(files, lengths, crossfade, joined, tmp)
        if crossfade:
            p["duration"] = media.probe(joined).duration
        words = caption_words(p) if (project["caption_on"] if captions is None else captions) else []
        ass_text, _ = compile_ass(p, words, width, height, with_captions=bool(words))
        ass_path = tmp / "overlay.ass"
        ass_path.write_text(ass_text, encoding="utf-8")
        note((total + 1) / (total + 3), "Mixing the sound")
        music = store.maybe_path(project.get("music"))
        mix = tmp / "mix.wav"
        mix_audio(joined, music, project["music_volume"], mix, p["duration"])
        stats = _measure_loudness(mix)
        loud = f"loudnorm=I={LUFS}:TP=-1:LRA=11"
        if stats.get("input_i") not in (None, "-inf"):
            loud += f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:linear=true"
        note((total + 2) / (total + 3), "Drawing captions and text")
        final = tmp / "final.mp4"
        vf = f"[0:v]ass={media.filter_path(ass_path)}:fontsdir={media.filter_path(texts.fonts_dir())}[v]"
        _ffmpeg(
            [
                "-i",
                str(joined),
                "-i",
                str(mix),
                "-filter_complex",
                f"{vf};[1:a]{loud},aresample=48000[a]",
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                "-t",
                f"{p['duration']:.3f}",
                str(final),
            ]
        )
        media_id = store.put_file(final)
        srt = None
        if words and project["caption_on"]:
            srt_text = to_srt(words, caption_preset(project), width, height)
            srt = store.put_bytes(srt_text.encode(), "srt") if srt_text else None
    out_dir = projects.project_dir(project_id) / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w\- ]+", "", out_name or project["name"]).strip().replace(" ", "-") or "ad"
    target = out_dir / f"{name}.mp4"
    target.write_bytes(store.path(media_id).read_bytes())
    srt_path = None
    if srt:
        srt_path = out_dir / f"{name}.srt"
        srt_path.write_bytes(store.path(srt).read_bytes())
    return {
        "media": media_id,
        "path": str(target),
        "duration": p["duration"],
        "srt": srt,
        "srt_path": str(srt_path) if srt_path else None,
        "url": store.url(media_id),
    }


def _brand_logo(project: dict[str, Any]) -> str | None:
    if not project.get("brand_id"):
        return None
    brand = db.one("SELECT logo FROM brands WHERE id = ?", (project["brand_id"],))
    return brand["logo"] if brand else None


def to_srt(words: list[dict[str, Any]], preset, width: int, height: int) -> str:
    cards = caption_layout.build_cards(words, preset, width, height, "auto", (texts.fonts_dir(),))
    blocks = []
    plain = preset.merged({"case": "none", "punctuation": True})
    for n, card in enumerate(cards, 1):
        group = [words[i] for i in card.indices]
        text = "\n".join(
            " ".join(caption_layout.display(group[j]["text"], plain) for j in line) for line in card.lines
        )
        blocks.append(f"{n}\n{_srt_time(card.start)} --> {_srt_time(card.end)}\n{text}")
    return "\n\n".join(blocks) + "\n" if blocks else ""


def _srt_time(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ── jobs ─────────────────────────────────────────────────────────────────────

from oh_my_ugc import jobs, runner  # noqa: E402


@jobs.register("assemble")
def _assemble_job(job: dict[str, Any]) -> dict[str, Any]:
    p = job["payload"]
    variant_id = p.get("variant_id")
    name = None
    if variant_id:
        from oh_my_ugc import scripts

        name = f"{projects.get(p['project_id'])['name']} {scripts.get_variant(variant_id)['name']}"
    return render(
        p["project_id"],
        variant_id,
        captions=p.get("captions"),
        progress=lambda f, s: runner.stage(s),
        out_name=name,
    )


def assemble(project_id: str, variant_id: str | None = None, captions: bool | None = None) -> str:
    projects.get(project_id)
    return jobs.enqueue(
        "assemble",
        project_id=project_id,
        payload={"project_id": project_id, "variant_id": variant_id, "captions": captions},
    )


@jobs.register("export_all")
def _export_all_job(job: dict[str, Any]) -> dict[str, Any]:
    from oh_my_ugc import scripts

    project_id = job["payload"]["project_id"]
    outputs = []
    runner.stage("Assembling the main ad")
    outputs.append({"name": "main", **render(project_id, progress=lambda f, s: runner.stage(s))})
    for variant in [v for v in scripts.variants(project_id) if v["kept"]]:
        runner.stage(f"Assembling {variant['name']}")
        outputs.append(
            {
                "name": variant["name"],
                "variant_id": variant["id"],
                **render(
                    project_id,
                    variant["id"],
                    progress=lambda f, s: runner.stage(s),
                    out_name=f"{projects.get(project_id)['name']} {variant['name']}",
                ),
            }
        )
    return {"files": outputs}


def export_all(project_id: str) -> str:
    projects.get(project_id)
    return jobs.enqueue("export_all", project_id=project_id, payload={"project_id": project_id})
