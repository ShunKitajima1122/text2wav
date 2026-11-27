"""Install the local CPU-only VOICEVOX Core dependencies for text2wav."""

import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlopen


CORE_VERSION = "0.17.1"
MODELS_VERSION = "0.17.0"
ONNXRUNTIME_VERSION = "1.23.2"
RELEASE = f"https://github.com/VOICEVOX/voicevox_core/releases/download/{CORE_VERSION}"
PLATFORMS = {
    ("Windows", "x64"): ("download-windows-x64.exe", "win_amd64"),
    ("Darwin", "x64"): ("download-osx-x64", "macosx_10_12_x86_64"),
    ("Darwin", "arm64"): ("download-osx-arm64", "macosx_11_0_arm64"),
    ("Linux", "x64"): ("download-linux-x64", "manylinux_2_34_x86_64"),
    ("Linux", "arm64"): ("download-linux-arm64", "manylinux_2_34_aarch64"),
}


def main():
    root = Path(__file__).resolve().parent
    system = platform.system()
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if (system, arch) not in PLATFORMS or sys.maxsize <= 2**32:
        print(f"対応する64ビット環境を使用してください ({system}, {machine})。", file=sys.stderr)
        return 1
    downloader_name, wheel_tag = PLATFORMS[system, arch]
    wheel = f"{RELEASE}/voicevox_core-{CORE_VERSION}-cp310-abi3-{wheel_tag}.whl"
    venv = root / ".venv"
    python = venv / ("Scripts/python.exe" if system == "Windows" else "bin/python")
    data = root / "voicevox_core"
    try:
        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError("uv が見つかりません。先にインストールしてください。")
        if not python.is_file():
            subprocess.run([uv, "venv", "--allow-existing", "--python", ">=3.10", str(venv)], check=True)
        if not data.exists():
            with tempfile.TemporaryDirectory(dir=root) as temporary:
                staging = Path(temporary)
                downloader = staging / downloader_name
                with urlopen(f"{RELEASE}/{downloader_name}", timeout=60) as response:
                    with downloader.open("wb") as file:
                        shutil.copyfileobj(response, file)
                if system != "Windows":
                    downloader.chmod(0o700)
                downloaded = staging / "voicevox_core"
                subprocess.run(
                    [str(downloader), "--exclude", "c-api", "--devices", "cpu",
                     "--onnxruntime-version", ONNXRUNTIME_VERSION,
                     "--models-version", MODELS_VERSION, "--models-pattern", "[0-9]*.vvm",
                     "--output", str(downloaded)],
                    check=True,
                )
                downloaded.rename(data)
        subprocess.run(
            [uv, "pip", "install", "--python", str(python), wheel,
             "audioop-lts; python_version >= '3.13'"],
            check=True, cwd=root,
        )
        subprocess.run([str(python), str(root / "text2wav.py"), "--list-speakers"], check=True, cwd=root)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"VOICEVOX Coreのセットアップに失敗しました。{error}", file=sys.stderr)
        return 1
    print("セットアップ完了。uv run text2wav.py script.txt で変換できます。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
