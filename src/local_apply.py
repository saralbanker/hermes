"""
local_apply.py — Browser automation via browser-use + local Ollama (qwen3:4b).
Zero API cost. Fully local. No cloud dependency.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent

SUCCESS_SIGNALS = [
    "submitted", "application sent", "successfully applied",
    "thank you for applying", "application complete",
    "we received your application", "application received",
    "your application has been",
]
FAILURE_SIGNALS = [
    "login required", "could not submit", "unable to submit",
    "failed to submit", "error occurred", "failed:",
    "sign in to", "create an account",
]


def _load_cfg() -> dict:
    return yaml.safe_load(open(ROOT / "config.yaml"))


async def _run_agent(prompt: str, cfg: dict) -> dict:
    from browser_use import Agent
    from browser_use.browser import BrowserSession, BrowserProfile
    from browser_use.llm.ollama.chat import ChatOllama

    ollama_cfg = cfg.get("ollama", cfg.get("qwen", {}))
    # qwen2.5:3b — no thinking mode, 1.9 GB, fast on CPU (browser action decisions don't need deep reasoning)
    model = ollama_cfg.get("apply_model", "qwen2.5:3b")
    host = ollama_cfg.get("base_url", "http://localhost:11434")
    timeout = float(ollama_cfg.get("timeout", 300))

    llm = ChatOllama(
        model=model,
        host=host,
        timeout=timeout,
        ollama_options={"temperature": 0.1},
    )

    session = BrowserSession(headless=True)

    try:
        agent = Agent(
            task=prompt,
            llm=llm,
            browser=session,
            max_actions_per_step=8,
            max_failures=3,
            use_vision=False,
            llm_timeout=180,   # qwen3:4b on CPU needs ~60-120s per call
            step_timeout=240,
        )
        result = await agent.run(max_steps=25)
        final_text = str(result.final_result() or "")
        return {"success": True, "output": final_text}
    except Exception as e:
        return {"success": False, "error": str(e)[:400]}
    finally:
        try:
            await session.close()
        except Exception:
            pass


def _parse(output: str, screenshot_path: str) -> dict:
    lower = output.lower()
    if any(s in lower for s in SUCCESS_SIGNALS):
        return {"success": True, "screenshot": screenshot_path}
    if any(s in lower for s in FAILURE_SIGNALS):
        return {"success": False, "error": output[-300:]}
    return {"success": False, "error": f"ambiguous: {output[-300:]}"}


def run_local_apply(prompt: str, resume_path: str, screenshot_path: str, timeout: int = 300) -> dict:
    cfg = _load_cfg()
    try:
        result = asyncio.run(
            asyncio.wait_for(_run_agent(prompt, cfg), timeout=timeout)
        )
    except asyncio.TimeoutError:
        return {"success": False, "error": f"timeout_{timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)[:300]}

    if not result.get("success"):
        return result

    return _parse(result.get("output", ""), screenshot_path)
