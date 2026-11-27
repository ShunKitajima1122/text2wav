#!/usr/bin/env python3
"""Convert a UTF-8 Japanese podcast script to one WAV using VOICEVOX.

Start the VOICEVOX editor or Engine before running this script.

    python podcast_to_wav.py script.txt
    python podcast_to_wav.py script.txt episode.wav --speaker 2 --speed 1.05
    python podcast_to_wav.py --list-speakers
"""

import argparse
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import wave


SAMPLE_RATE = 44100
MAX_CHARS = 200
SENTENCE_END = re.compile(r'[。！？!?]+[」』）】”’]*')


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


def synthesize(engine, speaker, speed, text):
    query = json.loads(request(
        engine, "/audio_query", {"speaker": speaker, "text": text}, post=True
    ))
    query.update(
        speedScale=speed,
        outputSamplingRate=SAMPLE_RATE,
        outputStereo=False,
        prePhonemeLength=0.06,
        postPhonemeLength=0.16,
    )
    return request(engine, "/synthesis", {"speaker": speaker}, body=query, post=True)


def write_episode(output, chunks, engine, speaker, speed, credit):
    silence = bytes(round(SAMPLE_RATE * 0.35) * 2)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent, suffix=".wav", delete=False
        ) as file:
            temporary = Path(file.name)
            with wave.open(file, "wb") as episode:
                episode.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
                for index, (chunk, pause) in enumerate(chunks, start=1):
                    print(f"音声合成 {index}/{len(chunks)}", file=sys.stderr)
                    with wave.open(io.BytesIO(synthesize(engine, speaker, speed, chunk)), "rb") as segment:
                        audio_format = (
                            segment.getnchannels(), segment.getsampwidth(), segment.getframerate()
                        )
                        frames = segment.readframes(segment.getnframes())
                        if (audio_format != (1, 2, SAMPLE_RATE) or not frames
                                or len(frames) != segment.getnframes() * 2):
                            raise ValueError(f"区間 {index} のWAVが空か、形式が異なります。")
                        if pause:
                            episode.writeframesraw(silence)
                        episode.writeframesraw(frames)
        os.replace(temporary, output)
        print(f"{output}\n音声クレジット　VOICEVOX:{credit}", file=sys.stderr)
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
        chunks = list(script_chunks(script.replace("\r\n", "\n").replace("\r", "\n")))
        if not chunks:
            raise ValueError("原稿が空です。")
        output = args.output
        if output is None:
            output = Path("podcast.wav") if args.script == "-" else Path(args.script).with_suffix(".wav")
        if output.suffix.lower() != ".wav":
            raise ValueError("出力ファイルの拡張子は .wav にしてください。")
        if args.script != "-" and output.resolve() == Path(args.script).resolve():
            raise ValueError("原稿と異なる出力先を指定してください。")
        speakers = fetch_speakers(args.engine)
        if args.speaker not in speakers:
            raise ValueError(f"話者ID {args.speaker} は利用できません。--list-speakers で確認してください。")
        speaker_name = speakers[args.speaker]
        if args.credit:
            chunks.append((f"音声合成は、ボイスボックスの、{speaker_name.split('（', 1)[0]}を使用しました。", True))
        write_episode(output, chunks, args.engine, args.speaker, args.speed, speaker_name)
        return 0
    except (OSError, ValueError, RuntimeError, EOFError, wave.Error) as error:
        print(f"エラー　{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
