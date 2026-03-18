import platform
import subprocess


def speak(text: str) -> None:
    """
    Very small text-to-speech helper.

    On macOS (your dev machine), this uses the built-in `say` command.
    On other platforms, it just prints to stdout.
    """
    system = platform.system()
    if system == "Darwin":
        try:
            subprocess.Popen(["say", text])
        except Exception:
            print("[TTS fallback]", text)
    else:
        print("[TTS]", text)

