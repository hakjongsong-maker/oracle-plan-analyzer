"""Oracle tnsnames.ora parser."""
import re
from typing import Dict, List


def parse_tnsnames(filepath: str) -> Dict[str, str]:
    """Parse tnsnames.ora and return {ALIAS_UPPER: descriptor_string}."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return {}

    # Remove comments and normalize line endings
    content = re.sub(r"#[^\n]*", "", content)
    content = re.sub(r"\r\n", "\n", content)

    aliases: Dict[str, str] = {}
    i = 0
    length = len(content)

    while i < length:
        # Skip whitespace
        while i < length and content[i] in " \t\n\r":
            i += 1
        if i >= length:
            break

        # Match alias name followed by '='
        m = re.match(r"([\w.$]+)\s*=\s*", content[i:])
        if not m:
            # Skip to next line
            while i < length and content[i] != "\n":
                i += 1
            continue

        alias = m.group(1).upper()
        j = i + m.end()

        # Skip extra whitespace
        while j < length and content[j] in " \t\n\r":
            j += 1

        if j >= length or content[j] != "(":
            i = j
            continue

        # Extract balanced parenthesis block
        start = j
        depth = 0
        k = j
        while k < length:
            if content[k] == "(":
                depth += 1
            elif content[k] == ")":
                depth -= 1
                if depth == 0:
                    k += 1
                    break
            k += 1

        aliases[alias] = content[start:k]
        i = k

    return aliases


def get_aliases(filepath: str) -> List[str]:
    return sorted(parse_tnsnames(filepath).keys())
