# text2wav

UTF-8の日本語原稿をVOICEVOXで読み上げ、ポッドキャスト用のWAVファイル1本に変換するコマンドラインツールです。長い原稿は文や段落の区切りを優先して分割し、段落間に短い間を入れます。

## 準備

1. Python 3.8以上を用意します。Pythonの追加パッケージは不要です。
2. [VOICEVOX](https://voicevox.hiroshiba.jp/)または[VOICEVOX Engine](https://github.com/VOICEVOX/voicevox_engine)を起動します。既定の接続先は `http://127.0.0.1:50021` です。
3. 読み上げる文章をUTF-8の `script.txt` に保存します。話題の区切りには空行を入れます。

### `script.txt` の例

次の文章をコピーし、`podcast_to_wav.py` と同じディレクトリに `script.txt` として保存します。

```text
こんにちは。週刊テックニュースのサンプルです。今日は、ゲーム開発とパソコンの省電力についてお話しします。

まずは、ゲーム開発です。ユニティでゲームを作るときは、エディターでの動作確認に加えて、実際に遊ぶ端末でも試してみましょう。キーボードとゲームパッドを切り替えると、操作の案内が正しく切り替わるか確認できます。

続いて、パソコンの省電力です。同じ処理でも、短時間で終わる設定と、実行中の電力が低い設定とでは、使うエネルギーが変わります。比べるときは、処理が終わるまでの時間と、使ったエネルギーの両方を測ってみましょう。

以上、週刊テックニュースのサンプルでした。それでは、また次回。
```

## 使い方

リポジトリのディレクトリで実行します。

```sh
python podcast_to_wav.py script.txt
```

`script.txt` と同じディレクトリに `script.wav` が生成されます。出力形式はモノラル、44.1 kHz、16-bit PCMです。環境に合わせて `python3` や `uv run` でも実行できます。

出力先、話者、速度を指定する例です。出力先にディレクトリを指定する場合は、先に作成してください。

```sh
python podcast_to_wav.py script.txt episode.wav --speaker 2 --speed 1.05
```

話者スタイルIDは次のコマンドで確認できます。

```sh
python podcast_to_wav.py --list-speakers
```

Bashなどでは、原稿をUTF-8の標準入力から渡せます。入力に `-` を指定し、出力先を省略すると `podcast.wav` が生成されます。

```sh
python podcast_to_wav.py - episode.wav < script.txt
```

## オプション

| オプション | 説明 |
| --- | --- |
| `--engine URL` | VOICEVOX Engineの接続先を指定 |
| `--speaker ID` | 話者スタイルIDを指定。既定値は `2` |
| `--speed 倍率` | 読み上げ速度を `0.5`〜`2.0` で指定。既定値は `1.0` |
| `--list-speakers` | 話者スタイルIDと名前を表示 |
| `--credit` | 音声クレジットの読み上げを末尾に追加 |

音声を共有する際は、[VOICEVOXの利用規約](https://voicevox.hiroshiba.jp/term/)と使用した音声ライブラリの規約に沿ってクレジットを記載してください。
