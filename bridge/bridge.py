import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOT_ID = os.environ["GROUPME_BOT_ID"]
ALLOWED_GROUP_ID = os.environ["GROUPME_ALLOWED_GROUP_ID"]
ALLOWED_USER_ID = os.environ["GROUPME_ALLOWED_USER_ID"]
SESSION_FILE = "/home/hermes/.hermes/groupme_session.txt"

GROUPME_URL = "https://api.groupme.com/v3/bots/post"
MAX_LEN = 950                      # GroupMe's limit is 1000
MAX_BODY = 64 * 1024
HERMES_TIMEOUT = 6000
WORKING_DELAY = float(os.environ.get("WORKING_DELAY", "60"))

CRON_OUTPUT_DIR = "/home/hermes/.hermes/cron/output/"

WORKING_MSG = "Working on it…"
APOLOGY_MSG = (
    "Sorry, I couldn't process that message. "
    "Please try again, or send /new to start a fresh session."
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("groupme-bridge")

jobs: "queue.Queue[str]" = queue.Queue()
seen_ids: deque = deque(maxlen=100)
seen_lock = threading.Lock()


# ---------- session handling ----------
def get_saved_session() -> str | None:
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def save_session(raw_output: str) -> None:
    match = re.search(r"Session:\s*([a-zA-Z0-9_-]+)", raw_output)
    if match:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            f.write(match.group(1))


def clear_session() -> None:
    try:
        os.remove(SESSION_FILE)
    except FileNotFoundError:
        pass

def watch_cron_outputs():
    os.makedirs(CRON_OUTPUT_DIR, exist_ok=True)
    seen_files = set()
    for root, _, files in os.walk(CRON_OUTPUT_DIR):
        for fn in files:
            seen_files.add(os.path.join(root, fn))

    while True:
        time.sleep(2)
        for root, _, files in os.walk(CRON_OUTPUT_DIR):
            for fn in files:
                full_path = os.path.join(root, fn)
                if full_path not in seen_files:
                    seen_files.add(full_path)
                    time.sleep(0.5)
                    try:
                        content = open(full_path, "r", encoding="utf-8", errors="ignore").read()
                        # Extract only the text after "## Response"
                        if "## Response" in content:
                            response_part = content.split("## Response", 1)[1].strip()
                        else:
                            response_part = content.strip()

                        cleaned = clean_hermes_output(response_part)
                        if cleaned and cleaned != "[SILENT]":
                            send_groupme(cleaned)
                    except Exception as e:
                        print(f"Cron output forward error: {e}", flush=True)


# ---------- output cleanup ----------
def clean_hermes_output(raw: str) -> str:
    # Remove ANSI color codes if present
    text = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    # Remove <think>...</think> blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Remove ┌─ ... └─┘ box blocks (like Reasoning boxes)
    text = re.sub(r"┌─.*?└─+┘", "", text, flags=re.DOTALL)
    # Remove trailing "Resume this session with:" footer and everything after it
    text = re.split(r"\n\s*Resume this session with:", text)[0]

    cleaned_lines = []
    for line in text.splitlines():
        s = line.strip()
        if (
            s.startswith(("Initializing agent", "Query:", "┊", "(tip)", "Session:",
                          "Messages:", "Duration:", "Tokens:", "Model:", "╭", "╰", "─"))
            or "(clarify timed out" in s
        ):
            continue
        cleaned_lines.append(line.rstrip())   # keeps indentation (original used strip())

    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines)).strip()


# ---------- GroupMe sending ----------
def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    chunks, text = [], text.strip()
    while len(text) > limit:
        window = text[:limit]
        cut = limit
        for sep in ("\n\n", "\n", " "):
            pos = window.rfind(sep)
            if pos > limit // 2:
                cut = pos
                break
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def _post(chunk: str, retries: int = 3) -> None:
    req = urllib.request.Request(
        GROUPME_URL,
        data=json.dumps({"bot_id": BOT_ID, "text": chunk}).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "User-Agent": "HermesGroupMeBridge/1.0"},
        method="POST",
    )
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15):
                return
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            if not (e.code == 429 or e.code >= 500) or attempt == retries:
                log.error("GroupMe API error %s: %s", e.code, body)
                raise
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries:
                log.error("GroupMe network error: %s", e)
                raise
        time.sleep(2 ** attempt)


def send_groupme(text: str) -> None:
    if not text or text.strip() == "[SILENT]":
        return
    chunks = split_message(text)
    for i, chunk in enumerate(chunks):
        _post(chunk)
        if i < len(chunks) - 1:
            time.sleep(0.5)


def safe_send(text: str) -> None:
    try:
        send_groupme(text)
    except Exception:
        log.exception("could not send message to GroupMe")


# ---------- Hermes ----------
def run_hermes(user_text: str) -> str | None:
    """Return the reply text, or None if Hermes failed entirely."""
    cmd = ["hermes", "chat", "-q", user_text]
    session_id = get_saved_session()
    if session_id:
        cmd.extend(["--resume", session_id])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=HERMES_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.warning("hermes timed out after %ss", HERMES_TIMEOUT)
        return None
    except OSError:
        log.exception("could not launch hermes")
        return None

    save_session(result.stdout)
    reply = clean_hermes_output(result.stdout)
    if not reply:
        log.warning("hermes gave no usable output (rc=%s) stderr=%r",
                    result.returncode, result.stderr[-500:])
        return None
    return reply


def run_with_progress(user_text: str) -> str | None:
    done = threading.Event()

    def notify():
        if not done.wait(WORKING_DELAY):
            safe_send(WORKING_MSG)

    threading.Thread(target=notify, daemon=True).start()
    try:
        return run_hermes(user_text)
    finally:
        done.set()


def worker() -> None:
    while True:
        text = jobs.get()
        try:
            if text.lower() in ("/new", "/reset"):
                clear_session()
                safe_send("Started a fresh conversation session.")
            else:
                reply = run_with_progress(text)
                safe_send(reply if reply else APOLOGY_MSG)
        except Exception:
            log.exception("failed handling message")
            safe_send(APOLOGY_MSG)
        finally:
            jobs.task_done()


# ---------- HTTP ----------
class WebhookHandler(BaseHTTPRequestHandler):
    def _respond(self, code: int) -> None:
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        # Local-only outbound notification endpoint for Hermes cron/skills
        if self.path == "/notify":
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                return self._respond(403)
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                msg = (body.get("text") or "").strip()
            except (ValueError, UnicodeDecodeError):
                return self._respond(400)

            self._respond(200)
            if msg:
                safe_send(msg)
            return
            
        if self.path not in ("/groupme-webhook", "/"):
            return self._respond(404)



        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= MAX_BODY:
                return self._respond(413 if length > MAX_BODY else 400)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._respond(400)

        self._respond(200)   # ack right away; real work happens in the worker

        if (
            body.get("sender_type") == "bot"
            or str(body.get("group_id")) != ALLOWED_GROUP_ID
            or str(body.get("sender_id")) != ALLOWED_USER_ID
        ):
            return

        user_text = (body.get("text") or "").strip()
        if not user_text:
            return

        msg_id = body.get("id")
        with seen_lock:
            if msg_id in seen_ids:      # GroupMe retry
                return
            seen_ids.append(msg_id)

        jobs.put(user_text)

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)


if __name__ == "__main__":
    threading.Thread(target=watch_cron_outputs, daemon=True).start()
    threading.Thread(target=worker, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8443), WebhookHandler).serve_forever()