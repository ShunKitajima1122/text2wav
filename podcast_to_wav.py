#!/usr/bin/env python3
"""Convert a UTF-8 Japanese podcast script to one WAV using VOICEVOX.

Start the VOICEVOX editor or Engine before running this script.

    python podcast_to_wav.py script.txt
    python podcast_to_wav.py script.txt episode.wav --speaker 2 --speed 1.05
    python podcast_to_wav.py --list-speakers
"""

import argparse
from decimal import Decimal, ROUND_HALF_UP
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import NamedTuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import wave


SAMPLE_RATE = 44100
MAX_CHARS = 200
SENTENCE_END = re.compile(r'[。！？!?]+[」』）】”’]*')
COMMAND = re.compile(r"《([^《》\r\n]*)》")
DURATION = re.compile(r"([0-9]+(?:\.[0-9]+)?)(ms|s)")
MAX_WAV_FRAMES = (0xFFFFFFFF - 36) // 2
DEFAULT_VOICES = {"男1": 11, "男2": 13, "女1": 2, "女2": 8}


class Speech(NamedTuple):
    text: str
    paragraph_pause: bool
    speaker: int


class Silence(NamedTuple):
    frames: int


def script_chunks(script):
    """Split at paragraph and sentence boundaries, keeping questions intact."""
    paragraphs = re.split(r"\n[ \t]*\n+", script.strip())
    for paragraph_index, paragraph in enumerate(paragraphs):
        text = " ".join(paragraph.split())
        start = 0
        first = True
        while start < len(text):
            limit = min(start + MAX_CHARS, len(text))
            end = limit
            if limit < len(text):
                endings = list(SENTENCE_END.finditer(text, start, limit))
                if endings:
                    end = endings[-1].end()
                else:
                    separator = max(text.rfind(mark, start, limit) for mark in "、， ")
                    if separator >= start + MAX_CHARS // 2:
                        end = separator + 1
            chunk = text[start:end].strip()
            if chunk:
                yield chunk, first and paragraph_index > 0
                first = False
            start = end


def voice_assignment(value):
    label, separator, style = value.partition("=")
    label = label.strip()
    if (separator and re.fullmatch(r"[^《》\r\n]+", label)
            and not DURATION.fullmatch(label) and re.fullmatch(r"[0-9]+", style.strip())):
        return label, int(style)
    raise argparse.ArgumentTypeError("話者は ラベル=ID の形式で指定してください。例: 司会=11")


def script_actions(script, speaker, voices):
    parts = COMMAND.split(script)
    previous_was_speech = False
    silence_frames = 0
    for index, part in enumerate(parts):
        if index % 2 == 0:
            if "《" in part or "》" in part:
                raise ValueError("原稿のコマンドは同じ行の《》で囲んでください。")
            for chunk_index, (chunk, paragraph_pause) in enumerate(script_chunks(part)):
                pause = paragraph_pause or (chunk_index == 0 and previous_was_speech)
                yield Speech(chunk, pause, speaker)
                previous_was_speech = True
            continue

        command = part.strip()
        duration = DURATION.fullmatch(command)
        if duration:
            amount, unit = duration.groups()
            seconds = Decimal(amount) / (1000 if unit == "ms" else 1)
            frames = int((seconds * SAMPLE_RATE).to_integral_value(rounding=ROUND_HALF_UP))
            silence_frames += frames
            if silence_frames > MAX_WAV_FRAMES:
                raise ValueError("無音の合計時間がWAV形式の上限を超えています。")
            yield Silence(frames)
            previous_was_speech = False
        elif command in voices:
            speaker = voices[command]
        else:
            raise ValueError(f"未定義のコマンド《{command}》です。話者名、秒数（1s）、またはミリ秒数（5ms）を指定してください。")


def request(engine, path, params=None, body=None, post=False):
    url = engine.rstrip("/") + path
    if params:
        url += "?" + urlencode(params)
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    response_request = Request(
        url, data=data, headers=headers, method="POST" if post else "GET"
    )
    try:
        with urlopen(response_request, timeout=120) as response:
            return response.read()
    except HTTPError as error:
        detail = error.read(512).decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"{path} が失敗しました（HTTP {error.code}）{detail}") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(
            f"VOICEVOX Engineとの通信に失敗しました。起動状況と接続先を確認してください。"
            f" {engine} ({error})"
        ) from error


def fetch_speakers(engine):
    speakers = json.loads(request(engine, "/speakers"))
    return {
        style["id"]: f'{speaker["name"]}（{style["name"]}）'
        for speaker in speakers
        for style in speaker["styles"]
        if style.get("type", "talk") == "talk"
    }


def synthesize(engine, speaker, speed, text, *, pad_start=True, pad_end=True):
    query = json.loads(request(
        engine, "/audio_query", {"speaker": speaker, "text": text}, post=True
    ))
    query.update(
        speedScale=speed,
        outputSamplingRate=SAMPLE_RATE,
        outputStereo=False,
        prePhonemeLength=0.06 if pad_start else 0.0,
        postPhonemeLength=0.16 if pad_end else 0.0,
    )
    return request(engine, "/synthesis", {"speaker": speaker}, body=query, post=True)


def write_silence(episode, frames):
    block = bytes(min(frames, SAMPLE_RATE) * 2)
    whole_seconds, remainder = divmod(frames, SAMPLE_RATE)
    for _ in range(whole_seconds):
        episode.writeframesraw(block)
    if remainder:
        episode.writeframesraw(block[:remainder * 2])


def write_episode(output, actions, engine, speed, credit):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent, suffix=".wav", delete=False
        ) as file:
            temporary = Path(file.name)
            with wave.open(file, "wb") as episode:
                episode.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
                for index, action in enumerate(actions):
                    if isinstance(action, Silence):
                        write_silence(episode, action.frames)
                        continue
                    print(f"区間 {index + 1}/{len(actions)} を音声合成", file=sys.stderr)
                    audio = synthesize(
                        engine, action.speaker, speed, action.text,
                        pad_start=index == 0 or not isinstance(actions[index - 1], Silence),
                        pad_end=index + 1 == len(actions) or not isinstance(actions[index + 1], Silence),
                    )
                    with wave.open(io.BytesIO(audio), "rb") as segment:
                        audio_format = (
                            segment.getnchannels(), segment.getsampwidth(), segment.getframerate()
                        )
                        frames = segment.readframes(segment.getnframes())
                        if (audio_format != (1, 2, SAMPLE_RATE) or not frames
                                or len(frames) != segment.getnframes() * 2):
                            raise ValueError(f"区間 {index + 1} のWAVが空か、形式が異なります。")
                        if action.paragraph_pause:
                            write_silence(episode, round(SAMPLE_RATE * 0.35))
                        episode.writeframesraw(frames)
        os.replace(temporary, output)
        print(output, file=sys.stderr)
        if credit:
            print(f"音声クレジット　VOICEVOX:{credit}", file=sys.stderr)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description="VOICEVOXで日本語原稿をモノラル・44.1 kHz・16ビットPCMのWAVに変換します。"
    )
    parser.add_argument("script", nargs="?", help="UTF-8原稿のパス。- は標準入力")
    parser.add_argument("output", nargs="?", type=Path, help="WAVのパス。省略時は原稿と同名")
    parser.add_argument("--engine", default="http://127.0.0.1:50021", help="VOICEVOX EngineのURL")
    parser.add_argument("--speaker", type=int, default=2, help="話者スタイルID。既定値は2")
    parser.add_argument(
        "--voice", action="append", type=voice_assignment, default=[], metavar="ラベル=ID",
        help="原稿内の話者ラベルにスタイルIDを割り当てる。複数指定可",
    )
    parser.add_argument("--speed", type=float, default=1.0, help="読み上げ速度。既定値は1.0")
    parser.add_argument("--list-speakers", action="store_true", help="利用できる話者を表示")
    parser.add_argument("--credit", action="store_true", help="番組末尾に音声クレジットを追加")
    args = parser.parse_args()
    if not args.list_speakers and args.script is None:
        parser.error("原稿ファイルを指定してください。")
    if not math.isfinite(args.speed) or not 0.5 <= args.speed <= 2.0:
        parser.error("--speed は 0.5 から 2.0 の間で指定してください。")

    try:
        if args.list_speakers:
            for style_id, name in sorted(fetch_speakers(args.engine).items()):
                print(f"{style_id}\t{name}")
            return 0
        script = (
            sys.stdin.buffer.read().decode("utf-8-sig") if args.script == "-"
            else Path(args.script).read_text(encoding="utf-8-sig")
        )
        script = script.replace("\r\n", "\n").replace("\r", "\n")
        voices = DEFAULT_VOICES.copy()
        voices.update(args.voice)
        actions = list(script_actions(script, args.speaker, voices))
        used_speakers = list(dict.fromkeys(action.speaker for action in actions if isinstance(action, Speech)))
        if not used_speakers and not any(isinstance(action, Silence) and action.frames for action in actions):
            raise ValueError("原稿に読み上げる文章または正の無音時間を指定してください。")
        output = args.output
        if output is None:
            output = Path("podcast.wav") if args.script == "-" else Path(args.script).with_suffix(".wav")
        if output.suffix.lower() != ".wav":
            raise ValueError("出力ファイルの拡張子は .wav にしてください。")
        if args.script != "-" and output.resolve() == Path(args.script).resolve():
            raise ValueError("原稿と異なる出力先を指定してください。")
        speakers = fetch_speakers(args.engine) if used_speakers else {}
        for speaker in used_speakers:
            if speaker not in speakers:
                raise ValueError(f"話者ID {speaker} は利用できません。--list-speakers で確認してください。")
        names = dict.fromkeys(speakers[speaker].split("（", 1)[0] for speaker in used_speakers)
        if args.credit and used_speakers:
            text = f"音声合成は、ボイスボックスの、{'、'.join(names)}を使用しました。"
            actions.append(Speech(text, isinstance(actions[-1], Speech), used_speakers[0]))
        credit = "、".join(speakers[speaker] for speaker in used_speakers)
        write_episode(output, actions, args.engine, args.speed, credit)
        return 0
    except (OSError, ValueError, RuntimeError, EOFError, wave.Error) as error:
        print(f"エラー　{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
