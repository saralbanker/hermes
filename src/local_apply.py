"""
local_apply.py — Browser automation via browser-use + local Ollama (qwen3:4b).
Zero API cost. Fully local. No cloud dependency.
"""
from __future__ import annotations

import asyncio
import re
import sys
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
    "sign in", "create an account",
]


def _load_cfg() -> dict:
    return yaml.safe_load(open(ROOT / "config.yaml"))


async def _run_agent(prompt: str, resume_path: str, cfg: dict) -> dict:
    from browser_use import Agent
    from browser_use.browser.browser import Browser, BrowserConfig
    from langchain_ollama import ChatOllama

    ollama_cfg = cfg.get("ollama", cfg.get("qwen", {}))
    model = ollama_cfg.get("model", "qwen3:4b")
    base_url = ollama_cfg.get("base_url", "http://localhost:11434")

    llm = ChatOllama(
        model=model,
        base_url=base_url,
        temperature=0.1,
        num_predict=1024,
        # Disable qwen3 thinking tokens — we need fast structured responses
        extra_body={"options": {"think": False}},
    )

    browser = Browser(
        config=BrowserConfig(
            headless=True,
            disable_security=True,
        )
    )

    try:
        agent = Agent(
            task=prompt,
            llm=llm,
            browser=browser,
            max_actions_per_step=8,
        )
        result = await agent.run(max_steps=25)
        final_text = str(result.final_result() or "")
        return {"success": True, "output": final_text}
    except Exception as e:
        return {"success": False, "error": str(e)[:400]}
    finally:
        await browser.close()


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
            asyncio.wait_for(_run_agent(prompt, resume_path, cfg), timeout=timeout)
        )
    except asyncio.TimeoutError:
        return {"success": False, "error": f"timeout_{timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)[:300]}

    if not result.get("success"):
        return result

    return _parse(result.get("output", ""), screenshot_path)
