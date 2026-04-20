import io
import textwrap
import traceback
from contextlib import redirect_stdout, redirect_stderr
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate


_CODE_GEN_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a Python code generation expert. Generate clean, working Python code. "
        "Return ONLY the code block — no markdown fences, no explanation.",
    ),
    ("human", "{task}"),
])

_BLOCKED = ["os.system(", "subprocess.", "shutil.rmtree", "__import__(", "eval(", "exec("]


def _is_safe(code: str) -> tuple[bool, str]:
    for pattern in _BLOCKED:
        if pattern in code:
            return False, f"Blocked: contains '{pattern}'"
    return True, ""


@tool
def execute_python(code: str) -> str:
    """Execute Python code in a sandboxed environment and return stdout/result. Blocks dangerous system calls."""
    safe, reason = _is_safe(code)
    if not safe:
        return f"Execution refused. {reason}"

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    local_ns: dict = {}

    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(textwrap.dedent(code), {"__builtins__": __builtins__}, local_ns)
    except Exception:
        err = traceback.format_exc(limit=5)
        return f"Runtime error:\n{err}"

    output = stdout_buf.getvalue()
    errors = stderr_buf.getvalue()

    parts = []
    if output:
        parts.append(f"Output:\n{output.strip()}")
    if errors:
        parts.append(f"Stderr:\n{errors.strip()}")
    if not parts:
        last_val = list(local_ns.values())[-1] if local_ns else None
        return f"Executed successfully. Last value: {last_val}"
    return "\n".join(parts)


@tool
def generate_code(task: str) -> str:
    """Generate Python code to accomplish a described data manipulation or analysis task."""
    try:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
        chain = _CODE_GEN_PROMPT | llm
        response = chain.invoke({"task": task})
        return response.content
    except Exception as e:
        return f"Code generation failed: {str(e)}"
