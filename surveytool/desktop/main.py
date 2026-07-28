import threading
from pathlib import Path

import uvicorn
import webview

from surveytool.desktop.app import app

HOST = "127.0.0.1"
PORT = 47812


def _run_server() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def _default_export_dir() -> str:
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.is_dir() else Path.home())


class ExportApi:
    """Exposed to the frontend as `window.pywebview.api` for native dialogs."""

    def choose_export_folder(self, default_dir: str | None = None) -> str | None:
        result = webview.windows[0].create_file_dialog(
            webview.FileDialog.FOLDER,
            directory=default_dir or _default_export_dir(),
        )
        if not result:
            return None
        return result[0]


def main() -> None:
    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    webview.create_window(
        "SurveyTool",
        f"http://{HOST}:{PORT}",
        min_size=(1024, 700),
        js_api=ExportApi(),
    )
    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
