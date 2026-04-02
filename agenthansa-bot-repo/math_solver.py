import re
from typing import List, Optional


def extract_first_int(text: str) -> Optional[int]:
    m = re.search(r"[-+]?\d+", text)
    return int(m.group()) if m else None


def extract_ints(text: str) -> List[int]:
    return [int(x) for x in re.findall(r"[-+]?\d+", text)]


def solve_math_challenge(question: str) -> int:
    """
    Solve simple natural-language arithmetic.
    Handles:
    - "subtract X from Y" => Y - X
    - plus / minus / multiply / divide phrasing
    """
    q = question.strip().lower()
    nums = extract_ints(q)

    m = re.search(r"subtract\s+([-+]?\d+)\s+from\s+([-+]?\d+)", q)
    if m:
        x = int(m.group(1))
        y = int(m.group(2))
        return y - x

    m = re.search(r"add\s+([-+]?\d+)\s+to\s+([-+]?\d+)", q)
    if m:
        x = int(m.group(1))
        y = int(m.group(2))
        return x + y

    if len(nums) >= 2:
        a, b = nums[0], nums[1]
        if "minus" in q or "subtract" in q or "-" in q:
            return a - b
        if "plus" in q or "add" in q or "+" in q:
            return a + b
        if "times" in q or "multipl" in q or "*" in q:
            return a * b
        if "divide" in q or "/" in q:
            if b == 0:
                raise ValueError("division by zero in challenge")
            return int(a / b)

    first = extract_first_int(q)
    if first is None:
        raise ValueError(f"unsupported challenge question: {question}")
    return first
