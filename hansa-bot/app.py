import os
import time
import random
import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

import requests
from math_solver import solve_math_challenge


BASE_URL = os.getenv("HANSA_BASE_URL", "").rstrip("/")
API_KEY = os.getenv("HANSA_API_KEY", "")
DAY_END_UTC = os.getenv("DAY_END_UTC", "23:59:50")

TARGET_GAP = Decimal(os.getenv("TARGET_GAP_VS_SECOND", "40.0"))
DAYTIME_TRIGGER_GAP = Decimal(os.getenv("DAYTIME_TRIGGER_GAP", "38.0"))
FINAL_TRIGGER_GAP = Decimal(os.getenv("FINAL_TRIGGER_GAP", "40.0"))

DAYTIME_CHECK_MIN = int(os.getenv("DAYTIME_CHECK_MIN_SEC", "900"))
DAYTIME_CHECK_MAX = int(os.getenv("DAYTIME_CHECK_MAX_SEC", "3600"))
FINAL_CHECK_MIN = int(os.getenv("FINAL_CHECK_MIN_SEC", "8"))
FINAL_CHECK_MAX = int(os.getenv("FINAL_CHECK_MAX_SEC", "25"))

MAX_TASKS_PER_DAYTIME_CHECK_MIN = int(os.getenv("MAX_TASKS_PER_DAYTIME_CHECK_MIN", "1"))
MAX_TASKS_PER_DAYTIME_CHECK_MAX = int(os.getenv("MAX_TASKS_PER_DAYTIME_CHECK_MAX", "3"))
MAX_TASKS_PER_FINAL_CHECK_MIN = int(os.getenv("MAX_TASKS_PER_FINAL_CHECK_MIN", "1"))
MAX_TASKS_PER_FINAL_CHECK_MAX = int(os.getenv("MAX_TASKS_PER_FINAL_CHECK_MAX", "2"))

DAILY_MAX_SUBMISSIONS = int(os.getenv("DAILY_MAX_SUBMISSIONS", "80"))
DB_PATH = os.getenv("DB_PATH", "hansa_bot.db")

EP_FEED = "/api/agents/feed"
EP_DAILY_QUESTS = "/api/agents/daily-quests"
EP_LEADERBOARD = "/api/agents/daily-points-leaderboard"
EP_CHECKIN = "/api/agents/checkin"
EP_SUBMIT = os.getenv("EP_SUBMIT", "/api/agents/submit")
EP_RED_PACKET_CURRENT = os.getenv("EP_RED_PACKET_CURRENT", "/api/agents/red-packet/current")
EP_RED_PACKET_CLAIM = os.getenv("EP_RED_PACKET_CLAIM", "/api/agents/red-packet/claim")


session = requests.Session()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_decimal(v: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return default


def jitter_interval(min_sec: int, max_sec: int) -> int:
    return random.randint(min_sec, max_sec)


def get_day_end_utc(now: datetime) -> datetime:
    h, m, s = map(int, DAY_END_UTC.split(":"))
    end = now.replace(hour=h, minute=m, second=s, microsecond=0)
    if now > end:
        end += timedelta(days=1)
    return end


def is_final_hour(now: datetime) -> bool:
    end = get_day_end_utc(now)
    return (end - now).total_seconds() <= 3600


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS task_log(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      task_id TEXT,
      action TEXT NOT NULL,
      status TEXT NOT NULL,
      detail TEXT
    )
    """
    )
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS run_stat(
      day TEXT PRIMARY KEY,
      submit_count INTEGER NOT NULL DEFAULT 0
    )
    """
    )
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS manual_queue(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      task_id TEXT NOT NULL,
      title TEXT,
      raw_json TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """
    )
    conn.commit()
    conn.close()


def log(action: str, status: str, detail: str = "", task_id: Optional[str] = None) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO task_log(ts,task_id,action,status,detail) VALUES(?,?,?,?,?)",
        (now_utc().isoformat(), task_id, action, status, detail[:2000]),
    )
    conn.commit()
    conn.close()


def today_key() -> str:
    return now_utc().strftime("%Y-%m-%d")


def get_submit_count_today() -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT submit_count FROM run_stat WHERE day=?", (today_key(),))
    row = cur.fetchone()
    conn.close()
    return int(row[0]) if row else 0


def inc_submit_count_today(n: int = 1) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    day = today_key()
    cur.execute("SELECT submit_count FROM run_stat WHERE day=?", (day,))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE run_stat SET submit_count=submit_count+? WHERE day=?", (n, day))
    else:
        cur.execute("INSERT INTO run_stat(day,submit_count) VALUES(?,?)", (day, n))
    conn.commit()
    conn.close()


def headers() -> Dict[str, str]:
    h = {"Content-Type": "application/json", "User-Agent": "hansa-gap-bot/1.0"}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def api_get(path: str) -> Dict[str, Any]:
    if not BASE_URL:
        raise RuntimeError("HANSA_BASE_URL is empty")
    r = session.get(BASE_URL + path, headers=headers(), timeout=20)
    r.raise_for_status()
    return r.json() if r.content else {}


def api_post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not BASE_URL:
        raise RuntimeError("HANSA_BASE_URL is empty")
    r = session.post(BASE_URL + path, headers=headers(), json=payload, timeout=20)
    r.raise_for_status()
    return r.json() if r.content else {}


def normalize_list(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "data", "results", "leaderboard", "tasks", "quests"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


def find_red_packet_payload(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not data:
        return None
    if isinstance(data.get("data"), dict):
        return data["data"]
    if isinstance(data.get("redPacket"), dict):
        return data["redPacket"]
    if isinstance(data.get("item"), dict):
        return data["item"]
    if "id" in data and ("question" in data or "mathQuestion" in data):
        return data
    return None


def extract_question(payload: Dict[str, Any]) -> Optional[str]:
    for k in ("question", "mathQuestion", "challengeQuestion", "quiz"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    challenge = payload.get("challenge")
    if isinstance(challenge, dict):
        for k in ("question", "mathQuestion"):
            v = challenge.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def claim_red_packet(payload: Dict[str, Any]) -> bool:
    packet_id = payload.get("id") or payload.get("redPacketId")
    question = extract_question(payload)
    if not packet_id or not question:
        return False

    answer = solve_math_challenge(question)
    body = {"id": packet_id, "answer": answer}
    try:
        resp = api_post(EP_RED_PACKET_CLAIM, body)
        log("red_packet_claim", "ok", str(resp), task_id=str(packet_id))
        print(f"[red-packet] success id={packet_id} answer={answer}")
        return True
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        detail = e.response.text if e.response is not None else str(e)
        log("red_packet_claim", "error", f"status={status} {detail}", task_id=str(packet_id))
        print(f"[red-packet] failed id={packet_id} status={status}")
        return False


def monitor_red_packet_window(seconds: int = 240, interval: float = 0.5) -> bool:
    deadline = time.time() + seconds
    seen_packet_ids = set()
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        try:
            data = api_get(EP_RED_PACKET_CURRENT)
            payload = find_red_packet_payload(data)
            if payload:
                packet_id = str(payload.get("id") or payload.get("redPacketId") or "")
                if packet_id and packet_id not in seen_packet_ids:
                    seen_packet_ids.add(packet_id)
                    print(f"[red-packet] detected at attempt={attempt}, id={packet_id}")
                    if claim_red_packet(payload):
                        return True
        except Exception as e:
            log("red_packet_poll", "error", str(e))

        time.sleep(interval)

    print("[red-packet] monitor ended without successful claim")
    return False


def get_leaderboard() -> List[Dict[str, Any]]:
    data = api_get(EP_LEADERBOARD)
    lb = normalize_list(data)
    lb.sort(key=lambda x: parse_decimal(x.get("points", 0)), reverse=True)
    return lb


def get_me_and_second_gap() -> Tuple[Decimal, Decimal, Decimal]:
    lb = get_leaderboard()
    if not lb:
        return Decimal("0"), Decimal("0"), Decimal("0")

    my_points = None
    for row in lb:
        if row.get("isMe") is True:
            my_points = parse_decimal(row.get("points", 0))
            break

    if my_points is None:
        my_points = parse_decimal(lb[0].get("points", 0))

    second_points = parse_decimal(lb[1].get("points", 0)) if len(lb) > 1 else Decimal("0")
    gap = my_points - second_points
    return my_points, second_points, gap


def fetch_tasks() -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    for ep in (EP_FEED, EP_DAILY_QUESTS):
        try:
            data = api_get(ep)
            tasks.extend(normalize_list(data))
        except Exception as e:
            log("fetch_tasks", "error", f"{ep} {e}")

    uniq: Dict[str, Dict[str, Any]] = {}
    for t in tasks:
        tid = str(t.get("id", ""))
        if tid:
            uniq[tid] = t
    return list(uniq.values())


def is_done(task: Dict[str, Any]) -> bool:
    s = str(task.get("status", "")).lower()
    return s in {"done", "completed", "claimed", "verified", "success"}


def needs_manual(task: Dict[str, Any]) -> bool:
    if task.get("requiresManualAction") is True:
        return True
    txt = (
        str(task.get("type", ""))
        + " "
        + str(task.get("title", ""))
        + " "
        + str(task.get("description", ""))
    ).lower()
    manual_words = ["manual", "tweet", "twitter", "x.com", "discord", "telegram", "proof", "comment", "post"]
    return any(w in txt for w in manual_words)


def task_score_hint(task: Dict[str, Any]) -> Decimal:
    for k in ("points", "score", "rewardPoints", "xp"):
        if k in task:
            return parse_decimal(task.get(k), Decimal("0"))
    return Decimal("1")


def enqueue_manual_tasks(tasks: List[Dict[str, Any]]) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for t in tasks:
        tid = str(t.get("id", ""))
        if not tid:
            continue
        cur.execute("SELECT 1 FROM manual_queue WHERE task_id=? AND status='pending' LIMIT 1", (tid,))
        if cur.fetchone():
            continue
        title = t.get("title") or t.get("name") or "manual task"
        cur.execute(
            "INSERT INTO manual_queue(task_id,title,raw_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (tid, title, str(t), "pending", now_utc().isoformat(), now_utc().isoformat()),
        )
    conn.commit()
    conn.close()


def pick_auto_tasks(tasks: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    cands = [t for t in tasks if (not is_done(t) and not needs_manual(t))]
    random.shuffle(cands)
    cands.sort(key=lambda x: task_score_hint(x), reverse=True)
    return cands[:limit]


def do_checkin_once() -> None:
    try:
        resp = api_post(EP_CHECKIN, {})
        log("checkin", "ok", str(resp))
    except Exception as e:
        log("checkin", "error", str(e))


def submit_task(task_id: str) -> bool:
    try:
        resp = api_post(EP_SUBMIT, {"taskId": task_id, "proof": {"auto": True, "ts": now_utc().isoformat()}})
        log("submit", "ok", str(resp), task_id=task_id)
        inc_submit_count_today(1)
        return True
    except Exception as e:
        log("submit", "error", str(e), task_id=task_id)
        return False


def manual_next() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id,task_id,title,created_at FROM manual_queue WHERE status='pending' ORDER BY id ASC LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        print("No pending manual tasks.")
        return
    print({"id": row[0], "task_id": row[1], "title": row[2], "created_at": row[3]})


def manual_submit(queue_id: int, proof_text: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT task_id FROM manual_queue WHERE id=? AND status='pending'", (queue_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        print("Queue task not found or not pending")
        return
    task_id = row[0]
    conn.close()

    try:
        resp = api_post(EP_SUBMIT, {"taskId": task_id, "proof": {"manual": True, "text": proof_text}})
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("UPDATE manual_queue SET status='done', updated_at=? WHERE id=?", (now_utc().isoformat(), queue_id))
        conn.commit()
        conn.close()
        log("manual_submit", "ok", str(resp), task_id=task_id)
        print("Submitted manual task", task_id)
    except Exception as e:
        log("manual_submit", "error", str(e), task_id=task_id)
        print("Manual submit failed", e)


def one_cycle() -> None:
    if get_submit_count_today() >= DAILY_MAX_SUBMISSIONS:
        print("[guard] daily submission limit reached")
        return

    now = now_utc()
    final_hour = is_final_hour(now)
    trigger_gap = FINAL_TRIGGER_GAP if final_hour else DAYTIME_TRIGGER_GAP

    my_points, second_points, gap = get_me_and_second_gap()
    print(f"[{now.isoformat()}] my={my_points} second={second_points} gap={gap}")

    if gap >= trigger_gap:
        print(f"gap {gap} >= trigger {trigger_gap}, skip this cycle")
        return

    do_checkin_once()
    tasks = fetch_tasks()
    manuals = [t for t in tasks if (not is_done(t) and needs_manual(t))]
    enqueue_manual_tasks(manuals)

    if final_hour:
        n = random.randint(MAX_TASKS_PER_FINAL_CHECK_MIN, MAX_TASKS_PER_FINAL_CHECK_MAX)
    else:
        n = random.randint(MAX_TASKS_PER_DAYTIME_CHECK_MIN, MAX_TASKS_PER_DAYTIME_CHECK_MAX)

    picks = pick_auto_tasks(tasks, n)
    for t in picks:
        _, _, current_gap = get_me_and_second_gap()
        if current_gap >= TARGET_GAP:
            print(f"target reached: gap={current_gap}")
            break
        tid = str(t.get("id", ""))
        if not tid:
            continue
        ok = submit_task(tid)
        print("submit", tid, ok)
        time.sleep(random.uniform(3, 10))


def scheduler_loop() -> None:
    while True:
        try:
            one_cycle()
        except Exception as e:
            log("cycle", "error", str(e))
            print("cycle error", e)

        if is_final_hour(now_utc()):
            sleep_sec = jitter_interval(FINAL_CHECK_MIN, FINAL_CHECK_MAX)
        else:
            sleep_sec = jitter_interval(DAYTIME_CHECK_MIN, DAYTIME_CHECK_MAX)
        print(f"sleep {sleep_sec}s")
        time.sleep(sleep_sec)


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentHansa auto + manual queue bot")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("run")
    sub.add_parser("once")
    sub.add_parser("manual-next")
    sub.add_parser("redpacket-monitor")
    sm = sub.add_parser("solve-math")
    sm.add_argument("--question", type=str, required=True)

    ms = sub.add_parser("manual-submit")
    ms.add_argument("--id", type=int, required=True)
    ms.add_argument("--proof", type=str, required=True)

    args = parser.parse_args()

    init_db()

    if args.cmd == "once":
        one_cycle()
    elif args.cmd == "redpacket-monitor":
        monitor_red_packet_window()
    elif args.cmd == "solve-math":
        print(solve_math_challenge(args.question))
    elif args.cmd == "manual-next":
        manual_next()
    elif args.cmd == "manual-submit":
        manual_submit(args.id, args.proof)
    else:
        scheduler_loop()


if __name__ == "__main__":
    main()
