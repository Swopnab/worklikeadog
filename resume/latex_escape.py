"""
resume/latex_escape.py
Proper LaTeX escaping for all special characters.
MUST be applied to any untrusted/user-provided text before inserting into LaTeX templates.
"""
import re


# LaTeX special characters and their escaped equivalents
# Order matters — backslash must be first
_LATEX_ESCAPE_MAP: list[tuple[str, str]] = [
    ("\\", r"\textbackslash{}"),
    ("&",  r"\&"),
    ("%",  r"\%"),
    ("$",  r"\$"),
    ("#",  r"\#"),
    ("_",  r"\_"),
    ("{",  r"\{"),
    ("}",  r"\}"),
    ("~",  r"\textasciitilde{}"),
    ("^",  r"\^{}"),
    ("<",  r"\textless{}"),
    (">",  r"\textgreater{}"),
    ("|",  r"\textbar{}"),
]

# Pre-compiled pattern for fast replacement
_ESCAPE_PATTERN = re.compile(
    r'([\\&%$#_{}~^<>|])'
)

# Mapping for re.sub
_ESCAPE_DICT = {
    "\\": r"\textbackslash{}",
    "&":  r"\&",
    "%":  r"\%",
    "$":  r"\$",
    "#":  r"\#",
    "_":  r"\_",
    "{":  r"\{",
    "}":  r"\}",
    "~":  r"\textasciitilde{}",
    "^":  r"\^{}",
    "<":  r"\textless{}",
    ">":  r"\textgreater{}",
    "|":  r"\textbar{}",
}


def escape(text: str) -> str:
    """
    Escape all LaTeX special characters in the given text.
    Use this on ANY user-provided string before inserting into LaTeX.
    
    Example:
        escape("AWS S3 & IAM") → "AWS S3 \\& IAM"
        escape("90% match")    → "90\\% match"
        escape("key_value")    → "key\\_value"
    """
    if not text:
        return ""
    # Process character by character for correctness
    result = []
    for char in text:
        result.append(_ESCAPE_DICT.get(char, char))
    return "".join(result)


def escape_url(url: str) -> str:
    """
    Minimal escaping for URLs in LaTeX href commands.
    URLs have different rules — primarily escape % and #.
    """
    if not url:
        return ""
    return url.replace("%", r"\%").replace("#", r"\#")


def escape_list(items: list[str]) -> list[str]:
    """Escape a list of strings."""
    return [escape(item) for item in items]


def test_escape():
    """Quick sanity checks."""
    assert escape("hello") == "hello"
    assert escape("50% match") == r"50\% match"
    assert escape("AWS & GCP") == r"AWS \& GCP"
    assert escape("key_name") == r"key\_name"
    assert escape("C++") == r"C++"  # + is safe
    assert escape("$100") == r"\$100"
    assert escape("") == ""
    print("latex_escape: all tests passed")


if __name__ == "__main__":
    test_escape()
